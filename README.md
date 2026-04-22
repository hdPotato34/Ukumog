# Anti-Gomoku Online

Last updated: `2026-04-21`

## Overview

Anti-Gomoku Online is a browser-first Anti-Gomoku project with local practice, online rooms, replay tools, record archives, and a lightweight account system.

Current shape of the project:

- One Node.js HTTP/HTTPS server serves both static assets and online match APIs.
- One React single-page frontend drives the hall, profile, room, and review flows.
- One Python `model-server` wraps `ukumog-engine` for engine-room and review AI.
- One optional Electron shell runs the same app as a desktop build.

Online play currently uses `HTTP + polling`. It does not use WebSocket yet.

AI-related flows now use the remote backend chain:

```text
React -> RemoteEngineClient -> server.mjs (/api/engine/*) -> model-server -> ukumog-engine
```

## Current Features

### Match and room flow

- Local practice mode
- Public rooms and invite-only rooms
- Spectator mode for started rooms
- Join by room code
- Invite link copy and auto-join
- Room reconnect before the game finishes
- Stable `roomId` plus per-game `game.id`
- Continuous rematches inside the same room, with a fresh game record each time
- Room settings for board size, host color, base time, and increment
- Public visibility toggle for online rooms, including direct invites
- Time presets: `3+2`, `5+3`, `10+5`, `15+10`, `Unlimited`, `Custom`
- Custom base time from `30s` to `2h`
- Custom increment from `0s` to `60s`
- In-room chat
- Spectator roster in the room view
- Draw, takeback, and rematch negotiation
- Endgame modal can be closed and reopened without leaving the room

### Accounts and hall

- Guest sessions
- Register, login, and logout
- User search
- Public room list in the hall
- Public room browser now lists both pending rooms and watchable active games
- Pending invites list
- Profile page for self and other users
- Profile presence status with direct room entry for visible active games
- Clickable opponent names in match history to jump to their profile

### Records and review

- Custom PGN-like format: `AntiGomokuPGN/1`
- Import, export, branch creation, and mainline promotion
- Save a local practice position into the archive
- Auto-archive finished online games locally
- Review screen with branch navigation
- Keyboard and button navigation for move stepping
- Import modal and clipboard export
- Local archive naming and save feedback
- Match history list and rating curve

### Board interaction

- Last-move and result highlighting
- Private right-click point marks
- Private right-click line marks with grid snapping
- Clear marks button for the current board view

### Rating system

- Registered users start at `1000`
- Only registered-vs-registered online games are rated
- Rating temperature starts high and cools down over early games
- Ratings are shown in the hall, room, history, and profile UI
- Match history stores historical rating snapshots, not live values

## Code Map

- `server.mjs`
  Node.js server entry. Handles static files, auth, users, rooms, online games, history, and persistence.
- `anti-gomoku.jsx`
  Frontend app state and screen routing.
- `hub-ui.jsx`
  Hall, profile, history, and rating-curve UI.
- `game-ui.jsx`
  Board, local game, online game, review UI, chat, negotiation controls, and endgame modal.
- `game-core.mjs`
  Pure rules layer: board state, move legality, result checks, time controls, and clock ticking.
- `game-record.mjs`
  Record tree model, import/export, branching, and archive helpers.
- `app-client.mjs`
  Browser API client and session-token storage helpers.
- `online-room.mjs`
  Room code, invite link, clipboard, and room URL helpers.
- `renderer.jsx`
  Browser entry point.
- `scripts/build.mjs`
  `esbuild` pipeline that outputs web assets into `site/`.
- `electron/main.cjs`
  Electron desktop entry.
- `data/app-state.json`
  Lightweight persisted app state.

## Running Locally

### Requirements

- Node.js 20 or compatible
- npm

### Install

```powershell
npm install
```

### Browser development

```powershell
npm run build:app
node server.mjs
```

Default URL:

```text
http://127.0.0.1:8787
```

### AI-enabled local run

Engine-room and review analysis now depend on the Python engine service. From the repo root:

```powershell
py -3.11 -m venv model-server\.venv
model-server\.venv\Scripts\python -m pip install --upgrade pip
model-server\.venv\Scripts\python -m pip install -r model-server\requirements-serving.txt
model-server\.venv\Scripts\python -m pip install -e .\ukumog-engine
model-server\.venv\Scripts\python -m uvicorn app:app --app-dir model-server/src/serving --host 127.0.0.1 --port 8011
```

Then in another terminal:

```powershell
npm run build:app
npm run server
```

