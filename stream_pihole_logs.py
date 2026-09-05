#!/usr/bin/env python3
"""
Stream and merge query logs from Pi-hole servers.

Supports multiple servers, real-time color-coded output, blocking filtering,
SSH config parsing, SSH key passphrases, auto-reconnection with exponential
backoff, and log export to JSONL format.
"""

import asyncio
import argparse
import getpass
import json
import os
import re
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import paramiko
from models import ServerConfig, LogEntry, _update_stats, print_stats, Colors, DEFAULT_COLORS

from config import load_servers


class PiHoleStreamer:
    """Manages SSH connection and log streaming for a single Pi-hole server."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.hostname: str = config.hostname
        self.username: str = config.username
        self.color: str = config.get_color()
        self.client: Optional[paramiko.SSHClient] = None
        self.dns_cache: Dict[str, str] = {}
        self.last_query_ip: Optional[str] = None
        self._stdin: Any = None
        self._stdout: Any = None
        self._stderr: Any = None

    # ── SSH config parsing ───────────────────────────────────────

    def _parse_ssh_config(self) -> Dict[str, Any]:
        """Parse ~/.ssh/config for this host's settings."""
        ssh_dir = Path.home() / '.ssh'
        config_path = ssh_dir / 'config'
        if not config_path.exists():
            return {}

        result: Dict[str, Any] = {
            'hostname': self.hostname, 'port': 22,
            'username': self.username, 'identityfile': None,
        }
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

                if directive == 'host':
                    hosts = value.split()
                    current_host = self.hostname if self.hostname in hosts else None
                    continue

                if current_host is not None or value == '*':
                    if directive == 'hostname' and 'resolved_hostname' not in result:
                        result['resolved_hostname'] = value
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

    # ── Passphrase handling ──────────────────────────────────────

    def _get_passphrase(self) -> str:
        """Get SSH key passphrase from env var or interactive prompt."""
        env_key = f'SSH_KEY_PASSPHRASE_{self.config.name.upper().replace("-", "_")}'
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val

        key_path = (self.config.key_file
                    or (Path.home() / '.ssh'
                        / (self._parse_ssh_config().get('identityfile') or Path(''))))
        if key_path and key_path.exists():
            try:
                print(f"\nEnter passphrase for {self.config.name} "
                      f"(or press Enter to skip):", end='', flush=True)
                return getpass.getpass()
            except (EOFError, KeyboardInterrupt):
                return ''
        return ''

    # ── Connection management ────────────────────────────────────

    async def connect(self) -> None:
        """Establish SSH connection to Pi-hole server."""
        loop = asyncio.get_event_loop()
        ssh_cfg = self._parse_ssh_config()
        connect_port = ssh_cfg.get('port', self.config.port)
        connect_user = ssh_cfg.get('username', self.username)

        key_file: Optional[Path] = None
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
            client.connect(**kwargs)
            return client

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

    # ── DNS resolution (with 2-second timeout) ──────────────────

    def resolve_hostname(self, ip: str) -> str:
        """Resolve IP to hostname with caching and 2-second timeout."""
        if ip in self.dns_cache:
            return self.dns_cache[ip]

        try:
            hostname = socket.gethostbyaddr(ip)[0]
            self.dns_cache[ip] = hostname
            return hostname
        except (socket.herror, socket.gaierror):
            self.dns_cache[ip] = ip
            return ip

    def resolve_hostname_with_timeout(self, ip: str) -> str:
        """Resolve IP with explicit 2-second timeout using ThreadPoolExecutor."""
        if ip in self.dns_cache:
            return self.dns_cache[ip]

        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = loop.run_in_executor(executor, socket.gethostbyaddr, ip)
            hostname = future.result(timeout=2)
            self.dns_cache[ip] = hostname
            return hostname
        except FuturesTimeoutError:
            self.dns_cache[ip] = ip
            return ip
        except (socket.herror, socket.gaierror):
            self.dns_cache[ip] = ip
            return ip

    # ── Log parsing ──────────────────────────────────────────────

    def parse_log_line(self, line: str) -> Optional[Tuple[str, str, bool]]:
        """Parse log line to extract (query_part, ip, is_blocked)."""
        match = re.search(r'query\[.*?\].*?from\s+([\d.]+)$', line)
        if match:
            ip = match.group(1)
            query_part = line[:match.start(1) - 6]
            self.last_query_ip = ip
            return (query_part, ip, False)

        if ('gravity blocked' in line.lower() or 'exactly blocked' in line.lower()
                or 'exactly denied' in line.lower()):
            if self.last_query_ip:
                return (line, self.last_query_ip, True)

        return None

    # ── Stream management ────────────────────────────────────────

    async def stream_logs(self, queue: asyncio.Queue,
                          show_blocked_only: bool = False,
                          filter_host: Optional[str] = None,
                          verbose: bool = False,
                          export_path: Optional[Path] = None) -> None:
        """Stream logs from Pi-hole with auto-reconnect and optional export."""
        loop = asyncio.get_event_loop()
        max_backoff: float = 60.0
        backoff: float = 1.0
        export_file = None

        if export_path:
            export_path = Path(export_path).resolve()
            export_file = open(export_path, 'a')

        while True:
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

            backoff = 1.0

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

                        hostname = self.resolve_hostname_with_timeout(ip)

                        if filter_host and filter_host.lower() not in hostname.lower() \
                                and filter_host != ip:
                            continue

                        timestamp = datetime.now().strftime('%H:%M:%S')
                        host_display = (f"{hostname} ({ip})" if hostname != ip else ip)

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

                        if export_file:
                            entry = LogEntry(
                                timestamp=timestamp,
                                server_name=self.config.name,
                                host_display=host_display,
                                query_part=query_part,
                                ip=ip,
                                is_blocked=is_blocked,
                            )
                            export_file.write(json.dumps(entry.to_dict()) + '\n')
                            export_file.flush()
                    elif verbose and not filter_host and not show_blocked_only:
                        timestamp = datetime.now().strftime('%H:%M:%S')
                        formatted = (f"[{timestamp}] "
                                     f"{self.color}[{self.config.name}]{Colors.RESET} "
                                     f"{line}")
                        await queue.put(formatted)

            except Exception:
                print(f"\n{Colors.YELLOW}{self.config.name}: Stream ended, "
                      f"reconnecting...{Colors.RESET}", file=sys.stderr)
                if export_file:
                    export_file.close()
                    export_file = None
                self.disconnect()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

        if export_file:
            export_file.close()

    def close(self) -> None:
        """Close SSH connection."""
        self.disconnect()


