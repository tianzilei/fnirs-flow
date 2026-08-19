"""Backward-compatible result-output imports.

New code should use :mod:`fnirs_flow.execution.result_outputs`.
"""

from fnirs_flow.execution.result_outputs import (
    ChannelResult,
    GroupSummary,
    ROIResult,
    compute_group_statistics,
    export_channel_results,
    export_group_summary,
    export_roi_results,
)

__all__ = [
    "ChannelResult",
    "GroupSummary",
    "ROIResult",
    "compute_group_statistics",
    "export_channel_results",
    "export_group_summary",
    "export_roi_results",
]
