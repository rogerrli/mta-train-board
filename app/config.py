"""Load user settings (watched stations, directions, refresh interval) from TOML.

Reads ``config.local.toml`` if it exists (a gitignored local override), otherwise
falls back to the committed ``config.example.toml``. Parsing uses the stdlib
``tomllib`` (Python 3.11+).
"""

import tomllib
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_CONFIG = _REPO_ROOT / "config.local.toml"
EXAMPLE_CONFIG = _REPO_ROOT / "config.example.toml"


def config_path() -> Path:
    """Return the config to load: the local override if present, else the example."""
    return LOCAL_CONFIG if LOCAL_CONFIG.exists() else EXAMPLE_CONFIG


def load_config() -> dict[str, Any]:
    """Parse and return the active config as a dict."""
    with config_path().open("rb") as f:
        return tomllib.load(f)
