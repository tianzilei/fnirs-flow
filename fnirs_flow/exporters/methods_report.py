"""fNIRS methods reporting: generate manuscript-ready methods sections."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def generate_methods_section(
    plan: dict[str, Any],
    qc_summary: dict[str, Any] | None = None,
    preprocessing_params: dict[str, Any] | None = None,
    analysis_params: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
) -> str:
    """Generate a methods section for fNIRS manuscript.

    Args:
        plan: Compiled plan dict
        qc_summary: QC metrics summary
        preprocessing_params: Preprocessing parameters
        analysis_params: Analysis parameters
        evidence_refs: List of evidence references

    Returns:
        Methods section text in markdown
    """
    lines = [
        "## Methods",
        "",
        "### Data Acquisition",
        "",
        _format_acquisition(plan),
        "",
        "### Quality Control",
        "",
        _format_qc(qc_summary),
        "",
        "### Preprocessing",
        "",
        _format_preprocessing(preprocessing_params),
        "",
        "### Statistical Analysis",
        "",
        _format_analysis(analysis_params),
        "",
        "### Reproducibility",
        "",
        _format_reproducibility(plan),
    ]

    # Add evidence references if provided
    if evidence_refs:
        lines.extend([
            "",
            "### Evidence References",
            "",
            "The following evidence sources informed the analysis methodology:",
            "",
        ])
        for ref in evidence_refs:
            lines.append(f"- {ref}")

    return "\n".join(lines)


def _format_acquisition(plan: dict[str, Any]) -> str:
    """Format acquisition parameters."""
    acq = plan.get("acquisition", {})
    if not acq:
        return (
            "fNIRS data were acquired using a continuous-wave system. "
            "Detailed acquisition parameters are provided in the supplementary materials."
        )

    lines = []
    if acq.get("device"):
        lines.append(f"Data were acquired using a {acq['device']} system.")
    if acq.get("wavelengths"):
        lines.append(f"Wavelengths: {', '.join(str(w) for w in acq['wavelengths'])} nm.")
    if acq.get("sampling_rate"):
        lines.append(f"Sampling rate: {acq['sampling_rate']} Hz.")
    if acq.get("source_detector_distance"):
        lines.append(f"Source-detector distance: {acq['source_detector_distance']} mm.")

    return " ".join(lines) if lines else "Acquisition parameters are detailed in the supplementary materials."


def _format_qc(qc_summary: dict[str, Any] | None) -> str:
    """Format QC reporting."""
    if not qc_summary:
        return "Quality control procedures are described in the supplementary materials."

    lines = []
    if qc_summary.get("sci_threshold"):
        lines.append(f"Scalp Coupling Index (SCI) threshold: {qc_summary['sci_threshold']}")
    if qc_summary.get("n_channels_excluded"):
        lines.append(f"Channels excluded: {qc_summary['n_channels_excluded']}")
    if qc_summary.get("n_subjects_excluded"):
        lines.append(f"Subjects excluded due to data quality: {qc_summary['n_subjects_excluded']}")

    return ". ".join(lines) + "." if lines else "QC metrics are reported in the supplementary materials."


def _format_preprocessing(params: dict[str, Any] | None) -> str:
    """Format preprocessing methods."""
    if not params:
        return "Preprocessing followed standard fNIRS analysis procedures."

    lines = []
    if params.get("motion_correction"):
        lines.append(f"Motion artifacts were corrected using {params['motion_correction']}.")
    if params.get("filter"):
        filt = params["filter"]
        if isinstance(filt, dict):
            lines.append(f"Data were bandpass filtered ({filt.get('l_freq', 0.01)}-{filt.get('h_freq', 0.2)} Hz).")
    if params.get("mbll"):
        lines.append("Optical density was converted to haemoglobin concentration using the modified Beer-Lambert law.")
    if params.get("short_channel_regression"):
        lines.append("Short-channel regression was applied to remove systemic physiological noise.")

    return " ".join(lines) if lines else "Preprocessing details are provided in the supplementary materials."


def _format_analysis(params: dict[str, Any] | None) -> str:
    """Format analysis methods."""
    if not params:
        return "Statistical analysis followed standard fNIRS GLM procedures."

    lines = []
    if params.get("hrf_model"):
        hrf = params["hrf_model"]
        lines.append(f"First-level analysis used a {hrf} hemodynamic response function.")
    if params.get("contrasts"):
        contrasts = params["contrasts"]
        if isinstance(contrasts, list):
            lines.append(f"Contrasts: {', '.join(str(c) for c in contrasts)}.")
    if params.get("roi_definition"):
        lines.append("Region-of-interest analysis was performed based on atlas-based parcellation.")

    return " ".join(lines) if lines else "Analysis details are provided in the supplementary materials."


def _format_reproducibility(plan: dict[str, Any]) -> str:
    """Format reproducibility statement."""
    lines = [
        "All analyses were performed using the fnirs-flow framework. "
        "A complete reproducibility package including configuration, "
        "software versions, and processing logs is available as supplementary material.",
    ]

    return " ".join(lines)


def write_methods_report(
    plan: dict[str, Any],
    outdir: Path,
    qc_summary: dict[str, Any] | None = None,
    preprocessing_params: dict[str, Any] | None = None,
    analysis_params: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
) -> Path:
    """Write methods report to file.

    Args:
        plan: Compiled plan dict
        outdir: Output directory
        qc_summary: QC metrics summary
        preprocessing_params: Preprocessing parameters
        analysis_params: Analysis parameters
        evidence_refs: List of evidence references

    Returns:
        Path to the written file
    """
    content = generate_methods_section(
        plan=plan,
        qc_summary=qc_summary,
        preprocessing_params=preprocessing_params,
        analysis_params=analysis_params,
        evidence_refs=evidence_refs,
    )

    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "methods_section.md"
    path.write_text(content, encoding="utf-8")
    return path
