# Docker Server Release Runbook

Last updated: `2026-04-21`

## Release Target

- Release grade: internal test release
- Target platform: `linux/amd64`
- Delivery shape:
  - Docker image tar
  - SHA-256 checksum
  - release manifest with commit and build metadata
  - this runbook

Frozen release naming for this cut:

- Image tag: `anti-gomoku-room-server:2026-04-21-r3`
- Archive: `anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar`
- Checksum: `anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.sha256`

## What This Package Contains

- One single container image
- Node `server.mjs`
- built frontend assets
- Python `model-server`
- packaged `ukumog-engine`

This release only exposes the Node service externally on `8787/tcp`.

- External port: `8787`
- Internal engine service port: `8011`
- `8011` stays container-internal unless you temporarily publish it for debugging

## Release Preconditions

Run the repo-level checks first:

```powershell
npm run test:engine-preflight
python -m unittest discover -s model-server/tests -p "test_*.py"
```

Or use the bundled release helper:

```powershell
npm run release:docker:verify
```

## Build and Package

### 1. Build the Linux x86_64 image

```powershell
npm run release:docker:build
```

Equivalent raw command:

```powershell
docker build --platform linux/amd64 -t anti-gomoku-room-server:2026-04-21-r3 .
```

### 2. Smoke-check the container locally

```powershell
npm run release:docker:smoke
```

This checks:

- `GET /health`
- `GET /api/engine/health`

### 3. Export the image tar and checksum

```powershell
npm run release:docker:save
```

Equivalent raw commands:

```powershell
docker save -o release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar anti-gomoku-room-server:2026-04-21-r3
Get-FileHash release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar -Algorithm SHA256 | ForEach-Object {
  "$($_.Hash.ToLower())  anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar"
} | Set-Content release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.sha256
```

The helper also writes:

- `release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.sha256`
- `release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.manifest.json`
- `release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.runbook.md`
- `release/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.checklist.md`

### 4. One-shot internal release flow

```powershell
npm run release:docker:package
```

This runs:

1. repo verification
2. image build
3. container smoke check
4. tar export
5. checksum generation
6. manifest generation

## Server Load and Start

For upload and server-side handoff, use the separate checklist:

- `anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.checklist.md`

### Load the image tar

```bash
docker load -i anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar
```

### Start with `docker run`

```bash
docker run -d \
  --name anti-gomoku-room-server \
  --restart unless-stopped \
  -p 8787:8787 \
  -e HOST=0.0.0.0 \
  -e PORT=8787 \
  -e UKUMOG_HOST=127.0.0.1 \
  -e UKUMOG_PORT=8011 \
  -e ENGINE_SERVICE_ORIGIN=http://127.0.0.1:8011 \
  -e ENGINE_SERVICE_TIMEOUT_MS=15000 \
  anti-gomoku-room-server:2026-04-21-r3
```

### Start with `docker compose`

```bash
docker compose up -d
```

The tracked compose file already assumes:

- `platform: linux/amd64`
- external `8787:8787`
- internal engine service only

## Health Checks and First Acceptance

### Basic health

```bash
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/api/engine/health
```

Expected:

- both return `200`
- `/api/engine/health` returns `ok: true`

### First acceptance

Verify at least:

1. Hall page opens in browser
2. `9x9` engine-room can start
3. `9x9` review can analyze
4. unsupported board sizes return `unsupported_board_size`

## Rollback

### Roll back to a previous image already loaded on the server

```bash
docker stop anti-gomoku-room-server
docker rm anti-gomoku-room-server
docker run -d \
  --name anti-gomoku-room-server \
  --restart unless-stopped \
  -p 8787:8787 \
  anti-gomoku-room-server:<previous-tag>
```

### Roll back from a previous tar

```bash
docker load -i anti-gomoku-room-server_<previous-version>_linux-x86_64.tar
```

Then start the older tag with the same `docker run` or `docker compose` flow.

## Known Limits

- Live rooms and unfinished games do not survive server restarts.
- Online play still uses HTTP polling rather than WebSocket.
- This release is only for Linux x86_64 Docker deployment.
- Electron release delivery is not included in this package.
- Multi-board runtime currently relies on search-first paths; ML-specific `11x11` coupling is not part of this release scope.
