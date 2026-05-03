from __future__ import annotations

import numpy as np

# Exact Sharur matrix supplied on 2026-05-03.
# Do not edit these coefficients without explicit user approval.
MATRIX_LITERAL = (
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

MATRIX = np.array(MATRIX_LITERAL, dtype=np.float64)
