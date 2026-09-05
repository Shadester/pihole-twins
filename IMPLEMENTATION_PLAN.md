# Pi-hole Twins 2.0 — Implementation Plan

## Branch: `v2.0`

---

## 18 Improvements — Status: **COMPLETE — all 18 items implemented**

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
- **File:** `stats.py` — `create_stats_parser()`, `_cmd_stats_cli()` with
  `--servers, -s SERVERS [SERVERS ...]` (default: from config)
- **File:** `export.py` — `create_export_parser()`, `_cmd_export_cli()` with
  `--servers, -s SERVERS [SERVERS ...]`, `--output, -o OUTPUT` (.jsonl/.csv),
  `--lines, -n LINES` (recent log lines to collect)

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

### ✅ Completed (Phase 2 — stats + export + models)

#### 8. Blocklist statistics (separate `stats.py` module)
- **Status:** ✅ Done
- **File:** `stats.py` (new) — SQLite persistence (`StatsDB`) with tables for
  summary/daily/raw logs, async SSH log collection via `collect_stats_from_server()`,
  CLI subcommand `stats` with `--servers, -s SERVERS [SERVERS ...]`,
  display helpers (`print_stats_table`, `print_daily_chart`)
- **File:** `export.py` (new) — CSV/JSONL historical stats export via `Exporter`
  class, convenience functions (`export_stats_to_csv`, `export_stats_to_jsonl`),
  CLI subcommand `export` with `--output, -o OUTPUT` and `--lines, -n LINES`
- **File:** `models.py` (new) — shared dataclasses (`ServerConfig`, `LogEntry`,
  `ServerStats`), `_update_stats()`, `print_stats()`, and `Colors` class
  for ANSI formatting — eliminates circular dependencies between modules

---

### ✅ Completed (Phase 2b — web, packaging, deployment)

#### 6. Web dashboard (Flask)
- **Status:** ✅ Done
- **File:** `web_dashboard.py` (new, 275 lines)
- **Features:**
  - Lightweight Flask server with SPA dashboard
  - `/` — responsive HTML5 dashboard with CSS bars and auto-refresh (30s)
  - `/api/summary` — server statistics (JSON)
  - `/api/daily/<server_name>&days=30` — daily breakdown
  - Real-time stats with domain rankings and device counts
  - `--port, -p PORT` (default 5000), `--debug` flags
- **Priority:** Low — deferred until core is stable

#### 15. Async DNS resolution with timeout
- **Status:** ✅ Done
- **File:** `stream_pihole_logs.py` — `resolve_hostname_with_timeout()` uses
  `ThreadPoolExecutor` with explicit 2-second `future.result(timeout=2)`,
  falls back to raw IP on timeout or failure
- **Priority:** Low — current behavior is acceptable

#### 16. `pyproject.toml` — pip-installable package
- **Status:** ✅ Done
- **File:** `pyproject.toml` (new, 47 lines)
- **Features:**
  - Package name: `pihole-tvens`, version `0.2.0`
  - Entry point: `piholetvens = "stream_pihole_logs:main"`
  - Dependencies: `paramiko>=3.0.0`, `flask>=3.0.0` (optional)
  - Build system: `setuptools`
  - Optional groups: `web`, `dev`
- **Priority:** Low — for distribution

#### 17. Dockerfile
- **Status:** ✅ Done
- **File:** `Dockerfile` (new, 38 lines)
- **Features:**
  - Multi-stage build: `builder` → `runtime` (python:3.14-slim)
  - Installs `tini` for proper PID 1 handling
  - Non-root `appuser`, exposes port 5000
  - Default command: `stream` CLI
- **Priority:** Low — for containerized deployment

#### 18. Systemd service file
- **Status:** ✅ Done
- **File:** `piholetvens.service` (new, 21 lines)
- **Features:**
  - Runs as dedicated `appuser`, restarts on failure (10s delay)
  - Security hardening: `NoNewPrivileges`, `ProtectSystem=strict`,
    `PrivateTmp`, read-only paths except config dir
  - Logs to systemd journal
  - WantedBy: `multi-user.target`
- **Priority:** Low — for server deployment

---

## File Structure (After Full Implementation)

```
pihole-twins/
├── .gitignore                  # (edited — exclude top-level venv/)
├── .env                        # (new — optional env overrides)
├── config.py                   # (new — configuration management, load_servers())
├── models.py                   # (new — shared dataclasses: ServerConfig, LogEntry,
│                               #          ServerStats; _update_stats(), print_stats())
├── stats.py                    # (new — SQLite persistence, CLI subcommand)
├── export.py                   # (new — CSV/JSONL historical stats export, CLI subcommand)
├── web_dashboard.py            # (new — Flask web UI, 275 lines)
├── stream_pihole_logs.py       # (edited — core rewrite: items 1-5, 7, 9-14)
├── piholetvens                 # (edited — launcher script with $@ forwarding)
├── pyproject.toml              # (new — pip-installable package, 47 lines)
├── Dockerfile                  # (new — container support, 38 lines)
├── piholetvens.service         # (new — systemd unit, 21 lines)
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

### ✅ Phase 2 — Remaining Features (COMPLETE)
4. **stats.py** — SQLite persistence and stats collection
5. **export.py** — CSV/JSONL historical stats export
6. **models.py** — shared dataclasses
7. **web_dashboard.py** — Flask web UI (SSE/WebSocket)
8. **pyproject.toml + Dockerfile + .service** — deployment

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

**Core rewrite completed in ~3 hours (items 1-5, 7, 9-14).**
**Phase 2 (stats + export + models) completed in ~5 hours.**
**Phase 2b (items 6, 15-18) completed — all 18 items done.**
