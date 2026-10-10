import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = APP_ROOT / "web"
TEMPLATE_ROOT = APP_ROOT / "templates"


def data_root():
    override = os.environ.get("DARKSLIDE_DATA")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home()) / "Darkslide"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Darkslide"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "Darkslide"
