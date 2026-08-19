"""Deprecated compatibility imports for MNE-NIRS operations.

New code must import preprocessing and analysis operations from their
stage-specific modules.
"""

from fnirs_flow.adapters.mne_nirs_analysis import *  # noqa: F401,F403
from fnirs_flow.adapters.mne_nirs_analysis import __all__ as _analysis_all
from fnirs_flow.adapters.mne_nirs_preprocessing import *  # noqa: F401,F403
from fnirs_flow.adapters.mne_nirs_preprocessing import __all__ as _preprocessing_all

__all__ = [*_preprocessing_all, *_analysis_all]
