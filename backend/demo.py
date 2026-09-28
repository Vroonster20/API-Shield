"""Loopback-only synthetic example origin; never use as an existing production API."""

import os
from pathlib import Path

from shield_api.demo import create_demo

base = Path(
    os.environ.get("SHIELD_DEMO_DATA_DIR")
    or Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "state"))) / "shield-api-demo"
)
app = create_demo(base / "application.sqlite3")
