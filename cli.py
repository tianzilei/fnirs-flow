"""Compatibility wrapper for the packaged fnirs-flow CLI."""

from __future__ import annotations

from fnirs_flow.cli import *  # noqa: F403
from fnirs_flow.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
