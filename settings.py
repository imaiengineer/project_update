"""Where the app keeps its settings, Google token, browser profile and logs."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import keyring

APP_NAME = "AttendanceSync"
KEYRING_SERVICE = "AttendanceSync-CULMS"
DEFAULT_BASE = "https://culms.chitkara.edu.in"

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
APP_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = APP_DIR / "config.json"
TOKEN_FILE = APP_DIR / "google_token.json"
PROFILE_DIR = APP_DIR / "browser-profile"
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


def resource_path(name: str) -> str:
    """client_secret.json next to the .exe wins; otherwise the copy bundled inside it."""
    exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    beside = exe_dir / name
    if beside.exists():
        return str(beside)
    bundled = Path(getattr(sys, "_MEIPASS", exe_dir)) / name
    return str(bundled)


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"base_url": DEFAULT_BASE, "schedule_time": "17:00"}


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def save_password(username: str, password: str):
    keyring.set_password(KEYRING_SERVICE, username, password)


def get_password(username: str):
    if not username:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, username)
    except Exception:
        return None


def delete_password(username: str):
    try:
        keyring.delete_password(KEYRING_SERVICE, username)
    except Exception:
        pass