# ─── Queue display ────────────────────────────────────────────────

async def display_queue(queue: asyncio.Queue) -> None:
    """Display messages from the queue."""
    while True:
        msg = await queue.get()
        print(msg, flush=True)
        queue.task_done()


# ─── CLI handlers ─────────────────────────────────────────────────

async def _cmd_stream(args: argparse.Namespace, servers: List[ServerConfig]) -> int:
    """Stream and merge logs from configured servers."""
    queue: asyncio.Queue = asyncio.Queue()

    export_path: Optional[Path] = getattr(args, 'export', None) or getattr(args, 'output', None)
    if export_path:
        export_path = Path(export_path).resolve()

    print(f"{Colors.BOLD}Connecting to {len(servers)} server(s)...{Colors.RESET}")

    streamers = [PiHoleStreamer(sv) for sv in servers]

    try:
        await asyncio.gather(*[s.connect() for s in streamers])
        print(f"{Colors.GREEN}Connected. Streaming logs... "
              f"(Ctrl+C to stop){Colors.RESET}\n")

        await asyncio.gather(
            *[streamer.stream_logs(queue, getattr(args, 'blocked_only', False),
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
    from stats import StatsDB, collect_stats_from_server

    db = StatsDB()
    all_stats: Dict[str, ServerStats] = {}

    for server in servers:
        streamer = PiHoleStreamer(server)
        try:
            print(f"{Colors.YELLOW}Collecting stats from {server.name}...{Colors.RESET}")
            stats = await collect_stats_from_server(streamer, db)
            all_stats[server.name] = stats
        except Exception as e:
            print(f"{Colors.RED}{server.name}: {e}{Colors.RESET}", file=sys.stderr)
        finally:
            streamer.close()

    print_stats(all_stats)
    return 0


# ─── CLI entry point ──────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog='pihole-twins',
        description='Stream and merge Pi-hole query logs from multiple servers.',
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # ── stream ────────────────────────────────────────────────────
    sp_stream = subparsers.add_parser('stream', help='Stream and merge live logs')
    sp_stream.set_defaults(func=_cmd_stream)
    sp_stream.add_argument('--servers', '-s', nargs='+',
                           help='Server names (default: from config)')
    sp_stream.add_argument('--blocked-only', '-b', action='store_true',
                           help='Show only blocked queries')
    sp_stream.add_argument('--filter', '-f', default=None,
                           help='Filter by hostname or IP')
    sp_stream.add_argument('--verbose', '-v', action='store_true',
                           help='Show unparseable log lines too')
    sp_stream.add_argument('--export', '-e', default=None,
                           help='Export log entries as JSONL to file')

    # ── stats ─────────────────────────────────────────────────────
    sp_stats = subparsers.add_parser('stats', help='Show blocklist statistics')
    sp_stats.set_defaults(func=_cmd_stats)
    sp_stats.add_argument('--servers', '-s', nargs='+',
                           help='Server names (default: from config)')

    # ── export ────────────────────────────────────────────────────
    sp_export = subparsers.add_parser('export', help='Export logs to JSONL/CSV')
    sp_export.set_defaults(func=_cmd_stream)
    sp_export.add_argument('--servers', '-s', nargs='+',
                           help='Server names (default: from config)')
    sp_export.add_argument('--output', '-o', required=True,
                           help='Output file path (.jsonl or .csv)')
    sp_export.add_argument('--lines', '-n', type=int, default=1000,
                           help='Number of recent log lines to collect')

    return parser


def main() -> int:
    """Main entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    server_names: Optional[List[str]] = getattr(args, 'servers', None)
    servers = load_servers(server_names) if server_names else load_servers()

    if not servers:
        print(f"{Colors.RED}No servers configured. Edit config or pass --servers."
              f"{Colors.RESET}", file=sys.stderr)
        return 1

    for i, sv in enumerate(servers):
        sv.color_index = i

    handler = getattr(args, 'func', _cmd_stream)
    return asyncio.run(handler(args, servers))


if __name__ == '__main__':
    sys.exit(main())
