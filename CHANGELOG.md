# Changelog

Notable changes to ChoreKeeper. The format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html): a patch fixes, a
minor adds, a major breaks something a household or an operator relies on.

Each release's section here becomes its GitHub Release notes, and a tag without one is refused
(`just release`, [.github/workflows/release.yml](.github/workflows/release.yml)). Every change
adds its line under **Unreleased** in the same commit; `release: X.Y.Z` turns that into the
version's section. History before the first tag is in `git log`, not here.

## [Unreleased]

## [0.2.0] - 2026-10-27

### Changed

- The in-app camera asks for a 1920x1440 picture instead of the browser's 640x480
  default, so photo checks see real detail (uploads stay capped at 1568 px).
- An automatic "fail" no longer takes money: on `llm_auto` chores it goes to the parent's
  review queue, the kid is told a parent will look, and only the parent's reject charges a
  penalty. Automatic passes are unchanged.
- Decider verdicts now say which photo each answer came from, and what every photo said,
  on the review screen, so an answer taken from the wrong photo is visible at a glance.

### Fixed

- `LLM_MAX_RETRIES` (also in Settings) was never applied: a dropped connection, timeout,
  5xx or empty reply from the vision model is now retried before the chore goes to review,
  and an error with no message now names its type instead of reading "vision endpoint error: ".

## [0.1.0] - 2026-10-26

The first tagged release.

### Added

- Release pipeline: a `vX.Y.Z` tag (`just release X.Y.Z`) runs the CI gates and publishes
  `ghcr.io/dmarchevsky/chorekeeper-api` and `chorekeeper-proxy`, plus a GitHub Release from
  this file.
- `just up-build`, `just pull`, `just prod-pull`.
- Optional d3-nano decider (halogen System One) as the photo checker, chosen in Settings;
  falls back to the vision LLM, then to review (spec §7.2).

### Changed

- Production no longer builds images: `docker-compose.prod.yml` runs the release named by the
  required `CHOREKEEPER_VERSION`.
- The dev stack defaults to the released images; `just up` no longer builds — use
  `just up-build` for the working tree.
- cloudflared 2026.8.3 → 2026.10.4.

[Unreleased]: https://github.com/dmarchevsky/chore-tracker/compare/v0.2.0...main
[0.2.0]: https://github.com/dmarchevsky/chore-tracker/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dmarchevsky/chore-tracker/releases/tag/v0.1.0
