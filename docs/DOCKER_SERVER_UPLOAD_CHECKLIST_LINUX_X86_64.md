# Docker Server Upload Checklist

Last updated: `2026-04-22`

## Scope

This checklist is for handing off the internal-test Linux x86_64 Docker tar package to a server.

Frozen release for this cut:

- Image tag: `anti-gomoku-room-server:2026-04-21-r3`
- Archive: `anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar`
- Checksum: `anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.sha256`

## Files To Carry

Take these four files together:

- `anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar`
- `anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.sha256`
- `anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.manifest.json`
- `anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.runbook.md`

Optional but recommended:

- this checklist

## Local Pre-Upload Check

Confirm before upload:

- `release/docker/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar` exists
- `release/docker/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.sha256` exists
- `release/docker/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.manifest.json` exists
- `release/docker/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.runbook.md` exists
- `release/docker/anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.checklist.md` exists
- `manifest.json` shows the expected `gitCommit`, `imageTag`, and `archiveSha256`

PowerShell quick check:

```powershell
Get-ChildItem release\docker\anti-gomoku-room-server_2026-04-21-r3_linux-x86_64*
Get-Content release\docker\anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.manifest.json
```

## Upload Examples

### Upload with `scp`

```bash
scp \
  anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar \
  anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.sha256 \
  anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.manifest.json \
  anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.runbook.md \
  anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.checklist.md \
  user@<server-ip>:/opt/anti-gomoku/releases/2026-04-21-r3/
```

### Upload with `rsync`

```bash
rsync -avP \
  anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar \
  anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.sha256 \
  anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.manifest.json \
  anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.runbook.md \
  anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.checklist.md \
  user@<server-ip>:/opt/anti-gomoku/releases/2026-04-21-r3/
```

## Server Landing Commands

### 1. Prepare the release directory

```bash
mkdir -p /opt/anti-gomoku/releases/2026-04-21-r3
cd /opt/anti-gomoku/releases/2026-04-21-r3
```

### 2. Verify checksum after upload

```bash
sha256sum -c anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.sha256
```

Expected result:

- `anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar: OK`

### 3. Load the image

```bash
docker load -i anti-gomoku-room-server_2026-04-21-r3_linux-x86_64.tar
```

### 4. Start with `docker run`

```bash
docker rm -f anti-gomoku-room-server 2>/dev/null || true
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

### 5. Confirm container state

```bash
docker ps
docker logs --tail 100 anti-gomoku-room-server
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/api/engine/health
```

## First Acceptance On Server

Verify at least:

1. The hall page opens normally.
2. `9x9` engine-room can start.
3. `9x9` review can analyze.
4. Unsupported board sizes return `unsupported_board_size`.

## Fast Rollback

If the new container looks wrong:

```bash
docker stop anti-gomoku-room-server
docker rm anti-gomoku-room-server
docker run -d \
  --name anti-gomoku-room-server \
  --restart unless-stopped \
  -p 8787:8787 \
  anti-gomoku-room-server:<previous-tag>
```

If the previous image is not loaded yet:

```bash
docker load -i anti-gomoku-room-server_<previous-version>_linux-x86_64.tar
```
