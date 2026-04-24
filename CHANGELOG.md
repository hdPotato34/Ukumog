# Changelog

## Beta 1.0 - 2026-04-25

This is the first beta-ready cut of the full Ukumog web package: site, online room server, local review tools, and vendored engine bridge.

### Added

- Play-vs-engine room mode with configurable depth and time cap.
- Engine games in the normal room lifecycle, including rematches, takebacks, match history, and local record archive support.
- Direct local analysis board entry from Local Practice.
- Linux deployment guide in `README.md`.
- Docker image support for the vendored engine bridge.
- Archived scaffolding notes under `docs/archive/`.

### Changed

- Create Room now separates game mode, board/color, clock, visibility, and engine controls.
- Custom clock uses working base-time and increment sliders.
- Engine rooms are unrated, disallow draws, allow takebacks, and allow rematches.
- Analysis top-candidate display is more compact and stable.
- Review keyboard navigation avoids focus-driven page jumps.

### Fixed

- Engine now moves correctly after rematches.
- Explicitly leaving an active game counts as a loss.
- Human rooms terminate only after both players leave.
- Engine rooms terminate when the human leaves, while still recording the game.
- Engine rooms no longer show the online invite-link panel.

### Validation

- `npm run build:app`
- Local server smoke tests for engine room creation and leave behavior
- Local server smoke tests for human abandonment
- Local server smoke tests for engine rematch move scheduling
- User local test pass before release

### Known Limits

- Live rooms are still in memory and do not survive server restart.
- Online sync still uses polling.
- Engine support is focused on `11x11`.
- Production hardening is still incremental: rate limits, structured logs, moderation, and admin tooling remain future work.
