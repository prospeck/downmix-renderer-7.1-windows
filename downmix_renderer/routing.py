from __future__ import annotations

import numpy as np

from .layouts import SHARUR_9_1_6_LAYOUT, WINDOWS_7_1_LAYOUT, Speaker


def fold_sharur_9_1_6_to_windows_7_1(sharur_bus: np.ndarray) -> np.ndarray:
    if sharur_bus.ndim != 2 or sharur_bus.shape[1] < len(SHARUR_9_1_6_LAYOUT.speakers):
        raise ValueError("sharur_bus must be frames x 16")

    out = np.zeros((sharur_bus.shape[0], len(WINDOWS_7_1_LAYOUT.speakers)), dtype=sharur_bus.dtype)
    for speaker in (
        Speaker.FL,
        Speaker.FR,
        Speaker.FC,
        Speaker.LFE,
        Speaker.BL,
        Speaker.BR,
        Speaker.SL,
        Speaker.SR,
    ):
        out[:, WINDOWS_7_1_LAYOUT.index_of(speaker)] = sharur_bus[:, SHARUR_9_1_6_LAYOUT.index_of(speaker)]

    out[:, WINDOWS_7_1_LAYOUT.index_of(Speaker.BL)] += 0.5 * sharur_bus[:, SHARUR_9_1_6_LAYOUT.index_of(Speaker.BLC)]
    out[:, WINDOWS_7_1_LAYOUT.index_of(Speaker.BR)] += 0.5 * sharur_bus[:, SHARUR_9_1_6_LAYOUT.index_of(Speaker.BRC)]
    out[:, WINDOWS_7_1_LAYOUT.index_of(Speaker.FL)] += 0.25 * sharur_bus[:, SHARUR_9_1_6_LAYOUT.index_of(Speaker.TFL)]
    out[:, WINDOWS_7_1_LAYOUT.index_of(Speaker.FR)] += 0.25 * sharur_bus[:, SHARUR_9_1_6_LAYOUT.index_of(Speaker.TFR)]
    out[:, WINDOWS_7_1_LAYOUT.index_of(Speaker.SL)] += 0.25 * sharur_bus[:, SHARUR_9_1_6_LAYOUT.index_of(Speaker.TSL)]
    out[:, WINDOWS_7_1_LAYOUT.index_of(Speaker.SR)] += 0.25 * sharur_bus[:, SHARUR_9_1_6_LAYOUT.index_of(Speaker.TSR)]
    out[:, WINDOWS_7_1_LAYOUT.index_of(Speaker.BL)] += 0.25 * sharur_bus[:, SHARUR_9_1_6_LAYOUT.index_of(Speaker.TBL)]
    out[:, WINDOWS_7_1_LAYOUT.index_of(Speaker.BR)] += 0.25 * sharur_bus[:, SHARUR_9_1_6_LAYOUT.index_of(Speaker.TBR)]
    return out
