"""Cedalion data contract: defines data formats and conversions between fnirs-flow and Cedalion."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CedalionDataContract:
    """Data contract for Cedalion backend.

    Defines how data is converted between fnirs-flow's internal representation
    and Cedalion's data format.
    """

    # Cedalion uses xarray DataArrays with specific dimension names
    DIMENSIONS = {
        "time": "time",
        "channel": "channel",
        "wavelength": "wavelength",
        "chromophore": "chromophore",
    }

    # Coordinate systems
    COORDINATE_SYSTEMS = {
        "head": "head",
        "mni": "mni",
        "native": "native",
    }

    # Supported data types
    DATA_TYPES = {
        "intensity": "RawIntensity",
        "optical_density": "OpticalDensity",
        "concentration": "HaemoglobinData",
    }

    @classmethod
    def validate_snirf_input(cls, snirf_data: dict[str, Any]) -> list[str]:
        """Validate SNIRF data for Cedalion compatibility.

        Returns list of validation errors (empty if valid).
        """
        errors = []

        # Check required fields
        required_fields = ["data", "metaDataTags", "measurementList"]
        for field in required_fields:
            if field not in snirf_data:
                errors.append(f"Missing required SNIRF field: {field}")

        # Check data dimensions
        if "data" in snirf_data:
            data = snirf_data["data"]
            if not isinstance(data, dict):
                errors.append("SNIRF data must be a dictionary")
            elif "dataTimeSeries" not in data:
                errors.append("Missing dataTimeSeries in SNIRF data")

        return errors

    @classmethod
    def create_recording_from_snirf(cls, snirf_data: dict[str, Any]) -> Any:
        """Create a Cedalion Recording from SNIRF data.

        This is a placeholder - actual implementation requires Cedalion.
        """
        try:
            import cedalion
            import cedalion.io

            # Convert SNIRF data to Cedalion Recording
            # This is a simplified version - actual implementation depends on Cedalion API
            return cedalion.io.read_snirf(snirf_data)
        except ImportError:
            raise ImportError("Cedalion is required for SNIRF conversion") from None

    @classmethod
    def recording_to_snirf(cls, recording: Any) -> dict[str, Any]:
        """Convert a Cedalion Recording to SNIRF format.

        This is a placeholder - actual implementation requires Cedalion.
        """
        try:
            import cedalion
            import cedalion.io

            # Convert Cedalion Recording to SNIRF
            result: dict[str, Any] = cedalion.io.to_snirf(recording)
            return result
        except ImportError:
            raise ImportError("Cedalion is required for SNIRF conversion") from None

    @classmethod
    def get_wavelengths(cls, recording: Any) -> list[float]:
        """Extract wavelengths from a Cedalion Recording."""
        try:
            # Cedalion stores wavelengths in the data array coordinates
            if hasattr(recording, "dims") and "wavelength" in recording.dims:
                return sorted(recording.wavelength.values.tolist())
            return []
        except (AttributeError, TypeError) as e:
            logger.debug("Could not extract wavelengths: %s", e)
            return []

    @classmethod
    def get_chromophores(cls, recording: Any) -> list[str]:
        """Extract chromophores from a Cedalion Recording."""
        try:
            if hasattr(recording, "dims") and "chromophore" in recording.dims:
                return sorted(recording.chromophore.values.tolist())
            return []
        except (AttributeError, TypeError) as e:
            logger.debug("Could not extract chromophores: %s", e)
            return []

    @classmethod
    def get_channel_labels(cls, recording: Any) -> list[str]:
        """Extract channel labels from a Cedalion Recording."""
        try:
            if hasattr(recording, "dims") and "channel" in recording.dims:
                result: list[str] = recording.channel.values.tolist()
                return result
            return []
        except (AttributeError, TypeError) as e:
            logger.debug("Could not extract channel labels: %s", e)
            return []

    @classmethod
    def get_sampling_frequency(cls, recording: Any) -> float:
        """Extract sampling frequency from a Cedalion Recording."""
        try:
            if hasattr(recording, "time"):
                # Calculate from time dimension
                times = recording.time.values
                if len(times) > 1:
                    result: float = 1.0 / (times[1] - times[0])
                    return result
            return 0.0
        except (AttributeError, TypeError, ZeroDivisionError) as e:
            logger.debug("Could not extract sampling frequency: %s", e)
            return 0.0
