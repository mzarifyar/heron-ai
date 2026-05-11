"""Absolute project-root paths — safe regardless of where the server is started."""

from pathlib import Path

# <repo>/app/core/paths.py  →  parents[2] == repo root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR   = PROJECT_ROOT / "data"


def config(filename: str) -> str:
    """Return absolute path to a file inside config/."""
    return str(CONFIG_DIR / filename)


def data(filename: str) -> str:
    """Return absolute path to a file inside data/."""
    DATA_DIR.mkdir(exist_ok=True)
    return str(DATA_DIR / filename)
