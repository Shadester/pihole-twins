#!/usr/bin/env python3
"""
Shared data models for pihole-twins.

This module contains all dataclasses and core types used across
stream_pihole_logs.py, stats.py, config.py, and export.py.

Importing from this module does NOT create circular dependencies
because it has no external imports beyond the standard library.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


# ANSI color codes (matches config.py DEFAULT_COLORS)
DEFAULT_COLORS: list[str] = [
    '\033[96m',  # CYAN
    '\033[95m',  # MAGENTA
    '\033[92m',  # GREEN
    '\033[93m',  # YELLOW
    '\033[94m',  # BLUE
    '\033[1;33m',  # BOLD YELLOW
]


@dataclass
class ServerConfig:
    """Configuration for a single Pi-hole server."""
    name: str
    hostname: str = ''
    username: str = 'pi'
    color_index: int = 0
    key_file: str | None = None
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


@dataclass
class ServerStats:
    """Accumulated statistics for a server."""
    total_queries: int = 0
    blocked_queries: int = 0
    top_domains: Dict[str, int] = field(default_factory=lambda: {})
    device_counts: Dict[str, int] = field(default_factory=lambda: {})
    daily_totals: Dict[str, Tuple[int, int]] = field(default_factory=lambda: {})

    @property
    def block_rate(self) -> float:
        return (self.blocked_queries / self.total_queries * 100) if self.total_queries else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize stats for database storage."""
        return {
            'total_queries': self.total_queries,
            'blocked_queries': self.blocked_queries,
            'block_rate': round(self.block_rate, 1),
            'top_domains': dict(sorted(self.top_domains.items(), key=lambda x: x[1], reverse=True)[:20]),
            'device_counts': dict(sorted(self.device_counts.items(), key=lambda x: x[1], reverse=True)[:10]),
            'daily_totals': dict(sorted(self.daily_totals.items())),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ServerStats':
        """Deserialize stats from database."""
        return cls(
            total_queries=data.get('total_queries', 0),
            blocked_queries=data.get('blocked_queries', 0),
            top_domains=data.get('top_domains', {}),
            device_counts=data.get('device_counts', {}),
            daily_totals={k: tuple(v) for k, v in data.get('daily_totals', {}).items()},
        )

    @classmethod
    def from_stream_pihole(cls, entry: 'LogEntry') -> 'ServerStats':
        """Create ServerStats from a single LogEntry (for bridging)."""
        stats = cls()
        total = 1
        blocked = entry.is_blocked and 1 or 0
        parts = entry.query_part.split()
        top_domains: Dict[str, int] = {}
        if len(parts) >= 3:
            domain = parts[-2]
            top_domains[domain] = 1
        device_counts: Dict[str, int] = {}
        if entry.host_display and entry.host_display != entry.ip:
            device_counts[entry.host_display] = 1

        stats = cls(total_queries=total, blocked_queries=blocked,
                    top_domains=top_domains, device_counts=device_counts)
        return stats


class Colors:
    """ANSI color codes (mirrors config.py DEFAULT_COLORS usage)."""
    BOLD = '\033[1m'
    RESET = '\033[0m'
    CYAN = '\033[96m'


def _update_stats(entry: 'LogEntry', stats: 'ServerStats') -> None:
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


def print_stats(all_stats: Dict[str, 'ServerStats']) -> None:
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
