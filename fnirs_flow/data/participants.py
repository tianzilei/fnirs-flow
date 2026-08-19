"""Deprecated compatibility imports for participant and group APIs.

New code must import table APIs from :mod:`fnirs_flow.data.participant_tables`
and statistical APIs from :mod:`fnirs_flow.data.group_analysis`.
"""

from fnirs_flow.data.group_analysis import *  # noqa: F401,F403
from fnirs_flow.data.group_analysis import __all__ as _group_all
from fnirs_flow.data.participant_tables import *  # noqa: F401,F403
from fnirs_flow.data.participant_tables import __all__ as _table_all

__all__ = [*_table_all, *_group_all]
