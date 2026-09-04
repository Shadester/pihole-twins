"""Configuration management for pihole-twins.

Supports:
  - ~/.config/piholetwins/config.json (or %APPDATA%/piholetwins/config.json on Windows)
  - ~/.env or .env file in project root (dotenv format)
  - Command-line overrides take highest priority
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# Default server colors (ANSI)
DEFAULT_COLORS = [
    '\033[96m',  # CYAN
    '\033[95m',  # MAGENTA
    '\033[92m',  # GREEN
    '\033[93m',  # YELLOW
    '\033[94m',  # BLUE
    '\033[1;33m',  # BOLD YELLOW
]


def _config_dir() -> Path:
    """Return the platform-appropriate config directory."""
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
    return Path.home() / '.config'


def config_file() -> Path:
    """Return path to the user config file."""
    return _config_dir() / 'piholetwins' / 'config.json'


def env_file() -> Path:
    """Return path to the .env file (project root)."""
    return Path(__file__).resolve().parent / '.env'


def load_config() -> Dict[str, Any]:
    """Load configuration from config file and .env, merging them."""
    cfg: Dict[str, Any] = {}

    # Load config.json if it exists
    path = config_file()
    if path.exists():
        try:
            with open(path) as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Could not read {path}: {e}", file=sys.stderr)

    # Load .env overrides (simple KEY=VALUE, no parsing library needed)
    env_path = env_file()
    if env_path.exists():
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, _, value = line.partition('=')
                        cfg[key.strip()] = value.strip().strip('"').strip("'")
        except OSError as e:
            print(f"Warning: Could not read {env_path}: {e}", file=sys.stderr)

    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    """Save configuration to the user config file."""
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(cfg, f, indent=2)


def get_server_config(server_name: str) -> Dict[str, Any]:
    """Get configuration for a specific server by name.

    Returns dict with keys: hostname, username, color_index, key_file, port
    """
    cfg = load_config()
    servers = cfg.get('servers', {})

    if server_name in servers:
        return dict(servers[server_name])  # shallow copy

    # Fallback to defaults
    return {
        'hostname': server_name,
        'username': 'pi',
        'color_index': 0,
        'key_file': None,
        'port': 22,
    }


def get_all_servers() -> List[Dict[str, Any]]:
    """Get all configured servers from config."""
    cfg = load_config()
    servers = cfg.get('servers', {})

    result = []
    for name, srv in servers.items():
        entry = dict(srv)
        entry.setdefault('username', 'pi')
        entry.setdefault('color_index', len(result) % len(DEFAULT_COLORS))
        entry.setdefault('key_file', None)
        entry.setdefault('port', 22)
        result.append(entry)

    return result


def init_config_file(servers: List[Dict[str, str]]) -> None:
    """Create a starter config file with the given servers."""
    cfg = load_config()
    server_dict = {}
    for i, srv in enumerate(servers):
        name = srv.get('name', f'pihole{i+1}')
        server_dict[name] = {
            'hostname': srv.get('hostname', name),
            'username': srv.get('username', 'pi'),
            'color_index': i % len(DEFAULT_COLORS),
            'key_file': None,
            'port': 22,
        }
    cfg['servers'] = server_dict
    save_config(cfg)
