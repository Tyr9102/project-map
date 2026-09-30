#!/usr/bin/env python3
"""Claude Code hook tying sessions to project maps.

PostToolUse(Bash): after `git commit` in a project that has a project map, tell
the session to load the project-map skill and bring the map up to date.
UserPromptSubmit: in a project with a map whose watcher (watcher.py) for THIS session
is not alive - first message, 2 h task limit, crash - tell the session to start it,
so "Send" wakes it without "check the map" and a compacted-away instruction.
SessionStart: point the session to the map, start the map server if needed and
report commits the map has not been reminded about (made outside Claude).

The hook decides WHEN, the skill knows HOW. The open session does the update
because it knows why the code changed - a background agent would not.

Input: hook JSON on stdin. Output: JSON with additionalContext, always exit 0.
IMPORTANT: this hook must never block or fail a commit - an error is printed to
stderr and the hook still exits 0.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))
from settings import MAPS_DIR  # noqa: E402 - needs the plugin root on sys.path

# Last commit each map was reminded about, one file per map slug. meta.updatedAt is only
# a day, so comparing with it would re-report commits already handled that day.
# PROJECT_MAP_STATE_DIR exists for the tests; CLAUDE_PLUGIN_DATA is set for plugin hooks.
STATE_DIR = Path(os.environ.get("PROJECT_MAP_STATE_DIR")
                 or Path(os.environ.get("CLAUDE_PLUGIN_DATA") or Path.home() / ".project-map-state") / "state")
MAX_LISTED_COMMITS = 10
# Same as LISTEN_TIMEOUT_S in server.py: the watcher touches its heartbeat every second.
LISTEN_TIMEOUT_S = 10
# `git -C <dir> commit` does not match on purpose: that is how map commits into the
# maps repo are made.
COMMIT_RE = re.compile(r"(^|[;&|]\s*)git(\s+-\S+)*\s+commit(\s|$)")


def git(directory, *args):
    """Stdout of a git command, or None when it fails (no repo, no commits)."""
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    return result.stdout.strip() if result.returncode == 0 else None


def maps_in_repo(repo):
    """Path prefix of the maps inside `repo` ("" when the repo is the maps directory),
    or None when the maps are not tracked by this repo."""
    toplevel = git(MAPS_DIR, "rev-parse", "--show-toplevel")
    if not toplevel or Path(toplevel).resolve() != repo:
        return None
    rel = MAPS_DIR.resolve().relative_to(repo).as_posix()
    return "" if rel == "." else rel + "/"


def find_map(cwd):
    """The map whose projectDir is cwd or its parent; the deepest projectDir wins
    when maps are nested. Same rule as SKILL.md."""
    best = None
    for f in sorted(MAPS_DIR.glob("*/map.json")):
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))["meta"]
        except (OSError, ValueError, KeyError):
            # A broken map is check_map.py's job to report; it must not hide the others.
            continue
        if not meta.get("projectDir"):
            continue
        project = Path(meta["projectDir"]).resolve()
        if project != cwd and project not in cwd.parents:
            continue
        if best is None or len(project.parts) > len(best["project"].parts):
            best = {"slug": f.parent.name, "title": meta.get("title") or f.parent.name,
                    "project": project, "updated": meta.get("updatedAt") or ""}
    return best


def emit(event, text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text},
                      "suppressOutput": True}, ensure_ascii=False))


def remember_head(slug, head):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / slug).write_text(head + "\n", encoding="utf-8")


def unseen_commits(found):
    """Commits in the project the map has not been reminded about yet, as "- subject"
    lines. Commits touching only the maps are map updates themselves."""
    project = found["project"]
    if git(project, "rev-parse", "HEAD") is None:
        return []
    paths = ["."]
    prefix = maps_in_repo(Path(git(project, "rev-parse", "--show-toplevel")).resolve())
    if prefix:
        paths.append(":(exclude)" + prefix)
    state = STATE_DIR / found["slug"]
    seen = state.read_text(encoding="utf-8").strip() if state.is_file() else ""
    if seen and git(project, "cat-file", "-e", seen + "^{commit}") is not None:
        rng = [seen + "..HEAD"]
    elif found["updated"]:
        # First run for this map: everything since the map's date, at most once too much.
        rng = [f"--since={found['updated']} 00:00", "HEAD"]
    else:
        return []
    log = git(project, "log", "--format=- %s", *rng, "--", *paths)
    return log.splitlines() if log else []


def session_listening(slug, session_id):
    """Whether a watcher started with this Claude session id keeps its heartbeat fresh."""
    for d in (MAPS_DIR / slug / "signals" / "sessions").glob("*"):
        try:
            if (d / "claude_session").read_text(encoding="utf-8") != session_id:
                continue
            beat = (d / "heartbeat").stat().st_mtime
        except OSError:
            # The watcher is exiting right now or has not written its files yet.
            continue
        if time.time() - beat < LISTEN_TIMEOUT_S:
            return True
    return False


def on_user_prompt(payload):
    session_id, cwd = payload.get("session_id"), payload.get("cwd")
    if not session_id or not cwd or not MAPS_DIR.is_dir():
        return
    found = find_map(Path(cwd).resolve())
    if not found or session_listening(found["slug"], session_id):
        return
    # Only Claude's own background task wakes the session when it ends, so the hook
    # cannot start the watcher itself - it asks the session to. Whether it may run is
    # the user's call: a permission rule, never something this hook decides.
    emit("UserPromptSubmit",
         f"This directory has the project map \"{found['title']}\", and this session's watcher "
         "is not running. Before handling the message, start it in the background "
         "(run_in_background: true, timeout: 7200000 - the default 30 min would silently "
         f"stop listening): project-map-watch {found['slug']} \"<topic>\" {session_id} - the "
         "topic is 2-4 words on what this session works on, in the user's language, without "
         "quotes or special characters. Do not load the skill for this and do not describe it "
         "to the user when it starts. If a permission check blocks it, do not retry and do not "
         "suggest running it with `!` (the watcher must be your background task to wake you); "
         "tell the user in two sentences that Send on the map can wake this session once they "
         "allow the watcher with the permission rule Bash(project-map-watch:*) - via "
         "/permissions or permissions.allow in settings.json. When the watcher ends with "
         "SIGNAL, load the project-map skill (section \"How Send wakes the session\").")


def on_session_start(payload):
    cwd = payload.get("cwd")
    if not cwd or not MAPS_DIR.is_dir():
        return
    found = find_map(Path(cwd).resolve())
    if not found:
        return
    # Imported here: every Bash call runs this hook, and only session start needs the server.
    from server import start_in_background
    # Without this the skill loads only when the user says "map" or after a commit,
    # so decisions from a plain conversation would never reach the map.
    context = [f"This project has the project map \"{found['title']}\". When you and the user "
               "settle something about the project, or a brainstorm ends, load the project-map "
               "skill (section \"The map grows live in the conversation\")."]
    server_error = start_in_background(wait=False)
    if server_error:
        context.append(f"The map page cannot start: {server_error}. Tell the user in one sentence.")
    commits = unseen_commits(found)
    if commits:
        listed = "\n".join(commits[:MAX_LISTED_COMMITS])
        if len(commits) > MAX_LISTED_COMMITS:
            listed += f"\n- and {len(commits) - MAX_LISTED_COMMITS} more"
        context.append(
            f"The project map \"{found['title']}\" may not include commits made since the "
            f"last check ({len(commits)}):\n{listed}\n"
            "In your first reply tell the user in one sentence and ask whether to update "
            "the map. After a yes, load the project-map skill (section \"Does the map "
            "keep up\").")
    emit("SessionStart", "\n\n".join(context))
    head = git(found["project"], "rev-parse", "HEAD")
    if head:
        remember_head(found["slug"], head)


def only_map_files_changed(repo):
    """A commit that touches only the maps IS the map update - reminding about it
    would loop forever."""
    prefix = maps_in_repo(repo)
    if prefix is None:
        return False
    changed = git(repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "HEAD")
    return bool(changed) and all(p.startswith(prefix) for p in changed.splitlines())


def on_bash(payload):
    command = (payload.get("tool_input") or {}).get("command") or ""
    session_id, cwd = payload.get("session_id"), payload.get("cwd")
    if not COMMIT_RE.search(command) or not session_id or not cwd or not MAPS_DIR.is_dir():
        return
    cwd = Path(cwd).resolve()
    toplevel = git(cwd, "rev-parse", "--show-toplevel")
    head = toplevel and git(toplevel, "rev-parse", "HEAD")
    if not head:
        return
    # One reminder per commit: a second hook call for the same HEAD (commit failed,
    # nothing new) must not ask for the same map update again.
    marker = Path(tempfile.gettempdir()) / f"claude-project-map-ctx-{session_id}-{head}"
    if marker.exists() or only_map_files_changed(Path(toplevel).resolve()):
        return
    found = find_map(cwd)
    if not found:
        return
    emit("PostToolUse",
         f"The project has the map \"{found['title']}\" ({(MAPS_DIR / found['slug']).as_posix()}). "
         f"Load the project-map skill and follow its section \"Update after a commit\" "
         f"for commit {head[:7]}.")
    marker.touch()
    remember_head(found["slug"], head)


HANDLERS = {"UserPromptSubmit": on_user_prompt, "SessionStart": on_session_start}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        HANDLERS.get(payload.get("hook_event_name"), on_bash)(payload)
    except Exception:
        # Never block the session or a commit; stderr shows up in Claude Code's debug log.
        traceback.print_exc()
    sys.exit(0)


if __name__ == "__main__":
    main()
