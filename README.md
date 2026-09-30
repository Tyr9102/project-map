# Project Map

[![English](https://img.shields.io/badge/English-555555?style=for-the-badge)](README.md) [![Polski](https://img.shields.io/badge/Polski-dc143c?style=for-the-badge)](README.pl.md)

[![tests](https://github.com/Tyr9102/project-map/actions/workflows/test.yml/badge.svg)](https://github.com/Tyr9102/project-map/actions/workflows/test.yml)

Keep an eye on your project at a glance. As a project grows, it gets hard to follow from a terminal conversation alone: what works, what is in progress, where the pitfalls are. Project Map shows the whole thing as a map of tiles in your browser, in plain language, without code. When you want something changed, you do not have to describe at length in the terminal which part you mean. You click the tile, write your note right on it, and Claude knows exactly what it is about. The map does not replace your work in the terminal - that is still where you talk to Claude and build the project. It helps you keep the context in one place and, while you work, pin down a specific point quickly.

A Claude Code plugin that turns a conversation about your project into a map of tiles in the browser. You leave notes on the tiles, click **Send**, and the Claude Code session you have open wakes up by itself, replies next to the tiles and updates the map.

![A note sent from the map wakes the Claude Code session, which replies and updates the map](docs/demo.gif)

*Real recording, sped up while Claude works: the note is sent on the left, the session on the right wakes within a second.*

Made for people who think about a project without reading its code: the important things in plain language, in zones read top to bottom - goal, how it works, features, rules and pitfalls, questions and ideas.

## What it does

- **"Make a project map"** - Claude reads the project's docs and history, checks features against the code and builds the map. Tiles it could not confirm are marked as open questions.
- **Notes on tiles** - comment, question or suggestion. Collect a few drafts, then Send them as one batch.
- **Filter at a glance** - status chips with counts (works, pitfall, open question...) dim every other tile. On a wide screen the notes panel sits beside the map, so it stays in view.
- **Send wakes the session** - within 1-2 seconds, no typing in the terminal. Replies appear next to the tiles.
- **The map keeps up** - after a commit Claude updates the tiles; at session start it reports commits the map has not seen. Decisions from the conversation go on the map at once; ideas from a brainstorm only the ones you pick at its end, so the map does not fill up with every "what if".
- **Everything stays local** - the page runs on `127.0.0.1`, maps are plain JSON files on your disk. Nothing is sent anywhere except to Claude, as part of your normal session.

The page speaks English or Polish, following your browser language.

## Requirements

- [Claude Code](https://code.claude.com)
- Python 3.9 or newer as `python3` or `python` (standard library only, nothing to install)
- git (for the "map keeps up" features)
- On Windows: Git Bash, which comes with Git for Windows

## Install

In Claude Code:

```
/plugin marketplace add Tyr9102/project-map
/plugin install project-map@project-map
```

Then allow the watcher - the small background command that lets **Send** wake your session. Run `/permissions` and add the allow rule `Bash(project-map-watch:*)`, or put it in `~/.claude/settings.json`:

```json
{
  "permissions": { "allow": ["Bash(project-map-watch:*)"] }
}
```

Or skip this step: when you make your first map, Claude asks whether to add the rule for you and writes it only after a yes.

Without it, auto mode may block the watcher (it runs code from the plugin, not from your project) and the map works without waking Claude - you type "check the map" instead.

Then, in a project directory, tell Claude: **"make a project map"**. It gives you the address, by default `http://127.0.0.1:8765`. Other things to say: [What to tell Claude](#what-to-tell-claude).

What changed in each version: [CHANGELOG.md](CHANGELOG.md).

## What to tell Claude

Plain sentences, in any language - no special syntax.

| Say | What happens |
|---|---|
| "make a project map" | builds the map of the project in the current directory (or refreshes it if it exists) and gives you the address |
| "make a project map of X" | the same for the project you name |
| "check the map" | reads and answers the notes you sent, when the watcher is not running |
| "put this on the map" | adds what you just settled in the conversation |
| "update the map" | brings the tiles in line with changes in the code |
| "stop the map server" | after a plugin update or before uninstalling |

If you prefer a command to a sentence: `/project-map:project-map`.

## Settings

Optional, in the `env` block of `~/.claude/settings.json`, so the hooks and the commands Claude runs see the same values:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PROJECT_MAP_DIR` | `~/.project-map` | Where maps are kept |
| `PROJECT_MAP_PORT` | `8765` | Local port of the map page |

```json
{
  "env": { "PROJECT_MAP_DIR": "/home/you/maps", "PROJECT_MAP_PORT": "8790" }
}
```

**History and backup:** make the maps directory a git repository (`git init` inside it) and Claude commits every map change there.

## How it works

- A small local server (Python, standard library) serves the page and stores notes as files, one file per note. The plugin starts it at session start in a project that has a map. It keeps running after you close Claude Code, on purpose: bookmark the page and your maps are one click away, with or without a session. It stops when you restart the computer or tell Claude **"stop the map server"**; the next session in a project with a map starts it again.
- A watcher runs as a Claude Code background task. Send writes a signal file; the watcher sees it, prints it and exits - and the end of a background task is what wakes the session. Claude then starts a new watcher.
- A hook checks on every message whether this session's watcher is alive and asks Claude to start one when it is not.
- The server refuses changes coming from other websites open in your browser.

## Security model

- **Websites open in your browser cannot touch your maps.** The server answers only under a local address, accepts changes only from the map page itself, refuses the request types a foreign page could send without asking, and does not let another site embed the map in a frame.
- **Other accounts on the same computer cannot open your map files** - the server makes the maps directory private to you (on Linux and macOS). **But they can use the server:** it runs under your account and answers any program on this computer, so another account can read your maps and notes through `127.0.0.1`, send notes, delete a map and stop the server. Only a password in the page address would stop that, not worth it for a rare setup - on a computer shared with people you do not trust, keep nothing confidential on a map.
- **Programs running under your own account are trusted**, like with any file on your disk: they could write a note straight into the maps directory without the server. A password on the page would not change that.

## Limitations - read before relying on it

- **It relies on Claude Code behaviour, not a documented API:** the session wakes because a finished background task starts a new turn. A Claude Code update may change that.
- **The watcher lives at most 2 hours** (the Claude Code limit for a background task). The next message you type starts a new one.
- **Every wake-up costs tokens** - it is a full turn with the whole session context. Send notes in batches and open the map in a fresh session.
- **Every commit in a project with a map costs tokens too** - right after it, in the same turn, Claude reads what changed, updates the tiles that the change affects and commits the map (into the maps directory's own repository, if it has one). A change that the map does not show costs only a short check.
- **Used day to day on Linux only.** The automated tests pass on Linux, macOS and Windows, but nobody has used it on macOS or Windows yet.
- After a plugin update, a server that is already running keeps the old version until you stop it - tell Claude **"stop the map server"**. The next Claude Code session starts the new one.

## Uninstall

First tell Claude **"stop the map server"**, then:

```
/plugin uninstall project-map@project-map
```

Your maps stay in `~/.project-map` (or your `PROJECT_MAP_DIR`) - delete that directory yourself if you no longer need them. Remove the `Bash(project-map-watch:*)` permission rule if you added it.

## Development

```
python3 tests/run_tests.py        # hook, watcher and server tests, on scratch maps and a free port
claude --plugin-dir .             # run Claude Code with the plugin from this directory
```

## License

MIT
