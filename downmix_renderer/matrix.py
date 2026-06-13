from __future__ import annotations

import numpy as np

# Exact Sharur matrix supplied on 2026-05-03 and re-locked on 2026-05-21.
# Do not edit these coefficients without explicit user approval.
SHARUR_916_STEREO_MATRIX_LITERAL = (
    (1.0, 0.0),
    (0.0, 1.0),
    (0.70710678, 0.70710678),
    (2.26464431, 2.26464431),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 0.0),
    (0.0, 1.0),
)

WINDOWS_71_STEREO_MATRIX_LITERAL = (
    (1.0, 0.0),
    (0.0, 1.0),
    (0.70710678, 0.70710678),
    (2.26464431, 2.26464431),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 0.0),
    (0.0, 1.0),
)

SHARUR_916_STEREO_MATRIX = np.array(SHARUR_916_STEREO_MATRIX_LITERAL, dtype=np.float64)
WINDOWS_71_STEREO_MATRIX = np.array(WINDOWS_71_STEREO_MATRIX_LITERAL, dtype=np.float64)

# Backwards-compatible names for older imports.
MATRIX_LITERAL = SHARUR_916_STEREO_MATRIX_LITERAL
MATRIX = SHARUR_916_STEREO_MATRIX
