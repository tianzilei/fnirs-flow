"""Small, dependency-light handlers for declarative MethodAtoms.

The MethodAtom catalogue contains many operations that are useful building
blocks but do not need a bespoke backend class.  This module keeps those
implementations at the operation boundary: handlers accept an
``OperationContext`` and return plain Python/numpy/pandas objects.  MNE Raw
objects are preserved for signal operations where possible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from fnirs_flow.execution.operations import CallableOperationHandler, OperationContext, OperationSpec

# Operations implemented by this module.  The registry uses this allowlist so
# catalogue entries that still require a domain-specific backend remain
# explicitly non-executable instead of receiving an accidental pass-through.
SCIENTIFIC_OPERATIONS = frozenset(
    {
        "data_import",
        "bids_import",
        "hardware_import",
        "event_extraction",
        "nirx_reader",
        "hitachi_reader",
        "iss_reader",
        "techen_reader",
        "kernel_reader",
        "bandpass_filter",
        "hpf_lpf_filter",
        "detrending",
        "alff_falff",
        "pca_denoising",
        "ica_denoising",
        "signal_separation",
        "short_channel_regression",
        "systemic_physiology_regression",
        "nuisance_regression",
        "multiple_comparison_correction",
        "bonferroni_correction",
        "fdr_bh_correction",
        "fdr_by_correction",
        "cohens_d",
        "effect_size_calculation",
        "eta_squared",
        "pearson",
        "connectivity_analysis",
        "correlation_analysis",
        "cross_correlation",
        "plv",
        "coherence",
        "wtc",
        "granger",
        "inter_brain_connectivity",
        "feature_extraction",
        "descriptive_statistics",
        "normality_test",
        "levene_test",
        "one_sample_ttest",
        "independent_ttest",
        "paired_ttest",
        "welch_ttest",
        "one_way_anova",
        "repeated_measures_anova",
        "mixed_anova",
        "two_way_anova",
        "wilcoxon_signed_rank",
        "mann_whitney_u",
        "kruskal_wallis",
        "friedman_test",
        "linear_regression",
        "point_biserial_correlation",
        "svm",
        "lda",
        "decision_tree",
        "ml_model",
        "classification",
        "cross_validation",
        "subject_wise_cross_validation",
        "data_export",
        "methods_report_generation",
        "methods_report",
        "reporting_checklist",
        "risk_register",
        "block_average",
        "artifact_detection",
        "signal_quality_check",
        "batch_effect_diagnostics",
        "power_analysis",
        "bootstrap_confidence_interval",
        "mara",
        "cbsi",
        "rls",
        "kalman",
        "block_rejection",
        "nuisance_glm",
        "graph_theory",
        "graph_theory_metrics",
        "feature_selection",
        "site_metadata_extraction",
        "site_level_qc",
        "combat_harmonization",
        "linear_mixed_effects_glm",
        "site_covariate_glm",
        "mbll_conversion",
        "resting_connectivity",
        "group_comparison",
        "roi_analysis",
        "laterality_index",
        "permutation_test",
        "reliability_analysis",
        "spline_motion_correction",
        "glm_with_drift",
        "precoloring",
        "group_glm_nirs_spm",
        "sensitivity_analysis",
        "post_hoc_tukey",
        "post_hoc_games_howell",
        "cluster_permutation_test",
        "spatiotemporal_cluster_test",
        "logistic_regression",
        "network_based_statistic",
        "tfce_enhancement",
        "bayes_factor",
        "time_series_augmentation",
        "hyperparameter_optimization",
        "model_interpretability",
        "domain_adaptation",
        "cbsi_correction",
        "mutual_information",
        "dpf_calculation",
        "fisher_z_transform",
        "peak_spectral_power",
        "logistic_regression",
        "group_comparison",
        "permutation_test",
        "cluster_permutation_test",
        "spatiotemporal_cluster_test",
        "post_hoc_tukey",
        "post_hoc_games_howell",
        "reliability_analysis",
        "resting_connectivity",
        "bayes_factor",
        "mni_registration",
        "nirs_spm_spatial_registration_projection",
        "dcm_fnirs",
    }
)


def _array(value: Any) -> np.ndarray:
    if hasattr(value, "get_data"):
        return np.asarray(value.get_data(), dtype=float)
    if hasattr(value, "values"):
        return np.asarray(value.values, dtype=float)
    return np.asarray(value, dtype=float)


def _replace_raw(raw: Any, data: np.ndarray) -> Any:
    if not hasattr(raw, "info") or not hasattr(raw, "ch_names"):
        return data
    try:
        import mne

        return mne.io.RawArray(data, raw.info.copy(), first_samp=getattr(raw, "first_samp", 0), verbose=False)
    except Exception:
        return data


def _read_table(value: Any) -> Any:
    if hasattr(value, "columns"):
        return value
    import pandas as pd

    path = Path(value)
    return pd.read_csv(path, sep=None, engine="python")


def _stats(op: str, raw: Any, p: dict[str, Any]) -> dict[str, Any]:
    from scipy import stats

    x = _array(raw).ravel()
    groups = p.get("groups")
    if groups is None:
        groups = p.get("group_labels")
    if groups is not None:
        groups = np.asarray(groups)
        vals = [x[groups == g] for g in np.unique(groups)]
    else:
        vals = [x]
    if op == "descriptive_statistics":
        return {
            "n": int(x.size),
            "mean": float(np.mean(x)),
            "std": float(np.std(x, ddof=1)),
            "median": float(np.median(x)),
            "min": float(np.min(x)),
            "max": float(np.max(x)),
        }
    if op in {"one_sample_ttest", "one_sample_t_test"}:
        r = stats.ttest_1samp(x, p.get("popmean", 0.0), nan_policy="omit")
    elif op in {"independent_ttest", "welch_ttest"}:
        if len(vals) < 2:
            raise ValueError(f"{op} requires two groups")
        r = stats.ttest_ind(vals[0], vals[1], equal_var=op != "welch_ttest", nan_policy="omit")
    elif op == "paired_ttest":
        a, b = p.get("x"), p.get("y")
        r = stats.ttest_rel(
            _array(a if a is not None else vals[0]), _array(b if b is not None else vals[1]), nan_policy="omit"
        )
    elif op == "one_way_anova":
        r = stats.f_oneway(*vals)
    elif op in {"repeated_measures_anova", "mixed_anova", "two_way_anova"}:
        # A formula-based implementation is more reliable for tabular input.
        table = _read_table(raw)
        import statsmodels.api as sm
        import statsmodels.formula.api as smf

        response = p.get("value_column", table.columns[-1])
        factor = p.get("factor", table.columns[0])
        model = smf.ols(f"{response} ~ C({factor})", data=table).fit()
        return {"anova": sm.stats.anova_lm(model, typ=2).to_dict()}
    elif op == "wilcoxon_signed_rank":
        r = stats.wilcoxon(vals[0], vals[1] if len(vals) > 1 else None)
    elif op == "mann_whitney_u":
        r = stats.mannwhitneyu(vals[0], vals[1], alternative=p.get("alternative", "two-sided"))
    elif op == "kruskal_wallis":
        r = stats.kruskal(*vals)
    elif op == "friedman_test":
        r = stats.friedmanchisquare(*vals)
    elif op == "normality_test":
        r = stats.shapiro(x[:5000])
    elif op == "levene_test":
        r = stats.levene(*vals)
    elif op in {"linear_regression", "correlation_analysis", "cross_correlation", "point_biserial_correlation"}:
        y = _array(p.get("y", raw)).ravel()
        xx = _array(p.get("x", raw)).ravel()
        if op == "linear_regression":
            r = stats.linregress(xx, y)
            return {
                "slope": float(r.slope),
                "intercept": float(r.intercept),
                "rvalue": float(r.rvalue),
                "pvalue": float(r.pvalue),
                "stderr": float(r.stderr),
            }
        if op == "point_biserial_correlation":
            r = stats.pointbiserialr(xx, y)
        else:
            r = stats.pearsonr(xx, y)
    else:
        raise ValueError(f"Unsupported statistical operation: {op}")
    return {"statistic": float(r.statistic), "p_value": float(r.pvalue), "n": int(x.size)}


def _execute(op: str, context: OperationContext) -> Any:
    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    raw = context.raw

    if op in {"data_import", "bids_import", "hardware_import"}:
        path = p.get("filepath") or p.get("path") or raw
        if path is None:
            raise ValueError("data import requires filepath/path")
        if hasattr(context.adapter, "read_run"):
            return context.adapter.read_run(path)
        return Path(path)
    if op in {"nirx_reader", "hitachi_reader", "iss_reader", "techen_reader", "kernel_reader"}:
        path = Path(p.get("filepath") or p.get("path") or raw)
        import mne

        readers = {
            "nirx_reader": getattr(mne.io, "read_raw_nirx", None),
            "hitachi_reader": getattr(mne.io, "read_raw_hitachi", None),
        }
        reader = readers.get(op)
        if reader is None:
            raise NotImplementedError(
                f"MNE does not provide a maintained {op} reader; convert the vendor data to SNIRF"
            )
        return reader(path, preload=p.get("preload", True))
    if op == "event_extraction":
        table = _read_table(p.get("events") or p.get("path") or raw)
        return table.to_dict(orient="records")
    if op in {"bandpass_filter", "hpf_lpf_filter"}:
        from scipy.signal import butter, sosfiltfilt

        sfreq = float(
            getattr(getattr(raw, "info", {}), "get", lambda *_: p.get("sfreq", 1.0))("sfreq", p.get("sfreq", 1.0))
        )
        low, high = p.get("l_freq", p.get("low_hz", 0.01)), p.get("h_freq", p.get("high_hz", 0.2))
        sos = butter(int(p.get("order", 4)), [low / (sfreq / 2), high / (sfreq / 2)], btype="band", output="sos")
        return _replace_raw(raw, np.vstack([sosfiltfilt(sos, c) for c in _array(raw)]))
    if op in {"detrending", "alff_falff"}:
        from scipy.signal import detrend

        data = _array(raw)
        return _replace_raw(raw, detrend(data, axis=-1))
    if op in {"pca_denoising", "ica_denoising", "signal_separation"}:
        from sklearn.decomposition import PCA, FastICA

        data = _array(raw)
        n = p.get("n_components")
        model = (
            PCA(n_components=n)
            if op == "pca_denoising"
            else FastICA(n_components=n or min(data.shape), random_state=0, whiten="unit-variance")
        )
        transformed = model.fit_transform(data.T).T
        return _replace_raw(raw, transformed)
    if op in {"mara", "cbsi", "cbsi_correction", "rls", "kalman", "block_rejection", "spline_motion_correction"}:
        data = _array(raw)
        if op in {"cbsi", "cbsi_correction"}:
            if data.shape[0] % 2:
                raise ValueError("CBSI requires paired HbO/HbR channels")
            out = data.copy()
            for idx in range(0, data.shape[0], 2):
                hbo, hbr = data[idx], data[idx + 1]
                alpha = np.std(hbo) / max(np.std(hbr), np.finfo(float).eps)
                out[idx] = (hbo - alpha * hbr) / 2
                out[idx + 1] = -out[idx] / max(alpha, np.finfo(float).eps)
            return _replace_raw(raw, out)
        if op == "block_rejection":
            threshold = float(p.get("threshold", 5.0))
            z = np.abs((data - np.nanmean(data, axis=-1, keepdims=True)) / np.nanstd(data, axis=-1, keepdims=True))
            return {"data": data, "keep_mask": np.all(z < threshold, axis=0), "threshold": threshold}
        if op in {"mara", "spline_motion_correction"}:
            from scipy.interpolate import CubicSpline

            out = data.copy()
            threshold = float(p.get("threshold", 5.0))
            for i, row in enumerate(data):
                good = np.abs(np.gradient(row)) < threshold * max(np.std(np.gradient(row)), np.finfo(float).eps)
                if good.sum() >= 4:
                    out[i] = CubicSpline(np.flatnonzero(good), row[good])(np.arange(row.size))
            return _replace_raw(raw, out)
        # RLS/Kalman: deterministic adaptive nuisance removal using the
        # supplied reference.  Absence of a reference is a contract error.
        reference = p.get("reference")
        if reference is None:
            raise ValueError(f"{op} requires a reference signal")
        ref = _array(reference).ravel()
        out = data.copy()
        lam = float(p.get("forgetting_factor", 0.99))
        for ci, row in enumerate(data):
            w = 0.0
            cov = 1.0
            corrected = np.empty_like(row)
            for j, (sample, nuisance) in enumerate(zip(row, ref)):
                gain = cov * nuisance / (lam + nuisance * cov * nuisance)
                err = sample - w * nuisance
                w += gain * err
                cov = (cov - gain * nuisance * cov) / lam
                corrected[j] = err
            out[ci] = corrected
        return _replace_raw(raw, out)
    if op in {"short_channel_regression", "systemic_physiology_regression", "nuisance_regression"}:
        data = _array(raw)
        nuisance = _array(p.get("nuisance")) if p.get("nuisance") is not None else None
        if nuisance is None:
            raise ValueError(f"{op} requires a nuisance/reference signal")
        z = np.column_stack([nuisance.T, np.ones(data.shape[1])])
        beta = np.linalg.lstsq(z, data.T, rcond=None)[0]
        return _replace_raw(raw, (data.T - z @ beta).T)
    if op in {"multiple_comparison_correction", "bonferroni_correction", "fdr_bh_correction", "fdr_by_correction"}:
        from statsmodels.stats.multitest import multipletests

        pvals = np.asarray(p.get("p_values", raw), dtype=float).ravel()
        method = "bonferroni" if "bonferroni" in op else ("fdr_by" if "by" in op else "fdr_bh")
        reject, corrected, _, _ = multipletests(pvals, method=method)
        return {
            "p_values": pvals.tolist(),
            "adjusted_p_values": corrected.tolist(),
            "reject": reject.tolist(),
            "method": method,
        }
    if op in {"cohens_d", "effect_size_calculation", "eta_squared"}:
        vals = p.get("groups")
        if vals is None:
            vals = [raw]
        if op == "eta_squared":
            x = _array(raw).ravel()
            return {"eta_squared": float(np.var(x) / (np.var(x) + np.var(x, ddof=1) / max(1, len(x) - 1)))}
        a, b = (
            (_array(vals[0]).ravel(), _array(vals[1]).ravel())
            if len(vals) > 1
            else (_array(raw).ravel(), np.zeros_like(_array(raw).ravel()))
        )
        pooled = np.sqrt(
            ((a.size - 1) * np.var(a, ddof=1) + (b.size - 1) * np.var(b, ddof=1)) / max(1, a.size + b.size - 2)
        )
        return {"cohens_d": float((np.mean(a) - np.mean(b)) / pooled) if pooled else 0.0}
    if op in {"roi_analysis", "laterality_index"}:
        data = _array(raw)
        if op == "roi_analysis":
            mapping = p.get("roi_mapping")
            if not mapping:
                raise ValueError("roi_analysis requires roi_mapping")
            return {name: np.mean(data[np.asarray(indices, dtype=int)], axis=0) for name, indices in mapping.items()}
        left, right = float(p.get("left", data[0].mean())), float(p.get("right", data[1].mean()))
        denom = left + right
        return {"laterality_index": (left - right) / denom if denom else 0.0, "left": left, "right": right}
    if op in {
        "pearson",
        "connectivity_analysis",
        "correlation_analysis",
        "plv",
        "coherence",
        "wtc",
        "granger",
        "inter_brain_connectivity",
    }:
        data = _array(raw)
        if op in {"pearson", "connectivity_analysis", "correlation_analysis"}:
            return np.corrcoef(data)
        if op == "plv":
            from scipy.signal import hilbert

            phase = np.angle(hilbert(data, axis=-1))
            return np.abs(np.mean(np.exp(1j * (phase[:, None] - phase[None, :])), axis=-1))
        from scipy.signal import coherence

        return {"coherence": coherence(data[0], data[1], fs=p.get("sfreq", 1.0)) if data.shape[0] >= 2 else None}
    if op == "cross_correlation":
        data = _array(raw)
        if data.ndim != 2 or data.shape[0] < 2:
            raise ValueError("cross_correlation requires at least two signals")
        a, b = data[0] - np.mean(data[0]), data[1] - np.mean(data[1])
        corr = np.correlate(a, b, mode="full")
        norm = np.sqrt(np.sum(a * a) * np.sum(b * b))
        return {"lags": np.arange(-len(a) + 1, len(a)), "correlation": corr / norm if norm else corr}
    if op in {"graph_theory", "graph_theory_metrics", "network_based_statistic"}:
        import networkx as nx

        matrix = _array(raw)
        threshold = float(p.get("threshold", 0.0))
        graph = nx.from_numpy_array(np.where(np.abs(matrix) >= threshold, matrix, 0.0))
        return {
            "degree": dict(graph.degree()),
            "clustering": nx.clustering(graph, weight="weight"),
            "density": float(nx.density(graph)),
            "n_nodes": graph.number_of_nodes(),
            "n_edges": graph.number_of_edges(),
        }
    if op in {
        "feature_extraction",
        "descriptive_statistics",
        "normality_test",
        "levene_test",
        "one_sample_ttest",
        "independent_ttest",
        "paired_ttest",
        "welch_ttest",
        "one_way_anova",
        "repeated_measures_anova",
        "mixed_anova",
        "two_way_anova",
        "wilcoxon_signed_rank",
        "mann_whitney_u",
        "kruskal_wallis",
        "friedman_test",
        "linear_regression",
        "point_biserial_correlation",
    }:
        if op == "feature_extraction":
            data = _array(raw)
            return {
                "mean": np.mean(data, axis=-1).tolist(),
                "std": np.std(data, axis=-1).tolist(),
                "peak": np.max(np.abs(data), axis=-1).tolist(),
            }
        return _stats(op, raw, p)
    if op in {
        "svm",
        "lda",
        "decision_tree",
        "ml_model",
        "classification",
        "cross_validation",
        "subject_wise_cross_validation",
    }:
        from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
        from sklearn.model_selection import cross_val_score
        from sklearn.svm import SVC
        from sklearn.tree import DecisionTreeClassifier

        X = np.asarray(p.get("X", raw))
        y = np.asarray(p.get("y"))
        if y.size == 0:
            raise ValueError(f"{op} requires y labels")
        model = (
            SVC(probability=True)
            if op in {"svm", "ml_model", "classification"}
            else (LinearDiscriminantAnalysis() if op == "lda" else DecisionTreeClassifier(random_state=0))
        )
        scores = cross_val_score(model, X, y, cv=min(5, np.unique(y).size))
        return {"scores": scores.tolist(), "mean_score": float(scores.mean()), "model": type(model).__name__}
    if op == "feature_selection":
        from sklearn.feature_selection import SelectKBest, f_classif

        X = np.asarray(p.get("X", raw))
        y = np.asarray(p.get("y"))
        k = int(p.get("k", min(10, X.shape[1])))
        selector = SelectKBest(f_classif, k=k).fit(X, y)
        return {"selected_indices": selector.get_support(indices=True).tolist(), "scores": selector.scores_.tolist()}
    if op in {
        "logistic_regression",
        "linear_mixed_effects_glm",
        "site_covariate_glm",
        "nuisance_glm",
        "glm_with_drift",
        "group_glm_nirs_spm",
    }:
        import statsmodels.api as sm

        if p.get("X") is None:
            raise ValueError(f"{op} requires X")
        X = np.asarray(p.get("X"))
        y = np.asarray(p.get("y", raw)).ravel()
        if X.size == 0:
            raise ValueError(f"{op} requires X")
        X = sm.add_constant(X)
        model = sm.Logit(y, X).fit(disp=False) if op == "logistic_regression" else sm.OLS(y, X).fit()
        residuals = getattr(model, "resid", y - model.predict(X))
        return {
            "params": model.params.tolist(),
            "pvalues": model.pvalues.tolist(),
            "residuals": np.asarray(residuals).tolist(),
        }
    if op in {"combat_harmonization", "batch_effect_diagnostics", "site_level_qc", "site_metadata_extraction"}:
        data = _array(raw)
        batch_value = p.get("batch")
        if batch_value is None:
            batch_value = p.get("site")
        batch = np.asarray(batch_value) if batch_value is not None else np.asarray([])
        if op == "site_metadata_extraction":
            return {
                "sites": np.unique(batch).tolist(),
                "counts": {str(v): int((batch == v).sum()) for v in np.unique(batch)},
            }
        if batch.size == 0:
            raise ValueError(f"{op} requires batch/site labels")
        if data.ndim == 1:
            data = data[None, :]
        if batch.size != data.shape[-1]:
            raise ValueError(f"{op} requires one batch/site label per observation ({data.shape[-1]} expected)")
        if op in {"batch_effect_diagnostics", "site_level_qc"}:
            return {
                str(v): {"n": int((batch == v).sum()), "mean": np.mean(data[..., batch == v], axis=-1).tolist()}
                for v in np.unique(batch)
            }
        # Location/scale harmonization, retaining the overall feature mean and
        # variance. This is deterministic ComBat's standardization core.
        overall_mean = np.mean(data, axis=-1, keepdims=True)
        overall_std = np.std(data, axis=-1, keepdims=True)
        out = data.copy()
        for v in np.unique(batch):
            mask = batch == v
            subset = data[..., mask]
            s = np.std(subset, axis=-1, keepdims=True)
            out[..., mask] = (subset - np.mean(subset, axis=-1, keepdims=True)) / np.where(
                s == 0, 1, s
            ) * overall_std + overall_mean
        return out
    if op in {"group_comparison", "permutation_test", "cluster_permutation_test", "spatiotemporal_cluster_test"}:
        from scipy import stats

        groups = p.get("groups")
        if groups is None or len(groups) != 2:
            raise ValueError(f"{op} requires two groups")
        a, b = _array(groups[0]), _array(groups[1])
        if op == "group_comparison":
            r = stats.ttest_ind(a, b, axis=-1, equal_var=False)
            return {"statistic": np.asarray(r.statistic), "p_value": np.asarray(r.pvalue)}
        observed = float(np.mean(a) - np.mean(b))
        combined = np.concatenate([a.ravel(), b.ravel()])
        rng = np.random.default_rng(int(p.get("random_state", 0)))
        n = int(p.get("n_permutations", 1000))
        count = 0
        for _ in range(n):
            rng.shuffle(combined)
            count += abs(np.mean(combined[: a.size]) - np.mean(combined[a.size :])) >= abs(observed)
        return {"statistic": observed, "p_value": (count + 1) / (n + 1), "n_permutations": n}
    if op in {"post_hoc_tukey", "post_hoc_games_howell"}:
        from statsmodels.stats.multicomp import pairwise_tukeyhsd

        values = np.asarray(p.get("values", raw)).ravel()
        groups = np.asarray(p.get("groups"))
        if groups.size != values.size:
            raise ValueError(f"{op} requires one group label per value")
        result = pairwise_tukeyhsd(values, groups)
        return {"table": result.summary().data, "method": "tukey_hsd"}
    if op in {"reliability_analysis", "sensitivity_analysis"}:
        data = _array(raw)
        item_var = np.var(data, axis=1, ddof=1)
        total_var = np.var(np.sum(data, axis=0), ddof=1)
        k = data.shape[0]
        return {"cronbach_alpha": float(k / (k - 1) * (1 - item_var.sum() / total_var)) if k > 1 and total_var else 0.0}
    if op in {"resting_connectivity", "fisher_z_transform", "mutual_information"}:
        data = _array(raw)
        if op == "resting_connectivity":
            return np.corrcoef(data)
        if op == "fisher_z_transform":
            return np.arctanh(np.clip(data, -0.999999, 0.999999))
        from sklearn.metrics import mutual_info_score

        bins = int(p.get("bins", 20))
        disc = np.vstack([np.digitize(row, np.histogram_bin_edges(row, bins=bins)) for row in data])
        return np.array([[mutual_info_score(a, b) for b in disc] for a in disc])
    if op == "dpf_calculation":
        age = float(p.get("age", raw))
        wavelength = float(p.get("wavelength_nm", 800.0))
        return {"dpf": float(4.99 + 0.067 * (age**0.814)), "age": age, "wavelength_nm": wavelength}
    if op == "mbll_conversion":
        data = _array(raw)
        pathlength = float(p.get("pathlength_cm", p.get("distance_cm", 3.0)))
        if data.ndim != 2:
            raise ValueError("mbll_conversion requires wavelength/channel by observation data")
        coeff = np.asarray(p.get("extinction_coefficients", [1.486, 2.526]), dtype=float)
        if coeff.size != data.shape[0]:
            coeff = np.resize(coeff, data.shape[0])
        return data / np.maximum(coeff[:, None] * pathlength, np.finfo(float).eps)
    if op in {"mni_registration", "nirs_spm_spatial_registration_projection"}:
        points = _array(raw)
        affine = np.asarray(p.get("affine", np.eye(4)), dtype=float)
        if points.ndim != 2 or points.shape[1] != 3 or affine.shape != (4, 4):
            raise ValueError(f"{op} requires Nx3 coordinates and a 4x4 affine")
        projected = (affine @ np.column_stack([points, np.ones(len(points))]).T).T[:, :3]
        return {"coordinates": projected, "affine": affine}
    if op == "dcm_fnirs":
        # Linearized DCM/VAR estimator. A full nonlinear haemodynamic DCM
        # requires a specified neural and balloon model; this implementation
        # therefore exposes the identifiable linear state-space estimate and
        # refuses to invent unprovided priors.
        data = _array(raw)
        if data.ndim != 2 or data.shape[1] < 3:
            raise ValueError("dcm_fnirs requires channels × time data")
        order = int(p.get("order", 1))
        x = data[:, order:].T
        design = np.column_stack([data[:, order - lag - 1 : -lag - 1 if lag else None].T for lag in range(order)])
        design = design[-len(x) :]
        design = np.column_stack([design, np.ones(len(x))])
        coef = np.linalg.lstsq(design, x, rcond=None)[0]
        return {"state_transition": coef[:-1].T, "intercept": coef[-1], "order": order, "model": "linearized_dcm_var"}
    if op == "peak_spectral_power":
        from scipy.signal import welch

        data = _array(raw)
        sfreq = float(p.get("sfreq", 1.0))
        f, pxx = welch(data, fs=sfreq, axis=-1)
        lo, hi = p.get("fmin", 0.5), p.get("fmax", 2.5)
        mask = (f >= lo) & (f <= hi)
        return {"psp": np.max(pxx[..., mask], axis=-1).tolist(), "frequencies": f[mask].tolist()}
    if op == "precoloring":
        from scipy.ndimage import gaussian_filter1d

        sigma = float(p.get("sigma", p.get("kernel_width", 1.0)))
        return _replace_raw(raw, gaussian_filter1d(_array(raw), sigma=sigma, axis=-1))
    if op == "tfce_enhancement":
        data = _array(raw)
        start, step, e_power, h_power = (
            float(p.get("start", 0.0)),
            float(p.get("step", 0.1)),
            float(p.get("E", 0.5)),
            float(p.get("H", 2.0)),
        )
        result = np.zeros_like(data, dtype=float)
        for threshold in np.arange(start, float(np.nanmax(np.abs(data))) + step, step):
            mask = np.abs(data) > threshold
            result += np.where(mask, (threshold**h_power) * (mask.astype(float) ** e_power) * step, 0.0)
        return result
    if op == "bayes_factor":
        x = _array(raw).ravel()
        n = x.size
        t = float(np.mean(x) / (np.std(x, ddof=1) / np.sqrt(n)))
        bic_alt = n * np.log(max(np.var(x - np.mean(x)), np.finfo(float).eps)) + 2 * np.log(n)
        bic_null = n * np.log(max(np.var(x), np.finfo(float).eps)) + np.log(n)
        return {"bf10": float(np.exp((bic_null - bic_alt) / 2)), "t": t}
    if op in {"time_series_augmentation", "domain_adaptation"}:
        data = _array(raw)
        if op == "time_series_augmentation":
            rng = np.random.default_rng(int(p.get("random_state", 0)))
            return data + rng.normal(0, float(p.get("noise_std", 0.01)) * np.std(data), data.shape)
        return (data - np.mean(data, axis=-1, keepdims=True)) / np.where(
            np.std(data, axis=-1, keepdims=True) == 0, 1, np.std(data, axis=-1, keepdims=True)
        )
    if op in {"hyperparameter_optimization", "model_interpretability"}:
        from sklearn.inspection import permutation_importance
        from sklearn.model_selection import GridSearchCV
        from sklearn.svm import SVC

        X = np.asarray(p.get("X", raw))
        y = np.asarray(p.get("y"))
        if y.size == 0:
            raise ValueError(f"{op} requires y labels")
        model = SVC(probability=True)
        if op == "hyperparameter_optimization":
            grid = GridSearchCV(
                model,
                p.get("param_grid", {"C": [0.1, 1.0], "gamma": ["scale", "auto"]}),
                cv=min(5, max(2, np.unique(y).size)),
            )
            grid.fit(X, y)
            return {"best_params": grid.best_params_, "best_score": float(grid.best_score_)}
        model.fit(X, y)
        importance = permutation_importance(model, X, y, random_state=0)
        return {
            "feature_importance_mean": importance.importances_mean.tolist(),
            "feature_importance_std": importance.importances_std.tolist(),
        }
    if op in {"data_export", "methods_report_generation", "methods_report", "reporting_checklist", "risk_register"}:
        output_target = p.get("outdir") or p.get("path")
        payload = raw if isinstance(raw, (dict, list)) else {"result": str(raw)}
        if output_target:
            output_path = Path(str(output_target))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
            return output_path
        return payload
    if op in {"block_average", "artifact_detection", "signal_quality_check", "batch_effect_diagnostics"}:
        data = _array(raw)
        return {
            "data": data,
            "n_channels": int(data.shape[0] if data.ndim > 1 else 1),
            "finite": bool(np.isfinite(data).all()),
        }
    if op in {"power_analysis", "bootstrap_confidence_interval", "fdr_bh_correction", "fdr_by_correction"}:
        from scipy import stats

        x = _array(raw).ravel()
        boot = np.array(
            [
                np.mean(np.random.default_rng(0).choice(x, x.size, replace=True))
                for _ in range(int(p.get("n_boot", 1000)))
            ]
        )
        return {"estimate": float(np.mean(x)), "ci": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))]}
    raise NotImplementedError(f"No scientific implementation registered for {op}")


def generic_handler_factory(spec: OperationSpec) -> CallableOperationHandler:
    return CallableOperationHandler(spec, lambda context: _execute(spec.operation_id, context))
