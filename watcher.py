#!/usr/bin/env python3
"""Waits for a "Send" signal meant for this session and exits with its content.

Claude runs it as a background task: the exit is what wakes the session,
so after handling the notes Claude must start it again.
Several sessions may listen to one map; the page asks which one to wake.

Usage: watcher.py <map-slug> "<session topic>" [<Claude session id>]
"""
import os
import secrets
import shutil
import signal
import sys
import time
from datetime import datetime, timezone

from settings import MAPS_DIR

POLL_SECONDS = 1
CLOSE_RETRIES = 20
CLOSE_RETRY_SECONDS = 0.05


def now_iso():
    # Same shape as toISOString() and now_iso() in server.py - the page compares text.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def exit_on_signal(signum, _frame):
    # Turns a kill from Claude Code into a normal exit, so `finally` removes the
    # session directory and the page stops showing this session at once.
    sys.exit(128 + signum)


def claim_shared_signals(signals_dir, session_dir):
    # Signals sent while nobody listened are shared; rename is atomic, so exactly one
    # session takes each. A failed rename means another session was faster.
    for f in signals_dir.glob("*.json"):
        try:
            f.rename(session_dir / f.name)
        except OSError:
            pass


def supersede_same_window(sessions_dir, session_dir, claude_pid):
    # /clear gives the conversation a new id while its old watcher keeps running in the
    # same Claude window; without this the page offers two sessions that are one.
    if not claude_pid:
        return
    for other in sessions_dir.iterdir():
        if other == session_dir:
            continue
        try:
            if (other / "claude_pid").read_text(encoding="utf-8") == claude_pid:
                (other / "superseded").touch()
        except FileNotFoundError:
            # Closing right now, or started by an older plugin version without the file.
            pass


def main():
    # Windows consoles default to a legacy code page that cannot print Polish letters.
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    slug = args[0] if args else ""
    topic = (args[1] if len(args) > 1 else "").replace("\n", " ")
    # Claude Code session id, passed by the map_context hook so it can tell whether
    # this session already listens.
    claude_session = args[2] if len(args) > 2 else ""
    if not slug or not topic or not (MAPS_DIR / slug / "map.json").is_file():
        sys.exit(f"usage: watcher.py <map slug> \"<session topic>\" [<Claude session id>] "
                 f"(map '{slug}' in {MAPS_DIR}, topic '{topic}')")

    map_file = MAPS_DIR / slug / "map.json"
    signals_dir = MAPS_DIR / slug / "signals"
    # Id format must match SESSION_ID_RE in server.py.
    session_dir = signals_dir / "sessions" / secrets.token_hex(8)
    session_dir.mkdir(parents=True)
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is not None:
            signal.signal(sig, exit_on_signal)
    try:
        (session_dir / "topic").write_text(topic, encoding="utf-8")
        (session_dir / "start").write_text(now_iso() + "\n", encoding="utf-8")
        (session_dir / "claude_session").write_text(claude_session, encoding="utf-8")
        # Set by Claude Code for its child processes: the window this watcher belongs to.
        claude_pid = os.environ.get("CLAUDE_PID", "")
        (session_dir / "claude_pid").write_text(claude_pid, encoding="utf-8")
        supersede_same_window(session_dir.parent, session_dir, claude_pid)
        while True:
            if not map_file.is_file():
                # Deleted on the page. Exiting wakes the session anyway, so tell it why.
                print(f"MAP DELETED: map '{slug}' was deleted on the page. Do not start the "
                      "watcher again; tell the user in one sentence.", flush=True)
                return
            # The page counts the session as listening only while this file keeps getting fresh.
            try:
                (session_dir / "heartbeat").touch()
            except FileNotFoundError:
                # The map was renamed away for deletion right after the check above;
                # a missing session directory under a living map is a real error.
                if map_file.is_file():
                    raise
                continue
            if (session_dir / "superseded").exists():
                print("SUPERSEDED: a newer watcher of this Claude window took over. Do not start "
                      "the watcher again and do not mention it to the user.", flush=True)
                return
            claim_shared_signals(signals_dir, session_dir)
            received = sorted(session_dir.glob("*.json"))
            if received:
                for f in received:
                    print("SIGNAL: " + f.read_text(encoding="utf-8"), flush=True)
                    f.unlink()
                return
            time.sleep(POLL_SECONDS)
    finally:
        close_session(session_dir, signals_dir)


def close_session(session_dir, signals_dir):
    # A signal the server wrote after our last check would be deleted with the directory.
    # Moving the directory out of sessions/ first makes later writes fall back to the
    # shared box; what already arrived goes there too, for the next session to claim.
    closing = signals_dir / f".closing-{session_dir.name}"
    for attempt in range(CLOSE_RETRIES):
        try:
            session_dir.rename(closing)
            break
        except FileNotFoundError:
            return
        except PermissionError:
            # Windows refuses the rename while the server has a file open inside.
            time.sleep(CLOSE_RETRY_SECONDS)
    else:
        print(f"watcher: could not close {session_dir}; signals in it may wait there", file=sys.stderr, flush=True)
        closing = session_dir
    for f in closing.glob("*.json"):
        f.replace(signals_dir / f.name)
    shutil.rmtree(closing, ignore_errors=True)


if __name__ == "__main__":
    main()
