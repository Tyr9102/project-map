"""Checks map files for mistakes an agent makes when editing them by hand.

    check_map.py                  # all maps
    check_map.py <maps dir>/<slug> # one map
Exit code 1 when any error is found.
"""
import json
import re
import sys
from pathlib import Path

from settings import MAPS_DIR

TILE_STATUSES = {"works", "in_progress", "idea", "pitfall", "question"}
NOTE_TYPES = {"comment", "question", "suggestion"}
NOTE_STATES = {"draft", "sent", "done"}
# Must match the browser's toISOString(); the page compares timestamps as text.
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_TILES, MAX_TILES = 15, 30


def load(path, errors):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        errors.append(f"{path}: cannot read ({e})")
        return None


def check_meta(meta, errors):
    for field in ("title", "updatedAt", "projectDir", "zones"):
        if not meta.get(field):
            errors.append(f"meta: missing field {field}")
    if meta.get("updatedAt") and not DATE_RE.match(meta["updatedAt"]):
        errors.append(f"meta.updatedAt: wrong format {meta['updatedAt']!r} (YYYY-MM-DD)")
    zone_ids = [z.get("id") for z in meta.get("zones", [])]
    if len(zone_ids) != len(set(zone_ids)):
        errors.append("meta.zones: repeated zone id")
    return set(zone_ids)


def check_tile(tid, t, zone_ids, errors):
    where = f"tile {tid}"
    if t.get("zone") not in zone_ids:
        errors.append(f"{where}: zone {t.get('zone')!r} is not in meta.zones")
    if t.get("status") not in TILE_STATUSES:
        errors.append(f"{where}: unknown status {t.get('status')!r}")
    # A realised idea once stayed among open questions with only its text updated.
    if t.get("zone") == "questions" and t.get("status") == "works":
        errors.append(f"{where}: status works in zone questions - move it to its proper zone or remove it")
    for field in ("row", "order"):
        if not isinstance(t.get(field), int):
            errors.append(f"{where}: {field} must be an integer")
    for field in ("title", "body"):
        if not str(t.get(field, "")).strip():
            errors.append(f"{where}: empty field {field}")
    for field in ("changedAt", "addedAt"):
        if field in t and not TIMESTAMP_RE.match(str(t[field])):
            errors.append(f"{where}: {field} in wrong format {t[field]!r} (YYYY-MM-DDTHH:MM:SS.000Z)")


def check_note(path, note, tile_ids, errors, warnings):
    where = f"note {path.name}"
    if note.get("tileId") not in tile_ids:
        errors.append(f"{where}: tile {note.get('tileId')!r} does not exist - the note vanished from the map")
    if note.get("type") not in NOTE_TYPES:
        errors.append(f"{where}: unknown type {note.get('type')!r}")
    if note.get("state") not in NOTE_STATES:
        errors.append(f"{where}: unknown state {note.get('state')!r}")
    for field in ("createdAt", "sentAt"):
        if field in note and not TIMESTAMP_RE.match(str(note[field])):
            errors.append(f"{where}: {field} in wrong format {note[field]!r}")
    if note.get("state") == "done" and not str(note.get("reply", "")).strip():
        warnings.append(f"{where}: done without a reply")


def check_map(map_dir):
    errors, warnings = [], []
    data = load(map_dir / "map.json", errors)
    if data is None:
        return errors, warnings
    zone_ids = check_meta(data.get("meta", {}), errors)
    tiles = data.get("tiles", {})
    for tid, t in tiles.items():
        check_tile(tid, t, zone_ids, errors)
    if not MIN_TILES <= len(tiles) <= MAX_TILES:
        warnings.append(f"{len(tiles)} tiles - outside {MIN_TILES}-{MAX_TILES}")
    for path in sorted((map_dir / "notes").glob("*.json")):
        note = load(path, errors)
        if note is not None:
            check_note(path, note, set(tiles), errors, warnings)
    return errors, warnings


def main(args):
    sys.stdout.reconfigure(encoding="utf-8")
    dirs = [Path(a) for a in args] or sorted(p.parent for p in MAPS_DIR.glob("*/map.json"))
    failed = False
    for d in dirs:
        errors, warnings = check_map(d)
        status = "ERRORS" if errors else "OK"
        print(f"{d.name}: {status} ({len(errors)} errors, {len(warnings)} warnings)")
        for line in errors:
            print(f"  ERROR {line}")
        for line in warnings:
            print(f"  warn  {line}")
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
