# Anti-Gomoku Online

Beta 1.0. Last updated: `2026-04-25`

Anti-Gomoku Online is a browser-first Anti-Gomoku app with online rooms, engine games, local analysis, replay tools, record archives, lightweight accounts, and an optional Electron shell.

The production app is one Node.js server:

- serves the React single-page app from `site/`
- hosts the online room, account, lobby, history, chat, and engine APIs
- calls the vendored Python Ukumog engine bridge from `vendor/ukumog-engine`

Online play currently uses `HTTP + polling`, not WebSocket.

## What's New In Beta 1.0

- Added play-vs-engine rooms with configurable engine depth and time cap.
- Engine games behave like normal rooms, but are unrated, disallow draws, allow takebacks, allow rematches, and record match history.
- Local practice now opens the analysis board directly.
- Abandoning an active game now records a loss for the leaver and a win for the opponent.
- Human rooms remain available to the opponent after one player leaves, then close after both players leave.
- Custom clock settings now use working sliders for base time and increment.
- Analysis view has more stable keyboard navigation and a more compact top-move panel.
- The Docker image now packages the vendored engine and Python bridge path.

See [CHANGELOG.md](CHANGELOG.md) for the running release journal.

## Current Features

### Match and Room Flow

- Online public rooms, hidden rooms, and direct invites
- Play with engine from the same room flow
- Spectator mode for started rooms
- Join by room code or invite link
- Continuous rematches inside the same room
- Board size, host color, clock preset, custom base time, and increment settings
- In-room chat and spectator roster
- Draw, takeback, and rematch negotiation for human games
- Endgame checkout with rating summary and review entry

### Accounts and Hall

- Guest sessions
- Register, login, and logout
- User search
- Public room browser
- Pending invite list
- Profiles, presence, match history, and rating curve
- Clickable opponent names in match history

### Records, Review, and Engine

- Custom PGN-like format: `AntiGomokuPGN/1`
- Import, export, branch creation, and mainline promotion
- Local archive in browser storage
- Auto-archive for finished online games
- Review keyboard navigation
- Engine analysis for non-terminal `11x11` positions
- Evaluation graph and top-candidate display

### Rating System

- Registered users start at `1000`
- Only registered-vs-registered human online games are rated
- Engine games and guest-only games are unrated
- Match history stores historical rating snapshots

## Code Map

- `server.mjs`: Node.js server, APIs, room lifecycle, persistence, engine bridge calls
- `anti-gomoku.jsx`: frontend app state and screen routing
- `hub-ui.jsx`: hall, profile, history, rating curve, and room creation UI
- `game-ui.jsx`: board, online game, review UI, chat, room actions, endgame modal
- `game-core.mjs`: pure game rules, board state, clocks, result checks
- `game-record.mjs`: record tree model, import/export, archive helpers
- `app-client.mjs`: browser API client and session-token helpers
- `online-room.mjs`: room code, invite link, clipboard, URL helpers
- `renderer.jsx`: browser entry point
- `scripts/build.mjs`: esbuild pipeline for `site/`
- `electron/main.cjs`: Electron desktop entry
- `vendor/ukumog-engine`: vendored Python engine subtree
- `docs/archive`: older scaffolding and workflow notes

## Running Locally

### Requirements

- Node.js 20 or compatible
- npm
- Python 3.11+ for engine analysis and engine games

### Install

```powershell
npm install
```

### Browser Development

```powershell
npm run build:app
npm run server
```

Default URL:

```text
http://127.0.0.1:8787
```

### Engine Integration

The recommended engine layout is the vendored subtree:

```text
vendor/ukumog-engine
```

The server also detects a sibling checkout:

```text
../ukumog-engine
```

You can point to a specific engine checkout:

```powershell
$env:UKUMOG_ENGINE_ROOT="D:\ukumog-engine"
$env:UKUMOG_PYTHON="D:\Python311\python.exe"
npm run server
```

The engine bridge entry point is:

```text
python -m ukumog_engine.apps.json_bridge
```

### Common Scripts

- `npm run build:app`: builds browser assets into `site/`
- `npm run server`: starts the Node server
- `npm run desktop`: builds and starts the Electron shell
- `npm run dist`: builds the Windows installer

## Deployment Guide

This section describes deploying the whole package on a Linux server: site, API server, persisted app data, and vendored engine bridge.

### Option A: Docker Compose

Docker Compose is the most repeatable path for beta deployments.

Requirements:

- Docker
- Docker Compose v2

Build and start:

