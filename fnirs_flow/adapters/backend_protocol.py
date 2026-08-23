"""Protocol for execution backends in fnirs-flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class BackendProtocol(Protocol):
    """Protocol that all execution backends must implement."""

    @property
    def versions(self) -> dict[str, str]:
        """Return backend software versions."""
        ...

    @property
    def capabilities(self) -> dict[str, Any]:
        """Return backend capabilities and supported operations."""
        ...

    @property
    def artifacts(self) -> Any:
        """Return artifact store."""
        ...

    @property
    def provenance(self) -> Any:
        """Return provenance record."""
        ...

    def read_run(self, filepath: str | Path) -> Any:
        """Read a SNIRF run file."""
        ...

    def to_optical_density(self, raw: Any) -> Any:
        """Convert intensity to optical density."""
        ...

    def compute_qc(self, raw: Any, **kwargs: Any) -> dict[str, Any]:
        """Compute QC metrics."""
        ...

    def apply_motion_correction(self, raw: Any, method: str = "tddr", **kwargs: Any) -> Any:
        """Apply motion correction."""
        ...

    def apply_filter(self, raw: Any, l_freq: float = 0.01, h_freq: float = 0.2, **kwargs: Any) -> Any:
        """Apply filter to raw data."""
        ...

    def to_haemoglobin(self, raw: Any, ppf: float = 6.0) -> Any:
        """Convert OD to haemoglobin concentration."""
        ...

    def block_averaging(self, raw: Any, events: Any, **kwargs: Any) -> dict[str, Any]:
        """Compute block/trial averages."""
        ...

    def build_design_matrix(self, raw: Any, events: Any, event_id: dict[str, int], **kwargs: Any) -> dict[str, Any]:
        """Build a GLM design matrix from events."""
        ...

    def fit_first_level_glm(self, raw: Any, design_matrix: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Fit first-level GLM."""
        ...

    def estimate_contrast(self, glm_result: dict[str, Any], contrasts: list[dict[str, Any]]) -> dict[str, Any]:
        """Estimate linear contrasts."""
        ...

    def channel_output(self, contrast_result: dict[str, Any]) -> dict[str, Any]:
        """Export channel-level results."""
        ...

    def roi_output(self, channel_results: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Export ROI-level results."""
        ...
