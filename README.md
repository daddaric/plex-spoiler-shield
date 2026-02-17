# Plex Spoiler Shield

A metadata proxy that sits between your Plex clients and Plex server, hiding episode titles, summaries, thumbnails, and guest stars for unwatched TV episodes. No more accidental spoilers.

## How It Works

```
Plex Client  →  Spoiler Proxy (:32401)  →  Plex Server (:32400)
                       ↓
              Metadata Interceptor
              ├─ Unwatched? → Obscure title, thumb, summary
              └─ Watched?   → Pass through real metadata
                       ↓
              SQLite watch-state cache
                       ↑
              Plex Webhook (media.scrobble) + background poll
```

- All Plex API traffic flows through the proxy transparently
- Episode metadata responses are intercepted — unwatched episodes get their title replaced with "Episode N", summary blanked, and thumbnail swapped with the series poster
- Watch state is tracked via Plex webhooks (instant) with a background poll as a safety net
- One shared watch state per household — if anyone has seen it, it's revealed for everyone

## Requirements

- **Docker Desktop** (Windows)
- **Plex Media Server** running natively on the same Windows machine
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
   http://<your-machine-ip>:32401/webhook/plex
   ```

5. **Point your Plex clients at the proxy**

   Configure clients to connect to `http://<your-machine-ip>:32401` instead of the default Plex port.

## Configuration

### Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `PLEX_URL` | `http://host.docker.internal:32400` | Plex server URL (from inside Docker) |
| `PLEX_TOKEN` | — | Your Plex authentication token |
| `PROXY_PORT` | `32401` | Port the proxy listens on |
| `DB_PATH` | `/data/watch_state.db` | SQLite database path inside the container |
| `POLL_INTERVAL` | `600` | Background poll interval in seconds |
| `LOG_LEVEL` | `info` | Logging level |
| `SSL_CERTFILE` | — | Path to SSL certificate (optional) |
| `SSL_KEYFILE` | — | Path to SSL private key (optional) |

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
  roles: true       # Remove guest star credits

# Customize the replacement title
title_template: "Episode {n}"
```

## HTTPS / SSL

Plex clients may reject plain HTTP connections. To enable HTTPS:

1. **Generate a self-signed certificate:**
   ```bash
   bash scripts/generate-cert.sh
   ```

2. **Update `.env`:**
   ```
   SSL_CERTFILE=/certs/cert.pem
   SSL_KEYFILE=/certs/key.pem
   ```

3. **Uncomment the certs volume** in `docker-compose.yml`:
   ```yaml
   volumes:
     - ./certs:/certs:ro
   ```

4. Rebuild: `docker compose up -d --build`

## Windows Firewall

The proxy and webhook ports need to be accessible on your LAN. If connections are blocked, allow them through Windows Firewall:

```powershell
# Allow proxy port (run as Administrator)
netsh advfirewall firewall add rule name="Plex Spoiler Shield - Proxy" dir=in action=allow protocol=TCP localport=32401

# If using a separate webhook port
netsh advfirewall firewall add rule name="Plex Spoiler Shield - Webhook" dir=in action=allow protocol=TCP localport=32401
```

## Project Structure

```
plex-spoiler-shield/
├── app/
│   ├── config.py           # Settings (env vars + YAML)
│   ├── database.py         # SQLite init and connection
│   ├── entrypoint.py       # Uvicorn launcher with optional SSL
│   ├── main.py             # FastAPI app entry point
│   ├── models/
│   ├── routers/
│   │   ├── proxy.py        # Catch-all reverse proxy + metadata interception
│   │   └── webhook.py      # Plex webhook receiver (media.scrobble)
│   └── services/
│       ├── metadata.py     # Episode metadata obscuring (XML + JSON)
│       ├── plex_client.py  # Plex API client
│       ├── sync.py         # Initial sync + background poll loop
│       └── watch_state.py  # SQLite watch-state CRUD
├── k8s/
│   └── deployment.yml      # Kubernetes manifests
├── scripts/
│   └── generate-cert.sh    # Self-signed cert generator
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
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env — set PLEX_URL to http://localhost:32400 and DB_PATH to ./watch_state.db
uvicorn app.main:app --reload --port 32401
```

## Kubernetes Migration

The app is designed for an easy migration from Docker Desktop to a k8s homelab. All config is env-var driven — no code changes needed.

Ready-to-use manifests are in `k8s/deployment.yml`:
- **Deployment** — single replica with health/readiness probes
- **PersistentVolumeClaim** — 100Mi for the SQLite watch-state DB
- **Service** — ClusterIP on port 32401
- **ConfigMap** — non-secret env vars
- **Secret** — `PLEX_TOKEN`

To deploy:
```bash
# Update the PLEX_TOKEN in k8s/deployment.yml
# Update PLEX_URL to point to your Plex service/pod

kubectl apply -f k8s/deployment.yml
```

Expose via your ingress controller or `NodePort` as needed.

## Future Plans

- Per-user profile isolation (per managed user watch state)
- Web-based config UI
- GDM (Plex multicast discovery) advertisement so clients auto-discover the proxy
