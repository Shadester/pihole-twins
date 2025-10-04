# Pi-hole Twins Log Streamer

Stream and merge DNS query logs from two Pi-hole servers in real-time. Perfect for monitoring DNS activity across multiple Pi-hole instances, debugging network issues, or watching what devices are doing on your network.

## Features

- 🔄 **Real-time streaming** from two Pi-hole servers simultaneously
- 🎨 **Color-coded output** with distinct colors for each server
- 🔍 **Hostname resolution** - Shows device names with IPs (e.g., `[macbook.local (192.168.1.100)]`)
- 🚫 **Blocked queries highlighted** in red for easy identification
- 🔎 **Filter by device** - Watch queries from specific devices
- ⚡ **Async I/O** for smooth merging of both streams
- 🔐 **SSH key-based authentication** - Secure, passwordless access

## Prerequisites

- Python 3.7+
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
```

3. Ensure your SSH keys are configured for passwordless access to both Pi-holes

## Usage

### Basic Usage

Default (assumes hostnames `pihole1` and `pihole2`):
```bash
python3 stream_pihole_logs.py
```

### Custom Hostnames/IPs

```bash
python3 stream_pihole_logs.py --pihole1 192.168.1.10 --pihole2 192.168.1.11
```

### Filter by Device

Watch queries from a specific device:
```bash
python3 stream_pihole_logs.py --filter macbook
# or by IP
python3 stream_pihole_logs.py --filter 192.168.1.100
```

### Show Only Blocked Queries

```bash
python3 stream_pihole_logs.py --blocked-only
```

### All Options

```bash
python3 stream_pihole_logs.py --pihole1 pihole1.local \
                               --pihole2 pihole2.local \
                               --username pi \
                               --filter "macbook" \
                               --blocked-only
```

### Command-line Options

```
--pihole1       Hostname/IP of first Pi-hole (default: pihole1)
--pihole2       Hostname/IP of second Pi-hole (default: pihole2)
-u, --username  SSH username (default: pi)
-f, --filter    Filter by hostname or IP
-b, --blocked-only  Show only blocked queries
```

## Output Format

Each query line displays:
- `[HH:MM:SS]` - Timestamp
- `[pihole1]` or `[pihole2]` - Server name (color-coded: cyan/magenta)
- `[hostname (IP)]` - Device making the query (yellow)
- Query details (red if blocked)

Example:
```
[14:18:46] [pihole1] [macbook.local (192.168.1.100)] query[A] example.com
[14:18:46] [pihole1] [macbook.local (192.168.1.100)] gravity blocked ads.example.com is 0.0.0.0
```

Press `Ctrl+C` to stop streaming.

## How It Works

1. Connects to both Pi-hole servers via SSH
2. Runs `sudo pihole -t` on each server to tail logs
3. Parses log entries and performs reverse DNS lookups for client IPs
4. Merges streams with timestamps and color coding
5. Applies any filters and displays results in real-time

## Troubleshooting

**"command not found: pip"** - Use `pip3` instead of `pip`

**"requires root privileges"** - Configure passwordless sudo (see Prerequisites)

**Connection timeout** - Verify SSH access: `ssh pi@pihole1`

**No hostname resolution** - Ensure your DNS server can perform reverse lookups

## License

MIT

## Contributing

Issues and pull requests welcome!
