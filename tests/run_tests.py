#!/usr/bin/env python3
"""Tests of the hook, the watcher and the server. Exit code 1 when anything fails.

Hook cases live in cases.jsonl: a fake hook payload, a scratch project ("setup")
and the expected output - a substring, or "" for silence. Cases sharing a setup
share its repo, so a case can depend on the state an earlier one left behind.
Everything runs on scratch maps and a free port, next to a map server already in use.
"""
import json
import os
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "map_context.py"
CASES = Path(__file__).with_name("cases.jsonl")
SESSION_ID = f"hook-tests-{os.getpid()}-{secrets.token_hex(4)}"
WAIT_SECONDS = 5
MAP_JSON = {"meta": {"title": "Sample"}, "tiles": {"t1": {"title": "Tile"}}}

results = {"ok": 0, "fail": 0}


def report(ok, name, detail=""):
    results["ok" if ok else "fail"] += 1
    print(f"{'OK  ' if ok else 'FAIL'}  {name}{'' if ok else ' - ' + detail}")


def git(directory, *args):
    subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True)


def commit_file(repo, name, content, message):
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)


def make_setup(tmp, kind):
    """Project repo with one commit; returns (project dir, maps dir, state dir).

    map-project - a map points at the repo; map-nomap - no map;
    map-mapsrepo - the repo IS the maps repo and its commit touches only maps/;
    map-stale - like map-project, plus a commit made after the one in the state dir;
    map-listening / map-listening-other - like map-project, plus a live watcher
    of this test session / of another session.
    """
    project, maps, state = tmp / kind, tmp / f"{kind}-maps", tmp / f"{kind}-state"
    map_json = json.dumps({"meta": {"title": "Sample", "projectDir": str(project)}, "tiles": {}})
    if kind == "map-mapsrepo":
        maps = project / "maps"
    if not project.exists():
        project.mkdir()
        git(project, "init", "-q")
        git(project, "config", "user.email", "t@t")
        git(project, "config", "user.name", "t")
        maps.mkdir(parents=True, exist_ok=True)
        if kind == "map-mapsrepo":
            commit_file(project, "maps/sample/map.json", map_json, "init")
        else:
            if kind != "map-nomap":
                (maps / "sample").mkdir()
                (maps / "sample" / "map.json").write_text(map_json, encoding="utf-8")
            commit_file(project, "README.md", "# hello\n", "init")
        if kind == "map-stale":
            head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
            state.mkdir()
            (state / "sample").write_text(head + "\n", encoding="utf-8")
            commit_file(project, "app.py", "x\n", "new feature")
    if kind.startswith("map-listening"):
        owner = "other-session" if kind == "map-listening-other" else SESSION_ID
        watcher = maps / "sample" / "signals" / "sessions" / "0123456789abcdef"
        watcher.mkdir(parents=True, exist_ok=True)
        (watcher / "claude_session").write_text(owner, encoding="utf-8")
        (watcher / "heartbeat").touch()
    return project, maps, state


def run_hook_case(tmp, case):
    project, maps, state = make_setup(tmp, case["setup"])
    payload = {"session_id": SESSION_ID, "cwd": str(project), "hook_event_name": case["event"],
               "tool_name": "Bash", "tool_input": {"command": case["command"]}}
    env = {**os.environ, "PROJECT_MAP_DIR": str(maps), "PROJECT_MAP_STATE_DIR": str(state)}
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload).encode(),
                          capture_output=True, cwd=project, env=env)
    out = proc.stdout.decode("utf-8")
    if out:
        out = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    expected = case["expect_output"]
    if proc.returncode != 0:
        report(False, case["why"], f"exit {proc.returncode}")
    elif proc.stderr:
        report(False, case["why"], "hook error: " + proc.stderr.decode("utf-8", "replace"))
    elif expected == "" and out:
        report(False, case["why"], "expected silence, got: " + out)
    elif expected and expected not in out:
        report(False, case["why"], f"no '{expected}' in: {out}")
    elif case.get("expect_absent") and case["expect_absent"] in out:
        report(False, case["why"], f"unexpected '{case['expect_absent']}' in: {out}")
    else:
        report(True, case["why"])


def wait_for(condition):
    deadline = time.time() + WAIT_SECONDS
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


