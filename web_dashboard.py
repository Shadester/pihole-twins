"""
Flask web dashboard for Pi-hole Twins.

Provides a real-time web interface to monitor multiple Pi-hole servers,
view block statistics, query history, and daily trends.

Usage:
    python web_dashboard.py [--port 5000] [--debug]
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template_string, request, Response

from config import load_servers
from models import Colors
from stats import StatsDB


app = Flask(__name__)

# ── Data helpers ──────────────────────────────────────────────────

def _get_db() -> StatsDB:
    """Get or create StatsDB instance."""
    db_path = Path.home() / '.config' / 'piholetwins' / 'stats.db'
    return StatsDB(db_path)


def _format_server_stats() -> Dict[str, Dict[str, Any]]:
    """Get formatted server statistics for the dashboard."""
    db = _get_db()
    all_stats = db.get_all_server_stats()
    result = {}
    for name, stats in all_stats.items():
        result[name] = stats.to_dict()
    return result


# ── API routes ────────────────────────────────────────────────────

@app.route('/api/stats')
def api_stats() -> Response:
    """JSON API for server statistics."""
    return jsonify(_format_server_stats())


@app.route('/api/daily/<server_name>')
def api_daily_stats(server_name: str) -> Response:
    """JSON API for daily statistics of a specific server."""
    db = _get_db()
    days = request.args.get('days', 30, type=int)
    daily = db.get_daily_stats(server_name, days)
    return jsonify(daily)


@app.route('/api/top-domains')
def api_top_domains() -> Response:
    """JSON API for top blocked/queried domains."""
    db = _get_db()
    server = request.args.get('server', None)
    limit = request.args.get('limit', 20, type=int)
    top = db.get_top_domains(server, limit)
    return jsonify([{'domain': d, 'count': c} for d, c in top])


@app.route('/api/connections')
def api_connections() -> Response:
    """Check connection status to all configured servers."""
    from stream_pihole_logs import PiHoleStreamer

    servers = load_servers()
    connections = {}
    for server in servers:
        streamer = PiHoleStreamer(server)
        try:
            streamer.connect()
            connections[server.name] = {'status': 'connected', 'reachable': True}
        except Exception as e:
            connections[server.name] = {'status': 'error', 'reachable': False, 'error': str(e)}
        finally:
            streamer.close()
    return jsonify(connections)


# ── Web pages ─────────────────────────────────────────────────────

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pi-hole Twins Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e; color: #eee; padding: 20px;
        }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 { color: #4ecca3; font-size: 2em; }
        .header p { color: #888; margin-top: 5px; }
        .servers { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .server-card {
            background: #16213e; border-radius: 10px; padding: 20px;
            border: 1px solid #0f3460;
        }
        .server-card h2 { color: #4ecca3; margin-bottom: 15px; }
        .stat-row { display: flex; justify-content: space-between; padding: 8px 0;
                    border-bottom: 1px solid #0f3460; }
        .stat-label { color: #aaa; }
        .stat-value { color: #4ecca3; font-weight: bold; }
        .blocked { color: #e94560; }
        .bar {
            height: 8px; background: #0f3460; border-radius: 4px; margin-top: 10px;
        }
        .bar-fill {
            height: 100%; background: #e94560; border-radius: 4px;
            transition: width 0.3s ease;
        }
        .domain-list { list-style: none; margin-top: 10px; }
        .domain-list li { padding: 5px 0; border-bottom: 1px solid #0f3460; font-size: 0.9em; }
        .status-connected { color: #4ecca3; }
        .status-error { color: #e94560; }
        .refresh-btn {
            background: #4ecca3; color: #1a1a2e; border: none; padding: 10px 20px;
            border-radius: 5px; cursor: pointer; font-weight: bold; margin: 20px 0;
        }
        .refresh-btn:hover { background: #3ba886; }
        #last-updated { color: #888; font-size: 0.8em; text-align: center; }
        .chart-container {
            background: #16213e; border-radius: 10px; padding: 20px;
            margin-top: 20px; border: 1px solid #0f3460;
        }
        .chart-container h2 { color: #4ecca3; margin-bottom: 15px; }
        .bar-chart { display: flex; align-items: flex-end; height: 200px; gap: 4px; }
        .bar-wrapper { flex: 1; display: flex; flex-direction: column; align-items: center; }
        .bar {
            width: 100%; background: #4ecca3; border-radius: 2px 2px 0 0;
            transition: height 0.3s ease; min-height: 2px;
        }
        .bar-label { font-size: 0.7em; color: #888; margin-top: 5px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Pi-hole Twins Dashboard</h1>
        <p>Real-time monitoring of multiple Pi-hole servers</p>
        <button class="refresh-btn" onclick="refreshData()">Refresh Data</button>
        <div id="last-updated"></div>
    </div>

    <div id="servers" class="servers"></div>

    <div class="chart-container">
        <h2>Daily Queries (Last 30 Days)</h2>
        <div id="chart" class="bar-chart"></div>
    </div>

    <script>
        async function refreshData() {
            try {
                const statsRes = await fetch('/api/stats');
                const stats = await statsRes.json();

                const serversDiv = document.getElementById('servers');
                serversDiv.innerHTML = '';

                for (const [name, data] of Object.entries(stats)) {
                    const card = document.createElement('div');
                    card.className = 'server-card';
                    const rate = data.block_rate.toFixed(1);
                    const total = data.total_queries.toLocaleString();
                    const blocked = data.blocked_queries.toLocaleString();
                    card.innerHTML = `
                        <h2>${name}</h2>
                        <div class="stat-row">
                            <span class="stat-label">Total Queries</span>
                            <span class="stat-value">${total}</span>
                        </div>
                        <div class="stat-row">
                            <span class="stat-label">Blocked</span>
                            <span class="stat-value blocked">${blocked}</span>
                        </div>
                        <div class="stat-row">
                            <span class="stat-label">Block Rate</span>
                            <span class="stat-value">${rate}%</span>
                        </div>
                        <div class="bar"><div class="bar-fill" style="width: ${rate}%"></div></div>
                        <ul class="domain-list">
                            ${Object.entries(data.top_domains || {}).slice(0, 5).map(([d, c]) =>
                                `<li>${d}: ${c.toLocaleString()}</li>`
                            ).join('')}
                        </ul>
                    `;
                    serversDiv.appendChild(card);
                }

                // Update chart with daily data for first server
                const serverNames = Object.keys(stats);
                if (serverNames.length > 0) {
                    const dailyRes = await fetch(`/api/daily/${serverNames[0]}&days=30`);
                    const daily = await dailyRes.json();
                    const chartDiv = document.getElementById('chart');
                    chartDiv.innerHTML = '';

                    const maxQueries = Math.max(...daily.map(d => d.total_queries), 1);
                    daily.forEach(entry => {
                        const wrapper = document.createElement('div');
                        wrapper.className = 'bar-wrapper';
                        const bar = document.createElement('div');
                        bar.className = 'bar';
                        const heightPercent = (entry.total_queries / maxQueries) * 100;
                        bar.style.height = `${heightPercent}%`;
                        const label = document.createElement('span');
                        label.className = 'bar-label';
                        const date = new Date(entry.date);
                        label.textContent = date.toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
                        wrapper.appendChild(bar);
                        wrapper.appendChild(label);
                        chartDiv.appendChild(wrapper);
                    });
                }

                document.getElementById('last-updated').textContent =
                    `Last updated: ${new Date().toLocaleTimeString()}`;
            } catch (err) {
                console.error('Failed to refresh data:', err);
            }
        }

        // Auto-refresh every 30 seconds
        setInterval(refreshData, 30000);
        refreshData();
    </script>
</body>
</html>
'''


@app.route('/')
def dashboard() -> str:
    """Main dashboard page."""
    return render_template_string(DASHBOARD_TEMPLATE)


# ── Entry point ──────────────────────────────────────────────────

def run_dashboard(port: int = 5000, debug: bool = False) -> None:
    """Run the Flask web dashboard."""
    print(f"{Colors.BOLD}Starting Pi-hole Twins Dashboard on port {port}{Colors.RESET}")
    app.run(host='0.0.0.0', port=port, debug=debug)


def create_web_parser() -> 'argparse.ArgumentParser':  # type: ignore
    """Create argument parser for web dashboard subcommand."""
    import argparse
    parser = argparse.ArgumentParser(prog='pihole-twins web',
                                     description='Start the web dashboard.')
    parser.add_argument('--port', '-p', type=int, default=5000,
                        help='Port to run the web dashboard on')
    parser.add_argument('--debug', '-d', action='store_true',
                        help='Enable debug mode')
    return parser


if __name__ == '__main__':
    parser = create_web_parser()
    args = parser.parse_args()
    run_dashboard(args.port, args.debug)
