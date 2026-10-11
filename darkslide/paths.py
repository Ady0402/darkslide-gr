"""Where Darkslide keeps its program files and the user's data.

The per-user data folder follows each platform's own convention: Windows roaming
AppData, macOS Application Support, and the XDG base-directory spec elsewhere.
`DARKSLIDE_DATA` overrides all of them (used by tests and portable setups).
"""
import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = APP_ROOT / "web"
TEMPLATE_ROOT = APP_ROOT / "templates"
APP_FOLDER = "Darkslide"


def _platform_base(env, home):
    """Folder that holds per-application data on this platform."""
    if os.name == "nt":
        appdata = env.get("APPDATA")
        return Path(appdata) if appdata else home
    if sys.platform == "darwin":
        return home.joinpath("Library", "Application Support")
    xdg = env.get("XDG_DATA_HOME")
    return Path(xdg) if xdg else home.joinpath(".local", "share")


def data_root():
    explicit = os.environ.get("DARKSLIDE_DATA")
    if explicit:
        return Path(explicit)
    return _platform_base(os.environ, Path.home()) / APP_FOLDER
