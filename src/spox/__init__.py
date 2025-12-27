"""Spox package entrypoint."""

from importlib.metadata import version

__all__ = ["__version__"]

try:
    __version__ = version("spox")
except Exception:
    # Fallback for editable installs before metadata is available
    __version__ = "0.1.0"
