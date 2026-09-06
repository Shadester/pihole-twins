# Pi-hole Twins Log Streamer

Stream and merge DNS query logs from two (or more) Pi-hole servers in real-time. Perfect for monitoring DNS activity across multiple Pi-hole instances, debugging network issues, or watching what devices are doing on your network.

## Features

- 🔄 **Real-time streaming** from multiple Pi-hole servers simultaneously
- 🎨 **Color-coded output** with distinct colors per server (cyan, magenta, green, etc.)
- 🔍 **Hostname resolution** — shows device names with IPs (e.g., `[macbook.local (192.168.1.100)]`)
- 🚫 **Blocked queries** highlighted in red for easy identification
- 🔎 **Filter by device** — watch queries from specific devices
- ⚡ **Async I/O** for smooth merging of both streams
- 🔐 **SSH key-based authentication** — secure, passwordless access
- 📋 **Live export** — pipe live logs to a JSONL file
- 📊 **Historical stats** — blockrate, top domains, device counts via SQLite
- 📤 **CSV/JSONL export** — export historical stats for analysis
- 🌐 **Web dashboard** — live Flask-based monitoring UI
- 🔁 **Auto-reconnect** — exponential backoff (1s → 60s) with per-server isolation
- 🔑 **`.ssh/config` support** — reads Host, Port, User, IdentityFile overrides
- 🔑🔐 **Encrypted keys** — handles passphrases via env var or interactive prompt

## Prerequisites

- Python 3.11+ (supports 3.11 through 3.14)
- SSH access to both Pi-hole servers with key-based authentication configured
- Passwordless sudo for the `pihole` command on both servers
- Pi-hole servers accessible on your network

### Setting up SSH Key Authentication

If you don't already have SSH keys set up:

