<div align="center">

# Sublarr

<img src="logo.png" alt="Sublarr Logo" width="140" />

### Subtitle Manager & Downloader for Anime and Media

*arr-compatible · Self-hosted · Open Source · Anime-first scoring

[![Version](https://img.shields.io/github/v/release/Nreel/sublarr?label=version&color=teal)](https://github.com/Nreel/sublarr/releases/latest)
[![CI](https://github.com/Nreel/sublarr/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/Nreel/sublarr/actions/workflows/ci.yml)
[![security](https://img.shields.io/badge/ruff_%2B_bandit_%2B_pip--audit_%2B_npm_audit_%2B_Semgrep_%2B_Trivy-22c55e.svg)](#-security)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776ab.svg)](https://www.python.org/)
[![React 19](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-ghcr.io-2496ed.svg)](https://github.com/Nreel/sublarr/pkgs/container/sublarr)

---

**[Quick Start](#-quick-start)** · **[Configuration](#️-configuration)** · **[Integrations](#-integrations)** · **[Limitations](#️-known-limitations)**

</div>

---

Sublarr is a self-hosted subtitle manager for anime and media libraries. It searches subtitle providers, scores the results (ASS-first), downloads the best match and gives you tools to edit, sync and convert subtitles — all on your LAN.

Connect it to Sonarr/Radarr and it reacts to imports via webhooks, or run it standalone: it watches your media folders and reads `.nfo` metadata, no *arr required.

---

## 🚀 Quick Start

Create a `docker-compose.yml`:

```yaml
services:
  sublarr:
    image: ghcr.io/nreel/sublarr:latest
    container_name: sublarr
    ports:
      - "5765:5765"
    volumes:
      - ./config:/config        # database, backups, logs
      - /path/to/media:/media   # your media library (same path your media server sees)
    environment:
      - PUID=1000
      - PGID=1000
    restart: unless-stopped
```

```bash
docker compose up -d
```

Open **http://localhost:5765**. The onboarding wizard walks you through languages, providers and automation.

- **PUID / PGID:** the container starts as root, remaps its `sublarr` user to `PUID`/`PGID`, makes `/config` owned by that user, then drops privileges with `gosu` and runs the app as `PUID:PGID`. `/media` is left untouched — its permissions must already allow that user to read and write. Use `id $USER` on the host to find the right IDs.
- More setups (PostgreSQL, Redis, reverse proxy, resource limits): [docker-compose.yml](docker-compose.yml), [docker-compose.postgres.yml](docker-compose.postgres.yml), [docker-compose.redis.yml](docker-compose.redis.yml).

---

## ⚙️ Configuration

Almost everything — providers and API keys, languages, Sonarr/Radarr/media-server connections, path mapping, automation, translation — is configured in the **Settings UI and stored in the database**. `SUBLARR_*` environment variables for those settings are ignored (Sublarr logs a warning at startup when it finds one).

Only these bootstrap variables are read from the environment (`backend/config_settings.py` → `BootSettings`):

| Variable | Default | Description |
|---|---|---|
| `SUBLARR_PORT` | `5765` | HTTP port |
| `SUBLARR_API_KEY` | *(empty)* | API key (`X-Api-Key` header). Set: mirrored into the settings store at startup, where the UI shows it and rotation is refused. Unset: Sublarr keeps a key in the store (auto-generated on first start, rotatable in Settings → System → API Keys). Explicitly empty: auth off |
| `SUBLARR_CORS_ORIGINS` | *(empty)* | Extra Socket.IO origins, comma-separated. Sublarr's own origin is always allowed; behind a reverse proxy, forward the original `Host` header (nginx: `proxy_set_header Host $http_host;`) or list the public origin here |
| `SUBLARR_MEDIA_PATH` | `/media` | Media library root inside the container |
| `SUBLARR_CONFIG_DIR` | `/config` | Persistent config directory |
| `SUBLARR_DB_PATH` | `/config/sublarr.db` | SQLite database path |
| `SUBLARR_DATABASE_URL` | *(empty)* | SQLAlchemy URL (e.g. PostgreSQL); wins over `DB_PATH` |
| `SUBLARR_REDIS_URL` | *(empty)* | Optional Redis for cache and queue |
| `SUBLARR_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SUBLARR_LOG_FILE` | `/config/sublarr.log` (image) | Log file path |
| `SUBLARR_LOG_FORMAT` | `text` | `text` or `json` |
| `SUBLARR_UPDATE_REPO` | `Nreel/sublarr` | GitHub repo the update check polls (`/api/v1/update`) |
| `SUBLARR_SCHEDULER_ROLE` | `primary` | `disabled` on extra replicas so recurring jobs do not run twice |
| `PUID` / `PGID` | `1000` | User/group the app runs as (see [Quick Start](#-quick-start)) |
| `UMASK` | `022` | umask for files written into `/media` |

The Settings UI is the full configuration reference; the bootstrap variables above are the only ones read from the environment.

> **Hardlinks:** most Sonarr/Radarr setups hardlink the library to the download folder. A container remux (foreign-track cleanup, signs removal, stream removal) rewrites the file and breaks that hardlink. The default hardlink policy `skip` refuses to remux hardlinked files.

---

## 🔌 Integrations

- **Sonarr & Radarr** — add the connection in *Settings → Connections*, then in Sonarr/Radarr add a webhook (*Settings → Connect → Webhook*) to `http://sublarr:5765/api/v1/webhook/sonarr` (or `/radarr`) for *On Import* and *On Upgrade*.
- **Jellyfin / Emby / Plex / Kodi / Shoko** — add the server in *Settings → Connections*; Sublarr triggers a rescan after each subtitle download. Shoko additionally supplies authoritative AniDB IDs and absolute episode numbers.
- **Standalone** — point Sublarr at your media folders; new video files are added to the wanted list.
- **Remote *arr hosts** — when paths differ between hosts, set a path mapping in *Settings → Connections*.

---

## ⚠️ Known limitations

- **One shared password, no user accounts.** No usernames, roles or per-user audit trail. For multi-user setups put it behind a reverse proxy with forward-auth; Sublarr can read proxy auth headers (Authelia / authentik).
- **One instance per library.** The scheduler assumes a single primary; extra replicas need `SUBLARR_SCHEDULER_ROLE=disabled`. No worker pool, no multi-host distribution.
- **No auto-update, by design.** The UI tells you when a newer release exists; you run the upgrade. Read the [CHANGELOG](CHANGELOG.md) first.
- **Docker is the supported path.** Running from source is for development; bare-metal installs are not tested.
- **Provider coverage depends on your accounts.** Several providers need credentials or an API key; without them you run a smaller subset.
- **Anime-first defaults.** ASS gets a large scoring bonus over SRT — deliberate for anime, less relevant for English live-action.
- **Solo-maintained.** Bug reports get read; response time varies.
- **Docs can drift.** If [the documentation in this repo](README.md) and the running app disagree, trust the app and [open an issue](https://github.com/Nreel/sublarr/issues).

Keep backups of your subtitle files before enabling automation.

---

## 🔒 Security

CI runs on every push to `master`.

- **Blocks the build:** `ruff check` + `ruff format --check`, `pip-audit -r requirements.txt` (no ignored advisories), `bandit` at HIGH severity / HIGH confidence ([`backend/.bandit`](backend/.bandit)), `npm audit --omit=dev --audit-level=high`, custom lint gates (`is_safe_path()` argument order, UI-first config, no `routes` imports in `services`), backend and frontend test suites.
- **Reported in the CI job log, non-blocking:** Semgrep, Trivy, bandit findings below the gate, `npm audit` over dev dependencies. Nothing is uploaded to GitHub code scanning.

Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

---

## 💻 Development

Workflow (branching, commits, release order): [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
# First-time setup (Python + Node dependencies, optional pre-commit hooks)
npm run setup:sh      # Linux/Mac
npm run setup:ps1     # Windows PowerShell

# Backend (:5765) + frontend (:5173)
npm run dev

# Tests
cd backend && python -m pytest
cd frontend && npm test

# Lint & type check
cd backend && ruff check . && ruff format --check .
cd frontend && npm run lint && npx tsc --noEmit
```

### Building the image

```bash
scripts/docker-build.sh        # Linux/Mac  (Windows: scripts/docker-build.ps1)
```

Wraps `docker build` with `VERSION` baked from `backend/VERSION` and prints a
version suggestion for your changes. Pass extra args, e.g.
`scripts/docker-build.sh -t sublarr:dev .`.

### Deploying a test image to a server

Quick iteration on a real server without touching the compose file between builds:

```bash
cp scripts/deploy.local.env.example scripts/deploy.local.env   # gitignored; see SSH setup inside
npm run deploy:dry                                             # print every command, run none
npm run deploy:ps1                                             # Windows
npm run deploy:sh                                              # Linux/Mac
```

The script builds the current working tree (uncommitted changes included),
ships the image over SSH (`scp` / `ssh docker load`) and — with
`DEPLOY_COMPOSE_DIR` set — recreates the stack (`docker compose up -d
--force-recreate`). `deploy.local.env` controls:

| Key | Effect |
|---|---|
| `DEPLOY_HOST` | SSH target (`user@host` or a `~/.ssh/config` alias); auth via SSH keys, nothing stored here |
| `DEPLOY_IMAGE` / `DEPLOY_TAG` | Image name and tag |
| `DEPLOY_OVERWRITE=true` | Constant tag (default `dev`): every deploy replaces it, old image pruned — the server compose keeps pointing at the same tag |
| `DEPLOY_OVERWRITE=false` | Tag = `sha-<git sha>`; each commit keeps its own image |
| `DEPLOY_PLATFORM` | Cross-build for a different server arch, e.g. `linux/arm64` (buildx + QEMU); empty builds this machine's arch |
| `DEPLOY_COMPOSE_DIR` / `DEPLOY_REMOTE_CMD` | Post-load command on the server (compose restart, or anything custom) |

### Images from CI

Pushed commits can also be built by GitHub Actions — workflow **"Build & Push
Docker Image"** (manual dispatch): multi-arch (amd64+arm64), pushes
`ghcr.io/nreel/sublarr:<branch>` and `:sha-<git sha>`; an optional `version`
input adds a version tag and mirrors `-rc` builds to Docker Hub. Releases are
tagged and published by `release.yml` (`:latest` + version tags).

Every instance serves its own API reference at `/api/docs` (Swagger UI) and `/api/v1/openapi.json`. Further reading: [docs/API.md](docs/API.md) · [docs/CUSTOM_PROVIDER_API.md](docs/CUSTOM_PROVIDER_API.md) · [docs/THIRD-PARTY-LICENSES.md](docs/THIRD-PARTY-LICENSES.md) · [ROADMAP.md](ROADMAP.md).

AI was used as a coding assistant during development (scaffolding, test drafting, refactoring sweeps, documentation drafts); architecture, scoring, provider integrations and release decisions were made and debugged by hand.