def make_maps(tmp):
    maps = Path(tempfile.mkdtemp(dir=tmp))
    (maps / "sample").mkdir()
    (maps / "sample" / "map.json").write_text(json.dumps(MAP_JSON), encoding="utf-8")
    return maps


def start_watcher(maps, slug="sample"):
    # Through the plugin command, as Claude runs it; sh comes with Git for Windows.
    proc = subprocess.Popen([shutil.which("sh"), str(ROOT / "bin" / "project-map-watch"), slug, "test", SESSION_ID],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**os.environ, "PROJECT_MAP_DIR": str(maps)})
    sessions = maps / slug / "signals" / "sessions"
    started = wait_for(lambda: any(sessions.glob("*/heartbeat")))
    return proc, sessions, started


def test_watcher_wakes(tmp):
    name = "the watcher claims a signal sent while nobody listened, prints it and cleans up"
    maps = make_maps(tmp)
    proc, sessions, started = start_watcher(maps)
    if not started:
        proc.kill()
        return report(False, name, "the watcher did not start listening")
    (maps / "sample" / "signals" / "abc.json").write_text('{"notes":1}', encoding="utf-8")
    try:
        out, err = proc.communicate(timeout=WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        return report(False, name, "the watcher did not exit after the signal")
    text = out.decode("utf-8")
    if proc.returncode != 0 or 'SIGNAL: {"notes":1}' not in text:
        return report(False, name, f"exit {proc.returncode}, output: {text} {err.decode()}")
    report(not any(sessions.iterdir()), name, "the session directory remained after exit")


def test_watcher_killed(tmp):
    name = "a killed watcher removes its session directory"
    proc, sessions, started = start_watcher(make_maps(tmp))
    if not started:
        proc.kill()
        return report(False, name, "the watcher did not start listening")
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=WAIT_SECONDS)
    report(wait_for(lambda: not any(sessions.iterdir())), name, "the session directory remained")


def test_watcher_killed_keeps_signal(tmp):
    name = "a signal that reaches a watcher as it is killed is printed or goes back to the shared box"
    maps = make_maps(tmp)
    proc, sessions, started = start_watcher(maps)
    if not started:
        proc.kill()
        return report(False, name, "the watcher did not start listening")
    session_dir = next(sessions.iterdir())
    (session_dir / "late.json").write_text('{"notes":2}', encoding="utf-8")
    proc.send_signal(signal.SIGTERM)
    out, err = proc.communicate(timeout=WAIT_SECONDS)
    kept = (maps / "sample" / "signals" / "late.json").is_file() or '{"notes":2}' in out.decode("utf-8")
    report(kept and not any(sessions.iterdir()), name, f"signal lost, output: {out.decode()} {err.decode()}")


def test_signal_to_gone_session(tmp):
    name = "a signal for a session that just exited goes to the shared box, no dead directory"
    sys.path.insert(0, str(ROOT))
    from server import deliver_signal
    d = make_maps(tmp) / "sample"
    gone = d / "signals" / "sessions" / "0123456789abcdef"
    landed = deliver_signal(d, gone, {"notes": 3})
    report(landed == d / "signals" and any((d / "signals").glob("*.json")) and not gone.exists(),
           name, f"landed in {landed}")


