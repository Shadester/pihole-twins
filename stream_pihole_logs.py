#!/usr/bin/env python3
"""
Stream and merge query logs from two Pi-hole servers.
"""

import asyncio
import argparse
import getpass
import json
import os
import re
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import paramiko


# ANSI color codes (matches config.py DEFAULT_COLORS)
DEFAULT_COLORS: List[str] = [
    '\033[96m',  # CYAN
    '\033[95m',  # MAGENTA
    '\033[92m',  # GREEN
    '\033[93m',  # YELLOW
    '\033[94m',  # BLUE
    '\033[1;33m',  # BOLD YELLOW
]


class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'


@dataclass
class ServerConfig:
    """Configuration for a single Pi-hole server."""
    name: str
    hostname: str = ''
    username: str = 'pi'
    color_index: int = 0
    key_file: Optional[str] = None
    port: int = 22
    passphrase: str = ''

    def __post_init__(self) -> None:
        if not self.hostname:
            self.hostname = self.name

    def get_color(self) -> str:
        """Get the ANSI color code for this server."""
        return DEFAULT_COLORS[self.color_index % len(DEFAULT_COLORS)]


@dataclass
class LogEntry:
    """Parsed log entry."""
    timestamp: str
    server_name: str
    host_display: str
    query_part: str
    ip: str = ''
    is_blocked: bool = False
    raw_line: str = ''
    export_dict: Dict[str, Any] = field(default_factory=dict)


