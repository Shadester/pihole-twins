# Pi-hole Twins 2.0 — Implementation Plan

## Branch: `v2.0`

---

## 18 Improvements to Implement

### Code Quality & Architecture (4 items)

#### 1. Fix `.gitignore` — exclude top-level `venv/`
- **File:** `.gitignore` (edit)
- **Change:** Add `venv/` at the root level (currently only matches nested venv dirs)
- **Also:** Remove existing `venv/` from git tracking

#### 2. Move `import re` to module level
- **File:** `stream_pihole_logs.py` (edit)
- **Change:** Remove `import re` from inside `parse_log_line()` and put it at the top with other imports

#### 3. Add comprehensive type hints
- **File:** `stream_pihole_logs.py` (edit)
- **Change:** Add return types to all methods, proper TypedDict for server config, etc.

#### 4. Config file support (`~/.config/piholetwins/config.json`)
- **File:** `config.py` (new)
- **Features:**
  - Platform-appropriate config dir (`~/.config/` on Linux, `%APPDATA%` on Windows)
  - `.env` file fallback (simple KEY=VALUE parsing, no external dependency)
  - `load_config()`, `save_config()`, `get_server_config()`, `get_all_servers()`
  - Per-server settings: hostname, username, color_index, key_file, port

---

### Features (6 items)

#### 5. Support N servers (not just 2)
- **File:** `stream_pihole_logs.py` (edit)
- **Change:** Replace hardcoded `streamer1`/`streamer2` with a dynamic list of `PiHoleStreamer` objects
- **CLI:** Add `--servers "name1,name2,name3"` flag; fall back to config file servers
- **Rename:** Update help text — "twins" → "multi-server"

#### 6. Web dashboard (Flask)
- **File:** `web_dashboard.py` (new)
- **Features:**
  - Lightweight Flask server serving a single-page app
  - Real-time merged log stream via Server-Sent Events (SSE) or WebSocket
  - Filter by server, device, blocked status
  - Responsive design (works on phone/tablet)

#### 7. Log export (CSV, JSONL)
- **File:** `stream_pihole_logs.py` (edit — add to PiHoleStreamer)
- **Features:**
  - `--export /path/to/output.jsonl` or `.csv`
  - Appends to file in real-time as logs arrive
  - Each line: `{timestamp, server, hostname, ip, query, blocked}`

#### 8. Blocklist statistics
- **File:** `stats.py` (new)
- **Features:**
  - Track top blocked domains, top queried domains, per-device stats
  - `--stats` flag to show a summary table at the bottom of terminal
  - Running counters: total queries, blocked count, unique domains

#### 9. Per-server color customization
- **File:** `stream_pihole_logs.py` + `config.py` (edit)
- **Change:** Add `--color1`, `--color2` (and N more) CLI flags
- **Config:** Per-server `color_index` maps to a palette in config

#### 10. CLI subcommand: `init-config`
- **File:** `stream_pihole_logs.py` (edit — argparse subparsers)
- **Feature:** `python stream_pihole_logs.py init-config pihole1 192.168.1.10` creates starter config

---

### Security (2 items)

#### 11. SSH `~/.ssh/config` support
- **File:** `stream_pihole_logs.py` (edit — connect method)
- **Change:** Parse `~/.ssh/config` using a lightweight parser or subprocess to `ssh -G`
- **Extract:** Hostname, IdentityFile (key path), Port — override defaults

#### 12. SSH key passphrase handling
- **File:** `stream_pihole_logs.py` (edit — connect method)
- **Change:** Check if key file exists and is encrypted; prompt for passphrase via `getpass`
- **Env var:** Also support `SSH_KEY_PASSPHRASE_<SERVERNAME>` env var

---

### Reliability (3 items)

#### 13. Auto-reconnection with exponential backoff
- **File:** `stream_pihole_logs.py` (edit — PiHoleStreamer)
- **Change:** `stream_logs()` catches connection errors, retries with 1s → 2s → 4s → ... backoff
- **Per-server:** One dead server doesn't kill the whole stream

#### 14. Graceful Ctrl+C with connection cleanup
- **File:** `stream_pihole_logs.py` (edit — main)
- **Change:** On KeyboardInterrupt, flush remaining queue items, close all SSH connections with a brief delay

#### 15. Async DNS resolution with timeout
- **File:** `stream_pihole_logs.py` (edit — resolve_hostname)
- **Change:** Use `concurrent.futures.ThreadPoolExecutor` with a 2-second timeout per lookup
- **Fallback:** If DNS times out, just show the IP

---

### Deployment / Packaging (3 items)

#### 16. `pyproject.toml` — pip-installable package
- **File:** `pyproject.toml` (new)
- **Features:**
  - Package name: `piholetwins`
  - Entry point: `piholetwins = "stream_pihole_logs:main"` (or via config)
  - Dependencies: `paramiko>=3.0.0`, `flask>=3.0` (optional, for web dashboard)
  - Build system: `setuptools` or `hatchling`

#### 17. Dockerfile
- **File:** `Dockerfile` (new)
- **Features:**
  - Multi-stage build: Python slim base → install deps → copy code
  - Volume mount for SSH keys and config

#### 18. Systemd service file
- **File:** `piholetwins.service` (new)
- **Features:**
  - Run as a background daemon
  - Restart on failure, log to journal

---

## File Structure (After Implementation)

```
pihole-twins/
├── .gitignore                  # (edited — exclude top-level venv/)
├── .env                        # (new — optional env overrides)
├── config.py                   # (new — configuration management)
├── stats.py                    # (new — blocklist statistics)
├── web_dashboard.py            # (new — Flask web UI)
├── stream_pihole_logs.py       # (edited — all improvements 1-5, 7-15)
├── piholetwins                 # (edited — launcher script)
├── pyproject.toml              # (new — pip-installable package)
├── Dockerfile                  # (new — container support)
├── piholetwins.service         # (new — systemd unit)
├── requirements.txt            # (edited — add flask, etc.)
├── LICENSE
├── README.md                   # (edited — document all new features)
└── venv/                       # (removed from git, re-created on demand)
```

---

## Implementation Order (Recommended)

1. **config.py** — foundation for everything else
2. **.gitignore fix + remove venv from git** — housekeeping
3. **stream_pihole_logs.py** — core rewrite (items 1-5, 7-8, 9-10, 11-12, 13-15)
4. **stats.py** — statistics module
5. **web_dashboard.py** — Flask web UI
6. **pyproject.toml + Dockerfile + .service** — deployment
7. **README.md** — documentation update

---

## Backward Compatibility

- All existing CLI flags (`--pihole1`, `--pihole2`, `-u`, `-f`, `-b`, `-v`) continue to work
- Default behavior (2 servers, hostnames `pihole1`/`pihole2`) unchanged
- Config file is opt-in — CLI args override config

---

## Estimated Effort

| Category | Items | Complexity |
|----------|-------|------------|
| Code Quality | 4 | Low-Medium |
| Features | 6 | Medium-High (web dashboard is heaviest) |
| Security | 2 | Medium |
| Reliability | 3 | Medium |
| Deployment | 3 | Low |

**Total: ~15-20 hours of focused work for a complete v2.0 release.**
