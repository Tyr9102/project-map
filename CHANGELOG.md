# Changelog

What changed for users in each version. The version is the one in `.claude-plugin/plugin.json`.

## 0.3.5 - 2026-09-30

- Maps are no longer squeezed to 30 tiles: Claude keeps everything important and above ~30 tiles only trims details and repeats.

## 0.3.4 - 2026-09-30

- Notes sent at the moment a session stopped listening are no longer lost - the next listening session picks them up.
- Two projects with the same folder name get separate maps instead of sharing one.

## 0.3.3 - 2026-09-30

- Claude offers to add the watcher permission rule for you - at your first map or when the watcher is blocked - and writes it only after a yes. No more editing settings by hand.
- README in Polish.

## 0.3.2 - 2026-09-30

- Claude tells you in one sentence when the watcher starts listening, instead of starting it silently.
- The maps directory is private to your account; other accounts on the same computer cannot read your maps.
- No more small files piling up in the temp directory after every commit.
- README: a security model section, the token cost of map updates after a commit, and why the map server keeps running after the session ends (so the page can be bookmarked).

## 0.3.1 - 2026-09-30

- Status chips with counts filter the map; on a wide screen the notes panel sits beside it.
- Settled decisions go on the map at once; brainstorm ideas only the ones you pick at the end.
- The commit reminder runs only on `git commit`, not on every command.
- Deleting a map a session listens to no longer wakes that session with an error.

## 0.3.0 - 2026-09-30

- "Stop the map server" - for after a plugin update, or before uninstalling.
- README: how to stop the server and uninstall.

## 0.2.0 - 2026-09-30

- First release.
