"""Local server for project maps: serves the page and stores notes as files.

Only the standard library - nothing to install.
    server.py            run in the foreground
    server.py --ensure   start it in the background unless it already runs
    server.py --stop     stop the running one (e.g. the old version after an update)
"""
import json
import os
import re
import secrets
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from settings import HOST, MAPS_DIR, PORT

# Read once at start: the plugin directory of an older version may be deleted
# after an update while this server still runs.
PAGE = (Path(__file__).resolve().parent / "map.html").read_bytes()
# Any website open in the browser can send requests to 127.0.0.1; only the map page
# itself may change data, and only under a local host name (DNS rebinding).
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}
MAPS_GITIGNORE = "# Watcher state, not history\n*/signals/\n*.tmp\n"
START_WAIT_S = 5
# The watcher touches the heartbeat every second; a few missed beats mean it is gone.
LISTEN_TIMEOUT_S = 10
MAX_TEXT_CHARS = 4000
NOTE_TYPES = {"comment", "question", "suggestion"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
NOTE_ID_RE = re.compile(r"^[a-f0-9]{16}$")
# watcher.py names its session directory with 16 random hex chars.
SESSION_ID_RE = re.compile(r"^[a-f0-9]{16}$")
MAX_TOPIC_CHARS = 60

write_lock = threading.Lock()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def now_iso():
    # Same shape as the browser's toISOString(), so text comparison of timestamps works.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        # Files are hand-edited by an agent; the page must name the broken one.
        raise ApiError(500, f"broken file {path.relative_to(MAPS_DIR)}: {e}") from e


def map_dir(slug):
    if not SLUG_RE.match(slug):
        raise ApiError(400, "invalid map name")
    d = MAPS_DIR / slug
    if not (d / "map.json").is_file():
        raise ApiError(404, f"no map {slug}")
    return d


def listening_sessions(d):
    sessions = []
    for s in (d / "signals" / "sessions").glob("*"):
        try:
            if time.time() - (s / "heartbeat").stat().st_mtime >= LISTEN_TIMEOUT_S:
                continue
            topic = (s / "topic").read_text(encoding="utf-8").strip()[:MAX_TOPIC_CHARS]
            since = (s / "start").read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            # The watcher removes its directory on exit, possibly mid-read.
            continue
        sessions.append({"id": s.name, "topic": topic, "since": since})
    return sorted(sessions, key=lambda x: x["since"])


def signal_dir(d, session):
    alive = listening_sessions(d)
    if session is None:
        if len(alive) > 1:
            raise ApiError(409, "several sessions listen - choose which one to wake")
        session = alive[0]["id"] if alive else None
    elif not SESSION_ID_RE.match(str(session)) or not any(s["id"] == session for s in alive):
        raise ApiError(409, "this session no longer listens - choose again")
    target = d / "signals" / "sessions" / session if session else None
    # A session that exited in the meantime would leave the signal in a dead directory;
    # the shared one is picked up by whichever session listens next.
    return target if target and target.is_dir() else d / "signals"


def load_notes(d):
    notes = []
    for f in sorted((d / "notes").glob("*.json")):
        note = read_json(f)
        note["id"] = f.stem
        notes.append(note)
    return notes


def list_maps():
    maps = []
    for f in sorted(MAPS_DIR.glob("*/map.json")):
        try:
            meta = read_json(f)["meta"]
            open_notes = sum(1 for n in load_notes(f.parent) if n.get("state") == "sent")
        except ApiError as e:
            # One broken map must not hide the others; show the error in its card instead.
            maps.append({"slug": f.parent.name, "title": f.parent.name, "subtitle": f"ERROR: {e}",
                         "updatedAt": "", "openNotes": 0, "listeners": 0})
            continue
        maps.append({"slug": f.parent.name, "title": meta.get("title", f.parent.name),
                     "subtitle": meta.get("subtitle", ""), "updatedAt": meta.get("updatedAt", ""),
                     "openNotes": open_notes, "listeners": len(listening_sessions(f.parent))})
    return {"maps": maps}


def get_map(slug):
    d = map_dir(slug)
    data = read_json(d / "map.json")
    tiles = [{"id": tid, **t} for tid, t in data.get("tiles", {}).items()]
    return {"meta": data["meta"], "tiles": tiles, "notes": load_notes(d), "sessions": listening_sessions(d)}


def add_note(slug, body):
    d = map_dir(slug)
    text = str(body.get("text", "")).strip()
    note_type = body.get("type")
    if not text or len(text) > MAX_TEXT_CHARS:
        raise ApiError(400, f"a note must have 1 to {MAX_TEXT_CHARS} characters")
    if note_type not in NOTE_TYPES:
        raise ApiError(400, "unknown note type")
    tiles = read_json(d / "map.json").get("tiles", {})
    tile_id = body.get("tileId")
    if tile_id not in tiles:
        raise ApiError(400, "no such tile")
    note = {"tileId": tile_id, "tileTitle": tiles[tile_id].get("title", ""), "type": note_type,
            "text": text, "state": "draft", "reply": "", "createdAt": now_iso()}
    note_id = secrets.token_hex(8)
    with write_lock:
        write_json_atomic(d / "notes" / f"{note_id}.json", note)
    return {"id": note_id, **note}


def delete_draft(slug, note_id):
    d = map_dir(slug)
    if not NOTE_ID_RE.match(note_id):
        raise ApiError(400, "invalid note id")
    path = d / "notes" / f"{note_id}.json"
    with write_lock:
        if not path.is_file():
            raise ApiError(404, "no such note")
        if read_json(path).get("state") != "draft":
            raise ApiError(409, "only a draft can be deleted")
        path.unlink()
    return {"deleted": note_id}


def delete_map(slug):
    d = map_dir(slug)
    # Renamed first: a watcher of this map touches its heartbeat every second, and a file
    # recreated mid-rmtree would fail the delete halfway. After the rename it finds nothing.
    doomed = MAPS_DIR / f".deleting-{slug}-{secrets.token_hex(4)}"
    with write_lock:
        os.replace(d, doomed)
        shutil.rmtree(doomed)
    return {"deleted": slug}


def send_drafts(slug, body):
    d = map_dir(slug)
    # Chosen before any note changes state, so a refused send leaves the drafts intact.
    target = signal_dir(d, body.get("session"))
    sent_at = now_iso()
    sent = []
    with write_lock:
        try:
            for f in sorted((d / "notes").glob("*.json")):
                note = read_json(f)
                if note.get("state") != "draft":
                    continue
                note.update(state="sent", sentAt=sent_at)
                write_json_atomic(f, note)
                sent.append({"tile": note["tileTitle"], "type": note["type"], "text": note["text"]})
        finally:
            # Notes already marked "sent" can no longer be re-sent from the page,
            # so they must reach Claude even if a later note failed to save.
            if sent:
                signal = {"map": slug, "sentAt": sent_at, "notes": sent}
                write_json_atomic(target / f"{secrets.token_hex(8)}.json", signal)
    return {"sent": len(sent), "listening": target != d / "signals"}


class Server(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer.server_bind looks up the machine's full DNS name, which can hang
        # for seconds on macOS; the name is only used in log lines.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "request is not valid JSON")

    def _check_caller(self, method):
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            raise ApiError(403, "unexpected Host header")
        if method == "GET":
            return
        # Browsers always send Origin with POST and DELETE; curl and scripts do not.
        origin = self.headers.get("Origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            raise ApiError(403, "request from another website")
        # A form or a text/plain fetch from another site skips the CORS preflight;
        # JSON cannot, and the preflight gets no CORS approval here.
        if method == "POST" and not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise ApiError(415, "expected application/json")

    def _route(self, method):
        self._check_caller(method)
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        if method == "GET" and not parts:
            return self._reply(200, PAGE, "text/html; charset=utf-8")
        if method == "POST" and parts == ["api", "stop"]:
            self._reply(200, {"stopped": True})
            # shutdown() waits for serve_forever to return, which waits for this handler.
            threading.Thread(target=self.server.shutdown).start()
            return None
        if parts[:2] != ["api", "maps"]:
            raise ApiError(404, "no such path")
        rest = parts[2:]
        if method == "GET" and not rest:
            return self._reply(200, list_maps())
        if method == "GET" and len(rest) == 1:
            return self._reply(200, get_map(rest[0]))
        if method == "DELETE" and len(rest) == 1:
            return self._reply(200, delete_map(rest[0]))
        if method == "POST" and len(rest) == 2 and rest[1] == "notes":
            return self._reply(201, add_note(rest[0], self._body()))
        if method == "DELETE" and len(rest) == 3 and rest[1] == "notes":
            return self._reply(200, delete_draft(rest[0], rest[2]))
        if method == "POST" and len(rest) == 2 and rest[1] == "send":
            return self._reply(200, send_drafts(rest[0], self._body()))
        raise ApiError(404, "no such path")

    def _handle(self, method):
        try:
            self._route(method)
        except ApiError as e:
            self._reply(e.status, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 - report every failure to the page, loudly
            self.log_error("%s %s failed: %r", method, self.path, e)
            self._reply(500, {"error": f"server error: {e}"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_DELETE(self):
        self._handle("DELETE")


def server_status():
    """"ours" when this map server answers on the port, "other" when something else
    does, None when nothing listens."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/maps", timeout=1) as res:
            return "ours" if "maps" in json.loads(res.read()) else "other"
    except urllib.error.HTTPError:
        return "other"
    except (OSError, ValueError):
        return None


def start_in_background(wait):
    """Starts the server detached from the calling process (a hook or a Claude command),
    so it outlives the session. Returns an error message, or None when it runs."""
    status = server_status()
    if status == "other":
        return f"port {PORT} is taken by another program - set PROJECT_MAP_PORT to a free one"
    if status == "ours":
        return None
    log_path = Path(tempfile.gettempdir()) / f"project-map-{PORT}.log"
    detach = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
              if os.name == "nt" else {"start_new_session": True})
    with open(log_path, "ab") as log:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve())], stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, **detach)
    if not wait:
        return None
    deadline = time.time() + START_WAIT_S
    while time.time() < deadline:
        if server_status() == "ours":
            return None
        time.sleep(0.2)
    return f"the server did not start - see {log_path}"


def stop_running():
    """Asks the map server on the port to exit. Returns an error message, or None when
    it stopped."""
    req = urllib.request.Request(f"http://{HOST}:{PORT}/api/stop", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=START_WAIT_S):
        pass
    deadline = time.time() + START_WAIT_S
    while time.time() < deadline:
        if server_status() is None:
            return None
        time.sleep(0.2)
    return f"the map server on port {PORT} did not stop"


def main():
    if sys.argv[1:] == ["--stop"]:
        status = server_status()
        if status is None:
            print("map server is not running")
            sys.exit(0)
        error = (f"port {PORT} is taken by another program, not the map server"
                 if status == "other" else stop_running())
        print(error or "map server stopped", file=sys.stderr if error else sys.stdout)
        sys.exit(1 if error else 0)
    if sys.argv[1:] == ["--ensure"]:
        error = start_in_background(wait=True)
        print(error or f"map server: http://{HOST}:{PORT}, maps in {MAPS_DIR}", file=sys.stderr if error else sys.stdout)
        sys.exit(1 if error else 0)
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    if not (MAPS_DIR / ".gitignore").exists():
        (MAPS_DIR / ".gitignore").write_text(MAPS_GITIGNORE, encoding="utf-8")
    server = Server((HOST, PORT), Handler)
    print(f"project-map: listening on {HOST}:{PORT}, maps in {MAPS_DIR}", file=sys.stderr, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