1. **Generate SSH key** (on your local machine, if you don't have one):
```bash
ssh-keygen -t ed25519
# Press Enter to accept all defaults (email/comment is optional)
```

2. **Copy SSH key to both Pi-holes**:
```bash
ssh-copy-id pi@pihole1
ssh-copy-id pi@pihole2
```

3. **Test passwordless login**:
```bash
ssh pi@pihole1  # Should connect without asking for password
ssh pi@pihole2
```

### Setting up Passwordless Sudo

On each Pi-hole server, create `/etc/sudoers.d/pihole`:
```bash
ssh pi@pihole1 "echo 'pi ALL=(ALL) NOPASSWD: /usr/local/bin/pihole' | sudo tee /etc/sudoers.d/pihole"
ssh pi@pihole2 "echo 'pi ALL=(ALL) NOPASSWD: /usr/local/bin/pihole' | sudo tee /etc/sudoers.d/pihole"
```

Replace `pi` with your SSH username if different.

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/pihole-twins.git
cd pihole-twins
```

2. Install dependencies:
```bash
pip3 install -r requirements.txt
# or
pip3 install -e .  # editable install with pip
```

3. Ensure your SSH keys are configured for passwordless access to both Pi-holes

## Usage

### Quick Start — Hostnames on the Command Line

No config file needed. Just pass the hostnames:
```bash
python3 stream_pihole_logs.py --pihole1 192.168.1.10 --pihole2 192.168.1.11
```

Or with a custom SSH username:
```bash
python3 stream_pihole_logs.py --pihole1 192.168.1.10 --pihole2 192.168.1.11 --username admin
```

### Using a Config File (Optional)

Save server presets in `~/.config/piholetwins/config.json` and reference them by name:

```json
{
  "servers": {
    "home": {
      "hostname": "192.168.1.10",
      "username": "pi",
      "key_file": "~/.ssh/home_key",
      "port": 22
    },
    "office": {
      "hostname": "192.168.1.20",
      "username": "admin"
    }
  }
}
```

Config file options:
| Field | Default | Description |
|---|---|---|
| `hostname` | server name | IP or hostname of the Pi-hole |
| `username` | `pi` | SSH username |
| `key_file` | `None` | Path to SSH private key (supports `~`) |
| `port` | `22` | SSH port |

Usage:
```bash
# Server names from config (two servers):
python3 stream_pihole_logs.py --servers home office

# No flags at all → loads ALL configured servers:
python3 stream_pihole_logs.py
```

**Priority** (highest → lowest):
1. `--pihole1` / `--pihole2` — bypasses config, creates servers named "pihole1", "pihole2"
2. `--servers NAME1 NAME2` — looks up names in config file, falls back to bare names
3. (nothing) — loads all servers from config file

### SSH Key Passphrases

Encrypted keys are supported in two ways:

**Environment variable** (per server):
```bash
export SSH_KEY_PASSPHRASE_HOME="my_passphrase"
python3 stream_pihole_logs.py --servers home
```

**Interactive prompt** — if a `key_file` is set in config AND the file exists, you'll be prompted.

### Advanced: `~/.ssh/config`

The tool reads `~/.ssh/config` for each server name and applies:
- `Host` — aliases match
- `Hostname` — resolves the actual host (overrides `--piholeN`)
- `Port` — SSH port
- `User` — SSH username
- `IdentityFile` — path to SSH key

Example `~/.ssh/config`:
```
Host pi01
    Hostname 192.168.1.10
    User admin
    Port 2222
    IdentityFile ~/.ssh/pikey

Host pi02
    Hostname 192.168.1.20
    User admin
    IdentityFile ~/.ssh/pikey
```

### Server Auto-Reconnect

If a connection drops, each server reconnects independently with exponential backoff:
1s → 2s → 4s → 8s → 16s → 32s → 60s (capped).

## Commands

### Stream (Default)

Stream and merge live logs from configured servers:

```bash
# Basic — two servers from CLI:
python3 stream_pihole_logs.py --pihole1 192.168.1.10 --pihole2 192.168.1.11

# With server names from config:
python3 stream_pihole_logs.py --servers home office

# All configured servers:
python3 stream_pihole_logs.py
```

**Stream with filters:**
```bash
# Filter by device hostname
python3 stream_pihole_logs.py --servers home office --filter macbook

# Show only blocked queries
python3 stream_pihole_logs.py --servers home office --blocked-only

# Verbose mode (show all log lines: cache, reply, forwarded)
python3 stream_pihole_logs.py --servers home office --verbose

# Combine filters
python3 stream_pihole_logs.py --pihole1 192.168.1.10 --pihole2 192.168.1.11 \
                              --filter "macbook" --blocked-only --verbose
```

**Live export** — append live log entries to a JSONL file while streaming:
```bash
python3 stream_pihole_logs.py --servers home office --export /tmp/live.jsonl
```

**Command-line options (Stream / Top-level):**
```
--pihole1 HOST       Hostname/IP of first server (overrides config)
--pihole2 HOST       Hostname/IP of second server (overrides config)
-u, --username       SSH username (default: pi)
-b, --blocked-only   Show only blocked queries
-f, --filter         Filter by hostname or IP
-v, --verbose        Show all log lines including cache/reply/forwarded
```

**Subcommand: `stream` (explicit):**
```
--servers, -s NAME1 [NAME2 ...]  Server names from config file
--export, -e FILE               Export live entries as JSONL to file
```

### Stats

Collect historical statistics from servers via their log file:

```bash
python3 stream_pihole_logs.py stats --servers server1 server2
```

Outputs a formatted table with:
- Total and blocked query counts
- Block rate percentage
- Top 10 blocked domains with histograms
- Top 5 devices

### Export

Collect historical log entries and export to CSV or JSONL:

```bash
# Collect up to 5000 log lines, export to JSONL:
python3 stream_pihole_logs.py export --servers home office --output logs.jsonl --lines 5000

# Export to CSV (includes summary + daily breakdown):
python3 stream_pihole_logs.py export --servers home office --output stats.csv --lines 10000
```

**Subcommand: `export` options:**
```
--servers, -s NAME1 [NAME2 ...]  Server names (default: from config)
--output, -o FILE                Output file path (.jsonl or .csv) — required
--lines, -n N                    Number of recent log lines to collect (default: 1000)
```

Output formats:
- **`.jsonl`** — one JSON object per line (server, timestamp, query, IP, is_blocked)
- **`.csv`** — two sections: "Server Summary" and "Daily Breakdown" (headers as section dividers)

## Web Dashboard

A real-time Flask-based web UI showing server stats, block rates, top domains, and daily query charts:

```bash
python3 web_dashboard.py --port 5000
# or with debug mode:
python3 web_dashboard.py --port 8080 --debug
```

Features:
- Live dashboard at `http://localhost:5000`
- Server cards showing total queries, blocked count, block rate, and top domains
- Bar chart of daily queries (last 30 days) for the first server
- Auto-refreshes every 30 seconds

### Docker

Build and run the web dashboard in a container:

```bash
# Build:
docker build -t pihole-twins .

# Run — exposes the web dashboard on port 5000:
docker run -d --name pihole-twins \
  -p 5000:5000 \
  -v "$HOME/.config/piholetwins:/home/appuser/.config/piholetwins" \
  pihole-twins

# Or run a stream directly inside the container:
docker run --rm -it pihole-twins \
  python3 stream_pihole_logs.py --servers myhome myoffice
```

The Docker image:
- Uses a two-stage build (builder + slim runtime) with Python 3.14
- Runs as unprivileged user `appuser` with `tini` init
- Hardened systemd-style: `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`
- Data directories created under `/home/appuser/.config/piholetwins`
- Exposes port 5000 for the web dashboard (CMD defaults to stream mode)

### Systemd Service

For persistent deployment, use the included `piholetwins.service` file:

```bash
# Copy to systemd directory:
sudo cp piholetwins.service /etc/systemd/system/

# Edit ExecStart to match your servers and install path:
sudo vim /etc/systemd/system/piholetwins.service

# Enable and start:
sudo systemctl daemon-reload
sudo systemctl enable --now pihole-twins
sudo journalctl -u pihole-twins -f
```

The service unit:
- Runs as user `appuser` (create with `useradd -m -s /bin/bash appuser`)
- Works directory: `/opt/pihole-tvens/` (adjust to your install path)
- Restarts on failure with 10s delay
- Logs to systemd journal
- Security hardening: `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, read-only system paths except config dir

## Output Format

Each query line displays:
- `[HH:MM:SS]` — Timestamp
- `[pihole1]` or `[pihole2]` — Server name (color-coded: cyan/magenta)
- `[hostname (IP)]` — Device making the query (yellow)
- Query details (red if blocked)

Example:
```
[14:18:46] [pihole1] [macbook.local (192.168.1.100)] query[A] example.com
[14:18:46] [pihole1] [macbook.local (192.168.1.100)] gravity blocked ads.example.com is 0.0.0.0
```

Press `Ctrl+C` to stop streaming.

## Data Storage

Statistics are persisted in an SQLite database at `~/.config/piholetwins/stats.db` with three tables:

| Table | Purpose |
|---|---|
| `server_stats` | Per-server summary (total queries, blocked, top domains, device counts, last updated) |
| `daily_stats` | Per-server per-day rollups for time-series charts |
| `log_entries` | Raw log entries for export and analysis |

## Troubleshooting

**"command not found: pip"** — Use `pip3` instead of `pip`

**"requires root privileges"** — Configure passwordless sudo (see Prerequisites)

**Connection timeout** — Verify SSH access: `ssh pi@pihole1`

**No hostname resolution** — Ensure your DNS server can perform reverse lookups

**Encrypted SSH keys not working** — Set `SSH_KEY_PASSPHRASE_<SERVERNAME>` env var or ensure the key file path in your config is correct

## Project Structure

```
pihole-twins/
├── stream_pihole_logs.py     # Core: streaming, SSH, log parsing, CLI
├── models.py                 # Data classes: ServerConfig, LogEntry, ServerStats, Colors
├── config.py                 # Configuration management, load_servers()
├── stats.py                  # SQLite persistence, stats collection, CLI subcommand
├── export.py                 # CSV/JSONL historical stats export, Exporter class
├── web_dashboard.py          # Flask web UI (dashboard, API routes)
├── pyproject.toml            # Package metadata, build config
├── Dockerfile                # Container build (two-stage)
├── piholetwins.service       # Systemd unit file
├── pihole-twins              # Launcher script (activates venv, runs)
├── requirements.txt          # Dependencies (paramiko)
└── .gitignore                # Excludes venv/, __pycache__/.
```

## License

MIT

## Contributing

Issues and pull requests welcome!
