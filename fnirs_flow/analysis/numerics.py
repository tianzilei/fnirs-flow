"""Finite linear-algebra helpers with explicit numerical contracts."""

from __future__ import annotations

from typing import cast

import numpy as np


def finite_matmul(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Multiply finite one- or two-dimensional operands without ``matmul``."""
    first = np.asarray(left, dtype=float)
    second = np.asarray(right, dtype=float)
    if not np.isfinite(first).all() or not np.isfinite(second).all():
        raise ValueError("matrix product operands must be finite")
    signatures = {
        (1, 1): "i,i->",
        (1, 2): "i,ij->j",
        (2, 1): "ij,j->i",
        (2, 2): "ij,jk->ik",
    }
    signature = signatures.get((first.ndim, second.ndim))
    if signature is None:
        raise ValueError("matrix product operands must be one- or two-dimensional")
    result = np.asarray(np.einsum(signature, first, second, optimize=False))
    if not np.isfinite(result).all():
        raise ValueError("matrix product result must be finite")
    return cast(np.ndarray, result)


def finite_pinv(matrix: np.ndarray, *, rcond: float | None = None) -> np.ndarray:
    """Return an SVD pseudoinverse while rejecting non-finite inputs/results.

    The reconstruction uses an explicit contraction because unsupported
    NumPy/SciPy combinations can emit false ``matmul`` warnings for finite SVD
    factors. Supported environments produce the same Moore-Penrose inverse.
    """
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("pseudoinverse input must be a finite matrix")
    u, singular_values, vh = np.linalg.svd(values, full_matrices=False)
    if singular_values.size == 0:
        return np.zeros((values.shape[1], values.shape[0]), dtype=float)
    relative_cutoff = rcond if rcond is not None else max(values.shape) * np.finfo(float).eps
    cutoff = float(relative_cutoff) * float(singular_values[0])
    inverse = np.divide(
        1.0,
        singular_values,
        out=np.zeros_like(singular_values),
        where=singular_values > cutoff,
    )
    result = np.einsum("ik,k,kj->ij", vh.T, inverse, u.T, optimize=False)
    if not np.isfinite(result).all():
        raise ValueError("pseudoinverse result must be finite")
    return cast(np.ndarray, result)