```bash
git clone https://github.com/hdPotato34/Ukumog.git
cd Ukumog
docker compose up -d --build
```

The app listens on:

```text
http://SERVER_IP:8787
```

The compose file mounts:

```text
./data:/app/data
```

That keeps accounts, sessions, and registered-user match history across container rebuilds.

Useful operations:

```bash
docker compose logs -f
docker compose restart
docker compose pull
docker compose down
```

To upgrade:

```bash
git pull
docker compose up -d --build
```

### Option B: Bare-Metal Linux Service

Requirements:

- Node.js 20+
- npm
- Python 3.11+
- git
- a reverse proxy such as nginx or Caddy for HTTPS

Install system packages on Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv build-essential
```

Install Node.js 20 using your preferred source. For example, with NodeSource:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

Deploy the app:

```bash
sudo mkdir -p /opt/ukumog
sudo chown "$USER":"$USER" /opt/ukumog
git clone https://github.com/hdPotato34/Ukumog.git /opt/ukumog/app
cd /opt/ukumog/app
npm ci --ignore-scripts --engine-strict=false
npm run build:app
mkdir -p data
```

Smoke test:

```bash
PORT=8787 \
UKUMOG_ENGINE_ROOT=/opt/ukumog/app/vendor/ukumog-engine \
UKUMOG_PYTHON=python3 \
node server.mjs
```

Health check:

```bash
curl http://127.0.0.1:8787/health
```

Engine check:

```bash
curl http://127.0.0.1:8787/api/engine/info
```

### systemd Unit

Create `/etc/systemd/system/ukumog.service`:

```ini
[Unit]
Description=Ukumog Anti-Gomoku Online
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/ukumog/app
Environment=NODE_ENV=production
Environment=PORT=8787
Environment=UKUMOG_ENGINE_ROOT=/opt/ukumog/app/vendor/ukumog-engine
Environment=UKUMOG_PYTHON=python3
ExecStart=/usr/bin/node server.mjs
Restart=always
RestartSec=5
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
```

Set permissions and start:

```bash
sudo chown -R www-data:www-data /opt/ukumog/app/data
sudo systemctl daemon-reload
sudo systemctl enable --now ukumog
sudo systemctl status ukumog
```

Watch logs:

```bash
journalctl -u ukumog -f
```

### Reverse Proxy

Example nginx site:

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Add HTTPS with Certbot, Caddy, or your normal certificate workflow.

### Deployment Environment Variables

- `PORT`: HTTP port, default `8787`
- `HOST`: bind host, default `0.0.0.0`
- `UKUMOG_ENGINE_ROOT`: path to the engine checkout or vendored subtree
- `UKUMOG_PYTHON`: Python executable, default auto-detects `python3`/`python`
- `UKUMOG_ENGINE_PERSISTENT`: set to `0` to disable the persistent bridge process
- `ENGINE_REQUEST_TIMEOUT_MS`: engine API timeout, default `15000`
- `HTTPS_KEY_PATH`, `HTTPS_CERT_PATH`, `HTTPS_PASSPHRASE`: optional direct HTTPS support

### Persistent Data

Server data is stored at:

```text
data/app-state.json
```

Back it up before deploys:

```bash
cp data/app-state.json data/app-state.$(date +%Y%m%d-%H%M%S).json
```

Live rooms are in memory. A server restart clears unfinished rooms but keeps registered users, sessions, and match history.

### Release Checklist

Run before pushing a release:

```bash
npm ci --ignore-scripts --engine-strict=false
npm run build:app
node server.mjs
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/api/engine/info
```

For Docker:

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100
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
- `GET /api/engine/info`
- `POST /api/engine/analyze`
- `POST /api/engine/cache`
- `GET /health`

Session tokens are accepted through request headers:

- `Authorization: Bearer <token>`
- `x-session-token: <token>`

Tokens should not be passed through URL query parameters.

## Known Limits

- Online sync still depends on polling instead of push events.
- A server restart does not restore live rooms or unfinished games.
- Rooms are kept in single-process memory and are not ready for multi-instance scaling.
- Local record archives depend on browser `localStorage` and do not sync across devices.
- Engine support currently targets `11x11` positions.
- There is no full automated test suite yet.
- Production deployments still need normal hardening around rate limits, logs, backups, and moderation.

## Suggested Next Steps

- Persist rooms and games so server restarts can recover state.
- Add automated tests for rules and core API flows.
- Add rate limiting and structured server logs.
- Consider SSE or another push model if polling becomes the next bottleneck.
