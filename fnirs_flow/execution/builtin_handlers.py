"""Built-in run-scope operation handlers.

Scientific adapter calls live here so the orchestrator schedules operations
without owning an operation-specific ``if/elif`` dispatch table.
"""

from __future__ import annotations

from typing import Any

from fnirs_flow.execution.operations import OperationContext, OperationHandler, OperationSpec, canonical_operation


def _public_params(params: dict[str, Any], *, exclude: set[str] | None = None) -> dict[str, Any]:
    excluded = {"method", *(exclude or set())}
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
    def _execute_optical_density(context: OperationContext) -> Any:
        kwargs: dict[str, Any] = {}
        if "cedalion" in getattr(context.adapter, "versions", {}):
            kwargs["nonpositive_policy"] = context.parameters.get("nonpositive_policy", "nan")
        return context.adapter.to_optical_density(context.raw, **kwargs)

    def _execute_compute_qc(self, context: OperationContext) -> Any:
        params = context.parameters
        declared = str(params.get("_declared_operation") or self.spec.operation_id)
        advanced = declared in {"cv_check", "snr_check", "bad_channel_detection"} and hasattr(
            context.adapter, "compute_advanced_qc"
        )

        def call(source: Any) -> Any:
            if advanced:
                return context.adapter.compute_advanced_qc(
                    source,
                    sci_threshold=params.get("sci_threshold", params.get("threshold", 0.8)),
                    cv_threshold=params.get("cv_threshold", params.get("threshold", 0.15)),
                    snr_threshold=params.get("snr_threshold", params.get("threshold", 2.0)),
                )
            try:
                return context.adapter.compute_qc(
                    source,
                    sci_threshold=params.get("sci_threshold", params.get("threshold", 0.8)),
                )
            except TypeError:
                return context.adapter.compute_qc(source)

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
        method = params.get("method") or (declared if declared in aliases else "tddr")
        return context.adapter.apply_motion_correction(
            context.raw,
            method=method,
            **_public_params(params),
        )

    def _execute_filtering(self, context: OperationContext) -> Any:
        params = context.parameters
        declared = str(params.get("_declared_operation") or self.spec.operation_id)
        aliases = {"bandpass", "notch", "lowpass"}
        method = params.get("method") or (declared if declared in aliases else "bandpass")
        return context.adapter.apply_filter(
            context.raw,
            l_freq=params.get("l_freq", 0.01),
            h_freq=params.get("h_freq", 0.2),
            method=method,
            **_public_params(params, exclude={"l_freq", "h_freq"}),
        )

    @staticmethod
    def _execute_beer_lambert_law(context: OperationContext) -> Any:
        kwargs: dict[str, Any] = {"ppf": context.parameters.get("ppf", 6.0)}
        if "cedalion" in getattr(context.adapter, "versions", {}):
            kwargs["spectrum"] = context.parameters.get("spectrum", "prahl")
        return context.adapter.to_haemoglobin(context.raw, **kwargs)

    @staticmethod
    def _execute_combat_harmonization(context: OperationContext) -> Any:
        return context.raw

    @staticmethod
    def _execute_block_averaging(context: OperationContext) -> Any:
        return context.adapter.block_averaging(
            context.raw,
            baseline_window=context.parameters.get("baseline_window", [-5, 0]),
            response_window=context.parameters.get("response_window", [0, 20]),
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
        )


def builtin_handler_factory(spec: OperationSpec) -> OperationHandler:
    return BuiltinOperationHandler(spec)
