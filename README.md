# Plex Spoiler Shield

Automatically hides episode titles, summaries, and thumbnails for unwatched TV episodes in Plex. Works with all clients — no proxy needed.

## How It Works

```
Plex Client  →  Plex Server (:32400)     ← metadata already obscured
                       ↑
              Spoiler Shield (:32401)     ← modifies Plex metadata directly
              ├─ Unwatched? → Obscure title, thumb, summary via Plex API
              └─ Watched?   → Restore original metadata
                       ↑
              Plex Webhook (media.scrobble) + background poll
```

- On startup, the service scans all TV episodes and obscures unwatched ones by modifying Plex's actual metadata via its API
- Original metadata is safely stored in a local SQLite database before modification
- When you finish watching an episode, Plex sends a webhook — the service immediately restores the real title, summary, and thumbnail
- A background poll runs every 10 minutes as a safety net for missed webhooks
- Fields are locked after modification so library scans don't overwrite the changes

## Requirements

- **Docker** (or Docker Desktop on Windows)
- **Plex Media Server** running on the same machine
- **Plex Pass** (required for webhook support)

## Quick Start

1. **Clone the repo**
   ```bash
   git clone https://github.com/your-user/plex-spoiler-shield.git
   cd plex-spoiler-shield
   ```

2. **Create your `.env` file**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set your `PLEX_TOKEN`. To find your token, see [Plex's guide](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

3. **Build and run**
   ```bash
   docker compose up -d
   ```

4. **Configure Plex webhook**

   In Plex Settings → Webhooks, add:
   ```
   http://localhost:32401/webhook/plex
   ```

5. **Verify** — check the service status:
   ```bash
   curl http://localhost:32401/status
   ```

That's it. No client configuration needed — all clients see the obscured metadata natively.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/status` | GET | List of currently obscured episodes |
| `/webhook/plex` | POST | Plex webhook receiver |
| `/restore/all` | POST | Emergency restore — reverts ALL obscured episodes |

## Configuration

### Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `PLEX_URL` | `http://host.docker.internal:32400` | Plex server URL (from inside Docker) |
| `PLEX_TOKEN` | — | Your Plex authentication token |
| `PROXY_PORT` | `32401` | Port the service listens on |
| `DB_PATH` | `/data/watch_state.db` | SQLite database path inside the container |
| `POLL_INTERVAL` | `600` | Background poll interval in seconds |
| `LOG_LEVEL` | `info` | Logging level |

### YAML Config (`config.yml`)

Fine-grained control over what gets obscured:

```yaml
# Which TV libraries to protect (empty = all)
protected_libraries: []

# Toggle individual obfuscation features
obfuscation:
  title: true       # Replace title with "Episode N"
  summary: true     # Blank out summary/description
  thumbnail: true   # Swap episode thumb with series poster
  roles: true       # Not supported in direct mode (logged as warning)

# Customize the replacement title
title_template: "Episode {n}"
```

## Safety Features

- **Original metadata is preserved** in a local database before any modifications
- **Safe upsert** — if an episode is already obscured, its stored originals won't be overwritten
- **Crash recovery** — each episode is written to Plex then immediately marked in the DB, so at most one episode can be inconsistent after a crash
- **Emergency restore** — `POST /restore/all` reverts every obscured episode to its original metadata
- **Field locking** — modified fields are locked (`field.locked=1`) so Plex library scans won't overwrite them; restoring unlocks them and triggers a metadata refresh

## Known Limitations

- **Guest stars / roles** cannot be modified via the Plex REST API. The `roles` config option is accepted but has no effect; a warning is logged on startup.
- **One shared watch state** per household — if anyone has watched an episode, it's revealed for everyone.

## Project Structure

```
plex-spoiler-shield/
├── app/
│   ├── config.py           # Settings (env vars + YAML)
│   ├── database.py         # SQLite init (watch_state + metadata_snapshot)
│   ├── entrypoint.py       # Uvicorn launcher
│   ├── main.py             # FastAPI app entry point
│   ├── routers/
│   │   ├── restore.py      # /restore/all and /status endpoints
│   │   └── webhook.py      # Plex webhook receiver (media.scrobble)
│   └── services/
│       ├── plex_client.py   # Plex API client (read)
│       ├── plex_writer.py   # Plex API client (write — obscure/restore)
│       ├── snapshot.py      # Metadata snapshot CRUD
│       ├── sync.py          # Initial sync + background poll + reconciliation
│       └── watch_state.py   # Watch state CRUD
├── tests/
├── config.yml              # Obfuscation settings
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Development

Run locally without Docker:

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
pip install pytest pytest-asyncio respx
cp .env.example .env
# edit .env — set PLEX_URL to http://localhost:32400 and DB_PATH to ./watch_state.db
uvicorn app.main:app --reload --port 32401
```

Run tests:

```bash
pytest -v
```
