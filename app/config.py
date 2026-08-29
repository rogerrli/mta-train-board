"""Load user settings (watched stations, directions, refresh interval) from TOML.

Reads ``config.local.toml`` if it exists (a gitignored local override), otherwise
falls back to the committed ``config.example.toml``. Parsing uses the stdlib
``tomllib`` (Python 3.11+).
"""

import logging
import tomllib
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_CONFIG = _REPO_ROOT / "config.local.toml"
EXAMPLE_CONFIG = _REPO_ROOT / "config.example.toml"


def config_path() -> Path:
    """Return the config to load: the local override if present, else the example.

    Raises FileNotFoundError (with a clear message) if neither file exists.
    """
    if LOCAL_CONFIG.exists():
        return LOCAL_CONFIG
    if EXAMPLE_CONFIG.exists():
        logger.warning(
            "No %s found; falling back to %s (placeholder stations). "
            "Copy the example to config.local.toml and edit it for your setup.",
            LOCAL_CONFIG.name,
            EXAMPLE_CONFIG.name,
        )
        return EXAMPLE_CONFIG
    raise FileNotFoundError(
        f"No config file found. Expected {LOCAL_CONFIG.name} "
        f"or {EXAMPLE_CONFIG.name} in {_REPO_ROOT}."
    )


def load_config() -> dict[str, Any]:
    """Parse and return the active config as a dict."""
    with config_path().open("rb") as f:
        return tomllib.load(f)
