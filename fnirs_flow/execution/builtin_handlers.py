"""Built-in run-scope operation handlers.

Scientific adapter calls live here so the orchestrator schedules operations
without owning an operation-specific ``if/elif`` dispatch table.
"""

from __future__ import annotations

from typing import Any

from fnirs_flow.execution.operation_contracts import (
    OperationContext,
    OperationHandler,
    OperationSpec,
    canonical_operation,
)


def _public_params(params: dict[str, Any], *, exclude: set[str] | None = None) -> dict[str, Any]:
    excluded = set(exclude or set())
    return {key: value for key, value in params.items() if not key.startswith("_") and key not in excluded}


class BuiltinOperationHandler(OperationHandler):
    """Execute one registered built-in operation against its selected adapter."""

    def __init__(self, spec: OperationSpec) -> None:
        self.spec = spec

    def execute(self, context: OperationContext) -> Any:
        operation = canonical_operation(self.spec.operation_id)
        handler = getattr(self, f"_execute_{operation}", None)
        if handler is None:
            raise ValueError(f"Operation has no built-in handler: {self.spec.operation_id}")
        return handler(context)

    @staticmethod
    def _execute_read_run(context: OperationContext) -> Any:
        filepath = context.parameters.get("filepath") or context.parameters.get("path") or context.raw
        if filepath is None:
            raise ValueError("read_run requires 'filepath' or 'path'")
        return context.adapter.read_run(filepath)

    @staticmethod
    def _execute_optical_density(context: OperationContext) -> Any:
        kwargs: dict[str, Any] = {}
        if "cedalion" in getattr(context.adapter, "versions", {}):
            kwargs["nonpositive_policy"] = context.parameters.get("nonpositive_policy", "nan")
        return context.adapter.to_optical_density(context.raw, **kwargs)

    def _execute_compute_qc(self, context: OperationContext) -> Any:
        params = context.parameters
        declared = str(params.get("_declared_operation") or self.spec.operation_id)

        def call(source: Any) -> Any:
            if declared == "sci_check":
                return context.adapter.compute_sci_qc(
                    source,
                    l_freq=params.get("l_freq", 0.7),
                    h_freq=params.get("h_freq", 1.5),
                    threshold=params.get("threshold", 0.8),
                )
            if declared == "cv_check":
                return context.adapter.compute_cv_qc(
                    source,
                    cv_threshold=params.get("cv_threshold", 0.15),
                )
            if declared == "snr_check":
                return context.adapter.compute_snr_qc(
                    source,
                    snr_threshold=params.get("snr_threshold", 2.0),
                    method=params.get("method", "spectral_power_ratio"),
                )
            if declared == "bad_channel_detection":
                return context.adapter.compute_advanced_qc(
                    source,
                    sci_threshold=params.get("sci_threshold", params.get("threshold", 0.8)),
                    cv_threshold=params.get("cv_threshold", params.get("threshold", 0.15)),
                    snr_threshold=params.get("snr_threshold", params.get("threshold", 2.0)),
                )
            return context.adapter.compute_qc(
                source,
                sci_threshold=params.get("sci_threshold", params.get("threshold", 0.8)),
                sd_distance_min=params.get("sd_distance_min", 0.01),
                sd_distance_max=params.get("sd_distance_max", 0.08),
                min_sci_pass_rate=params.get("min_sci_pass_rate"),
                preset=params.get("preset"),
            )

        try:
            return call(context.raw)
        except RuntimeError as exc:
            if "must operate on optical density data" not in str(exc):
                raise
            return call(context.adapter.to_optical_density(context.raw))

    def _execute_motion_correction(self, context: OperationContext) -> Any:
        params = context.parameters
        declared = str(params.get("_declared_operation") or self.spec.operation_id)
        aliases = {"tddr", "wavelet", "spline", "ica", "pca", "cbsi"}
        method = declared if declared in aliases else params.get("method", "tddr")
        return context.adapter.apply_motion_correction(
            context.raw,
            method=method,
            **_public_params(params, exclude={"method"}),
        )

    def _execute_filtering(self, context: OperationContext) -> Any:
        params = context.parameters
        declared = str(params.get("_declared_operation") or self.spec.operation_id)
        aliases = {"bandpass", "notch", "lowpass"}
        filter_type = declared if declared in aliases else params.get("filter_type", "bandpass")
        implementation = params.get("implementation", params.get("method", "fir"))
        return context.adapter.apply_filter(
            context.raw,
            l_freq=params.get("l_freq", 0.01),
            h_freq=params.get("h_freq", 0.2),
            filter_type=filter_type,
            implementation=implementation,
            **_public_params(
                params,
                exclude={"l_freq", "h_freq", "filter_type", "implementation", "method"},
            ),
        )

    @staticmethod
    def _execute_short_channel_regression(context: OperationContext) -> Any:
        """Use the backend's native short-channel regression implementation.

        The literature library exposes several descriptive parameter names;
        only the adapter contract is forwarded so unsupported evidence fields
        cannot accidentally alter (or break) native execution.
        """
        params = context.parameters
        threshold = params.get(
            "short_channel_threshold",
            params.get("short_channel_distance_mm", 10.0),
        )
        # MNE uses metres for the distance threshold, while literature rows
        # conventionally report millimetres.
        try:
            threshold = float(threshold)
            if threshold > 1.0:
                threshold /= 1000.0
        except (TypeError, ValueError):
            threshold = 0.01
        method = str(params.get("method", params.get("regression_type", "linear")))
        return context.adapter.apply_short_channel_regression(
            context.raw,
            short_channel_threshold=threshold,
            method=method,
        )

    @staticmethod
    def _execute_beer_lambert_law(context: OperationContext) -> Any:
        # Lightweight test/dry-run adapters may intentionally expose no
        # backend methods. Preserve the declarative numeric fallback there;
        # real MNE/Cedalion adapters always take the native path below.
        if not hasattr(context.adapter, "to_haemoglobin"):
            import numpy as np

            data = np.asarray(context.raw, dtype=float)
            if data.ndim != 2:
                raise ValueError("mbll_conversion requires wavelength/channel by observation data")
            ppf = float(context.parameters.get("ppf", context.parameters.get("pathlength_cm", 6.0)))
            coeff = np.asarray(context.parameters.get("extinction_coefficients", [1.486, 2.526]), dtype=float)
            if coeff.size != data.shape[0]:
                coeff = np.resize(coeff, data.shape[0])
            return data / np.maximum(coeff[:, None] * ppf, np.finfo(float).eps)
        kwargs: dict[str, Any] = {"ppf": context.parameters.get("ppf", 6.0)}
        if "cedalion" in getattr(context.adapter, "versions", {}):
            kwargs["spectrum"] = context.parameters.get("spectrum", "prahl")
        return context.adapter.to_haemoglobin(context.raw, **kwargs)

    @staticmethod
    def _execute_block_averaging(context: OperationContext) -> Any:
        return context.adapter.block_averaging(
            context.raw,
            baseline_window=context.parameters.get("baseline_window", [-5, 0]),
            response_window=context.parameters.get("response_window", [0, 20]),
            baseline_correction=context.parameters.get("baseline_correction", "mean"),
            events=context.parameters.get("events"),
        )

    @staticmethod
    def _execute_build_design_matrix(context: OperationContext) -> Any:
        events = context.parameters.get("events")
        if events is None:
            raise ValueError(
                "build_design_matrix requires 'events' in params. Provide MNE events array or events TSV path."
            )
        return context.adapter.build_design_matrix(
            context.raw,
            events=events,
            event_id=context.parameters.get("event_id", {}),
            hrf_model=context.service._normalize_hrf_model(context.parameters.get("hrf_model", "glover")),
            drift_order=context.parameters.get("drift_order", 1),
            high_pass=context.parameters.get("high_pass", 0.01),
        )

    @staticmethod
    def _execute_first_level_glm(context: OperationContext) -> Any:
        design_matrix = context.parameters.get("design_matrix")
        if design_matrix is None:
            raise ValueError("first_level_glm requires 'design_matrix' in params. Run build_design_matrix first.")
        kwargs = {
            "hrf_model": context.service._normalize_hrf_model(context.parameters.get("hrf_model", "glover")),
            "noise_model": context.parameters.get("noise_model", "ar1"),
        }
        if "nonfinite_policy" in context.parameters:
            kwargs["nonfinite_policy"] = context.parameters["nonfinite_policy"]
        return context.adapter.fit_first_level_glm(context.raw, design_matrix, **kwargs)

    @staticmethod
    def _execute_estimate_contrast(context: OperationContext) -> Any:
        glm_result = context.parameters.get("glm_result")
        if glm_result is None:
            raise ValueError("estimate_contrast requires 'glm_result' in params. Run first_level_glm first.")
        contrasts = context.service._normalize_contrasts(context.parameters.get("contrasts", []), glm_result)
        return context.adapter.estimate_contrast(glm_result, contrasts)

    @staticmethod
    def _execute_channel_output(context: OperationContext) -> Any:
        contrast_result = context.parameters.get("contrast_result")
        if contrast_result is None:
            raise ValueError("channel_output requires 'contrast_result' in params. Run estimate_contrast first.")
        return context.adapter.channel_output(contrast_result)

    @staticmethod
    def _execute_roi_output(context: OperationContext) -> Any:
        channel_results = context.parameters.get("channel_results")
        if channel_results is None:
            raise ValueError("roi_output requires 'channel_results' in params. Run channel_output first.")
        return context.adapter.roi_output(
            channel_results,
            atlas=context.parameters.get("atlas", "mni"),
            roi_mapping=context.parameters.get("roi_mapping"),
            aggregation=context.parameters.get("aggregation", "mean"),
        )


def builtin_handler_factory(spec: OperationSpec) -> OperationHandler:
    return BuiltinOperationHandler(spec)