def request(port, method, path, body=None, headers=None):
    """(status, parsed JSON) of a request to the test server."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=None if body is None else body.encode(), headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=WAIT_SECONDS) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_server_guards(port):
    note = json.dumps({"tileId": "t1", "type": "question", "text": "x"})
    json_type = {"Content-Type": "application/json"}
    path = "/api/maps/sample/notes"
    status, _ = request(port, "POST", path, note, {**json_type, "Origin": "https://evil.example"})
    report(status == 403, "the server refuses a change sent from another website", f"status {status}")
    status, _ = request(port, "POST", path, note, {"Content-Type": "text/plain"})
    report(status == 415, "the server refuses a non-JSON write (skips the preflight)", f"status {status}")
    status, _ = request(port, "GET", "/api/maps", headers={"Host": f"evil.example:{port}"})
    report(status == 403, "the server refuses a foreign host name (DNS rebinding)", f"status {status}")
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=WAIT_SECONDS) as res:
        frame_policy = res.headers.get("Content-Security-Policy"), res.headers.get("X-Frame-Options")
    report(frame_policy == ("frame-ancestors 'none'", "DENY"),
           "the page refuses to be framed by another website", str(frame_policy))


def test_maps_private(maps):
    mode = stat.S_IMODE(maps.stat().st_mode)
    report(mode == 0o700, "the server makes the maps directory private to its owner", oct(mode))


def test_send_wakes_watcher(port, maps):
    name = "a note + Send on the page wakes the watcher with the note text"
    proc, _sessions, started = start_watcher(maps)
    if not started:
        proc.kill()
        return report(False, name, "the watcher did not start listening")
    headers = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"}
    note = json.dumps({"tileId": "t1", "type": "question", "text": "does it work?"})
    added, body = request(port, "POST", "/api/maps/sample/notes", note, headers)
    sent, _ = request(port, "POST", "/api/maps/sample/send", "{}", headers)
    try:
        out, _err = proc.communicate(timeout=WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        return report(False, name, f"the watcher did not wake (add {added} {body}, send {sent})")
    report("does it work?" in out.decode("utf-8"), name, "no note text in the watcher output")


def test_server_stops(port, server):
    name = "server.py --stop stops the running server"
    result = subprocess.run([sys.executable, str(ROOT / "server.py"), "--stop"], capture_output=True,
                            env={**os.environ, "PROJECT_MAP_PORT": str(port)})
    try:
        server.wait(timeout=WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        return report(False, name, f"the server still runs ({result.stdout!r} {result.stderr!r})")
    report(result.returncode == 0, name, f"exit code {result.returncode}: {result.stderr!r}")


def test_delete_listened_map(port, maps):
    name = "deleting a map a session listens to succeeds and the watcher exits with MAP DELETED"
    (maps / "doomed").mkdir()
    (maps / "doomed" / "map.json").write_text(json.dumps(MAP_JSON), encoding="utf-8")
    proc, _sessions, started = start_watcher(maps, "doomed")
    if not started:
        proc.kill()
        return report(False, name, "the watcher did not start listening")
    status, body = request(port, "DELETE", "/api/maps/doomed", headers={"Origin": f"http://127.0.0.1:{port}"})
    try:
        out, err = proc.communicate(timeout=WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        return report(False, name, f"the watcher did not exit (delete {status} {body})")
    ok = status == 200 and proc.returncode == 0 and "MAP DELETED" in out.decode("utf-8")
    report(ok and not (maps / "doomed").exists(), name,
           f"delete {status} {body}, exit {proc.returncode}: {out.decode()} {err.decode()}")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(maps, port):
    """The hook starts a server on session start unless one answers; this one answers."""
    log = maps.parent / "test-server.log"
    with open(log, "wb") as out:
        proc = subprocess.Popen([sys.executable, str(ROOT / "server.py")], stdout=out, stderr=out,
                                env={**os.environ, "PROJECT_MAP_DIR": str(maps), "PROJECT_MAP_PORT": str(port)})

    def answers():
        try:
            return request(port, "GET", "/api/maps")[0] == 200
        except OSError:
            return False
    if not wait_for(answers):
        proc.kill()
        sys.exit("the test server did not start:\n" + log.read_text(encoding="utf-8", errors="replace"))
    return proc


def main():
    # Windows consoles default to a legacy code page that cannot print Polish letters.
    sys.stdout.reconfigure(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp())
    port = free_port()
    os.environ["PROJECT_MAP_PORT"] = str(port)
    server_maps = make_maps(tmp)
    server = start_server(server_maps, port)
    try:
        for line in CASES.read_text(encoding="utf-8").splitlines():
            if line.strip():
                run_hook_case(tmp, json.loads(line))
        test_watcher_wakes(tmp)
        # Windows has no SIGTERM to catch: terminate() ends the process at once, and
        # the page drops the session after LISTEN_TIMEOUT_S instead.
        if os.name != "nt":
            test_watcher_killed(tmp)
            test_watcher_killed_keeps_signal(tmp)
        test_signal_to_gone_session(tmp)
        test_server_guards(port)
        # Windows has no owner-only mode bits; its access rules are left alone.
        if os.name != "nt":
            test_maps_private(server_maps)
        test_send_wakes_watcher(port, server_maps)
        test_delete_listened_map(port, server_maps)
        # Last: it ends the test server.
        test_server_stops(port, server)
    finally:
        server.terminate()
        server.wait(timeout=WAIT_SECONDS)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"----- {results['ok']} OK, {results['fail']} FAIL")
    sys.exit(1 if results["fail"] else 0)


if __name__ == "__main__":
    main()
