"""ROI mapping: define and apply region-of-interest definitions."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ROIDefinition(BaseModel):
    """Defines a region of interest."""

    roi_id: str
    name: str
    description: str = ""
    channels: list[str] = Field(default_factory=list)
    aggregation: str = Field(default="mean", pattern="^(mean|median|max|min)$")
    source: str = Field(default="user", pattern="^(user|bids|template|atlas)$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ROIMapping(BaseModel):
    """Complete ROI mapping for a study."""

    mapping_id: str
    name: str = ""
    rois: list[ROIDefinition] = Field(default_factory=list)
    fallback_to_channel: bool = True
    warnings: list[str] = Field(default_factory=list)


# Standard ROI templates for common fNIRS montages
STANDARD_ROI_TEMPLATES: dict[str, list[ROIDefinition]] = {
    "motor": [
        ROIDefinition(
            roi_id="left_motor",
            name="Left Motor Cortex",
            description="Left primary motor cortex (M1)",
            channels=[],  # To be filled based on montage
            aggregation="mean",
            source="template",
        ),
        ROIDefinition(
            roi_id="right_motor",
            name="Right Motor Cortex",
            description="Right primary motor cortex (M1)",
            channels=[],
            aggregation="mean",
            source="template",
        ),
    ],
    "prefrontal": [
        ROIDefinition(
            roi_id="left_pfc",
            name="Left Prefrontal Cortex",
            description="Left dorsolateral prefrontal cortex (dlPFC)",
            channels=[],
            aggregation="mean",
            source="template",
        ),
        ROIDefinition(
            roi_id="right_pfc",
            name="Right Prefrontal Cortex",
            description="Right dorsolateral prefrontal cortex (dlPFC)",
            channels=[],
            aggregation="mean",
            source="template",
        ),
    ],
    "broca": [
        ROIDefinition(
            roi_id="broca",
            name="Broca's Area",
            description="Broca's area (language production)",
            channels=[],
            aggregation="mean",
            source="template",
        ),
    ],
}


class ROIMappingManager:
    """Manage ROI mappings for fNIRS analysis."""

    def __init__(self) -> None:
        self._mappings: dict[str, ROIMapping] = {}

    def create_mapping(self, mapping_id: str, name: str = "") -> ROIMapping:
        """Create a new empty ROI mapping."""
        mapping = ROIMapping(mapping_id=mapping_id, name=name)
        self._mappings[mapping_id] = mapping
        return mapping

    def get_mapping(self, mapping_id: str) -> ROIMapping | None:
        """Get a mapping by ID."""
        return self._mappings.get(mapping_id)

    def add_roi(self, mapping_id: str, roi: ROIDefinition) -> bool:
        """Add an ROI to a mapping."""
        mapping = self._mappings.get(mapping_id)
        if mapping is None:
            return False
        mapping.rois.append(roi)
        return True

    def create_from_template(self, mapping_id: str, template_name: str) -> ROIMapping | None:
        """Create a mapping from a standard template."""
        template = STANDARD_ROI_TEMPLATES.get(template_name)
        if template is None:
            return None

        mapping = ROIMapping(
            mapping_id=mapping_id,
            name=f"{template_name} template",
            rois=[roi.model_copy() for roi in template],
        )
        self._mappings[mapping_id] = mapping
        return mapping

    def assign_channels(
        self,
        mapping_id: str,
        roi_id: str,
        channels: list[str],
    ) -> bool:
        """Assign channels to an ROI."""
        mapping = self._mappings.get(mapping_id)
        if mapping is None:
            return False

        for roi in mapping.rois:
            if roi.roi_id == roi_id:
                roi.channels = channels
                return True

        return False

    def create_from_user_mapping(
        self,
        mapping_id: str,
        channel_roi_pairs: list[tuple[str, str]],
    ) -> ROIMapping:
        """Create mapping from user-provided channel-ROI pairs.

        Args:
            mapping_id: Mapping ID
            channel_roi_pairs: List of (channel_name, roi_name) tuples

        Returns:
            Created ROIMapping
        """
        # Group channels by ROI
        roi_channels: dict[str, list[str]] = {}
        for ch, roi_name in channel_roi_pairs:
            if roi_name not in roi_channels:
                roi_channels[roi_name] = []
            roi_channels[roi_name].append(ch)

        # Create ROIs
        rois = []
        for roi_name, channels in roi_channels.items():
            rois.append(
                ROIDefinition(
                    roi_id=roi_name.lower().replace(" ", "_"),
                    name=roi_name,
                    channels=channels,
                    aggregation="mean",
                    source="user",
                )
            )

        mapping = ROIMapping(
            mapping_id=mapping_id,
            name="User-defined mapping",
            rois=rois,
        )
        self._mappings[mapping_id] = mapping
        return mapping

    def validate_mapping(self, mapping_id: str, available_channels: list[str]) -> list[str]:
        """Validate that all mapped channels exist.

        Args:
            mapping_id: Mapping ID
            available_channels: List of available channel names

        Returns:
            List of warnings
        """
        mapping = self._mappings.get(mapping_id)
        if mapping is None:
            return ["Mapping not found"]

        warnings = []
        channel_set = set(available_channels)

        for roi in mapping.rois:
            for ch in roi.channels:
                if ch not in channel_set:
                    warnings.append(f"Channel '{ch}' in ROI '{roi.name}' not found in data")

        if not mapping.rois:
            warnings.append("No ROIs defined")

        return warnings


def aggregate_roi_data(
    data: dict[str, list[float]],
    roi: ROIDefinition,
) -> list[float]:
    """Aggregate channel data within an ROI.

    Args:
        data: Dict of channel_name -> data_values
        roi: ROI definition with channels to aggregate

    Returns:
        Aggregated data values
    """
    import numpy as np

    # Collect data for ROI channels
    roi_data = []
    for ch in roi.channels:
        if ch in data:
            roi_data.append(data[ch])

    if not roi_data:
        return []

    roi_array = np.array(roi_data)

    if roi.aggregation == "mean":
        result: list[float] = np.mean(roi_array, axis=0).tolist()
    elif roi.aggregation == "median":
        result = np.median(roi_array, axis=0).tolist()
    elif roi.aggregation == "max":
        result = np.max(roi_array, axis=0).tolist()
    elif roi.aggregation == "min":
        result = np.min(roi_array, axis=0).tolist()
    else:
        result = np.mean(roi_array, axis=0).tolist()
    return result
