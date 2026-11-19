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

**[Quick Start](#-quick-start)** · **[Configuration](#️-configuration)** · **[Integrations](#-integrations)** · **[Limitations](#️-known-limitations)** · **[Website](https://sublarr.de)** · **[Docs](https://sublarr.de/docs/)**

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

Open **http://localhost:5765**. The onboarding wizard walks you through languages, providers and automation. Next step: [First 10 minutes](https://sublarr.de/docs/getting-started/first-10-minutes/).

- **Unraid:** search for **Sublarr** in Community Applications (template: [unraid/README.md](unraid/README.md)).
- **PUID / PGID:** the container starts as root, remaps its `sublarr` user to `PUID`/`PGID`, makes `/config` owned by that user, then drops privileges with `gosu` and runs the app as `PUID:PGID`. `/media` is left untouched — its permissions must already allow that user to read and write. Use `id $USER` on the host to find the right IDs (Unraid uses `99`/`100`).
- More setups (PostgreSQL, Redis, reverse proxy, resource limits): [Installation](https://sublarr.de/docs/getting-started/installation/).

---

## ⚙️ Configuration

Almost everything — providers and API keys, languages, Sonarr/Radarr/media-server connections, path mapping, automation, translation — is configured in the **Settings UI and stored in the database**. `SUBLARR_*` environment variables for those settings are ignored (Sublarr logs a warning at startup when it finds one).

Only these bootstrap variables are read from the environment (`backend/config_settings.py` → `BootSettings`):

| Variable | Default | Description |
|---|---|---|
| `SUBLARR_PORT` | `5765` | HTTP port |
| `SUBLARR_API_KEY` | *(empty)* | Optional API key (`X-Api-Key` header); empty = no API-key auth |
| `SUBLARR_CORS_ORIGINS` | *(empty)* | Extra Socket.IO origins, comma-separated. Sublarr's own origin is always allowed; behind a reverse proxy, forward the original `Host` header (nginx: `proxy_set_header Host $http_host;`) or list the public origin here |
| `SUBLARR_MEDIA_PATH` | `/media` | Media library root inside the container |
| `SUBLARR_CONFIG_DIR` | `/config` | Persistent config directory |
| `SUBLARR_DB_PATH` | `/config/sublarr.db` | SQLite database path |
| `SUBLARR_DATABASE_URL` | *(empty)* | SQLAlchemy URL (e.g. PostgreSQL); wins over `DB_PATH` |
| `SUBLARR_REDIS_URL` | *(empty)* | Optional Redis for cache and queue |
| `SUBLARR_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SUBLARR_LOG_FILE` | `/config/sublarr.log` (image) | Log file path |
| `SUBLARR_LOG_FORMAT` | `text` | `text` or `json` |
| `SUBLARR_STATS_ENDPOINT` | `https://stats.sublarr.de/v1/ping` | Opt-in usage statistics target; empty disables sending |
| `SUBLARR_SCHEDULER_ROLE` | `primary` | `disabled` on extra replicas so recurring jobs do not run twice |
| `PUID` / `PGID` | `1000` | User/group the app runs as (see [Quick Start](#-quick-start)) |
| `UMASK` | `022` | umask for files written into `/media` |

Full reference: [Environment variables](https://sublarr.de/docs/getting-started/environment-variables/) · [Settings](https://sublarr.de/docs/user-guide/settings/).

> **Hardlinks:** most Sonarr/Radarr setups hardlink the library to the download folder. A container remux (foreign-track cleanup, signs removal, stream removal) rewrites the file and breaks that hardlink. The default hardlink policy `skip` refuses to remux hardlinked files.

---

## 🔌 Integrations

- **Sonarr & Radarr** — add the connection in *Settings → Connections*, then in Sonarr/Radarr add a webhook (*Settings → Connect → Webhook*) to `http://sublarr:5765/api/v1/webhook/sonarr` (or `/radarr`) for *On Import* and *On Upgrade*.
- **Jellyfin / Emby / Plex / Kodi / Shoko** — add the server in *Settings → Connections*; Sublarr triggers a rescan after each subtitle download. Shoko additionally supplies authoritative AniDB IDs and absolute episode numbers.
- **Standalone** — point Sublarr at your media folders; new video files are added to the wanted list.
- **Remote *arr hosts** — when paths differ between hosts, set a [path mapping](https://sublarr.de/docs/user-guide/path-mapping/) in *Settings → Connections*.

Walkthroughs: [Integrations](https://sublarr.de/docs/user-guide/integrations/) · [AniDB](https://sublarr.de/docs/user-guide/anidb/) · [Reverse proxy](https://sublarr.de/docs/troubleshooting/reverse-proxy/).

---

## ⚠️ Known limitations

- **One shared password, no user accounts.** No usernames, roles or per-user audit trail. For multi-user setups put it behind a reverse proxy with forward-auth; Sublarr can read proxy auth headers (Authelia / authentik).
- **One instance per library.** The scheduler assumes a single primary; extra replicas need `SUBLARR_SCHEDULER_ROLE=disabled`. No worker pool, no multi-host distribution.
- **No auto-update, by design.** The UI tells you when a newer release exists; you run the upgrade. Read the [CHANGELOG](CHANGELOG.md) first.
- **Docker is the supported path.** Running from source is for development; bare-metal installs are not tested.
- **Provider coverage depends on your accounts.** Several providers need credentials or an API key; without them you run a smaller subset.
- **Anime-first defaults.** ASS gets a large scoring bonus over SRT — deliberate for anime, less relevant for English live-action.
- **Solo-maintained.** Bug reports get read; response time varies.
- **Docs can drift.** If [the documentation](https://sublarr.de/docs/) and the running app disagree, trust the app and [open an issue](https://github.com/Abrechen2/sublarr/issues).

Keep backups of your subtitle files before enabling automation.

---

## 🔒 Security

CI runs on every push to `master`.

- **Blocks the build:** `ruff check` + `ruff format --check`, `pip-audit -r requirements.txt` (no ignored advisories), `bandit` at HIGH severity / HIGH confidence ([`backend/.bandit`](backend/.bandit)), `npm audit --omit=dev --audit-level=high`, custom lint gates (`is_safe_path()` argument order, UI-first config, no `routes` imports in `services`), backend and frontend test suites.
- **Reported in the CI job log, non-blocking:** Semgrep, Trivy, bandit findings below the gate, `npm audit` over dev dependencies. Nothing is uploaded to GitHub code scanning.

Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

---

## 💻 Development

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

Every instance serves its own API reference at `/api/docs` (Swagger UI) and `/api/v1/openapi.json`. Further reading: [Architecture](https://sublarr.de/docs/development/architecture/) · [API reference](https://sublarr.de/docs/development/api-reference/) · [Plugin development](https://sublarr.de/docs/development/plugin-development/) · [Database schema](https://sublarr.de/docs/development/database-schema/) · [ROADMAP.md](ROADMAP.md).

AI was used as a coding assistant during development (scaffolding, test drafting, refactoring sweeps, documentation drafts); architecture, scoring, provider integrations and release decisions were made and debugged by hand.
