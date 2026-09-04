# Pi-hole Twins 2.0 — Implementation Plan

## Branch: `v2.0`

---

## 18 Improvements — Status: **Core rewrite complete (items 1-5, 7, 9-14)**

### ✅ Completed (Core Rewrite — commit `dcfef83`)

#### 1. Fix `.gitignore` — exclude top-level `venv/`
- **Status:** ✅ Done
- **File:** `.gitignore` — added `venv/` at root level

#### 2. Move `import re` to module level
- **Status:** ✅ Done (as part of consolidated imports)
- **File:** `stream_pihole_logs.py` — all imports now at module level

#### 3. Add comprehensive type hints
- **Status:** ✅ Done
- **File:** `stream_pihole_logs.py` — return types on all methods, proper dataclasses

#### 4. Config file support (`~/.config/piholetwins/config.json`)
- **Status:** ✅ Done
- **File:** `config.py` (new) — platform-appropriate config dir, `.env` fallback,
  `load_servers()` with per-server settings (hostname, username, color_index, key_file, port)

#### 5. Support N servers (not just 2)
- **Status:** ✅ Done
- **File:** `stream_pihole_logs.py` — dynamic list of `PiHoleStreamer` objects,
  `--servers "name1,name2,..."` CLI flag, fallback to config file servers

#### 7. Log export (CSV, JSONL)
- **Status:** ✅ Done
- **File:** `stream_pihole_logs.py` — `--export /path/to/output.jsonl` flag,
  real-time append, each line: `{timestamp, server, hostname, ip, query, blocked}`
  (persistent file handle with proper lifecycle management)

#### 9. Per-server color customization
- **Status:** ✅ Done
- **File:** `stream_pihole_logs.py` + `config.py` — per-server `color_index`
  maps to a palette in `DEFAULT_COLORS`; assigned automatically by server order

#### 10. CLI subcommands (`stream`, `stats`, `export`)
- **Status:** ✅ Done (expanded beyond original scope)
- **File:** `stream_pihole_logs.py` — unified `_build_parser()` with subparsers:
  `stream`, `stats`, `export` dispatched through single `main()`

#### 11. SSH `~/.ssh/config` support
- **Status:** ✅ Done
- **File:** `stream_pihole_logs.py` — `_parse_ssh_config()` parses Host aliases,
  Port, User, IdentityFile; overrides defaults

#### 12. SSH key passphrase handling
- **Status:** ✅ Done
- **File:** `stream_pihole_logs.py` — checks encrypted key files, prompts via
  `getpass`, supports `SSH_KEY_PASSPHRASE_<SERVERNAME>` env var

#### 13. Auto-reconnection with exponential backoff
- **Status:** ✅ Done
- **File:** `stream_pihole_logs.py` — `stream_logs()` retries with 1s → 2s → 4s …
  (up to 60s); per-server isolation — one dead server doesn't kill the stream

#### 14. Graceful Ctrl+C with connection cleanup
- **Status:** ✅ Done
- **File:** `stream_pihole_logs.py` — `KeyboardInterrupt` handler closes all
  SSH connections via `finally` block in `_cmd_stream()`

---

### ⏳ Pending (Remaining items)

#### 6. Web dashboard (Flask)
- **File:** `web_dashboard.py` (new)
- **Features:**
  - Lightweight Flask server serving a single-page app
  - Real-time merged log stream via Server-Sent Events (SSE) or WebSocket
  - Filter by server, device, blocked status
  - Responsive design (works on phone/tablet)
- **Priority:** Low — deferred until core is stable

#### 8. Blocklist statistics (separate `stats.py` module)
- **Status:** ⚠️ Partially done — inline `_cmd_stats()` exists in `stream_pihole_logs.py`
  but no separate module or historical persistence
- **File:** `stats.py` (new) — track top blocked/queried domains, per-device stats,
  `--stats` flag for summary table, running counters
- **Enhancement:** Add SQLite/JSON persistence for historical stats across restarts
- **Priority:** Medium — useful standalone feature

#### 15. Async DNS resolution with timeout
- **Status:** ⚠️ Partially done — `resolve_hostname()` uses `ThreadPoolExecutor` but
  lacks an explicit 2-second timeout per lookup
- **File:** `stream_pihole_logs.py` — add 2-second timeout to DNS lookup,
  fallback to IP on timeout
- **Priority:** Low — current behavior is acceptable

#### 16. `pyproject.toml` — pip-installable package
- **File:** `pyproject.toml` (new)
- **Features:**
  - Package name: `piholetwins`
  - Entry point: `piholetwins = "stream_pihole_logs:main"`
  - Dependencies: `paramiko>=3.0.0`, `flask>=3.0` (optional)
  - Build system: `setuptools` or `hatchling`
- **Priority:** Low — for distribution

#### 17. Dockerfile
- **File:** `Dockerfile` (new)
- **Features:**
  - Multi-stage build: Python slim base → install deps → copy code
  - Volume mount for SSH keys and config
- **Priority:** Low — for containerized deployment

#### 18. Systemd service file
- **File:** `piholetwins.service` (new)
- **Features:**
  - Run as a background daemon
  - Restart on failure, log to journal
- **Priority:** Low — for server deployment

---

## File Structure (After Full Implementation)

```
pihole-twins/
├── .gitignore                  # (edited — exclude top-level venv/)
├── .env                        # (new — optional env overrides)
├── config.py                   # (new — configuration management)
├── stats.py                    # (pending — blocklist statistics module)
├── web_dashboard.py            # (pending — Flask web UI)
├── stream_pihole_logs.py       # (edited — core rewrite: items 1-5, 7, 9-14)
├── piholetwins                 # (edited — launcher script with $@ forwarding)
├── pyproject.toml              # (pending — pip-installable package)
├── Dockerfile                  # (pending — container support)
├── piholetwins.service         # (pending — systemd unit)
├── requirements.txt            # (edited — add flask, etc.)
├── LICENSE
├── README.md                   # (pending — document all new features)
└── venv/                       # (removed from git, re-created on demand)
```

---

## Implementation Order (Recommended)

### ✅ Phase 1 — Core Rewrite (COMPLETE)
1. **config.py** — foundation for everything else
2. **.gitignore fix + remove venv from git** — housekeeping
3. **stream_pihole_logs.py** — core rewrite (items 1-5, 7, 9-14)

### ⏳ Phase 2 — Remaining Features (TODO)
4. **stats.py** — statistics module with historical persistence
5. **web_dashboard.py** — Flask web UI (SSE/WebSocket)
6. **pyproject.toml + Dockerfile + .service** — deployment
7. **README.md** — documentation update

---

## Backward Compatibility

- All existing CLI flags (`--pihole1`, `--pihole2`, `-u`, `-f`, `-b`, `-v`) continue to work
- Default behavior (2 servers, hostnames `pihole1`/`pihole2`) unchanged
- Config file is opt-in — CLI args override config
- `stream` subcommand replicates original behavior when no servers are configured

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

**Core rewrite completed in ~3 hours (items 1-5, 7, 9-14).** Remaining items estimated at ~8-12 hours.
