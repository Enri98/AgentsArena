# Deployment Guide — AgentsArena on Fly.io

## What this guide covers

This guide walks you through deploying the AgentsArena WebSocket server to [Fly.io](https://fly.io) so that two local Ollama agents running on your laptop can play against each other through a public `wss://` endpoint. By the end you will have a URL like `wss://arena-server-alice.fly.dev` that anyone on the internet can connect to, served over TLS without any extra configuration.

---

## Prerequisites

Before you start, make sure you have:

- A **Fly.io account** — sign up free at <https://fly.io/app/sign-up>
- **Docker Desktop** installed and running — download at <https://www.docker.com/products/docker-desktop>. Verify it is working:
  ```powershell
  docker --version
  ```
- **Windows PowerShell** (built into Windows; the commands below are written for it)
- This repository cloned and a working `.venv`:
  ```powershell
  .\.venv\Scripts\pip.exe install -e ".[server]"
  ```

---

## Step 1: Install `flyctl`

`flyctl` is the Fly.io command-line tool. Install it with the official one-liner:

```powershell
iwr https://fly.io/install.ps1 -useb | iex
```

This downloads and runs the installer script. It adds `flyctl` to your PATH. Open a new PowerShell window, then authenticate:

```powershell
flyctl auth login
```

Your browser opens a Fly.io login page. Complete the sign-in there. Back in PowerShell, confirm `flyctl` is ready:

```powershell
flyctl version
```

You should see a version line like `flyctl v0.x.y ...`.

---

## Step 2: Test the Docker image locally

Before deploying, confirm the image builds and the server responds correctly on your machine.

**Build the image** (run from the repo root — where `Dockerfile` lives):

```powershell
docker build -t arena-server .
```

This compiles a two-stage image: a `builder` stage installs all Python dependencies, and a slim runtime stage copies only what is needed. The first build takes 2–4 minutes; subsequent builds are fast because Docker caches the dependency layer.

**Run the container** in one PowerShell window:

```powershell
docker run --rm -p 8080:8080 arena-server
```

Open a second PowerShell window and call the health endpoint:

```powershell
curl http://127.0.0.1:8080/games
```

You should see JSON listing the built-in games:

```json
["connect4", "tictactoe", "nim"]
```

Stop the container with `Ctrl+C` in the first window.

> **Port already in use?** Use `-p 9000:8080` instead and adjust the curl URL to `http://127.0.0.1:9000/games`. See [Troubleshooting](#troubleshooting) below.

---

## Step 3: Launch the Fly app

The repo ships a `fly.toml` that pre-configures the app. Run:

```powershell
flyctl launch --no-deploy --copy-config
```

Fly reads `fly.toml` and prompts you for:

1. **App name** — choose something unique across all of Fly.io, e.g. `arena-server-alice`. You will use this name in every URL and command that follows.
2. **Organisation** — press Enter to accept your personal org.
3. **Region** — `fra` (Frankfurt) is pre-set in `fly.toml`; press Enter or pick something closer to you.
4. **"Would you like to copy its configuration to the new app?"** — type `y` and press Enter.
5. **"Would you like to deploy now?"** — type `n` and press Enter. You want to review the config before the first deploy.

After this step, Fly registers your app name but does not deploy anything yet.

> Replace `arena-server-alice` with your actual chosen name in every command from this point on.

---

## Step 4: First deploy

Deploy to Fly.io:

```powershell
flyctl deploy
```

Fly uploads your source, builds the Docker image remotely on its builders (5–10 minutes on first run), pushes the image to its registry, and starts a machine. Watch the output for:

```
==> Successfully deployed
```

If the build fails, read the error and check [Troubleshooting](#troubleshooting).

---

## Step 5: Get your public URL

Check the app status:

```powershell
flyctl status
```

You will see a `Hostname` line such as `arena-server-alice.fly.dev`. Test the HTTPS endpoint (note `https://`, not `http://`):

```powershell
curl https://arena-server-alice.fly.dev/games
```

Fly's edge terminates TLS automatically — there is nothing extra to configure. Your WebSocket URL is:

```
wss://arena-server-alice.fly.dev
```

---

## Step 6: Run the demo against your deployed server

Make sure Ollama is running locally in a separate terminal:

```powershell
ollama serve
```

Pull the model if you have not already:

```powershell
ollama pull llama3.2
```

Then start the acceptance demo (substitute your actual app name):

```powershell
python examples/run_remote_demo.py `
    --server-url wss://arena-server-alice.fly.dev `
    --game connect4 `
    --model-seat-0 llama3.2 `
    --model-seat-1 llama3.2 `
    --out-dir runs/remote-connect4
```

The demo will:

1. Probe your local Ollama daemon for `llama3.2`.
2. POST to `/matches` on your Fly app to create a new Connect 4 match.
3. Open two concurrent WebSocket connections (one per seat) and run each `OllamaAgent` locally, forwarding moves to the remote server.
4. Dump each seat's final transcript to `runs/remote-connect4/seat-{0,1}.transcript.json` and validate them.

Both agents still call your local Ollama daemon — only match state lives on Fly. Swap `--game connect4` for `tictactoe` or `nim` to exercise the other games. To deliberately trigger an abort (acceptance criterion), append `--abort-after-turns 3` — seat 1 will drop mid-match and the server must produce an `aborted` transcript with `reason="peer_disconnected"`.

For a CLI-driven session (live terminal rendering, human-vs-LLM, etc.) use the existing `python -m arena.cli.play --server-url wss://...` entrypoint instead.

---

## Step 7: Inspect logs

Stream live structured logs from your deployed app:

```powershell
flyctl logs
```

Each line is a JSON object. Filter for specific events using PowerShell's `Select-String`:

```powershell
flyctl logs | Select-String '"event": "match_created"'
flyctl logs | Select-String '"event": "turn_deadline_expired"'
flyctl logs | Select-String '"event": "match_aborted"'
```

Every log line includes these Phase-33 fields:

| Field | Description |
|-------|-------------|
| `timestamp` | ISO-8601 UTC time |
| `level` | `info`, `warning`, or `error` |
| `event` | Event name (see table in README) |
| `match_id` | Opaque match token |
| `seat` | Integer seat index, or `null` for match-level events |
| `schema_version` | Always `1` in v1 |

To filter by a specific match:

```powershell
flyctl logs | Select-String '"match_id": "abc123"'
```

---

## Step 8: Tear it down to avoid charges

When you are done, destroy the app:

```powershell
flyctl apps destroy arena-server-alice
```

Fly will ask you to type the app name to confirm. Then verify it is gone:

```powershell
flyctl apps list
```

---

## Cost notes

Fly.io's free allowance and pricing change over time. Always check current terms before deploying: <https://fly.io/docs/about/pricing/>

The `fly.toml` in this repo is configured with:

```toml
auto_stop_machines = "stop"
min_machines_running = 0
```

This means the machine **stops when idle** and restarts on the first incoming connection. You pay only for active compute time, so a lightly used demo server costs very little or nothing under the free allowance. The trade-off is a **cold start delay of ~5 seconds** on the first connection after the machine has been idle.

To eliminate cold starts at the cost of running continuously, edit `fly.toml`:

```toml
min_machines_running = 1
```

Then redeploy:

```powershell
flyctl deploy
```

---

## Troubleshooting

### "WebSocket handshake timed out"

The machine is likely cold-starting. Retry the connection. If this happens frequently, either increase the SDK handshake timeout (see `src/arena/sdk/_connect.py`) or set `min_machines_running = 1` in `fly.toml` and redeploy.

### "Match aborted with reason `turn_deadline_expired`"

The local Ollama agent is taking longer than the server's per-turn deadline to respond. Try:

- `--ollama-timeout 60` to give the agent more time
- Switching to a smaller/faster model (e.g. `qwen2.5:1.5b`)

### "Connection refused" on local Docker test

Port 8080 is already in use on your machine. Use a different host port:

```powershell
docker run --rm -p 9000:8080 arena-server
```

Then test with:

```powershell
curl http://127.0.0.1:9000/games
```

### `flyctl deploy` fails with "app name already taken"

App names are global across all Fly.io users. Choose a more specific name (e.g. include your username or a random suffix) and re-run `flyctl launch --no-deploy --copy-config`.

### Server returns 502 right after deploy

The machine may still be starting. Wait 10–15 seconds and retry. Check `flyctl logs` for startup errors.

---

## Appendix A — Self-host on a VPS with Caddy

If you have a Linux VPS and a domain name, you can self-host without Fly.io. Caddy handles TLS automatically via Let's Encrypt.

**Caddyfile** (`/etc/caddy/Caddyfile`):

```
arena.example.com {
    reverse_proxy localhost:8080
}
```

**Run the server container:**

```bash
docker run -d --restart unless-stopped \
    --name arena-server \
    -p 127.0.0.1:8080:8080 \
    arena-server
```

Restart Caddy to pick up the new config:

```bash
systemctl reload caddy
```

Your WebSocket URL will be `wss://arena.example.com`. Caddy upgrades HTTP to HTTPS and proxies WebSocket connections transparently.

---

## Appendix B — What gets shipped

When you run `flyctl deploy` (or `docker build`), the following is included in the image:

| Path | Purpose |
|------|---------|
| `Dockerfile` | Two-stage build definition |
| `fly.toml` | Fly.io app configuration |
| `.dockerignore` | Excludes tests, `.venv`, dev files from the image |
| `src/arena/` | All arena packages (core, games, match, runtime, server, sdk, etc.) |
| `pyproject.toml` | Package metadata and dependency declaration |

**The server is stateless.** Matches live in memory inside the running process. Restarting the server (e.g. via `flyctl deploy` or a machine restart) drops all in-flight matches. Clients will receive a disconnect and need to create a new match. Transcript persistence by the server is not in scope for v1.