class PiHoleStreamer:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.hostname: str = config.hostname
        self.username: str = config.username
        self.color: str = config.get_color()
        self.client: Optional[paramiko.SSHClient] = None
        self.dns_cache: Dict[str, str] = {}
        self.last_query_ip: Optional[str] = None
        self._stdin: Any = None  # SSH stdin for pty
        self._stdout: Any = None  # SSH stdout
        self._stderr: Any = None  # SSH stderr

    def _parse_ssh_config(self) -> Dict[str, Any]:
        """Parse ~/.ssh/config for this host's settings."""
        ssh_dir = Path.home() / '.ssh'
        config_path = ssh_dir / 'config'
        if not config_path.exists():
            return {}

        result: Dict[str, Any] = {'hostname': self.hostname, 'port': 22,
                                   'username': self.username, 'identityfile': None}
        current_host: Optional[str] = None

        with open(config_path) as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                parts = stripped.split(None, 1)
                if len(parts) < 2:
                    continue
                directive, value = parts[0].lower(), parts[1]

                # Handle Host aliases (Host foo bar pihole1)
                if directive == 'host':
                    hosts = value.split()
                    current_host = self.hostname if self.hostname in hosts else None
                    continue

                # Only apply to our host (or wildcard)
                if current_host is not None or value == '*':
                    if directive == 'hostname' and result['identityfile'] is None:
                        result['hostname'] = value
                    elif directive == 'port':
                        try:
                            result['port'] = int(value)
                        except ValueError:
                            pass
                    elif directive == 'user':
                        result['username'] = value
                    elif directive == 'identityfile':
                        result['identityfile'] = Path(Path.home() / '.ssh' / value.split()[0])

        return result

    def _get_passphrase(self) -> str:
        """Get SSH key passphrase from env var or interactive prompt."""
        env_key = f'SSH_KEY_PASSPHRASE_{self.config.name.upper().replace("-", "_")}'
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val
        # Check if key is encrypted
        key_path = self.config.key_file or (Path.home() / '.ssh' /
              (self._parse_ssh_config().get('identityfile') or Path('')))
        if key_path and key_path.exists():
            try:
                print(f"\nEnter passphrase for {self.config.name} (or press Enter to skip):",
                      end='', flush=True)
                return getpass.getpass()
            except (EOFError, KeyboardInterrupt):
                return ''
        return ''

    async def connect(self) -> None:
        """Establish SSH connection to Pi-hole server."""
        loop = asyncio.get_event_loop()

        # Parse SSH config for overrides
        ssh_cfg = self._parse_ssh_config()
        connect_hostname = self.config.key_file or str(ssh_cfg.get('hostname', self.hostname))
        connect_port = ssh_cfg.get('port', self.config.port)
        connect_user = ssh_cfg.get('username', self.username)

        # Resolve key file
        key_file = None
        if self.config.key_file:
            key_file = Path(self.config.key_file)
        elif ssh_cfg.get('identityfile'):
            key_file = ssh_cfg['identityfile']

        def _connect() -> paramiko.SSHClient:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            kwargs: Dict[str, Any] = {
                'hostname': self.hostname,
                'username': connect_user,
                'port': connect_port,
                'allow_agent': True,
                'look_for_keys': True,
            }
            if key_file and key_file.exists():
                kwargs['key_filename'] = str(key_file)
            passphrase = self.config.passphrase or self._get_passphrase()
            if passphrase:
                kwargs['passphrase'] = passphrase
            return client.connect(**kwargs)

        self.client = await loop.run_in_executor(None, _connect)

    def disconnect(self) -> None:
        """Close SSH connection and clean up file handles."""
        for f in (self._stdin, self._stdout, self._stderr):
            try:
                if f:
                    f.close()
            except Exception:
                pass
        self._stdin = self._stdout = self._stderr = None
        if self.client:
            self.client.close()
            self.client = None

    def resolve_hostname(self, ip: str) -> str:
        """Resolve IP to hostname with caching."""
        if ip in self.dns_cache:
            return self.dns_cache[ip]

        try:
            hostname = socket.gethostbyaddr(ip)[0]
            self.dns_cache[ip] = hostname
            return hostname
        except (socket.herror, socket.gaierror):
            self.dns_cache[ip] = ip
            return ip

    def parse_log_line(self, line: str) -> Optional[Tuple[str, str, bool]]:
        """Parse log line to extract IP and other info.

        Returns (query_part, ip, is_blocked) or None.
        """
        # Pi-hole log format:
        #   "Oct  4 14:18:46: query[A] example.com from 192.168.1.100"
        #   "Oct  4 14:18:46: gravity blocked example.com is 0.0.0.0"

        # Match query lines: "query[TYPE] domain from IP"
        match = re.search(r'query\[.*?\].*?from\s+([\d.]+)$', line)
        if match:
            ip = match.group(1)
            query_part = line[:match.start(1) - 6]
            self.last_query_ip = ip
            return (query_part, ip, False)

        # Check for block/deny lines
        if ('gravity blocked' in line.lower() or 'exactly blocked' in line.lower()
                or 'exactly denied' in line.lower()):
            if self.last_query_ip:
                return (line, self.last_query_ip, True)

        return None

    async def stream_logs(self, queue: asyncio.Queue,
                          show_blocked_only: bool = False,
                          filter_host: Optional[str] = None,
                          verbose: bool = False,
                          export_path: Optional[Path] = None) -> None:
        """Stream logs from Pi-hole with auto-reconnect and optional export.

        Reconnects on failure using exponential backoff (1s → 2s → 4s ...).
        """
        loop = asyncio.get_event_loop()
        max_backoff: float = 60.0
        backoff: float = 1.0
        export_file = None
        if export_path:
            export_file = open(export_path, 'a')

        while True:
            # (Re)connect if needed
            try:
                await self.connect()
            except Exception as e:
                print(f"\n{Colors.RED}{self.config.name}: Connection failed ({e}), "
                      f"retrying in {backoff:.0f}s...{Colors.RESET}", file=sys.stderr)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue

            try:
                stdin, stdout, stderr = self.client.exec_command(
                    'sudo pihole -t', get_pty=True)
                self._stdin, self._stdout, self._stderr = stdin, stdout, stderr
            except Exception as e:
                print(f"\n{Colors.RED}{self.config.name}: Command failed ({e}), "
                      f"retrying in {backoff:.0f}s...{Colors.RESET}", file=sys.stderr)
                self.disconnect()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue

            backoff = 1.0  # Reset on successful connect

            try:
                while True:
                    line = await loop.run_in_executor(None, stdout.readline)
                    if not line:
                        break

                    line = line.strip()
                    if not line:
                        continue

                    parsed = self.parse_log_line(line)

                    if parsed:
                        query_part, ip, is_blocked = parsed

                        if show_blocked_only and not is_blocked:
                            continue

                        hostname = await loop.run_in_executor(None, self.resolve_hostname, ip)

                        if filter_host and filter_host.lower() not in hostname.lower() \
                                and filter_host != ip:
                            continue

                        timestamp = datetime.now().strftime('%H:%M:%S')
                        host_display = f"{hostname} ({ip})" if hostname != ip else ip

                        if is_blocked:
                            formatted = (f"{Colors.BOLD}[{timestamp}] "
                                         f"{self.color}[{self.config.name}]{Colors.RESET} "
                                         f"{Colors.YELLOW}[{host_display}]{Colors.RESET} "
                                         f"{Colors.RED}{query_part}{Colors.RESET}")
                        else:
                            formatted = (f"[{timestamp}] "
                                         f"{self.color}[{self.config.name}]{Colors.RESET} "
                                         f"{Colors.YELLOW}[{host_display}]{Colors.RESET} "
                                         f"{query_part}")

                        await queue.put(formatted)

                        # Export to file if requested
                        if export_file:
                            entry = LogEntry(
                                timestamp=timestamp,
                                server_name=self.config.name,
                                host_display=f"{hostname} ({ip})" if hostname != ip else ip,
                                query_part=query_part,
                                ip=ip,
                                is_blocked=is_blocked,
                            )
                            export_file.write(json.dumps(entry) + '\n')
                            export_file.flush()
                    else:
                        if verbose and not filter_host and not show_blocked_only:
                            timestamp = datetime.now().strftime('%H:%M:%S')
                            formatted = (f"[{timestamp}] "
                                         f"{self.color}[{self.config.name}]{Colors.RESET} "
                                         f"{line}")
                            await queue.put(formatted)
            except Exception:
                # Connection dropped — reconnect with backoff
                print(f"\n{Colors.YELLOW}{self.config.name}: Stream ended, reconnecting..."
                      f"{Colors.RESET}", file=sys.stderr)
                if export_file:
                    export_file.close()
                    export_file = None
                self.disconnect()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

        # Stream completed successfully — close export file
        if export_file:
            export_file.close()

    def close(self) -> None:
        """Close SSH connection (alias for disconnect)."""
        self.disconnect()


