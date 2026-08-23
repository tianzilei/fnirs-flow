"""fnirs-flow v1: fNIRS analysis Flow orchestration framework."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("fnirs-flow")
except PackageNotFoundError:  # Source checkout without an editable install.
    __version__ = "1.2.5"

# Initialize logging on import
from fnirs_flow.logging_config import init_logging

init_logging()
