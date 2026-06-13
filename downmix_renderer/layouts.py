from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Speaker(Enum):
    FL = "FL"
    FR = "FR"
    FC = "FC"
    LFE = "LFE"
    BL = "BL"
    BR = "BR"
    SL = "SL"
    SR = "SR"
    BLC = "BLC"
    BRC = "BRC"
    TFL = "TFL"
    TFR = "TFR"
    TSL = "TSL"
    TSR = "TSR"
    TBL = "TBL"
    TBR = "TBR"


@dataclass(frozen=True)
class SpeakerLayout:
    id: str
    label: str
    speakers: tuple[Speaker, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(speaker.value for speaker in self.speakers)

    def index_of(self, speaker: Speaker) -> int:
        try:
            return self.speakers.index(speaker)
        except ValueError:
            return -1

    def has(self, speaker: Speaker) -> bool:
        return speaker in self.speakers


WINDOWS_7_1_LAYOUT = SpeakerLayout(
    id="windows_7_1",
    label="7.1 Monitor",
    speakers=(
        Speaker.FL,
        Speaker.FR,
        Speaker.FC,
        Speaker.LFE,
        Speaker.BL,
        Speaker.BR,
        Speaker.SL,
        Speaker.SR,
    ),
)

SHARUR_9_1_6_LAYOUT = SpeakerLayout(
    id="sharur_9_1_6",
    label="9.1.6 Monitor",
    speakers=(
        Speaker.FL,
        Speaker.FR,
        Speaker.FC,
        Speaker.LFE,
        Speaker.BL,
        Speaker.BR,
        Speaker.BLC,
        Speaker.BRC,
        Speaker.SL,
        Speaker.SR,
        Speaker.TFL,
        Speaker.TFR,
        Speaker.TSL,
        Speaker.TSR,
        Speaker.TBL,
        Speaker.TBR,
    ),
)

LAYOUTS = {
    WINDOWS_7_1_LAYOUT.id: WINDOWS_7_1_LAYOUT,
    SHARUR_9_1_6_LAYOUT.id: SHARUR_9_1_6_LAYOUT,
}

WINDOWS_TO_SHARUR_COPY = tuple(
    (WINDOWS_7_1_LAYOUT.index_of(speaker), SHARUR_9_1_6_LAYOUT.index_of(speaker))
    for speaker in WINDOWS_7_1_LAYOUT.speakers
)

GENERATED_SHARUR_SPEAKERS = (
    Speaker.BLC,
    Speaker.BRC,
    Speaker.TFL,
    Speaker.TFR,
    Speaker.TSL,
    Speaker.TSR,
    Speaker.TBL,
    Speaker.TBR,
)


def layout_from_id(layout_id: str) -> SpeakerLayout:
    return LAYOUTS.get(layout_id, WINDOWS_7_1_LAYOUT)


def index_of(layout: SpeakerLayout | str, speaker: Speaker) -> int:
    if isinstance(layout, str):
        layout = layout_from_id(layout)
    return layout.index_of(speaker)