# ─── Stats helpers ───────────────────────────────────────────────

@dataclass
class ServerStats:
    """Accumulated statistics for a server."""
    total_queries: int = 0
    blocked_queries: int = 0
    top_domains: Dict[str, int] = field(default_factory=lambda: {})
    device_counts: Dict[str, int] = field(default_factory=lambda: {})

    @property
    def block_rate(self) -> float:
        return (self.blocked_queries / self.total_queries * 100) if self.total_queries else 0.0


def _update_stats(entry: LogEntry, stats: ServerStats) -> None:
    """Update statistics from a parsed log entry."""
    stats.total_queries += 1
    if entry.is_blocked:
        stats.blocked_queries += 1
    parts = entry.query_part.split()
    if len(parts) >= 3:
        domain = parts[-2]
        stats.top_domains[domain] = stats.top_domains.get(domain, 0) + 1
    if entry.host_display and entry.host_display != entry.ip:
        stats.device_counts[entry.host_display] = \
            stats.device_counts.get(entry.host_display, 0) + 1


def print_stats(all_stats: Dict[str, ServerStats]) -> None:
    """Print formatted statistics table."""
    print(f"\n{Colors.BOLD}{'='*70}{Colors.RESET}")
    print(f"{Colors.BOLD}  Pi-hole Twins — Statistics Summary{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*70}{Colors.RESET}\n")

    for server_name, stats in all_stats.items():
        print(f"  {Colors.CYAN}{server_name}{Colors.RESET}")
        print(f"    Total queries : {stats.total_queries:>10,}")
        print(f"    Blocked       : {stats.blocked_queries:>10,} "
              f"({stats.block_rate:.1f}%)")
        if stats.top_domains:
            top = sorted(stats.top_domains.items(), key=lambda x: x[1],
                         reverse=True)[:10]
            print(f"    Top domains   :")
            for domain, count in top:
                bar = '█' * min(count // max(1, stats.total_queries // 50), 30)
                print(f"      {domain:<40s} {count:>6,}  {bar}")
        if stats.device_counts:
            top_devs = sorted(stats.device_counts.items(), key=lambda x: x[1],
                              reverse=True)[:5]
            print(f"    Top devices   :")
            for dev, count in top_devs:
                print(f"      {dev:<40s} {count:>6,}")
        print()

    # Totals across all servers
    total_all = sum(s.total_queries for s in all_stats.values())
    blocked_all = sum(s.blocked_queries for s in all_stats.values())
    rate_all = (blocked_all / total_all * 100) if total_all else 0.0
    print(f"  {Colors.BOLD}Total (all servers){Colors.RESET}")
    print(f"    Total queries : {total_all:>10,}")
    print(f"    Blocked       : {blocked_all:>10,} ({rate_all:.1f}%)")
    print(f"{Colors.BOLD}{'='*70}{Colors.RESET}\n")


# ─── Queue display (unchanged) ─────────────────────────────────────

async def display_queue(queue: asyncio.Queue) -> None:
    """Display messages from the queue."""
    while True:
        msg = await queue.get()
        print(msg, flush=True)
        queue.task_done()


# ─── CLI helpers (stream / stats / export) ────────────────────────

async def _cmd_stream(args: argparse.Namespace, servers: List[ServerConfig]) -> int:
    """Stream and merge logs from configured servers."""
    queue: asyncio.Queue = asyncio.Queue()

    # Resolve export path (from --export or --output)
    export_path: Optional[Path] = getattr(args, 'export', None) or getattr(args, 'output', None)
    if export_path:
        export_path = Path(export_path).resolve()

    print(f"{Colors.BOLD}Connecting to {len(servers)} server(s)...{Colors.RESET}")

    streamers = [PiHoleStreamer(sv) for sv in servers]

    try:
        # Connect all servers concurrently (status check)
        await asyncio.gather(*[s.connect() for s in streamers])

        print(f"{Colors.GREEN}Connected. Streaming logs... (Ctrl+C to stop){Colors.RESET}\n")

        await asyncio.gather(
            *[streamer.stream_logs(queue, args.blocked_only,
                                    getattr(args, 'filter', None),
                                    getattr(args, 'verbose', False),
                                    export_path)
              for streamer in streamers],
            display_queue(queue)
        )
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Stopping...{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.RESET}", file=sys.stderr)
        return 1
    finally:
        for s in streamers:
            s.close()
    return 0


async def _cmd_stats(args: argparse.Namespace, servers: List[ServerConfig]) -> int:
    """Collect stats from servers and print summary."""
    all_stats: Dict[str, ServerStats] = {}

    for server in servers:
        streamer = PiHoleStreamer(server)
        stats = ServerStats()
        try:
            await streamer.connect()
            print(f"{Colors.YELLOW}Collecting stats from {server.name}...{Colors.RESET}")
            # Read last N lines from log (use pihole -f for recent, or tail)
            loop = asyncio.get_running_loop()

            def _read_log() -> List[str]:
                client = paramiko.SSHClient()
                try:
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    client.connect(server.hostname, username=server.username,
                                   port=server.port)
                    _, stdout, _ = client.exec_command(
                        'sudo tail -500 /var/log/pihole.log')
                    lines = stdout.read().decode().splitlines()
                finally:
                    client.close()
                return lines

            log_lines = await loop.run_in_executor(None, _read_log)
            for raw_line in log_lines:
                parsed = streamer.parse_log_line(raw_line)
                if parsed:
                    query_part, ip, is_blocked = parsed
                    ts = datetime.now().strftime('%H:%M:%S')
                    hostname = streamer.resolve_hostname(ip)
                    host_display = f"{hostname} ({ip})" if hostname != ip else ip
                    entry = LogEntry(
                        timestamp=ts, server_name=server.name,
                        host_display=host_display, query_part=query_part,
                        ip=ip, is_blocked=is_blocked)
                    _update_stats(entry, stats)
            all_stats[server.name] = stats
        except Exception as e:
            print(f"{Colors.RED}{server.name}: {e}{Colors.RESET}", file=sys.stderr)
        finally:
            streamer.close()

    print_stats(all_stats)
    return 0


# ─── CLI entry point with subcommands ─────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    from config import load_servers  # lazy import to avoid circular deps

    parser = argparse.ArgumentParser(
        prog='pihole-twins',
        description='Stream and merge Pi-hole query logs from multiple servers.',
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # ── stream (default) ────────────────────────────────────────
    sp_stream = subparsers.add_parser('stream', help='Stream and merge live logs')
    sp_stream.set_defaults(func=_cmd_stream)
    sp_stream.add_argument('--servers', '-s', nargs='+',
                           help='Server names (default: from config.py)')
    sp_stream.add_argument('--blocked-only', '-b', action='store_true',
                           help='Show only blocked queries')
    sp_stream.add_argument('--filter', '-f', default=None,
                           help='Filter by hostname or IP')
    sp_stream.add_argument('--verbose', '-v', action='store_true',
                           help='Show unparseable log lines too')
    sp_stream.add_argument('--export', '-e', default=None,
                           help='Export log entries as JSONL to file')

    # ── stats ───────────────────────────────────────────────────
    sp_stats = subparsers.add_parser('stats', help='Show blocklist statistics')
    sp_stats.set_defaults(func=_cmd_stats)
    sp_stats.add_argument('--servers', '-s', nargs='+',
                           help='Server names (default: from config.py)')

    # ── export (collect logs to file) ───────────────────────────
    sp_export = subparsers.add_parser('export', help='Export logs to JSONL/CSV')
    sp_export.set_defaults(func=_cmd_stream)  # reuse stream with --export
    sp_export.add_argument('--servers', '-s', nargs='+',
                           help='Server names (default: from config.py)')
    sp_export.add_argument('--output', '-o', required=True,
                           help='Output file path (.jsonl or .csv)')
    sp_export.add_argument('--lines', '-n', type=int, default=1000,
                           help='Number of recent log lines to collect')

    return parser


def main() -> int:
    """Main entry point."""
    from config import load_servers

    parser = _build_parser()
    args = parser.parse_args()

    # Resolve servers from CLI or config
    server_names: Optional[List[str]] = getattr(args, 'servers', None)
    servers = load_servers(server_names) if server_names else load_servers()

    if not servers:
        print("{Colors.RED}No servers configured. Edit config.py or pass --servers.{Colors.RESET}",
              file=sys.stderr)
        return 1

    # Assign colors
    for i, sv in enumerate(servers):
        sv.color_index = i

    # Dispatch to subcommand handler
    handler = getattr(args, 'func', _cmd_stream)
    return asyncio.run(handler(args, servers))


if __name__ == '__main__':
    sys.exit(main())
