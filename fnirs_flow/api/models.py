"""Deprecated API DTO imports; canonical contracts live in application."""

from fnirs_flow.application.models import *  # noqa: F403

# Keep this deprecated facade limited to DTO/model classes.  A bare star
# re-export otherwise leaks ``Any``, ``Field`` and other implementation names
# into the public API namespace.
__all__ = [
    name
    for name, value in globals().items()
    if isinstance(value, type) and getattr(value, "__module__", "") == "fnirs_flow.application.models"
]
