"""Export channel-level, ROI-level, and group summary outputs."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ChannelResult(BaseModel):
    """Result for a single channel."""

    subject: str
    session: str = ""
    run: str = ""
    channel: str
    chromophore: str = ""  # hbo, hbr
    condition: str = ""
    contrast: str = ""
    beta: float = 0.0
    t_stat: float = 0.0
    p_value: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ROIResult(BaseModel):
    """Result for a single ROI."""

    subject: str
    session: str = ""
    run: str = ""
    roi: str
    chromophore: str = ""
    condition: str = ""
    contrast: str = ""
    beta: float = 0.0
    t_stat: float = 0.0
    p_value: float = 1.0
    n_channels: int = 0
    channels: list[str] = Field(default_factory=list)
    aggregation: str = "mean"
    metadata: dict[str, Any] = Field(default_factory=dict)


class GroupSummary(BaseModel):
    """Group-level summary."""

    roi: str
    chromophore: str = ""
    contrast: str = ""
    n_subjects: int = 0
    mean_beta: float = 0.0
    std_beta: float = 0.0
    mean_t_stat: float = 0.0
    p_value: float = 1.0
    confidence_interval: tuple[float, float] = (0.0, 0.0)
    excluded_subjects: list[str] = Field(default_factory=list)


def export_channel_results(
    results: list[ChannelResult],
    outdir: Path,
) -> Path:
    """Export channel-level results to CSV.

    Args:
        results: List of ChannelResult
        outdir: Output directory

    Returns:
        Path to exported CSV
    """
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "channel_results.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "subject",
                "session",
                "run",
                "channel",
                "chromophore",
                "condition",
                "contrast",
                "beta",
                "t_stat",
                "p_value",
            ]
        )

        for r in results:
            writer.writerow(
                [
                    r.subject,
                    r.session,
                    r.run,
                    r.channel,
                    r.chromophore,
                    r.condition,
                    r.contrast,
                    r.beta,
                    r.t_stat,
                    r.p_value,
                ]
            )

    return path


def export_roi_results(
    results: list[ROIResult],
    outdir: Path,
) -> Path:
    """Export ROI-level results to CSV.

    Args:
        results: List of ROIResult
        outdir: Output directory

    Returns:
        Path to exported CSV
    """
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "roi_results.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "subject",
                "session",
                "run",
                "roi",
                "chromophore",
                "condition",
                "contrast",
                "beta",
                "t_stat",
                "p_value",
                "n_channels",
                "aggregation",
            ]
        )

        for r in results:
            writer.writerow(
                [
                    r.subject,
                    r.session,
                    r.run,
                    r.roi,
                    r.chromophore,
                    r.condition,
                    r.contrast,
                    r.beta,
                    r.t_stat,
                    r.p_value,
                    r.n_channels,
                    r.aggregation,
                ]
            )

    return path


def export_group_summary(
    summaries: list[GroupSummary],
    outdir: Path,
) -> Path:
    """Export group-level summary to CSV.

    Args:
        summaries: List of GroupSummary
        outdir: Output directory

    Returns:
        Path to exported CSV
    """
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "group_summary.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "roi",
                "chromophore",
                "contrast",
                "n_subjects",
                "mean_beta",
                "std_beta",
                "mean_t_stat",
                "p_value",
                "ci_lower",
                "ci_upper",
                "excluded_subjects",
            ]
        )

        for s in summaries:
            writer.writerow(
                [
                    s.roi,
                    s.chromophore,
                    s.contrast,
                    s.n_subjects,
                    s.mean_beta,
                    s.std_beta,
                    s.mean_t_stat,
                    s.p_value,
                    s.confidence_interval[0],
                    s.confidence_interval[1],
                    ";".join(s.excluded_subjects),
                ]
            )

    return path


def compute_group_statistics(
    roi_results: list[ROIResult],
    exclude_subjects: list[str] | None = None,
) -> list[GroupSummary]:
    """Compute group-level statistics from ROI results.

    Args:
        roi_results: List of ROIResult
        exclude_subjects: Subjects to exclude

    Returns:
        List of GroupSummary
    """
    import numpy as np
    from scipy import stats

    exclude = set(exclude_subjects or [])

    # Group by ROI + chromophore + contrast
    groups: dict[tuple[str, str, str], list[ROIResult]] = {}
    for r in roi_results:
        if r.subject in exclude:
            continue
        key = (r.roi, r.chromophore, r.contrast)
        if key not in groups:
            groups[key] = []
        groups[key].append(r)

    summaries = []
    for (roi, chromophore, contrast), results in groups.items():
        betas = [r.beta for r in results]
        t_stats = [r.t_stat for r in results]

        if not betas:
            continue

        mean_beta = float(np.mean(betas))
        std_beta = float(np.std(betas, ddof=1)) if len(betas) > 1 else 0.0
        mean_t = float(np.mean(t_stats))

        # Compute p-value (one-sample t-test: H0: mean_beta = 0)
        n = len(betas)
        if n > 1:
            t_stat, p_value = stats.ttest_1samp(betas, 0)
            p_value = float(p_value)

            # 95% CI using t-distribution
            se = std_beta / np.sqrt(n)
            t_crit = stats.t.ppf(0.975, n - 1)
            ci_lower = mean_beta - t_crit * se
            ci_upper = mean_beta + t_crit * se
        else:
            p_value = 1.0
            ci_lower = mean_beta
            ci_upper = mean_beta

        # Find excluded subjects for this group
        all_subjects = {r.subject for r in roi_results if r.roi == roi}
        excluded = list(exclude & all_subjects)

        summaries.append(
            GroupSummary(
                roi=roi,
                chromophore=chromophore,
                contrast=contrast,
                n_subjects=n,
                mean_beta=mean_beta,
                std_beta=std_beta,
                mean_t_stat=mean_t,
                p_value=p_value,
                confidence_interval=(ci_lower, ci_upper),
                excluded_subjects=excluded,
            )
        )

    return summaries
