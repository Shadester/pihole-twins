#!/usr/bin/env python3
"""
Stream and merge query logs from two Pi-hole servers.
"""

import asyncio
import argparse
import sys
import socket
from datetime import datetime
import paramiko
from typing import Optional, Dict


# ANSI color codes
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'


class PiHoleStreamer:
    def __init__(self, hostname: str, username: str = 'pi', color: str = Colors.CYAN):
        self.hostname = hostname
        self.username = username
        self.color = color
        self.client: Optional[paramiko.SSHClient] = None
        self.dns_cache: Dict[str, str] = {}  # IP -> hostname cache
        self.last_query_ip: Optional[str] = None  # Track last query IP for block associations

    async def connect(self):
        """Establish SSH connection to Pi-hole server."""
        loop = asyncio.get_event_loop()

        def _connect():
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self.hostname, username=self.username)
            return client

        self.client = await loop.run_in_executor(None, _connect)

    def resolve_hostname(self, ip: str) -> str:
        """Resolve IP to hostname with caching."""
        if ip in self.dns_cache:
            return self.dns_cache[ip]

        try:
            hostname = socket.gethostbyaddr(ip)[0]
            self.dns_cache[ip] = hostname
            return hostname
        except (socket.herror, socket.gaierror):
            self.dns_cache[ip] = ip  # Cache the IP itself if resolution fails
            return ip

    def parse_log_line(self, line: str) -> Optional[tuple]:
        """Parse log line to extract IP and other info."""
        # Pi-hole log format: "Oct  4 14:18:46: query[A] example.com from 192.168.1.100"
        # Blocked: "Oct  4 14:18:46: gravity blocked example.com is 0.0.0.0"
        import re

        # Match lines that have "query[TYPE]" followed by "from IP"
        match = re.search(r'query\[.*?\].*?from\s+([\d.]+)$', line)
        if match:
            ip = match.group(1)
            query_part = line[:match.start(1)-6]  # Get everything before " from "
            is_blocked = False
            self.last_query_ip = ip  # Remember this IP for potential block lines
            return (query_part, ip, is_blocked)

        # Check for block/deny lines (these typically follow a query line)
        if ('gravity blocked' in line.lower() or 'exactly blocked' in line.lower() or 'exactly denied' in line.lower()):
            if self.last_query_ip:
                # Use the last query IP for this block
                return (line, self.last_query_ip, True)

        return None

    async def stream_logs(self, queue: asyncio.Queue, show_blocked_only: bool = False, filter_host: Optional[str] = None, verbose: bool = False):
        """Stream logs from Pi-hole and add to queue."""
        if not self.client:
            raise RuntimeError("Not connected. Call connect() first.")

        # Use 'sudo pihole -t' command which tails the log
        # get_pty=True allows sudo to work without password if configured
        stdin, stdout, stderr = self.client.exec_command('sudo pihole -t', get_pty=True)

        loop = asyncio.get_event_loop()

        while True:
            line = await loop.run_in_executor(None, stdout.readline)
            if not line:
                break

            line = line.strip()
            if not line:
                continue

            # Parse the log line
            parsed = self.parse_log_line(line)

            if parsed:
                query_part, ip, is_blocked = parsed

                # Filter for blocked queries if requested
                if show_blocked_only and not is_blocked:
                    continue

                # Resolve hostname
                hostname = await loop.run_in_executor(None, self.resolve_hostname, ip)

                # Filter by host if specified
                if filter_host and filter_host.lower() not in hostname.lower() and filter_host != ip:
                    continue

                # Add formatted line to queue
                timestamp = datetime.now().strftime('%H:%M:%S')
                host_display = f"{hostname} ({ip})" if hostname != ip else ip

                if is_blocked:
                    formatted = f"{Colors.BOLD}[{timestamp}] {self.color}[{self.hostname}]{Colors.RESET} {Colors.YELLOW}[{host_display}]{Colors.RESET} {Colors.RED}{query_part}{Colors.RESET}"
                else:
                    formatted = f"[{timestamp}] {self.color}[{self.hostname}]{Colors.RESET} {Colors.YELLOW}[{host_display}]{Colors.RESET} {query_part}"

                await queue.put(formatted)
            else:
                # If we can't parse it, only show it in verbose mode (or when no filters active)
                if verbose and not filter_host and not show_blocked_only:
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    formatted = f"[{timestamp}] {self.color}[{self.hostname}]{Colors.RESET} {line}"
                    await queue.put(formatted)

    def close(self):
        """Close SSH connection."""
        if self.client:
            self.client.close()


async def display_queue(queue: asyncio.Queue):
    """Display messages from the queue."""
    while True:
        msg = await queue.get()
        print(msg, flush=True)
        queue.task_done()


async def main(args):
    """Main function to coordinate streaming from both Pi-holes."""
    queue = asyncio.Queue()

    # Create streamers for both Pi-holes
    streamer1 = PiHoleStreamer(args.pihole1, args.username, Colors.CYAN)
    streamer2 = PiHoleStreamer(args.pihole2, args.username, Colors.MAGENTA)

    print(f"{Colors.BOLD}Connecting to Pi-hole servers...{Colors.RESET}")

    try:
        # Connect to both servers
        await asyncio.gather(
            streamer1.connect(),
            streamer2.connect()
        )

        print(f"{Colors.GREEN}Connected to {args.pihole1} and {args.pihole2}{Colors.RESET}")
        print(f"{Colors.BOLD}Streaming logs... (Press Ctrl+C to stop){Colors.RESET}\n")

        # Start streaming from both servers and displaying output
        await asyncio.gather(
            streamer1.stream_logs(queue, args.blocked_only, args.filter, args.verbose),
            streamer2.stream_logs(queue, args.blocked_only, args.filter, args.verbose),
            display_queue(queue)
        )

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Stopping...{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.RESET}", file=sys.stderr)
        return 1
    finally:
        streamer1.close()
        streamer2.close()

    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Stream and merge Pi-hole query logs from two servers')
    parser.add_argument('--pihole1', default='pihole1', help='Hostname of first Pi-hole (default: pihole1)')
    parser.add_argument('--pihole2', default='pihole2', help='Hostname of second Pi-hole (default: pihole2)')
    parser.add_argument('--username', '-u', default='pi', help='SSH username (default: pi)')
    parser.add_argument('--blocked-only', '-b', action='store_true', help='Show only blocked queries')
    parser.add_argument('--filter', '-f', help='Filter by hostname or IP')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show all log lines including cache/reply/forwarded')

    args = parser.parse_args()

    sys.exit(asyncio.run(main(args)))
