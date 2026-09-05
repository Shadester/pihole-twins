"""
Blocklist statistics module for Pi-hole Twins.

Tracks top blocked/queried domains, per-device stats, and provides
historical persistence via SQLite across restarts.

Usage:
    from stats import StatsDB, collect_stats_from_server, print_stats_table

    db = StatsDB()
    stats = await collect_stats_from_server(streamer, db)
    print_stats_table(db)
"""

import asyncio
import csv
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from models import ServerStats, LogEntry, _update_stats, Colors
from stream_pihole_logs import PiHoleStreamer


class StatsDB:
    """SQLite-backed persistent statistics storage."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            config_dir = Path.home() / '.config' / 'piholetwins'
            db_path = config_dir / 'stats.db'
        self.db_path = Path(db_path)
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create the database and tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS server_stats (
                    server_name TEXT PRIMARY KEY,
                    total_queries INTEGER DEFAULT 0,
                    blocked_queries INTEGER DEFAULT 0,
                    top_domains TEXT,
                    device_counts TEXT,
                    last_updated TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_name TEXT NOT NULL,
                    stat_date TEXT NOT NULL,
                    total_queries INTEGER DEFAULT 0,
                    blocked_queries INTEGER DEFAULT 0,
                    top_domains TEXT,
                    UNIQUE(server_name, stat_date)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS log_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    domain TEXT,
                    device TEXT,
                    ip TEXT,
                    is_blocked INTEGER DEFAULT 0,
                    raw_line TEXT
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_daily_stats
                ON daily_stats(server_name, stat_date)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_log_entries
                ON log_entries(server_name, timestamp)
            ''')
            conn.commit()
        finally:
            conn.close()

    def update_server_stats(self, server_name: str, stats: ServerStats) -> None:
        """Update the summary statistics for a server."""
        today = datetime.now().strftime('%Y-%m-%d')
        now_iso = datetime.now().isoformat()
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO server_stats (server_name, total_queries, blocked_queries,
                                          top_domains, device_counts, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_name) DO UPDATE SET
                    total_queries = excluded.total_queries,
                    blocked_queries = excluded.blocked_queries,
                    top_domains = excluded.top_domains,
                    device_counts = excluded.device_counts,
                    last_updated = excluded.last_updated
            ''', (server_name, stats.total_queries, stats.blocked_queries,
                  json.dumps(stats.top_domains), json.dumps(stats.device_counts),
                  now_iso))
            cursor.execute('''
                INSERT INTO daily_stats (server_name, stat_date, total_queries,
                                         blocked_queries, top_domains)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(server_name, stat_date) DO UPDATE SET
                    total_queries = excluded.total_queries,
                    blocked_queries = excluded.blocked_queries,
                    top_domains = excluded.top_domains
            ''', (server_name, today, stats.total_queries, stats.blocked_queries,
                  json.dumps(stats.top_domains)))
            conn.commit()
        finally:
            conn.close()

    def add_log_entry(self, server_name: str, timestamp: str, domain: Optional[str],
                      device: Optional[str], ip: Optional[str], is_blocked: bool,
                      raw_line: str = '') -> None:
        """Add a single log entry to the database."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO log_entries (server_name, timestamp, domain, device, ip,
                                         is_blocked, raw_line)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (server_name, timestamp, domain, device, ip,
                  1 if is_blocked else 0, raw_line))
            conn.commit()
        finally:
            conn.close()

    def get_server_stats(self, server_name: str) -> Optional[ServerStats]:
        """Retrieve summary statistics for a server."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM server_stats WHERE server_name = ?',
                           (server_name,))
            row = cursor.fetchone()
            if not row:
                return None
            stats = ServerStats(total_queries=row[1], blocked_queries=row[2])
            stats.top_domains = json.loads(row[3]) if row[3] else {}
            stats.device_counts = json.loads(row[4]) if row[4] else {}
            return stats
        finally:
            conn.close()

    def get_all_server_stats(self) -> Dict[str, ServerStats]:
        """Retrieve summary statistics for all servers."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM server_stats')
            rows = cursor.fetchall()
            result: Dict[str, ServerStats] = {}
            for row in rows:
                stats = ServerStats(total_queries=row[1], blocked_queries=row[2])
                stats.top_domains = json.loads(row[3]) if row[3] else {}
                stats.device_counts = json.loads(row[4]) if row[4] else {}
                result[row[0]] = stats
            return result
        finally:
            conn.close()

    def get_daily_stats(self, server_name: str, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily statistics for a server over the last N days."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT stat_date, total_queries, blocked_queries, top_domains
                FROM daily_stats
                WHERE server_name = ? AND stat_date >= ?
                ORDER BY stat_date DESC
            ''', (server_name, start_date))
            rows = cursor.fetchall()
            result = []
            for row in rows:
                entry = {
                    'date': row[0], 'total_queries': row[1],
                    'blocked_queries': row[2],
                }
                entry['top_domains'] = json.loads(row[3]) if row[3] else {}
                result.append(entry)
            return result
        finally:
            conn.close()

    def get_top_domains(self, server_name: Optional[str] = None,
                        limit: int = 20) -> List[Tuple[str, int]]:
        """Get the most frequently queried/blocked domains."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            if server_name:
                query = '''
                    SELECT domain, SUM(count) as total
                    FROM (
                        SELECT json_extract(json_each.value, '$[0]') as domain,
                               json_extract(json_each.value, '$[1]') as count
                        FROM daily_stats, json_each(top_domains)
                        WHERE server_name = ?
                    )
                    GROUP BY domain ORDER BY total DESC LIMIT ?
                '''
                rows = cursor.execute(query, (server_name, limit)).fetchall()
            else:
                query = '''
                    SELECT domain, SUM(count) as total
                    FROM (
                        SELECT json_extract(json_each.value, '$[0]') as domain,
                               json_extract(json_each.value, '$[1]') as count
                        FROM daily_stats, json_each(top_domains)
                    )
                    GROUP BY domain ORDER BY total DESC LIMIT ?
                '''
                rows = cursor.execute(query, (limit,)).fetchall()
            return [(r[0], int(r[1])) for r in rows]
        finally:
            conn.close()

    # ── Export helpers ────────────────────────────────────────────

    def get_summary_csv(self) -> List[List[str]]:
        """Get summary data as CSV-ready rows."""
        all_stats = self.get_all_server_stats()
        rows: List[List[str]] = []
        for name, stats in all_stats.items():
            rows.append([name, str(stats.total_queries),
                         str(stats.blocked_queries),
                         f"{stats.block_rate:.1f}%"])
        return rows

    def get_daily_csv(self) -> List[List[str]]:
        """Get daily stats as CSV-ready rows."""
        all_stats = self.get_all_server_stats()
        rows: List[List[str]] = []
        for name in all_stats:
            daily = self.get_daily_stats(name)
            for entry in daily:
                rows.append([name, entry['date'], str(entry['total_queries']),
                             str(entry['blocked_queries'])])
        return rows

    def get_summary_json(self) -> Dict[str, Dict[str, Any]]:
        """Get summary data as JSON-serializable dict."""
        all_stats = self.get_all_server_stats()
        result: Dict[str, Dict[str, Any]] = {}
        for name, stats in all_stats.items():
            result[name] = stats.to_dict()
        return result


# ── Stats collection via SSH ──────────────────────────────────────

async def collect_stats_from_server(streamer: PiHoleStreamer,
                                    db: StatsDB) -> ServerStats:
    """Collect statistics from a Pi-hole server via SSH log file."""
    loop = asyncio.get_event_loop()
    try:
        await streamer.connect()
        stdin, stdout, stderr = streamer.client.exec_command(
            'sudo cat /var/log/pihole.log | tail -5000', get_pty=True)
        output = await loop.run_in_executor(None, stdout.read)

        if isinstance(output, bytes):
            output = output.decode('utf-8', errors='ignore')

        stats = ServerStats()
        entries = (output.strip()
                   .replace('\r', '')
                   .split('\n')) if output.strip() else []

        for line in entries:
            parsed = streamer.parse_log_line(line)
            if parsed:
                query_part, ip, is_blocked = parsed
                hostname = await streamer.resolve_hostname_with_timeout(ip)
                host_display = (f"{hostname} ({ip})" if hostname != ip else ip)

                entry = LogEntry(
                    timestamp=datetime.now().strftime('%H:%M:%S'),
                    server_name=streamer.config.name,
                    host_display=host_display,
                    query_part=query_part,
                    ip=ip,
                    is_blocked=is_blocked,
                    raw_line=line,
                )
                _update_stats(entry, stats)

                parts = query_part.split()
                domain = parts[-2] if len(parts) >= 3 else None
                db.add_log_entry(
                    streamer.config.name, datetime.now().isoformat(),
                    domain, host_display, ip, is_blocked, line)

        db.update_server_stats(streamer.config.name, stats)
        return stats
    except Exception as e:
        raise Exception(f"Failed to collect stats from {streamer.config.name}: {e}")
    finally:
        streamer.close()


# ── Display helpers ───────────────────────────────────────────────

def print_stats_table(db: StatsDB) -> None:
    """Print formatted statistics table from database."""
    all_stats = db.get_all_server_stats()

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
                bar = '\u2588' * min(count // max(1, stats.total_queries // 50), 30)
                print(f"      {domain:<40s} {count:>6,}  {bar}")
        if stats.device_counts:
            top_devs = sorted(stats.device_counts.items(), key=lambda x: x[1],
                              reverse=True)[:5]
            print(f"    Top devices   :")
            for dev, count in top_devs:
                print(f"      {dev:<40s} {count:>6,}")
        print()

    total_all = sum(s.total_queries for s in all_stats.values())
    blocked_all = sum(s.blocked_queries for s in all_stats.values())
    rate_all = (blocked_all / total_all * 100) if total_all else 0.0
    print(f"  {Colors.BOLD}Total (all servers){Colors.RESET}")
    print(f"    Total queries : {total_all:>10,}")
    print(f"    Blocked       : {blocked_all:>10,} ({rate_all:.1f}%)")


# ── CLI helpers ───────────────────────────────────────────────────

def create_stats_parser() -> 'argparse.ArgumentParser':  # type: ignore
    """Create argument parser for stats subcommand."""
    import argparse
    parser = argparse.ArgumentParser(prog='pihole-twins stats',
                                     description='Show blocklist statistics.')
    parser.add_argument('--servers', '-s', nargs='+',
                        help='Server names (default: from config)')
    return parser


async def _cmd_stats_cli(args: 'argparse.Namespace') -> int:  # type: ignore
    """CLI handler for stats subcommand."""
    from config import load_servers
    server_names = getattr(args, 'servers', None)
    servers = load_servers(server_names) if server_names else load_servers()

    if not servers:
        print(f"{Colors.RED}No servers configured.{Colors.RESET}", file=sys.stderr)
        return 1

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

    print_stats_table(db)
    return 0
