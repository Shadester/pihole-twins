"""Export module for Pi-hole Twins.

Supports exporting historical statistics to CSV and JSONL formats.
Integrates with stats.py for database-backed exports.

Usage:
    from export import Exporter, export_stats_to_csv, export_stats_to_jsonl

    exporter = Exporter()
    await exporter.export_all(db, output_path)
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from stats import ServerStats, StatsDB


class Exporter:
    """Handles exporting statistics to various formats."""

    def __init__(self, db: Optional[StatsDB] = None):
        """Initialize exporter with optional StatsDB instance.

        Args:
            db: Optional StatsDB instance for database-backed exports.
        """
        self.db = db

    async def export_all(self, output_path: Path) -> int:
        """Export all available statistics to the specified file.

        Args:
            output_path: Path to export file (.csv or .jsonl).

        Returns:
            Number of records exported.
        """
        if not self.db:
            raise ValueError("No StatsDB instance provided for export")

        output_path = Path(output_path).resolve()
        suffix = output_path.suffix.lower()

        if suffix == '.csv':
            return await self._export_csv(output_path)
        elif suffix in ('.jsonl', '.json'):
            return await self._export_jsonl(output_path)
        else:
            raise ValueError(f"Unsupported export format: {suffix}. Use .csv or .jsonl")

    async def _export_csv(self, output_path: Path) -> int:
        """Export statistics to CSV format."""
        summary_rows = self.db.get_summary_csv()
        daily_rows = self.db.get_daily_csv()

        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)

            # Summary section
            writer.writerow(['=== Server Summary ==='])
            writer.writerow(['Server', 'Total Queries', 'Blocked Queries', 'Block Rate (%)'])
            for row in summary_rows:
                writer.writerow(row)

            # Daily section (if available)
            if daily_rows:
                writer.writerow([])
                writer.writerow(['=== Daily Breakdown ==='])
                writer.writerow(['Server', 'Date', 'Total Queries', 'Blocked Queries'])
                for row in daily_rows:
                    writer.writerow(row)

        return len(summary_rows) + (len(daily_rows) if daily_rows else 0)

    async def _export_jsonl(self, output_path: Path) -> int:
        """Export statistics to JSONL format."""
        summary_data = self.db.get_summary_json()

        with open(output_path, 'w') as f:
            for server_name, stats_dict in summary_data.items():
                record = {
                    'server': server_name,
                    'exported_at': datetime.now().isoformat(),
                    **stats_dict,
                }
                f.write(json.dumps(record) + '\n')

        return len(summary_data)


def export_stats_to_csv(db: StatsDB, output_path: Path) -> int:
    """Convenience function to export stats to CSV.

    Args:
        db: StatsDB instance with collected statistics.
        output_path: Path to export file.

    Returns:
        Number of records exported.
    """
    exporter = Exporter(db)
    return exporter.export_all(output_path)


def export_stats_to_jsonl(db: StatsDB, output_path: Path) -> int:
    """Convenience function to export stats to JSONL.

    Args:
        db: StatsDB instance with collected statistics.
        output_path: Path to export file.

    Returns:
        Number of records exported.
    """
    exporter = Exporter(db)
    return exporter.export_all(output_path)