Default engine health URLs:

```text
http://127.0.0.1:8011/health
http://127.0.0.1:8787/api/engine/health
```

### Common scripts

- `npm run build:app` builds the web app into `site/`
- `npm run server` starts the Node server
- `npm run test:engine-contract` validates the end-to-end engine contract across `RemoteEngineClient -> Node -> Python`
- `npm run test:engine-preflight` runs the current engine release preflight: `build + rules compare + engine contract + engine smoke + review smoke`
- `npm run test:engine-smoke` runs the engine-room smoke regression
- `npm run test:review-smoke` runs the review regression for remote analysis and branching
- `npm run test:rules-compare` compares `game-core.mjs` rules against `ukumog-engine`
- `npm run release:docker:verify` runs the repo-level release verification checks
- `npm run release:docker:build` builds the Linux x86_64 Docker image
- `npm run release:docker:smoke` smoke-checks the Docker container health endpoints
- `npm run release:docker:save` exports the Docker image tar, checksum, and manifest
- `npm run release:docker:package` runs verify + build + smoke + tar export in one flow
- `npm run desktop` builds and starts the Electron shell
- `npm run dist` builds the Windows installer

### Docker server release

The current Linux x86_64 Docker server release path is documented in:

- [docs/DOCKER_RELEASE_RUNBOOK_LINUX_X86_64.md](docs/DOCKER_RELEASE_RUNBOOK_LINUX_X86_64.md)

### Custom port

```powershell
$env:PORT=8790
node server.mjs
```

### HTTPS

```powershell
$env:HTTPS_KEY_PATH="D:\certs\server.key"
$env:HTTPS_CERT_PATH="D:\certs\server.crt"
node server.mjs
```

If the certificate has a passphrase:

```powershell
$env:HTTPS_PASSPHRASE="your-passphrase"
```

## API Summary

Main endpoints:

- `POST /api/auth/guest`
- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/me`
- `GET /api/me/history`
- `GET /api/lobby`
- `GET /api/users/search?q=...`
- `GET /api/users/:loginId`
- `POST /api/rooms`
- `POST /api/rooms/:roomId/join`
- `GET /api/rooms/:roomId`
- `POST /api/rooms/:roomId/move`
- `POST /api/rooms/:roomId/rematch`
- `POST /api/rooms/:roomId/request`
- `POST /api/rooms/:roomId/chat`
- `POST /api/rooms/:roomId/leave`
- `GET /health`

Session tokens are accepted through request headers:

- `Authorization: Bearer <token>`
- `x-session-token: <token>`

Tokens should not be passed through URL query parameters.

## Data and Persistence

### Persisted in `data/app-state.json`

- Registered users
- Sessions
- Password hashes and salts
- Recent online match history summaries for registered users

### Stored only in server memory

- Live rooms
- Active game state
- Active spectators and room visibility flags
- Room chat messages
- Negotiation request state
- Room timers

### Stored only in browser local storage

- Local record archive
- Local copies of finished online game records
- Local review branches and edits

## Important Model Notes

### Room and game are separate layers

- `roomId`
  Stable room identity used for invites, reconnect, and reopening the same room.
- `game.id`
  Identity for one concrete game inside the room. A rematch creates a new `game.id`.

This split is what makes later features easier:

- record storage
- match history
- review deep links
- per-game rating snapshots

### Rating rules

- Initial rating: `1000`
- Only games between two registered users are rated
- Temperature is high early and gradually stabilizes
- History stores the rating snapshot from that time

## Known Limits

- Online sync still depends on polling instead of push events
- A server restart does not restore live rooms or unfinished games
- Rooms are still kept in single-process memory and are not ready for multi-instance scaling
- Local record archives depend on browser `localStorage` and do not sync across devices
- Engine-room and review AI require the separate Python engine service to be running
- Engine AI availability depends on the Python `model-server` and its current supported board-size/runtime paths
- There is no full automated test suite yet
- There is no admin tooling, moderation, rate limiting, or audit trail for production use

## Cleanup in This Pass

- Fixed corrupted rating-delta text in the UI
- Removed duplicate dead formatting helpers
- Hardened session-token handling so tokens are no longer accepted from URL query parameters
- Rewrote `README.md` into a current, readable developer document

## Suggested Next Steps

- Persist rooms and games so server restarts can recover state
- Add automated tests for the rules layer and core API flows
- Continue hardening rate limits, logging, and auditability for online endpoints
- Evaluate `SSE` or another push model if polling becomes the next bottleneck
