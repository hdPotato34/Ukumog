# Website Integration

This repo is ready to be vendored into the website as a subtree and called through a small JSON bridge.

## Recommended repo shape

Use a subtree in the website repo so the engine code lives in the website tree, but the engine can still evolve in its own repo:

```powershell
git subtree add --prefix vendor/ukumog-engine https://github.com/hdPotato34/ukumog-engine.git main --squash
```

To pull future engine updates into the website repo:

```powershell
git subtree pull --prefix vendor/ukumog-engine https://github.com/hdPotato34/ukumog-engine.git main --squash
```

Why subtree instead of submodule for v1:

* the website already has its own stable `main` flow
* deployment stays simpler because the engine code is physically present in the website checkout
* there is no separate submodule initialization step in CI or on new machines

## Engine bridge

The website should call:

```powershell
python -m ukumog_engine.apps.json_bridge
```

Requests are JSON on stdin and responses are JSON on stdout.

### Engine info

```json
{"command":"engine_info"}
```

### Analyze a position

```json
{
  "command": "analyze",
  "position": {
    "rows": [
      "...........",
      "...........",
      "...........",
      "...........",
      "...........",
      "B.B.B.B....",
      "...........",
      "...........",
      "...........",
      "...........",
      "..........."
    ],
    "side_to_move": "black"
  },
  "engine": {
    "depth": 4,
    "time_ms": 1500,
    "analyze_root": true,
    "include_move_maps": false
  }
}
```

### Apply one move

```json
{
  "command": "play_move",
  "position": {
    "rows": [
      "...........",
      "...........",
      "...........",
      "...........",
      "...........",
      "B.B.B.B....",
      "...........",
      "...........",
      "...........",
      "...........",
      "..........."
    ],
    "side_to_move": "black"
  },
  "move": {"row": 5, "col": 8}
}
```

## Website-side notes

The website server can spawn the bridge as a child process per request for v1. That keeps the integration stateless and avoids managing another HTTP service or port.

Suggested website responsibilities:

* validate user auth and rate limits
* normalize board payloads from the analyze page
* spawn the Python bridge
* return the bridge JSON directly, or reshape it into the website API format

Suggested engine responsibilities:

* validate board and move payloads
* analyze positions
* apply moves with exact rule handling
* serialize results in a stable machine-readable shape
