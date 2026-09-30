"""Settings shared by the server, the watcher, the checker and the hook.

Set them in the "env" block of Claude Code's settings.json, so hooks and the
commands Claude runs see the same values.
"""
import os
from pathlib import Path

# Maps live outside the plugin: its directory is replaced on every update.
MAPS_DIR = Path(os.environ.get("PROJECT_MAP_DIR") or Path.home() / ".project-map").expanduser()
PORT = int(os.environ.get("PROJECT_MAP_PORT") or 8765)
HOST = "127.0.0.1"
