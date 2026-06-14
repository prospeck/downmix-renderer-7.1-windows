from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from time import monotonic

from PyQt5 import QtCore, QtGui, QtSvg, QtWidgets

from .audio_engine import DEFAULT_STREAM_PROFILE, STREAM_PROFILES, AudioEngine
from .constants import (
    APP_DISPLAY_NAME,
    CHANNEL_LAYOUTS,
    DEFAULT_CHANNEL_CONFIG,
    DEFAULT_PREAMP_DB,
    TRIM_MAX_DB,
    TRIM_MIN_DB,
)
from .devices import (
    AudioDevice,
    WASAPI_HOSTAPI,
    default_wasapi_output,
    find_saved_device,
    list_devices,
    preferred_input,
    preferred_output,
    renderer_input_devices,
    renderer_output_devices,
)
from .dsp import clamp_trim_db, linear_to_db
from .peq import PeqParseReport, build_runtime_config
from .presets import (
    PRESET_SCHEMA_VERSION,
    Preset,
    load_presets,
    match_preset_for_output,
    preset_from_current,
    update_preset_from_current,
)
from .route_probe import run_probe
from .sample_rates import (
    DEFAULT_SAMPLE_RATE_MODE,
    SAMPLE_RATE_LABELS,
    SAMPLE_RATE_MODES,
    normalize_sample_rate_mode,
    resolve_sample_rate,
)
from .settings import load_settings, save_settings
from .startup import is_system_autostart_enabled, set_system_autostart

BLACK = "#000000"
PANEL = "#030303"
PANEL_LIFT = "#080808"
PANEL_SOFT = "#0f0f0f"
BORDER = "#181818"
BORDER_HOT = "#eeeeee"
TEXT = "#eeeeee"
MID = "#b7b7b7"
DIM = "#747474"
WARN = "#c8c8c8"
ERROR = "#f26d6d"
SUCCESS = "#68d98f"
STOPPED = "#b06a6a"
ACCENT = "#eeeeee"
BLUE = "#45b7ff"
GREEN_SOFT = "#102018"
BLUE_SOFT = "#0c1720"
ACCENT_SOFT = "#141414"
APP_HEADING = "DOWNMIX RENDERER"
USER_VOLUME_SLIDER_MAX = 1000
BASELINE_RECOVERY_VERSION = 1
DEVICE_FORCE_REFRESH_INTERVAL = 3
IDLE_RECOVERY_SECONDS = 2.5
RECOVERY_COOLDOWN_SECONDS = 8.0
RECOVERY_INPUT_ACTIVITY_THRESHOLD = 0.003
RECOVERY_OUTPUT_SILENCE_THRESHOLD = 0.0005
GITHUB_URL = "https://github.com/prospeck/downmix-renderer-7.1-windows.git"
APP_USER_MODEL_ID = "Taran.DownmixRenderer.DownmixRenderer"
GITHUB_MARK_SVG = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 0.296997C5.37 0.296997 0 5.67 0 12.297C0 17.6 3.438 22.097 8.205 23.682C8.805 23.795 9.025 23.424 9.025 23.105C9.025 22.82 9.015 22.065 9.01 21.065C5.672 21.789 4.968 19.455 4.968 19.455C4.422 18.07 3.633 17.7 3.633 17.7C2.546 16.956 3.717 16.971 3.717 16.971C4.922 17.055 5.555 18.207 5.555 18.207C6.625 20.042 8.364 19.512 9.05 19.205C9.158 18.429 9.467 17.9 9.81 17.6C7.145 17.3 4.344 16.268 4.344 11.67C4.344 10.36 4.809 9.29 5.579 8.45C5.444 8.147 5.039 6.927 5.684 5.274C5.684 5.274 6.689 4.952 8.984 6.504C9.944 6.237 10.964 6.105 11.984 6.099C13.004 6.105 14.024 6.237 14.984 6.504C17.264 4.952 18.269 5.274 18.269 5.274C18.914 6.927 18.509 8.147 18.389 8.45C19.154 9.29 19.619 10.36 19.619 11.67C19.619 16.28 16.814 17.295 14.144 17.59C14.564 17.95 14.954 18.686 14.954 19.81C14.954 21.416 14.939 22.706 14.939 23.096C14.939 23.411 15.149 23.786 15.764 23.666C20.565 22.092 24 17.592 24 12.297C24 5.67 18.627 0.296997 12 0.296997Z" fill="{color}"/></svg>"""

BASE_STYLE = f"""
QWidget {{
    background-color: {BLACK};
    color: {TEXT};
    font-family: Segoe UI, Inter, Arial;
    font-size: 12px;
}}
QWidget#rendererRoot {{
    background-color: {BLACK};
}}
QWidget#content,
QWidget#mainPage,
QWidget#presetsPage,
QWidget#presetsBody,
QWidget#presetListContainer,
QWidget#profileActions,
QWidget#rendererLeftColumn,
QWidget#rendererCenterColumn,
QWidget#rendererRightColumn,
QWidget#routeColumn,
QWidget#channelTilesPanel,
QWidget#rendererDetailsBody,
QWidget#transparentViewport {{
    background-color: transparent;
}}
QLabel#title {{
    color: {TEXT};
    font-size: 21px;
    font-weight: 650;
}}
QLabel#fixedDevice {{
    background-color: #020202;
    border: 1px solid #242424;
    border-radius: 8px;
    padding: 7px 11px;
    min-height: 30px;
    color: {TEXT};
    font-weight: 620;
}}
QLabel#routeEyebrow {{
    color: #eef6f5;
    background-color: transparent;
    font-size: 11px;
    font-weight: 760;
    padding: 0px;
}}
QLabel#routeFixedValue {{
    color: #f4f6f5;
    background-color: transparent;
    border: none;
    padding: 0px 2px 0px 10px;
    font-size: 11px;
    font-weight: 660;
}}
QLabel#routeArrow {{
    color: rgba(192, 224, 223, 170);
    background-color: transparent;
    font-size: 16px;
    font-weight: 650;
    padding: 0px 2px;
}}
QLabel#subtitle {{
    color: {DIM};
    font-size: 11px;
    font-weight: 500;
}}
QLabel#keepAwakeHelper {{
    color: #828986;
    font-size: 11px;
    font-weight: 520;
    background-color: transparent;
}}
QLabel#heroStatus {{
    color: {MID};
    font-size: 11px;
    font-weight: 600;
    padding: 6px 14px;
    border: 1px solid #282828;
    border-radius: 10px;
    background-color: #030303;
}}
QLabel#section {{
    color: {MID};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0px;
}}
QLabel#value {{
    color: {TEXT};
    font-family: Consolas, monospace;
    font-size: 11px;
}}
QLabel#value[status="running"] {{
    color: {SUCCESS};
}}
QLabel#value[status="stopped"] {{
    color: {STOPPED};
}}
QLabel#value[status="warning"] {{
    color: {WARN};
}}
QLabel#value[status="error"] {{
    color: {ERROR};
}}
QLabel#value[status="neutral"] {{
    color: {MID};
}}
QLabel#sessionStatus {{
    color: {MID};
    font-family: Segoe UI, Inter, Arial;
    font-size: 10px;
    font-weight: 800;
    padding: 0px;
    border: none;
    background-color: transparent;
}}
QLabel#sessionStatus[status="running"] {{
    color: {SUCCESS};
}}
QLabel#sessionStatus[status="stopped"] {{
    color: {STOPPED};
}}
QLabel#sessionStatus[status="warning"] {{
    color: {WARN};
}}
QLabel#sessionStatus[status="error"] {{
    color: {ERROR};
}}
QFrame#card,
QFrame#keepAwakeCard {{
    background-color: #030303;
    border: 1px solid #1d1d1d;
    border-radius: 8px;
}}
QFrame#routeLane {{
    background-color: #030303;
    border: 1px solid #1d1d1d;
    border-radius: 12px;
}}
QWidget#routeColumn {{
    background-color: transparent;
}}
QFrame#routeSegment {{
    background-color: #050505;
    border: 1px solid #252525;
    border-radius: 10px;
}}
QFrame#routeSegment:hover {{
    border-color: #363636;
    background-color: #070707;
}}
QFrame#card[presetSurface="true"] {{
    background-color: rgba(5, 5, 5, 210);
    border-color: rgba(255, 255, 255, 30);
}}
QFrame#profileManagerCard {{
    background-color: rgba(5, 5, 5, 216);
    border: 1px solid #222222;
    border-radius: 8px;
}}
QFrame#card:hover,
QFrame#keepAwakeCard:hover {{
    border-color: #262626;
}}
QTabWidget::pane {{
    border: none;
    margin-top: 8px;
    background-color: transparent;
}}
QTabWidget#mainTabs::tab-bar {{
    alignment: left;
}}
QTabBar {{
    background-color: transparent;
}}
QTabBar::tab {{
    background-color: #030303;
    border: 1px solid #242424;
    border-radius: 8px;
    color: {DIM};
    padding: 9px 24px;
    margin-top: 7px;
    margin-bottom: 7px;
    margin-right: 8px;
    min-width: 96px;
    min-height: 24px;
    font-weight: 650;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    border-color: {ACCENT};
    background-color: #050505;
}}
QTabBar::tab:hover {{
    color: {TEXT};
    border-color: #707070;
    background-color: #050505;
}}
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QScrollArea > QWidget {{
    background-color: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}
QScrollBar:vertical {{
    background: #050505;
    width: 9px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #2a2a2a;
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: #3a3a3a;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: #050505;
    height: 9px;
    margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: #2a2a2a;
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QComboBox {{
    background-color: #020202;
    border: 1px solid #242424;
    border-radius: 7px;
    padding: 5px 28px 5px 10px;
    min-height: 28px;
    color: {TEXT};
    font-weight: 560;
}}
QComboBox:hover {{
    border-color: #575757;
    background-color: #050505;
}}
QComboBox:focus {{
    border-color: #777777;
}}
QComboBox::drop-down {{
    border: none;
}}
QComboBox QAbstractItemView {{
    background-color: #030303;
    border: 1px solid #242424;
    outline: none;
    padding: 4px;
    color: {TEXT};
    selection-background-color: #171717;
    selection-color: #ffffff;
}}
QComboBox#routeGlassCombo {{
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px 18px 0px 8px;
    min-height: 24px;
    color: #f4f6f5;
    font-size: 11px;
    font-weight: 660;
}}
QComboBox#routeGlassCombo:hover {{
    background-color: transparent;
    border: none;
    color: #ffffff;
}}
QComboBox#routeGlassCombo:focus {{
    border: none;
}}
QComboBox#routeGlassCombo::drop-down {{
    border: none;
    width: 16px;
}}
QComboBox#routeGlassCombo::down-arrow {{
    image: none;
    width: 0px;
    height: 0px;
}}
QComboBox#routeGlassCombo QAbstractItemView {{
    background-color: rgba(3, 3, 3, 248);
    border: 1px solid rgba(255, 255, 255, 58);
    border-radius: 10px;
    outline: none;
    padding: 6px;
    color: #f4f6f5;
    selection-background-color: rgba(255, 255, 255, 28);
    selection-color: #ffffff;
}}
QListView#routeGlassPopup {{
    background-color: rgba(3, 3, 3, 250);
    border: 1px solid rgba(255, 255, 255, 46);
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QListView#routeGlassPopup::item {{
    color: #e4e4e4;
    min-height: 20px;
    padding: 2px 9px;
    border-radius: 6px;
}}
QListView#routeGlassPopup::item:hover {{
    background-color: rgba(255, 255, 255, 22);
    color: #ffffff;
}}
QListView#routeGlassPopup::item:selected {{
    background-color: rgba(255, 255, 255, 36);
    color: #ffffff;
}}
QLineEdit {{
    background-color: #000000;
    border: 1px solid #151515;
    border-radius: 7px;
    padding: 8px 10px;
    color: {TEXT};
    selection-background-color: #ffffff;
    selection-color: #000000;
}}
QLineEdit:hover {{
    border-color: #444444;
}}
QLineEdit:focus {{
    border-color: #5f5b52;
}}
QLineEdit#trimInput {{
    background-color: #010101;
    border: 1px solid #282828;
    border-radius: 7px;
    padding: 7px 10px;
    color: {TEXT};
    font-family: Consolas, monospace;
    font-size: 12px;
    font-weight: 650;
}}
QLineEdit#trimInput:hover {{
    border-color: #5f5f5f;
}}
QLineEdit#trimInput:focus {{
    border-color: #eeeeee;
    background-color: #050505;
}}
QPushButton {{
    background-color: #020304;
    border: 1px solid #242424;
    border-radius: 7px;
    padding: 6px 12px;
    min-height: 29px;
    color: {TEXT};
    font-weight: 600;
}}
QPushButton:hover {{
    border-color: #707070;
    background-color: #070707;
}}
QPushButton:pressed {{
    background-color: #0d0d0d;
}}
QPushButton#preset {{
    color: {MID};
    text-align: left;
    min-height: 32px;
    max-height: 34px;
    padding: 0px 10px;
}}
QPushButton#preset:hover {{
    color: {TEXT};
    border-color: #777777;
    background-color: #070707;
}}
QPushButton#preset[active="true"] {{
    color: {ACCENT};
    background-color: {ACCENT_SOFT};
    border-color: {ACCENT};
}}
QPushButton#ghost {{
    color: {MID};
}}
QPushButton#ghost:hover {{
    color: {TEXT};
    border-color: #777777;
    background-color: #070707;
}}
QPushButton#profileAction {{
    color: {TEXT};
    background-color: #050505;
    border: 1px solid #2a2a2a;
    border-radius: 7px;
    min-height: 32px;
    padding: 5px 12px;
    font-weight: 650;
}}
QPushButton#profileAction:hover {{
    border-color: #777777;
    background-color: #090909;
}}
QPushButton#profileAction:pressed {{
    border-color: #eeeeee;
    background-color: #0d0d0d;
}}
QPushButton#rawMonitor {{
    color: {TEXT};
    background-color: #020202;
    border: 1px solid #2a2a2a;
    border-radius: 7px;
    min-height: 30px;
    font-weight: 600;
}}
QPushButton#rawMonitor:hover {{
    border-color: #777777;
    background-color: #070707;
}}
QPushButton#rawMonitor:pressed {{
    border-color: #eeeeee;
    background-color: #0c0c0c;
}}
QPushButton#routeRefresh {{
    color: {TEXT};
    background-color: #050505;
    border: 1px solid #252525;
    border-radius: 10px;
    min-height: 42px;
    max-height: 42px;
    padding: 0px;
}}
QPushButton#routeRefresh:hover {{
    border-color: #454545;
    background-color: #090909;
}}
QPushButton#routeRefresh:pressed {{
    border-color: #6a6a6a;
    background-color: #101010;
}}
QPushButton#peqAction {{
    color: {TEXT};
    background-color: #050505;
    border: 1px solid #282828;
    border-radius: 7px;
    font-weight: 600;
    min-height: 29px;
}}
QPushButton#peqAction:hover {{
    border-color: #777777;
    background-color: #090909;
}}
QPushButton#peqAction:pressed {{
    border-color: #eeeeee;
    background-color: #0d0d0d;
}}
QFrame#peqPanel {{
    background-color: #020202;
    border: 1px solid #1c1c1c;
    border-radius: 8px;
}}
QPlainTextEdit#peqText {{
    background-color: #010101;
    border: 1px solid #242424;
    border-radius: 8px;
    color: {TEXT};
    font-family: Consolas, monospace;
    font-size: 11px;
    padding: 8px;
    selection-background-color: #ffffff;
    selection-color: #000000;
}}
QPlainTextEdit#peqText:focus {{
    border-color: #6a6a6a;
}}
QLabel#peqHelper {{
    color: {MID};
    font-size: 11px;
    font-weight: 500;
}}
QLabel#peqStatus {{
    color: {MID};
    font-size: 10px;
    font-weight: 600;
}}
QLabel#peqStatus[status="warning"] {{
    color: {WARN};
}}
QLabel#peqStatus[status="error"] {{
    color: {ERROR};
}}
QPushButton#info {{
    border-radius: 16px;
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    padding: 0px;
    color: {TEXT};
    border-color: #343434;
    background-color: #080808;
    font-weight: 800;
}}
QPushButton#info:hover {{
    border-color: #888888;
    background-color: #101010;
}}
QPushButton#headerIconButton {{
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    padding: 0px;
    border: none;
    background-color: transparent;
}}
QPushButton#mode {{
    color: {MID};
    background-color: #020202;
    border-color: #202020;
    padding-left: 10px;
    padding-right: 10px;
}}
QPushButton#mode:hover {{
    color: {TEXT};
    border-color: #666666;
    background-color: #050505;
}}
QPushButton#mode[active="true"] {{
    color: {TEXT};
    background-color: #101010;
    border-color: {ACCENT};
}}
QSlider::groove:horizontal {{
    height: 5px;
    background: #101820;
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {BLUE}, stop:1 {SUCCESS});
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: #ffffff;
    border: 1px solid #4cc8ff;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider#preampSlider::groove:horizontal {{
    height: 4px;
    background: #050505;
    border: 1px solid #1d1d1d;
    border-radius: 2px;
}}
QSlider#preampSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffffff, stop:0.58 #dddddd, stop:1 #9b9b9b);
    border-radius: 2px;
}}
QSlider#preampSlider::handle:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f7f7f7, stop:0.46 #cfd3d5, stop:0.54 #ffffff, stop:1 #8f9498);
    border: 1px solid #eeeeee;
    width: 9px;
    height: 20px;
    margin: -8px 0;
    border-radius: 3px;
}}
QSlider#preampSlider::handle:horizontal:hover {{
    border-color: #ffffff;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffffff, stop:0.5 #f0f0f0, stop:1 #b6babd);
}}
QCheckBox {{
    color: {MID};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 30px;
    height: 16px;
    border-radius: 8px;
    background: #111111;
    border: 1px solid #202020;
}}
QCheckBox::indicator:checked {{
    background: #e8e8e8;
    border-color: {ACCENT};
}}
"""


ROUTE_GLASS_POPUP_STYLE = """
QFrame#routeGlassPopupWindow {
    background-color: transparent;
    border: none;
}
QListView#routeGlassPopup {
    background-color: rgba(3, 3, 3, 250);
    border: 1px solid rgba(255, 255, 255, 46);
    border-radius: 8px;
    padding: 4px;
    outline: none;
}
QListView#routeGlassPopup::item {
    color: #e4e4e4;
    min-height: 20px;
    padding: 2px 9px;
    border-radius: 6px;
}
QListView#routeGlassPopup::item:hover {
    background-color: rgba(255, 255, 255, 22);
    color: #ffffff;
}
QListView#routeGlassPopup::item:selected {
    background-color: rgba(255, 255, 255, 36);
    color: #ffffff;
}
QListView#routeGlassPopup QScrollBar:vertical {
    background: #050505;
    width: 8px;
    margin: 5px 2px 5px 0px;
}
QListView#routeGlassPopup QScrollBar::handle:vertical {
    background: #2d2d2d;
    border-radius: 4px;
    min-height: 24px;
}
QListView#routeGlassPopup QScrollBar::handle:vertical:hover {
    background: #3f3f3f;
}
QListView#routeGlassPopup QScrollBar::add-line:vertical,
QListView#routeGlassPopup QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


def section_label(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text.upper())
    label.setObjectName("section")
    return label


def value_label(text: str = "--") -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("value")
    return label


def _draw_refresh_glyph(
    painter: QtGui.QPainter,
    center: QtCore.QPointF,
    radius: float,
    color: QtGui.QColor,
    stroke_width: float,
    rotation_degrees: float = 0.0,
    wheel_morph: float = 0.0,
) -> None:
    wheel_morph = max(0.0, min(1.0, float(wheel_morph)))
    painter.save()
    painter.translate(center)
    if rotation_degrees:
        painter.rotate(rotation_degrees)
    pen = QtGui.QPen(color, stroke_width, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    if wheel_morph >= 0.985:
        painter.drawEllipse(QtCore.QRectF(-radius, -radius, radius * 2.0, radius * 2.0))
    else:
        sweep = RouteRefreshButton.refresh_icon_arc_sweep_degrees + (
            (354.0 - RouteRefreshButton.refresh_icon_arc_sweep_degrees) * wheel_morph
        )
        painter.drawArc(QtCore.QRectF(-radius, -radius, radius * 2.0, radius * 2.0), 32 * 16, int(sweep * 16))

    arrow_alpha = int(color.alpha() * max(0.0, 1.0 - (wheel_morph * 1.35)))
    if arrow_alpha > 8:
        arrow_color = QtGui.QColor(color)
        arrow_color.setAlpha(arrow_alpha)
        painter.setPen(QtGui.QPen(arrow_color, stroke_width, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
        painter.setBrush(QtCore.Qt.NoBrush)
        tip = QtCore.QPointF(radius * 0.98, radius * -0.58)
        trailing_wing = QtCore.QPointF(radius * 0.34, radius * -0.56)
        upper_wing = QtCore.QPointF(radius * 0.69, radius * -1.10)
        painter.drawLine(tip, trailing_wing)
        painter.drawLine(tip, upper_wing)
    painter.restore()


def refresh_icon(size: int = 22) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    _draw_refresh_glyph(
        painter,
        QtCore.QPointF(size / 2.0, size / 2.0),
        size * 0.305,
        QtGui.QColor("#f7fbfa"),
        2.3,
    )
    painter.end()
    return QtGui.QIcon(pixmap)


class RouteRefreshButton(QtWidgets.QPushButton):
    REFRESH_ANIMATION_MS = 315
    has_premium_refresh_animation = True
    refresh_icon_stroke_width = 2.3
    refresh_icon_gap_degrees = 100
    refresh_icon_arrow_size = 6.2
    refresh_arrow_direction = "clockwise_upper_right"
    refresh_arrow_head_style = "line_chevron"
    refresh_arrow_tip_angle_degrees = 34
    refresh_arrow_tip_y_ratio = -0.58
    refresh_icon_radius = 6.85
    refresh_icon_arc_sweep_degrees = 282.0
    refresh_spin_degrees = 360
    uses_refresh_pulse = False
    uses_refresh_animation_group = True
    refresh_press_feedback_enabled = True
    uses_refresh_wheel_morph = True
    refresh_wheel_morph_peak = 0.5
    refresh_wheel_hold_start = 0.34
    refresh_wheel_hold_end = 0.66
    refresh_wheel_accent_color = "#45d88f"
    refresh_wheel_tint_follows_morph = True
    refresh_easing_curve_name = "OutCubic"

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("routeRefresh")
        self.setToolTip("Refresh devices")
        self.setAccessibleName("Refresh devices")
        self.setIcon(refresh_icon(24))
        self.setIconSize(QtCore.QSize(20, 20))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(QtCore.Qt.WA_Hover, True)
        self._refresh_progress = 0.0
        self._refresh_press_depth = 0.0
        self._refresh_animation_group = QtCore.QParallelAnimationGroup(self)
        self._refresh_animation = QtCore.QPropertyAnimation(self, b"refreshProgress", self._refresh_animation_group)
        self._refresh_animation.setDuration(self.REFRESH_ANIMATION_MS)
        self._refresh_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._refresh_press_animation = QtCore.QPropertyAnimation(self, b"refreshPressDepth", self._refresh_animation_group)
        self._refresh_press_animation.setDuration(118)
        self._refresh_press_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._refresh_animation_group.addAnimation(self._refresh_animation)
        self._refresh_animation_group.addAnimation(self._refresh_press_animation)
        self._refresh_animation_group.finished.connect(self._finish_refresh_animation)
        self.pressed.connect(self.animate_refresh)

    @property
    def refresh_progress(self) -> float:
        return self._refresh_progress

    def _set_refresh_progress(self, value: float) -> None:
        self._refresh_progress = max(0.0, min(1.0, float(value)))
        self.update()

    refreshProgress = QtCore.pyqtProperty(float, fget=lambda self: self._refresh_progress, fset=_set_refresh_progress)

    @property
    def refresh_wheel_morph(self) -> float:
        progress = self._refresh_progress
        if progress <= 0.0001 or progress >= 0.9999:
            return 0.0
        if progress <= self.refresh_wheel_hold_start:
            t = progress / self.refresh_wheel_hold_start
            return t * t * (3.0 - (2.0 * t))
        if progress <= self.refresh_wheel_hold_end:
            return 1.0
        t = (progress - self.refresh_wheel_hold_end) / (1.0 - self.refresh_wheel_hold_end)
        return max(0.0, 1.0 - (t * t * (3.0 - (2.0 * t))))

    def refresh_glyph_color(self) -> QtGui.QColor:
        base = QtGui.QColor("#ffffff" if self.underMouse() or self.hasFocus() or self.isDown() else "#f0f4f3")
        accent = QtGui.QColor(self.refresh_wheel_accent_color)
        t = self.refresh_wheel_morph
        if t <= 0.0:
            return base
        return QtGui.QColor(
            int(base.red() + ((accent.red() - base.red()) * t)),
            int(base.green() + ((accent.green() - base.green()) * t)),
            int(base.blue() + ((accent.blue() - base.blue()) * t)),
            255,
        )

    @property
    def refresh_press_depth(self) -> float:
        return self._refresh_press_depth

    def _set_refresh_press_depth(self, value: float) -> None:
        self._refresh_press_depth = max(0.0, min(1.0, float(value)))
        self.update()

    refreshPressDepth = QtCore.pyqtProperty(
        float,
        fget=lambda self: self._refresh_press_depth,
        fset=_set_refresh_press_depth,
    )

    def animate_refresh(self) -> None:
        if self._refresh_animation_group.state() == QtCore.QAbstractAnimation.Running:
            self._refresh_animation_group.stop()
        self._set_refresh_progress(0.0)
        self._set_refresh_press_depth(0.0)
        self._refresh_animation.setStartValue(self._refresh_progress)
        self._refresh_animation.setEndValue(1.0)
        self._refresh_press_animation.setStartValue(0.0)
        self._refresh_press_animation.setKeyValueAt(0.42, 1.0)
        self._refresh_press_animation.setEndValue(0.0)
        self._refresh_animation_group.start()
        self._refresh_animation_group.setCurrentTime(1)

    def cancel_refresh_animation(self) -> None:
        if self._refresh_animation_group.state() == QtCore.QAbstractAnimation.Running:
            self._refresh_animation_group.stop()
        self._finish_refresh_animation()

    def _finish_refresh_animation(self) -> None:
        self._set_refresh_progress(0.0)
        self._set_refresh_press_depth(0.0)

    def hideEvent(self, event) -> None:
        self.cancel_refresh_animation()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hover = self.underMouse() or self.hasFocus()
        active = self.isDown() or self._refresh_progress > 0.01

        bg = QtGui.QColor("#101010" if self.isDown() else ("#090909" if hover or active else "#050505"))
        border = QtGui.QColor("#6a6a6a" if self.isDown() else ("#4a4a4a" if hover or active else "#252525"))
        painter.setPen(QtGui.QPen(border, 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 10, 10)

        press = math.sin(math.pi * self._refresh_press_depth)
        center = rect.center() + QtCore.QPointF(0.0, 0.45 * press)
        icon_color = self.refresh_glyph_color()
        painter.save()
        if press > 0.0:
            painter.translate(rect.center())
            scale = 1.0 - (0.035 * press)
            painter.scale(scale, scale)
            painter.translate(-rect.center())
        _draw_refresh_glyph(
            painter,
            center,
            self.refresh_icon_radius,
            icon_color,
            self.refresh_icon_stroke_width,
            -self.refresh_spin_degrees * self._refresh_progress,
            self.refresh_wheel_morph,
        )
        painter.restore()
        painter.end()


class RouteValueLabel(QtWidgets.QLabel):
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setObjectName("routeFixedValue")
        self.setMinimumWidth(0)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
        painter.setPen(QtGui.QColor("#f4f6f5"))
        painter.setFont(QtGui.QFont("Segoe UI", 8, QtGui.QFont.DemiBold))
        rect = QtCore.QRectF(self.rect()).adjusted(2, 0, -2, 0)
        text = self.fontMetrics().elidedText(self.text(), QtCore.Qt.ElideMiddle, max(16, int(rect.width())))
        painter.drawText(rect, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, text)
        painter.end()


class RouteGlassItemDelegate(QtWidgets.QStyledItemDelegate):
    has_smooth_feedback = True
    has_keyboard_navigation_feedback = True

    def __init__(self, view: QtWidgets.QListView) -> None:
        super().__init__(view)
        self._view = view
        self._hover_row = -1
        self._pressed_row = -1
        self._hover_alpha: dict[int, float] = {}
        self._press_alpha: dict[int, float] = {}
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._animate)
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self._view:
            if event.type() == QtCore.QEvent.KeyPress:
                QtCore.QTimer.singleShot(0, self._sync_current_row)
            elif event.type() == QtCore.QEvent.FocusOut:
                self._set_hover_row(-1)
                self._pressed_row = -1
                self._start_animation()
        elif watched is self._view.viewport():
            if event.type() == QtCore.QEvent.MouseMove:
                index = self._view.indexAt(event.pos())
                self._set_hover_row(index.row() if index.isValid() else -1)
            elif event.type() == QtCore.QEvent.Leave:
                self._set_hover_row(-1)
                self._pressed_row = -1
                self._start_animation()
            elif event.type() == QtCore.QEvent.MouseButtonPress:
                index = self._view.indexAt(event.pos())
                self._pressed_row = index.row() if index.isValid() else -1
                self._start_animation()
            elif event.type() == QtCore.QEvent.MouseButtonRelease:
                self._pressed_row = -1
                self._start_animation()
        return super().eventFilter(watched, event)

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        row = index.row()
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        hover_alpha = self._hover_alpha.get(row, 0.0)
        press_alpha = self._press_alpha.get(row, 0.0)
        background_alpha = max(36.0 if selected else 0.0, hover_alpha, press_alpha)
        if background_alpha > 0.5:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(255, 255, 255, int(background_alpha)))
            painter.drawRoundedRect(QtCore.QRectF(option.rect).adjusted(2, 1, -2, -1), 6, 6)

        text = str(index.data(QtCore.Qt.DisplayRole) or "")
        text_color = "#ffffff" if selected or hover_alpha > 8 or press_alpha > 8 else "#e4e4e4"
        painter.setPen(QtGui.QColor(text_color))
        painter.setFont(option.font)
        text_rect = QtCore.QRect(option.rect).adjusted(9, 0, -9, 0)
        elided = option.fontMetrics.elidedText(text, QtCore.Qt.ElideMiddle, max(12, text_rect.width()))
        painter.drawText(text_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, elided)
        painter.restore()

    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> QtCore.QSize:
        hint = super().sizeHint(option, index)
        hint.setHeight(RouteGlassCombo.POPUP_ITEM_HEIGHT)
        return hint

    def _set_hover_row(self, row: int) -> None:
        if row == self._hover_row:
            return
        if self._hover_row >= 0:
            self._hover_alpha.setdefault(self._hover_row, 22.0)
        self._hover_row = row
        if row >= 0:
            self._hover_alpha.setdefault(row, 0.0)
        self._start_animation()

    def _sync_current_row(self) -> None:
        index = self._view.currentIndex()
        self._set_hover_row(index.row() if index.isValid() else -1)

    def _start_animation(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
        self._view.viewport().update()

    def _animate(self) -> None:
        changed = False
        rows = set(self._hover_alpha) | set(self._press_alpha)
        if self._hover_row >= 0:
            rows.add(self._hover_row)
        if self._pressed_row >= 0:
            rows.add(self._pressed_row)

        for row in list(rows):
            hover_target = 24.0 if row == self._hover_row else 0.0
            press_target = 48.0 if row == self._pressed_row else 0.0
            changed |= self._approach(self._hover_alpha, row, hover_target)
            changed |= self._approach(self._press_alpha, row, press_target)

        if changed:
            self._view.viewport().update()
        else:
            self._timer.stop()

    @staticmethod
    def _approach(values: dict[int, float], row: int, target: float) -> bool:
        current = values.get(row, 0.0)
        next_value = current + (target - current) * 0.34
        if abs(next_value - target) < 0.6:
            next_value = target
        if next_value <= 0.0:
            values.pop(row, None)
        else:
            values[row] = next_value
        return abs(next_value - current) > 0.1


class RouteGlassCombo(QtWidgets.QComboBox):
    POPUP_ITEM_HEIGHT = 20
    POPUP_VERTICAL_PADDING = 20
    POPUP_SCREEN_MARGIN = 10
    OPEN_ANIMATION_MS = 120
    ARROW_ANIMATION_MS = 110
    has_premium_open_animation = True
    has_arrow_motion_feedback = True

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("routeGlassCombo")
        self.setMinimumWidth(0)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        view = QtWidgets.QListView()
        view.setObjectName("routeGlassPopup")
        view.setFrameShape(QtWidgets.QFrame.NoFrame)
        view.setUniformItemSizes(True)
        view.setSpacing(1)
        view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        view.setMouseTracking(True)
        view.setTextElideMode(QtCore.Qt.ElideMiddle)
        view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        view.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        view.viewport().setAttribute(QtCore.Qt.WA_StyledBackground, True)
        view.setStyleSheet(ROUTE_GLASS_POPUP_STYLE)
        self.setView(view)
        view.setItemDelegate(RouteGlassItemDelegate(view))
        self.setMaxVisibleItems(24)
        self._popup_animation_group: QtCore.QParallelAnimationGroup | None = None
        self._open_progress = 0.0
        self._open_progress_animation = QtCore.QPropertyAnimation(self, b"openProgress", self)
        self._open_progress_animation.setDuration(self.ARROW_ANIMATION_MS)
        self._open_progress_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)

    @property
    def open_progress(self) -> float:
        return self._open_progress

    def _set_open_progress(self, value: float) -> None:
        self._open_progress = max(0.0, min(1.0, float(value)))
        self.update()

    openProgress = QtCore.pyqtProperty(float, fget=lambda self: self._open_progress, fset=_set_open_progress)

    def showPopup(self) -> None:
        self.setMaxVisibleItems(max(1, self.count(), self.maxVisibleItems()))
        super().showPopup()
        segment = self.parentWidget()
        popup = self.view().window()
        if segment is None or popup is None:
            return
        width = max(160, segment.width())
        global_pos = segment.mapToGlobal(QtCore.QPoint(0, segment.height() + 2))
        popup_pos = QtCore.QPoint(global_pos)
        rows = max(1, self.count())
        desired_height = rows * self.POPUP_ITEM_HEIGHT + self.POPUP_VERTICAL_PADDING
        screen = QtWidgets.QApplication.screenAt(global_pos) or QtWidgets.QApplication.primaryScreen()
        height = desired_height
        if screen is not None:
            available = screen.availableGeometry()
            max_screen_height = max(
                self.POPUP_ITEM_HEIGHT + self.POPUP_VERTICAL_PADDING,
                available.height() - (self.POPUP_SCREEN_MARGIN * 2),
            )
            height = min(desired_height, max_screen_height)
            max_y = available.bottom() + 1 - height - self.POPUP_SCREEN_MARGIN
            max_x = available.right() + 1 - width - self.POPUP_SCREEN_MARGIN
            popup_pos.setY(max(available.top() + self.POPUP_SCREEN_MARGIN, min(global_pos.y(), max_y)))
            popup_pos.setX(max(available.left() + self.POPUP_SCREEN_MARGIN, min(global_pos.x(), max_x)))
        if height >= desired_height:
            self.view().setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        else:
            self.view().setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        popup.setObjectName("routeGlassPopupWindow")
        popup.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        popup.setStyleSheet(ROUTE_GLASS_POPUP_STYLE)
        popup.setFixedWidth(width)
        popup.setFixedHeight(height)
        self.view().setFixedWidth(width)
        self.view().setFixedHeight(height)
        self._hide_private_scrollers(popup)
        QtCore.QTimer.singleShot(0, lambda: self._hide_private_scrollers(popup))
        popup.move(popup_pos)
        self._animate_open_progress(1.0, prime=True)
        self._animate_popup_open(popup, popup_pos)

    def hidePopup(self) -> None:
        if self._popup_animation_group is not None and self._popup_animation_group.state() == QtCore.QAbstractAnimation.Running:
            self._popup_animation_group.stop()
        super().hidePopup()
        self._animate_open_progress(0.0)

    def _animate_open_progress(self, target: float, prime: bool = False) -> None:
        if self._open_progress_animation.state() == QtCore.QAbstractAnimation.Running:
            self._open_progress_animation.stop()
        if prime and self._open_progress <= 0.0:
            self._set_open_progress(0.08)
        self._open_progress_animation.setDuration(self.OPEN_ANIMATION_MS if target >= 1.0 else self.ARROW_ANIMATION_MS)
        self._open_progress_animation.setStartValue(self._open_progress)
        self._open_progress_animation.setEndValue(target)
        self._open_progress_animation.start()

    def _hide_private_scrollers(self, popup: QtWidgets.QWidget) -> None:
        try:
            scrollers = popup.findChildren(QtWidgets.QWidget)
        except RuntimeError:
            return
        for child in scrollers:
            if child.metaObject().className() == "QComboBoxPrivateScroller":
                child.hide()
                child.setFixedHeight(0)

    def _animate_popup_open(self, popup: QtWidgets.QWidget, global_pos: QtCore.QPoint) -> None:
        if self._popup_animation_group is not None and self._popup_animation_group.state() == QtCore.QAbstractAnimation.Running:
            self._popup_animation_group.stop()

        start_pos = QtCore.QPoint(global_pos.x(), max(0, global_pos.y() - 4))
        popup.setWindowOpacity(0.0)
        popup.move(start_pos)

        group = QtCore.QParallelAnimationGroup(self)
        opacity = QtCore.QPropertyAnimation(popup, b"windowOpacity", group)
        opacity.setDuration(115)
        opacity.setStartValue(0.0)
        opacity.setEndValue(1.0)
        opacity.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        slide = QtCore.QPropertyAnimation(popup, b"pos", group)
        slide.setDuration(115)
        slide.setStartValue(start_pos)
        slide.setEndValue(global_pos)
        slide.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        group.finished.connect(lambda: self._finish_popup_open(popup))
        self._popup_animation_group = group
        group.start()

    def _finish_popup_open(self, popup: QtWidgets.QWidget) -> None:
        try:
            popup.setWindowOpacity(1.0)
        except RuntimeError:
            return

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
        hover = self.underMouse() or self.hasFocus() or self._open_progress > 0.01
        text_alpha = 245 if hover else 228
        color = QtGui.QColor(255, 255, 255, text_alpha) if hover else QtGui.QColor("#f4f6f5")
        painter.setPen(color)
        painter.setFont(QtGui.QFont("Segoe UI", 8, QtGui.QFont.DemiBold))
        rect = QtCore.QRectF(self.rect()).adjusted(2, 0, -14, 0)
        text = self.fontMetrics().elidedText(self.currentText(), QtCore.Qt.ElideMiddle, max(16, int(rect.width())))
        painter.drawText(rect, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, text)

        arrow_x = self.width() - 8
        arrow_y = self.height() / 2.0 + 1.0
        arrow_alpha = int(130 + (70 * max(1.0 if self.hasFocus() else 0.0, self._open_progress, 0.78 if self.underMouse() else 0.0)))
        pen = QtGui.QPen(QtGui.QColor(230, 230, 230, arrow_alpha), 1.2)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.translate(QtCore.QPointF(arrow_x, arrow_y))
        painter.rotate(180.0 * self._open_progress)
        painter.translate(QtCore.QPointF(-arrow_x, -arrow_y))
        painter.drawLine(QtCore.QPointF(arrow_x - 3.0, arrow_y - 2.0), QtCore.QPointF(arrow_x, arrow_y + 1.0))
        painter.drawLine(QtCore.QPointF(arrow_x, arrow_y + 1.0), QtCore.QPointF(arrow_x + 3.0, arrow_y - 2.0))
        painter.end()


class SessionRenderToggle(QtWidgets.QPushButton):
    def __init__(self) -> None:
        super().__init__("Render")
        self.setObjectName("sessionRenderToggle")
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumHeight(46)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._rendering = False
        self._pulse_phase = 0.0
        self._pulse_timer = QtCore.QTimer(self)
        self._pulse_timer.setInterval(80)
        self._pulse_timer.timeout.connect(self._advance_pulse)
        self.setProperty("state", "idle")

    def set_rendering(self, rendering: bool) -> None:
        rendering = bool(rendering)
        if self._rendering == rendering:
            return
        self._rendering = rendering
        self.setChecked(rendering)
        self.setText("Rendering" if rendering else "Render")
        self.setProperty("state", "rendering" if rendering else "idle")
        if rendering:
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
            self._pulse_phase = 0.0
        self.update()

    def _advance_pulse(self) -> None:
        self._pulse_phase = (self._pulse_phase + 0.18) % math.tau
        self.update()

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        hover = self.underMouse()
        down = self.isDown()

        offset = 1.0 if down else (-1.0 if hover else 0.0)
        body = rect.adjusted(0, offset, 0, offset)
        radius = min(12.0, body.height() / 2.8)

        base = QtGui.QLinearGradient(body.topLeft(), body.bottomLeft())
        base.setColorAt(0.0, QtGui.QColor("#101010" if hover else "#080808"))
        base.setColorAt(0.42, QtGui.QColor("#030303"))
        base.setColorAt(1.0, QtGui.QColor("#000000"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#6c6c6c" if hover else "#303030"), 1))
        painter.setBrush(base)
        painter.drawRoundedRect(body, radius, radius)

        inset = QtGui.QLinearGradient(body.topLeft(), body.bottomLeft())
        inset.setColorAt(0.0, QtGui.QColor(255, 255, 255, 42 if hover else 28))
        inset.setColorAt(0.22, QtGui.QColor(255, 255, 255, 8))
        inset.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(inset)
        painter.drawRoundedRect(body.adjusted(2, 2, -2, -body.height() * 0.52), radius - 2, radius - 2)

        text_color = QtGui.QColor("#ffffff" if self._rendering else "#e7e7e7")
        painter.setPen(text_color)
        painter.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.DemiBold))
        painter.drawText(body.adjusted(16, 0, -44, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, self.text())

        dot_center = QtCore.QPointF(body.right() - 21, body.center().y())
        if self._rendering:
            pulse = 0.5 + 0.5 * math.sin(self._pulse_phase)
            halo = QtGui.QColor(104, 217, 143, int(26 + pulse * 42))
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(dot_center, 7.0 + pulse * 1.8, 7.0 + pulse * 1.8)
            dot = QtGui.QColor("#68d98f")
            border = QtGui.QColor("#bfffd1")
        else:
            dot = QtGui.QColor(176, 76, 76, 118)
            border = QtGui.QColor(176, 106, 106, 150)
        painter.setPen(QtGui.QPen(border, 1))
        painter.setBrush(dot)
        painter.drawEllipse(dot_center, 4.2, 4.2)
        painter.end()


def card(layout: QtWidgets.QLayout, preset_surface: bool = False) -> QtWidgets.QFrame:
    frame = QtWidgets.QFrame()
    frame.setObjectName("card")
    if preset_surface:
        frame.setProperty("presetSurface", True)
    frame.setLayout(layout)
    shadow = QtWidgets.QGraphicsDropShadowEffect(frame)
    shadow.setBlurRadius(18)
    shadow.setOffset(0, 1)
    shadow.setColor(QtGui.QColor(255, 255, 255, 8))
    frame.setGraphicsEffect(shadow)
    return frame


class SpatialPage(QtWidgets.QWidget):
    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        window = self.window()
        phase = float(getattr(self.window(), "_backdrop_phase", 0.0))
        origin = self.mapTo(window, QtCore.QPoint(0, 0))
        dirty_rect = event.rect().intersected(self.rect())
        paint_bounds = QtCore.QRect(self.mapTo(window, dirty_rect.topLeft()), dirty_rect.size())
        painter.save()
        painter.setClipRect(dirty_rect)
        painter.translate(-origin.x(), -origin.y())
        paint_spatial_backdrop(
            painter,
            window.rect(),
            phase,
            cursor=window.mapFromGlobal(QtGui.QCursor.pos()),
            lower_balance=True,
            intensity=0.44,
            cinematic_depth=True,
            paint_bounds=paint_bounds,
        )
        painter.restore()
        painter.end()


def apply_windows_dark_titlebar(widget: QtWidgets.QWidget) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        dark = ctypes.c_int(1)
        black = ctypes.c_int(0x000000)
        text = ctypes.c_int(0xEDEBE4)
        dwm = ctypes.windll.dwmapi
        for attribute in (20, 19):
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(dark), ctypes.sizeof(dark))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(black), ctypes.sizeof(black))
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text), ctypes.sizeof(text))
    except Exception:
        return


def paint_spatial_backdrop(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    phase: float,
    cursor: QtCore.QPoint | None = None,
    lower_balance: bool = False,
    subtle: bool = False,
    intensity: float = 1.0,
    cinematic_depth: bool = False,
    paint_bounds: QtCore.QRect | None = None,
) -> None:
    bounds = QtCore.QRect(rect if paint_bounds is None else paint_bounds).intersected(rect)
    if bounds.isEmpty():
        return

    painter.save()
    painter.setClipRect(bounds)
    painter.fillRect(bounds, QtGui.QColor(BLACK))
    intensity = max(0.0, min(1.0, float(intensity)))
    spacing = 20 if not subtle else 22
    cursor_inside = cursor is not None and rect.contains(cursor)
    height = max(1, rect.height())
    if not subtle:
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        for band in range(5):
            base_y = rect.height() * (0.16 + band * 0.18)
            path = QtGui.QPainterPath()
            for step in range(-18, rect.width() + 19, 18):
                wave_y = base_y + math.sin(step * 0.015 + phase * 1.8 + band * 0.9) * (7.0 + band * 1.2)
                point = QtCore.QPointF(float(step), float(wave_y))
                if step == -18:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            alpha = int((9 + band * 2) * intensity)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, alpha), 0.8))
            painter.drawPath(path)
        painter.restore()

    dot_margin = 26
    first_dot = -spacing
    row_start = max(0, math.floor((bounds.top() - dot_margin - first_dot) / spacing))
    row_end = max(row_start, math.ceil((bounds.bottom() + dot_margin - first_dot) / spacing))
    column_start = max(0, math.floor((bounds.left() - dot_margin - first_dot) / spacing))
    column_end = max(column_start, math.ceil((bounds.right() + dot_margin - first_dot) / spacing))

    for row in range(row_start, row_end + 1):
        y = first_dot + row * spacing
        y_ratio = min(1.0, max(0.0, y / height))
        lower_gain = 0.92 + y_ratio * 0.36 if lower_balance else 1.0
        if subtle:
            lower_gain *= 0.72
        for column in range(column_start, column_end + 1):
            x = first_dot + column * spacing
            wave = math.sin(column * 0.30 + row * 0.18 + phase)
            slow_column = math.sin(column * 0.52 + phase * 0.42)
            drift = math.cos(column * 0.14 - row * 0.24 - phase * 0.72)
            dot_x = float(x) + wave * (5.0 if not subtle else 3.4) + slow_column * (2.2 if not subtle else 1.4)
            dot_y = float(y) + drift * (3.7 if not subtle else 2.5)

            if cursor_inside and cursor is not None:
                dx = dot_x - cursor.x()
                dy = dot_y - cursor.y()
                distance = math.hypot(dx, dy)
                if 0.001 < distance < 190.0:
                    strength = (1.0 - distance / 190.0) ** 2
                    dot_x += (dx / distance) * strength * 7.0
                    dot_y += (dy / distance) * strength * 7.0

            shimmer = 0.5 + 0.5 * math.sin(column * 0.19 + row * 0.15 + phase * 1.18)
            column_lift = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(column * 0.72 + phase * 0.22))
            alpha = int(((22 if not subtle else 13) + shimmer * (48 if not subtle else 34)) * lower_gain * column_lift * intensity)
            radius = (0.72 if not subtle else 0.62) + shimmer * (0.62 if not subtle else 0.48)
            painter.setPen(QtCore.Qt.NoPen)
            min_alpha = max(3, int((9 if not subtle else 7) * intensity))
            max_alpha = max(min_alpha, int((74 if not subtle else 56) * intensity))
            painter.setBrush(QtGui.QColor(255, 255, 255, max(min_alpha, min(max_alpha, alpha))))
            painter.drawEllipse(QtCore.QPointF(dot_x, dot_y), radius, radius)

    if cinematic_depth:
        painter.save()
        veil = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        veil.setColorAt(0.0, QtGui.QColor(0, 0, 0, 24))
        veil.setColorAt(0.38, QtGui.QColor(0, 0, 0, 0))
        veil.setColorAt(1.0, QtGui.QColor(0, 0, 0, 42))
        painter.fillRect(bounds, veil)
        painter.restore()

    vignette = QtGui.QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.76)
    vignette.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
    vignette.setColorAt(0.78 if cinematic_depth else 0.84, QtGui.QColor(0, 0, 0, 46 if cinematic_depth else (34 if lower_balance else 46)))
    vignette.setColorAt(1.0, QtGui.QColor(0, 0, 0, 158 if cinematic_depth else 138))
    painter.fillRect(bounds, vignette)
    painter.restore()


class DotBackdropDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._backdrop_phase = 0.0
        self.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
        self.setStyleSheet(BASE_STYLE)
        self._backdrop_timer = QtCore.QTimer(self)
        self._backdrop_timer.timeout.connect(self._advance_backdrop)
        self._backdrop_timer.start(70)

    def _advance_backdrop(self) -> None:
        if not self.isVisible() or self.isMinimized():
            return
        self._backdrop_phase = (self._backdrop_phase + 0.022) % math.tau
        self.update()

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        paint_spatial_backdrop(painter, self.rect(), self._backdrop_phase, subtle=True)
        painter.end()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_windows_dark_titlebar(self)


class InfoButton(QtWidgets.QPushButton):
    def __init__(self) -> None:
        super().__init__("")
        self.setObjectName("info")
        self.setToolTip("Renderer details")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedSize(34, 34)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        bounds = QtCore.QRectF(self.rect())
        side = max(0.0, min(bounds.width(), bounds.height()) - 2.0)
        rect = QtCore.QRectF(
            bounds.center().x() - side / 2,
            bounds.center().y() - side / 2,
            side,
            side,
        )
        hover = self.underMouse()
        pressed = self.isDown()
        painter.setPen(QtGui.QPen(QtGui.QColor("#888888" if hover else "#343434"), 1))
        painter.setBrush(QtGui.QColor("#101010" if pressed else "#080808"))
        painter.drawEllipse(rect)
        painter.setPen(QtGui.QColor("#ffffff" if hover else "#d8d8d8"))
        painter.setFont(QtGui.QFont("Segoe UI", 13, QtGui.QFont.DemiBold))
        painter.drawText(rect.adjusted(0, -1, 0, 0), QtCore.Qt.AlignCenter, "i")
        painter.end()


class HeaderIconButton(QtWidgets.QPushButton):
    def __init__(self, kind: str, tooltip: str) -> None:
        super().__init__("")
        if kind != "github":
            raise ValueError(f"Unsupported header icon kind: {kind}")
        self.kind = kind
        self.setObjectName("headerIconButton")
        self.setProperty("kind", kind)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedSize(34, 34)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self._github_renderer = QtSvg.QSvgRenderer(self._github_svg("#f4f4f4"), self)
        self._github_hover_renderer = QtSvg.QSvgRenderer(self._github_svg("#ffffff"), self)

    @staticmethod
    def _github_svg(color: str) -> QtCore.QByteArray:
        return QtCore.QByteArray(GITHUB_MARK_SVG.format(color=color).encode("utf-8"))

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        bounds = QtCore.QRectF(self.rect())
        side = max(0.0, min(bounds.width(), bounds.height()) - 2.0)
        rect = QtCore.QRectF(
            bounds.center().x() - side / 2,
            bounds.center().y() - side / 2,
            side,
            side,
        )
        hover = self.underMouse()
        pressed = self.isDown()

        fill = QtGui.QRadialGradient(rect.center() + QtCore.QPointF(-5, -6), rect.width() * 0.78)
        if pressed:
            fill.setColorAt(0.0, QtGui.QColor("#151515"))
            fill.setColorAt(1.0, QtGui.QColor("#030303"))
        elif hover:
            fill.setColorAt(0.0, QtGui.QColor("#1b1b1b"))
            fill.setColorAt(0.65, QtGui.QColor("#0a0a0a"))
            fill.setColorAt(1.0, QtGui.QColor("#000000"))
        else:
            fill.setColorAt(0.0, QtGui.QColor("#101010"))
            fill.setColorAt(1.0, QtGui.QColor("#020202"))

        painter.setPen(QtGui.QPen(QtGui.QColor("#9a9a9a" if hover else "#383838"), 1))
        painter.setBrush(QtGui.QBrush(fill))
        painter.drawEllipse(rect)

        if hover:
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 34), 1))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(rect.adjusted(3.5, 3.5, -3.5, -3.5))

        icon_rect = rect.adjusted(6.4, 6.4, -6.4, -6.4)
        self._draw_github_icon(painter, icon_rect, hover)
        painter.end()

    def _draw_github_icon(self, painter: QtGui.QPainter, rect: QtCore.QRectF, hover: bool) -> None:
        renderer = self._github_hover_renderer if hover else self._github_renderer
        renderer.render(painter, rect)


class RendererTitle(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("rendererTitle")
        self.setAccessibleName(APP_HEADING)
        self.setMinimumSize(520, 42)
        self.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(560, 44)

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
        baseline = self.height() - 9
        x = 1.0

        thin = QtGui.QFont("Segoe UI Light", 27, QtGui.QFont.Light)
        thin.setCapitalization(QtGui.QFont.AllUppercase)
        thin.setLetterSpacing(QtGui.QFont.PercentageSpacing, 128)
        mix = QtGui.QFont("Segoe UI", 27, QtGui.QFont.Black)
        mix.setCapitalization(QtGui.QFont.AllUppercase)
        mix.setLetterSpacing(QtGui.QFont.PercentageSpacing, 104)

        painter.setPen(QtGui.QColor(255, 255, 255, 22))
        self._draw_tracked_text(painter, x + 1.0, baseline + 1.0, "DOWN", thin)
        x += self._draw_tracked_text(painter, x, baseline, "DOWN", thin, QtGui.QColor("#f3f5f6"))

        mix_start = x - 2.0
        painter.setPen(QtGui.QColor(255, 255, 255, 34))
        self._draw_tracked_text(painter, mix_start + 1.0, baseline + 1.0, "MIX", mix)
        mix_width = self._draw_tracked_text(painter, mix_start, baseline, "MIX", mix, QtGui.QColor("#ffffff"))

        glow = QtGui.QLinearGradient(mix_start, baseline + 5, mix_start + mix_width, baseline + 5)
        glow.setColorAt(0.0, QtGui.QColor(255, 255, 255, 0))
        glow.setColorAt(0.5, QtGui.QColor(255, 255, 255, 96))
        glow.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
        painter.setPen(QtGui.QPen(QtGui.QBrush(glow), 1.15))
        painter.drawLine(QtCore.QPointF(mix_start + 1, baseline + 7), QtCore.QPointF(mix_start + mix_width - 2, baseline + 7))

        x = mix_start + mix_width + 19.0
        painter.setPen(QtGui.QColor(255, 255, 255, 18))
        self._draw_tracked_text(painter, x + 1.0, baseline + 1.0, "RENDERER", thin)
        self._draw_tracked_text(painter, x, baseline, "RENDERER", thin, QtGui.QColor("#edf0f1"))
        painter.end()

    @staticmethod
    def _draw_tracked_text(
        painter: QtGui.QPainter,
        x: float,
        baseline: float,
        text: str,
        font: QtGui.QFont,
        color: QtGui.QColor | None = None,
    ) -> float:
        painter.setFont(font)
        if color is not None:
            painter.setPen(color)
        metrics = QtGui.QFontMetricsF(font)
        cursor = x
        for index, char in enumerate(text):
            painter.drawText(QtCore.QPointF(cursor, baseline), char)
            cursor += metrics.horizontalAdvance(char)
            if index < len(text) - 1:
                cursor += 3.8
        return cursor - x


class SwitchCheckBox(QtWidgets.QCheckBox):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setObjectName("switchControl")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setMinimumHeight(28)

    def sizeHint(self) -> QtCore.QSize:
        metrics = self.fontMetrics()
        return QtCore.QSize(52 + metrics.horizontalAdvance(self.text()) + 10, 28)

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        checked = self.isChecked()
        enabled = self.isEnabled()
        hover = self.underMouse()
        track = QtCore.QRectF(3, (self.height() - 20) / 2, 40, 20)
        track_color = QtGui.QColor("#173923" if checked else "#05080a")
        border_color = QtGui.QColor(SUCCESS if checked else ("#375263" if hover else "#31373d"))
        if not enabled:
            track_color.setAlpha(90)
            border_color.setAlpha(90)
        if checked and enabled:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(69, 183, 255, 28))
            painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), 12, 12)
        painter.setPen(QtGui.QPen(border_color, 1.15))
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 10, 10)

        thumb_x = track.right() - 17 if checked else track.left() + 3
        thumb = QtCore.QRectF(thumb_x, track.top() + 3, 14, 14)
        painter.setPen(QtCore.Qt.NoPen)
        thumb_grad = QtGui.QLinearGradient(thumb.topLeft(), thumb.bottomRight())
        thumb_grad.setColorAt(0.0, QtGui.QColor("#ffffff"))
        thumb_grad.setColorAt(1.0, QtGui.QColor("#bfefff" if checked else "#ccd4dc"))
        painter.setBrush(thumb_grad)
        painter.drawEllipse(thumb)

        text_rect = QtCore.QRectF(54, 0, self.width() - 54, self.height())
        painter.setPen(QtGui.QColor(TEXT if checked else ("#d6dce3" if hover else MID)))
        painter.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Medium))
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, self.text())
        painter.end()


class TrimLineEdit(QtWidgets.QLineEdit):
    valueChanged = QtCore.pyqtSignal(float)

    def __init__(self, value: float = 0.0) -> None:
        super().__init__()
        self.setObjectName("trimInput")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setFixedHeight(34)
        validator = QtGui.QDoubleValidator(TRIM_MIN_DB, TRIM_MAX_DB, 2, self)
        validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
        validator.setLocale(QtCore.QLocale.c())
        self.setValidator(validator)
        self._normalizing = False
        self.textEdited.connect(self._clamp_live)
        self.editingFinished.connect(self.normalize)
        self.set_value_db(value)

    def value_db(self) -> float:
        text = self.text().strip()
        if text in {"", "-", ".", "-."}:
            return 0.0
        return clamp_trim_db(text)

    def set_value_db(self, value: object) -> None:
        normalized = clamp_trim_db(value)
        text = self._format_value(normalized)
        if self.text() != text:
            blocker = QtCore.QSignalBlocker(self)
            self.setText(text)
            del blocker
        self.valueChanged.emit(normalized)

    def normalize(self) -> None:
        self.set_value_db(self.value_db())

    def _clamp_live(self, text: str) -> None:
        if self._normalizing:
            return
        stripped = text.strip()
        if stripped in {"", "-", ".", "-."}:
            return
        if stripped.startswith("+"):
            value = 0.0
        else:
            try:
                value = float(stripped)
            except ValueError:
                return
        clamped = clamp_trim_db(value)
        if clamped != value:
            self._normalizing = True
            self.setText(self._format_value(clamped))
            self.setCursorPosition(len(self.text()))
            self._normalizing = False
        self.valueChanged.emit(clamped)

    @staticmethod
    def _format_value(value: float) -> str:
        if abs(value) < 0.005:
            return "0"
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return "0" if text == "-0" else text


class VUMeter(QtWidgets.QWidget):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label
        self.level = 0.0
        self.display_level = 0.0
        self.peak = 0.0
        self.setMinimumSize(40, 170)
        self.setMaximumWidth(52)

    def set_level(self, value: float) -> None:
        self.level = min(1.0, max(0.0, float(value)))
        attack = 0.45 if self.level > self.display_level else 0.18
        self.display_level += (self.level - self.display_level) * attack
        self.peak = max(self.level, self.peak * 0.965)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        width, height = self.width(), self.height()
        rect = QtCore.QRectF(12, 6, width - 24, height - 36)

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#070707"))
        painter.drawRoundedRect(rect, 3, 3)

        fill_height = rect.height() * self.display_level
        if fill_height > 0.5:
            fill = QtCore.QRectF(rect.left(), rect.bottom() - fill_height, rect.width(), fill_height)
            grad = QtGui.QLinearGradient(fill.left(), fill.bottom(), fill.left(), fill.top())
            grad.setColorAt(0.0, QtGui.QColor("#ffffff"))
            grad.setColorAt(0.78, QtGui.QColor("#d8d8d8"))
            grad.setColorAt(1.0, QtGui.QColor(WARN))
            painter.setBrush(grad)
            painter.drawRoundedRect(fill, 3, 3)

        if self.peak > 0.01:
            peak_y = rect.bottom() - rect.height() * self.peak
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2))
            painter.drawLine(int(rect.left()) - 1, int(peak_y), int(rect.right()) + 1, int(peak_y))

        painter.setPen(QtGui.QColor(MID))
        painter.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Bold))
        painter.drawText(0, height - 22, width, 18, QtCore.Qt.AlignCenter, self.label)


class StereoSumMeter(QtWidgets.QWidget):
    SCALE_DB = (-60, -45, -30, -25, -20, -15, -10, -5, 0)
    CLIP_HOLD_SECONDS = 1.2
    CHANNEL_LABELS = ("Left", "Right")
    HELPER_TEXT = "Meters show recent sample-peak level of the final stereo output channels."
    SHOW_CLIP_BADGES = False
    HELPER_FONT_SIZE = 9
    CHANNEL_PANEL_HEIGHT = 88
    CHANNEL_PANEL_GAP = 14
    HELPER_TOP_GAP = 10
    HELPER_HEIGHT = 30
    BAR_TOP_OFFSET = 40
    TICK_LABEL_OFFSET = 15
    FIXED_HEIGHT = CHANNEL_PANEL_HEIGHT * 2 + CHANNEL_PANEL_GAP + HELPER_TOP_GAP + HELPER_HEIGHT

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("stereoSumMeter")
        self.left_level = 0.0
        self.right_level = 0.0
        self.left_display = 0.0
        self.right_display = 0.0
        self.left_clip_until = 0.0
        self.right_clip_until = 0.0
        self.setFixedHeight(self.FIXED_HEIGHT)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    @property
    def left_clipping(self) -> bool:
        return monotonic() < self.left_clip_until

    @property
    def right_clipping(self) -> bool:
        return monotonic() < self.right_clip_until

    def set_levels(self, left: float, right: float) -> None:
        now = monotonic()
        self.left_level = max(0.0, float(left))
        self.right_level = max(0.0, float(right))
        if self.left_level >= 1.0:
            self.left_clip_until = now + self.CLIP_HOLD_SECONDS
        if self.right_level >= 1.0:
            self.right_clip_until = now + self.CLIP_HOLD_SECONDS
        self.left_display = self._smooth(self.left_display, self.left_level)
        self.right_display = self._smooth(self.right_display, self.right_level)
        self.update()

    @staticmethod
    def _smooth(current: float, target: float) -> float:
        amount = 0.42 if target > current else 0.18
        return current + (target - current) * amount

    @staticmethod
    def _fraction_for_level(value: float) -> float:
        db = max(-60.0, min(0.0, linear_to_db(max(1.0e-6, value))))
        return (db + 60.0) / 60.0

    @staticmethod
    def _fraction_for_db(db: float) -> float:
        return (float(db) + 60.0) / 60.0

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0, 0, -1, -1)

        panel_top = rect.top()
        left_rect = QtCore.QRectF(rect.left(), panel_top, rect.width(), self.CHANNEL_PANEL_HEIGHT)
        right_rect = QtCore.QRectF(rect.left(), left_rect.bottom() + self.CHANNEL_PANEL_GAP, rect.width(), self.CHANNEL_PANEL_HEIGHT)
        self._draw_channel(painter, left_rect, self.CHANNEL_LABELS[0], self.left_display)
        self._draw_channel(painter, right_rect, self.CHANNEL_LABELS[1], self.right_display)

        painter.setPen(QtGui.QColor(DIM))
        painter.setFont(QtGui.QFont("Segoe UI", self.HELPER_FONT_SIZE, QtGui.QFont.Medium))
        helper_rect = QtCore.QRectF(rect.left(), right_rect.bottom() + self.HELPER_TOP_GAP, rect.width(), self.HELPER_HEIGHT)
        painter.drawText(helper_rect, QtCore.Qt.AlignLeft | QtCore.Qt.TextWordWrap, self.HELPER_TEXT)
        painter.end()

    def _draw_channel(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRectF,
        label: str,
        value: float,
    ) -> None:
        painter.setPen(QtGui.QPen(QtGui.QColor("#242424"), 1.1))
        painter.setBrush(QtGui.QColor("#030303"))
        painter.drawRoundedRect(rect, 8, 8)

        painter.setPen(QtGui.QColor(TEXT))
        painter.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.DemiBold))
        painter.drawText(rect.adjusted(14, 8, -14, -44), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, label)

        bar = QtCore.QRectF(rect.left() + 14, rect.top() + self.BAR_TOP_OFFSET, rect.width() - 28, 15)
        painter.setPen(QtGui.QPen(QtGui.QColor("#202020"), 1))
        painter.setBrush(QtGui.QColor("#090909"))
        painter.drawRoundedRect(bar, 7, 7)

        hot_zone = QtCore.QRectF(bar.left() + bar.width() * self._fraction_for_db(-10), bar.top(), bar.width() * self._fraction_for_db(0) - bar.width() * self._fraction_for_db(-10), bar.height())
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(77, 23, 16, 88))
        painter.drawRoundedRect(hot_zone, 7, 7)

        fill_w = bar.width() * self._fraction_for_level(value)
        if fill_w > 1.0:
            fill = QtCore.QRectF(bar.left(), bar.top(), fill_w, bar.height())
            grad = QtGui.QLinearGradient(fill.left(), fill.center().y(), fill.right(), fill.center().y())
            grad.setColorAt(0.0, QtGui.QColor("#4387ff"))
            grad.setColorAt(0.62, QtGui.QColor("#56d5f4"))
            grad.setColorAt(0.88, QtGui.QColor("#68d98f"))
            grad.setColorAt(1.0, QtGui.QColor("#ff746d"))
            painter.setBrush(grad)
            painter.drawRoundedRect(fill, 7, 7)

        painter.setPen(QtGui.QColor("#74808b"))
        painter.setFont(QtGui.QFont("Segoe UI", 7, QtGui.QFont.Bold))
        for db in self.SCALE_DB:
            x = bar.left() + bar.width() * self._fraction_for_db(db)
            painter.drawLine(QtCore.QPointF(x, bar.bottom() + 5), QtCore.QPointF(x, bar.bottom() + 11))
            painter.drawText(QtCore.QRectF(x - 17, bar.bottom() + self.TICK_LABEL_OFFSET, 34, 12), QtCore.Qt.AlignCenter, str(db))


class ChannelTile(QtWidgets.QWidget):
    def __init__(self, name: str, source_index: int) -> None:
        super().__init__()
        self.name = name
        self.source_index = source_index
        self.level = 0.0
        self.display_level = 0.0
        self.setMinimumSize(66, 50)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    def set_channel(self, name: str, source_index: int) -> None:
        self.name = name
        self.source_index = source_index
        self.level = 0.0
        self.display_level = 0.0
        self.update()

    def set_level(self, value: float) -> None:
        self.level = min(1.0, max(0.0, float(value)))
        attack = 0.48 if self.level > self.display_level else 0.16
        self.display_level += (self.level - self.display_level) * attack
        self.update()

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        width, height = self.width(), self.height()
        active = self.display_level > 0.01

        bg = "#050505" if active else "#020202"
        border = "#303030" if active else "#202020"
        painter.setPen(QtGui.QPen(QtGui.QColor(border), 1))
        painter.setBrush(QtGui.QColor(bg))
        painter.drawRoundedRect(1, 1, width - 2, height - 2, 6, 6)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(255, 255, 255, 12 if active else 5))
        painter.drawRoundedRect(2, 2, width - 4, max(18, int(height * 0.22)), 5, 5)

        dot = QtCore.QPointF(width - 13, 13)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(104, 217, 143, 190 if active else 42))
        painter.drawEllipse(dot, 2.4, 2.4)

        painter.setPen(QtGui.QColor("#f2f2f2" if active else "#d2d5dc"))
        painter.setFont(QtGui.QFont("Segoe UI", 11 if height > 76 else 9, QtGui.QFont.DemiBold))
        painter.drawText(0, 7, width, 18, QtCore.Qt.AlignCenter, self.name)

        meter_top = max(30, int(height * 0.50))
        bar = QtCore.QRectF(11, meter_top, width - 22, max(5, int(height * 0.08)))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#161616"))
        painter.drawRoundedRect(bar, 3, 3)
        if self.display_level > 0.002:
            fill = QtCore.QRectF(bar.left(), bar.top(), bar.width() * self.display_level, bar.height())
            grad = QtGui.QLinearGradient(fill.left(), fill.top(), fill.right(), fill.top())
            grad.setColorAt(0.0, QtGui.QColor("#effff3"))
            grad.setColorAt(1.0, QtGui.QColor("#68d98f"))
            painter.setBrush(grad)
            painter.drawRoundedRect(fill, 3, 3)

        painter.setPen(QtGui.QColor("#c8cfca" if active else "#737373"))
        painter.setFont(QtGui.QFont("Consolas", 8 if height > 78 else 7))
        db_text = f"{linear_to_db(self.level):.0f} dB" if self.level > 0.001 else "--"
        painter.drawText(0, int(bar.bottom()) + 7, width, 16, QtCore.Qt.AlignCenter, db_text)


class RawChannelTile(QtWidgets.QWidget):
    def __init__(self, name: str, source_index: int) -> None:
        super().__init__()
        self.name = name
        self.source_index = source_index
        self.peak = 0.0
        self.rms = 0.0
        self.display_peak = 0.0
        self.setMinimumSize(154, 38)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def set_levels(self, peak: float, rms: float) -> None:
        self.peak = min(1.0, max(0.0, float(peak)))
        self.rms = min(1.0, max(0.0, float(rms)))
        attack = 0.46 if self.peak > self.display_peak else 0.14
        self.display_peak += (self.peak - self.display_peak) * attack
        self.update()

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        width, height = self.width(), self.height()
        active = self.display_peak > 0.003

        painter.setPen(QtGui.QPen(QtGui.QColor("#344237" if active else "#202020"), 1))
        painter.setBrush(QtGui.QColor("#080808" if active else "#020202"))
        painter.drawRoundedRect(1, 1, width - 2, height - 2, 6, 6)

        painter.setPen(QtGui.QColor("#f2f2f2" if active else MID))
        painter.setFont(QtGui.QFont("Segoe UI", 8, QtGui.QFont.Bold))
        painter.drawText(8, 5, 58, 13, QtCore.Qt.AlignLeft, f"{self.source_index:02d} {self.name}")

        peak_text = f"P {linear_to_db(self.peak):.0f}" if self.peak > 0.0001 else "P --"
        rms_text = f"R {linear_to_db(self.rms):.0f}" if self.rms > 0.0001 else "R --"
        painter.setPen(QtGui.QColor(MID))
        painter.setFont(QtGui.QFont("Consolas", 7))
        painter.drawText(66, 5, width - 74, 13, QtCore.Qt.AlignRight, f"{peak_text}  {rms_text}")

        bar = QtCore.QRectF(8, height - 12, width - 16, 4)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#1a1a1a"))
        painter.drawRoundedRect(bar, 2, 2)
        if self.display_peak > 0.002:
            fill = QtCore.QRectF(bar.left(), bar.top(), bar.width() * self.display_peak, bar.height())
            grad = QtGui.QLinearGradient(fill.left(), fill.top(), fill.right(), fill.top())
            grad.setColorAt(0.0, QtGui.QColor("#ffffff"))
            grad.setColorAt(1.0, QtGui.QColor("#68d98f"))
            painter.setBrush(grad)
            painter.drawRoundedRect(fill, 2, 2)


class RoomVisualizer(QtWidgets.QWidget):
    ACTIVE_THRESHOLD = 0.01
    FIXED_HEIGHT = 360
    ROOM_ASPECT = 1.55
    IDLE_ANIMATION_INTERVAL_MS = 55
    AUDIO_SAFE_ANIMATION_INTERVAL_MS = 90
    DEFAULT_YAW = -0.58
    DEFAULT_PITCH = 0.23
    DEFAULT_ZOOM = 1.02
    MIN_PITCH = -0.18
    MAX_PITCH = 0.46
    MIN_ZOOM = 0.82
    MAX_ZOOM = 1.24

    def __init__(self) -> None:
        super().__init__()
        self.view_mode = "3d"
        self.channel_config = DEFAULT_CHANNEL_CONFIG
        self.levels = [0.0] * 16
        self.phase = 0.0
        self.camera_yaw = self.DEFAULT_YAW
        self.camera_pitch = self.DEFAULT_PITCH
        self.camera_zoom = self.DEFAULT_ZOOM
        self._target_yaw = self.camera_yaw
        self._target_pitch = self.camera_pitch
        self.current_speakers = self._speakers_for_config(self.channel_config)
        self._view_3d_rect = QtCore.QRectF()
        self._view_top_rect = QtCore.QRectF()
        self._content_rect = QtCore.QRectF()
        self._drag_pos: QtCore.QPoint | None = None
        self._drag_yaw = self.camera_yaw
        self._drag_pitch = self.camera_pitch
        self._orbit_cursor = self._make_orbit_cursor(active=False)
        self._orbit_drag_cursor = self._make_orbit_cursor(active=True)
        self.setFixedHeight(self.FIXED_HEIGHT)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setMouseTracking(True)

        self.animation_timer = QtCore.QTimer(self)
        self.animation_timer.timeout.connect(self._advance)
        self.animation_timer.start(self.IDLE_ANIMATION_INTERVAL_MS)

    def set_animation_interval(self, interval_ms: int) -> None:
        interval_ms = max(16, int(interval_ms))
        if self.animation_timer.interval() != interval_ms:
            self.animation_timer.setInterval(interval_ms)

    def _advance(self) -> None:
        self.phase = (self.phase + 0.026) % math.tau
        if self.view_mode == "3d":
            if self._drag_pos is not None:
                self._smooth_camera(0.34)
            self.update()

    @property
    def speaker_count(self) -> int:
        return len(self.current_speakers)

    @property
    def active_speaker_count(self) -> int:
        return sum(1 for index, *_ in self.current_speakers if self._speaker_level(index) > self.ACTIVE_THRESHOLD)

    def set_channel_config(self, config_id: str) -> None:
        self.channel_config = config_id if config_id in CHANNEL_LAYOUTS else DEFAULT_CHANNEL_CONFIG
        self.current_speakers = self._speakers_for_config(self.channel_config)
        self.update()

    def set_levels(self, levels: object) -> None:
        for index in range(16):
            self.levels[index] = float(levels[index]) if index < len(levels) else 0.0
        self.update()

    def mousePressEvent(self, event) -> None:
        if self._view_3d_rect.contains(event.pos()):
            self.view_mode = "3d"
            self.update()
            event.accept()
            return
        if self._view_top_rect.contains(event.pos()):
            self.view_mode = "top"
            self.update()
            event.accept()
            return
        if event.button() == QtCore.Qt.LeftButton and self.view_mode == "3d" and self._content_rect.contains(event.pos()):
            self._drag_pos = event.pos()
            self._drag_yaw = self._target_yaw
            self._drag_pitch = self._target_pitch
            self.setCursor(self._orbit_drag_cursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None:
            delta = event.pos() - self._drag_pos
            self._target_yaw = (self._drag_yaw + delta.x() * 0.0108) % math.tau
            self._target_pitch = max(self.MIN_PITCH, min(self.MAX_PITCH, self._drag_pitch + delta.y() * 0.0054))
            self._smooth_camera(0.62)
            self.update()
            event.accept()
            return
        if self.view_mode == "3d" and self._content_rect.contains(event.pos()):
            self.setCursor(self._orbit_cursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_pos is not None:
            self._drag_pos = None
            self._smooth_camera(0.82)
            self.setCursor(self._orbit_cursor if self.view_mode == "3d" else QtCore.Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        if self._drag_pos is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:
        if self.view_mode != "3d":
            super().wheelEvent(event)
            return
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.camera_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.camera_zoom + steps * 0.055))
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.view_mode == "3d" and self._content_rect.contains(event.pos()):
            self.camera_yaw = self.DEFAULT_YAW
            self.camera_pitch = self.DEFAULT_PITCH
            self.camera_zoom = self.DEFAULT_ZOOM
            self._target_yaw = self.camera_yaw
            self._target_pitch = self.camera_pitch
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    @staticmethod
    def _angle_delta(current: float, target: float) -> float:
        return (target - current + math.pi) % math.tau - math.pi

    def _smooth_camera(self, amount: float) -> None:
        yaw_delta = self._angle_delta(self.camera_yaw, self._target_yaw)
        self.camera_yaw = (self.camera_yaw + yaw_delta * amount) % math.tau
        self.camera_pitch += (self._target_pitch - self.camera_pitch) * amount
        self.camera_pitch = max(self.MIN_PITCH, min(self.MAX_PITCH, self.camera_pitch))
        self.camera_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.camera_zoom))

    @staticmethod
    def _make_orbit_cursor(active: bool) -> QtGui.QCursor:
        size = 22
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        center = QtCore.QPointF(size / 2, size / 2)
        pen_color = QtGui.QColor("#f2f2f2" if active else "#d7d7d7")
        halo = QtGui.QColor(255, 255, 255, 42 if active else 24)
        painter.setPen(QtGui.QPen(halo, 2.1))
        painter.drawEllipse(center, 7.2, 5.0)
        painter.setPen(QtGui.QPen(pen_color, 1.35))
        painter.drawArc(QtCore.QRectF(4.4, 6.0, 13.2, 10.0), 28 * 16, 248 * 16)
        painter.drawLine(QtCore.QPointF(16.4, 7.2), QtCore.QPointF(18.5, 4.9))
        painter.drawLine(QtCore.QPointF(16.4, 7.2), QtCore.QPointF(13.5, 6.0))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#ffffff" if active else "#dedede"))
        painter.drawEllipse(center, 2.1, 2.1)
        painter.end()
        return QtGui.QCursor(pixmap, size // 2, size // 2)

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)

        painter.setPen(QtGui.QPen(QtGui.QColor("#222222"), 1))
        painter.setBrush(QtGui.QColor("#030303"))
        painter.drawRoundedRect(QtCore.QRectF(rect), 7, 7)

        header_rect = QtCore.QRectF(rect.left() + 10, rect.top() + 7, rect.width() - 20, 24)
        painter.setPen(QtGui.QColor(DIM))
        painter.setFont(QtGui.QFont("Segoe UI", 7, QtGui.QFont.Bold))
        painter.drawText(header_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, "ROOM VISUALIZER")
        self._draw_view_toggle(painter, header_rect)

        self._content_rect = QtCore.QRectF(rect.left() + 10, rect.top() + 34, rect.width() - 20, rect.height() - 44)
        if self.view_mode == "top":
            self._draw_top_view(painter, self._content_rect)
        else:
            self._draw_3d_view(painter, self._content_rect)
        painter.end()

    def _room_viewport(self, rect: QtCore.QRectF, margin_x: float, margin_y: float) -> QtCore.QRectF:
        available = rect.adjusted(margin_x, margin_y, -margin_x, -margin_y)
        if available.width() <= 1 or available.height() <= 1:
            return available
        width = available.width()
        height = width / self.ROOM_ASPECT
        if height > available.height():
            height = available.height()
            width = height * self.ROOM_ASPECT
        left = available.center().x() - width / 2
        top = available.center().y() - height / 2
        return QtCore.QRectF(left, top, width, height)

    def _draw_view_toggle(self, painter: QtGui.QPainter, header_rect: QtCore.QRectF) -> None:
        button_w = 54
        button_h = 20
        gap = 5
        top = header_rect.top() + 1
        self._view_top_rect = QtCore.QRectF(header_rect.right() - button_w, top, button_w, button_h)
        self._view_3d_rect = QtCore.QRectF(self._view_top_rect.left() - button_w - gap, top, button_w, button_h)
        for mode, label, rect in (("3d", "3D View", self._view_3d_rect), ("top", "Top View", self._view_top_rect)):
            active = self.view_mode == mode
            painter.setPen(QtGui.QPen(QtGui.QColor(ACCENT if active else "#2f2f2f"), 1))
            painter.setBrush(QtGui.QColor("#151513" if active else "#050505"))
            painter.drawRoundedRect(rect, 6, 6)
            painter.setPen(QtGui.QColor(TEXT if active else MID))
            painter.setFont(QtGui.QFont("Segoe UI", 7, QtGui.QFont.Bold))
            painter.drawText(rect, QtCore.Qt.AlignCenter, label)

    def _draw_top_view(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        room = self._room_viewport(rect, 7, 5)
        painter.setPen(QtGui.QPen(QtGui.QColor("#1d1d1d"), 1))
        painter.setBrush(QtGui.QColor("#060606"))
        painter.drawRoundedRect(room, 5, 5)
        self._draw_orientation_labels(painter, room)

        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 22), 1))
        painter.drawLine(QtCore.QPointF(room.center().x(), room.top() + 8), QtCore.QPointF(room.center().x(), room.bottom() - 8))
        painter.drawLine(QtCore.QPointF(room.left() + 8, room.center().y()), QtCore.QPointF(room.right() - 8, room.center().y()))

        listener = QtCore.QRectF(room.center().x() - 7, room.center().y() - 5, 14, 10)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 38), 1))
        painter.setBrush(QtGui.QColor(255, 255, 255, 16))
        painter.drawRoundedRect(listener, 3, 3)

        for source_index, label, x, y, z in self.current_speakers:
            point = QtCore.QPointF(room.left() + x * room.width(), room.top() + y * room.height())
            self._draw_speaker_marker(painter, point, label, self._speaker_level(source_index), z > 0.5, top_view=True)

    def _draw_3d_view(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        room = self._room_viewport(rect, 14, 8)
        corners = {
            "fl": self._project_3d(room, 0.08, 0.08, 0.05),
            "fr": self._project_3d(room, 0.92, 0.08, 0.05),
            "br": self._project_3d(room, 0.92, 0.92, 0.05),
            "bl": self._project_3d(room, 0.08, 0.92, 0.05),
            "tfl": self._project_3d(room, 0.08, 0.08, 0.96),
            "tfr": self._project_3d(room, 0.92, 0.08, 0.96),
            "tbr": self._project_3d(room, 0.92, 0.92, 0.96),
            "tbl": self._project_3d(room, 0.08, 0.92, 0.96),
        }
        faces = (
            ("floor", ("fl", "fr", "br", "bl"), QtGui.QColor(255, 255, 255, 11)),
            ("left", ("fl", "bl", "tbl", "tfl"), QtGui.QColor(255, 255, 255, 8)),
            ("right", ("fr", "br", "tbr", "tfr"), QtGui.QColor(255, 255, 255, 7)),
            ("back", ("bl", "br", "tbr", "tbl"), QtGui.QColor(255, 255, 255, 10)),
        )
        painter.setPen(QtCore.Qt.NoPen)
        for _name, keys, color in faces:
            painter.setBrush(color)
            painter.drawPolygon(QtGui.QPolygonF([corners[key] for key in keys]))

        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 48), 1))
        for a, b in (
            ("fl", "fr"), ("fr", "br"), ("br", "bl"), ("bl", "fl"),
            ("tfl", "tfr"), ("tfr", "tbr"), ("tbr", "tbl"), ("tbl", "tfl"),
            ("fl", "tfl"), ("fr", "tfr"), ("br", "tbr"), ("bl", "tbl"),
        ):
            painter.drawLine(corners[a], corners[b])

        screen = QtGui.QPolygonF(
            [
                self._project_3d(room, 0.36, 0.09, 0.46),
                self._project_3d(room, 0.64, 0.09, 0.46),
                self._project_3d(room, 0.64, 0.09, 0.65),
                self._project_3d(room, 0.36, 0.09, 0.65),
            ]
        )
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(255, 255, 255, 42))
        painter.drawPolygon(screen)

        projected: list[tuple[float, int, str, QtCore.QPointF, QtCore.QPointF, bool]] = []
        for source_index, label, x, y, z in self.current_speakers:
            point = self._project_3d(room, x, y, z)
            base = self._project_3d(room, x, y, 0.18)
            projected.append((point.y(), source_index, label, point, base, z > 0.5))
        for _depth, source_index, label, point, base, elevated in sorted(projected, key=lambda item: item[0]):
            if elevated:
                painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 26), 1))
                painter.drawLine(base, point)
            self._draw_speaker_marker(painter, point, label, self._speaker_level(source_index), elevated, top_view=False)

    def _draw_orientation_labels(self, painter: QtGui.QPainter, room: QtCore.QRectF) -> None:
        painter.setPen(QtGui.QColor("#8ca3b8"))
        painter.setFont(QtGui.QFont("Segoe UI", 6, QtGui.QFont.Bold))
        painter.drawText(
            QtCore.QRectF(room.left() + 18, room.top() + 3, room.width() - 36, 12),
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
            "FRONT",
        )
        painter.drawText(
            QtCore.QRectF(room.left() + 18, room.bottom() - 15, room.width() - 36, 12),
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
            "REAR",
        )
        painter.save()
        painter.translate(room.left() + 12, room.center().y())
        painter.rotate(-90)
        painter.drawText(QtCore.QRectF(-36, -6, 72, 12), QtCore.Qt.AlignCenter, "LEFT")
        painter.restore()
        painter.save()
        painter.translate(room.right() - 12, room.center().y())
        painter.rotate(90)
        painter.drawText(QtCore.QRectF(-36, -6, 72, 12), QtCore.Qt.AlignCenter, "RIGHT")
        painter.restore()

    def _project_3d(self, rect: QtCore.QRectF, x: float, y: float, z: float) -> QtCore.QPointF:
        side = (x - 0.5) * 2.05
        depth = (y - 0.5) * 2.28
        height = (z - 0.28) * 1.22

        yaw_cos = math.cos(self.camera_yaw)
        yaw_sin = math.sin(self.camera_yaw)
        rx = side * yaw_cos - depth * yaw_sin
        rz = side * yaw_sin + depth * yaw_cos

        pitch = max(self.MIN_PITCH, min(self.MAX_PITCH, self.camera_pitch))
        floor_tilt = 0.26 + ((pitch - self.MIN_PITCH) / (self.MAX_PITCH - self.MIN_PITCH)) * 0.30
        height_scale = 0.82 - ((pitch - self.MIN_PITCH) / (self.MAX_PITCH - self.MIN_PITCH)) * 0.10
        scale = min(rect.width() * 0.35, rect.height() * 0.72) * max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.camera_zoom))
        return QtCore.QPointF(
            rect.center().x() + rx * scale,
            rect.center().y() + rz * scale * floor_tilt - height * scale * height_scale,
        )

    def _draw_speaker_marker(
        self,
        painter: QtGui.QPainter,
        point: QtCore.QPointF,
        label: str,
        level: float,
        elevated: bool,
        top_view: bool = False,
    ) -> None:
        active = level > self.ACTIVE_THRESHOLD
        if active:
            glow_alpha = min(150, 55 + int(level * 130))
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(104, 217, 143, glow_alpha // 3))
            painter.drawEllipse(point, 8.0, 8.0)
            painter.setBrush(QtGui.QColor(104, 217, 143, glow_alpha))
            painter.drawEllipse(point, 4.0, 4.0)
        else:
            painter.setPen(QtGui.QPen(QtGui.QColor("#6f7280"), 1.4))
            painter.setBrush(QtGui.QColor("#111111" if not elevated else "#171717"))
            painter.drawEllipse(point, 4.5, 4.5)

        label_y = point.y() + 7 if top_view or not elevated else point.y() - 18
        label_rect = QtCore.QRectF(point.x() - 24, label_y, 48, 13)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0, 95))
        painter.drawRoundedRect(label_rect.adjusted(2, 1, -2, -1), 3, 3)
        painter.setPen(QtGui.QColor("#edf2f7" if active else "#aeb4c0"))
        painter.setFont(QtGui.QFont("Segoe UI", 7, QtGui.QFont.Bold))
        painter.drawText(label_rect, QtCore.Qt.AlignCenter, label)

    def _speaker_level(self, source_index: int) -> float:
        return float(self.levels[source_index]) if 0 <= source_index < len(self.levels) else 0.0

    @staticmethod
    def _speakers_for_config(config_id: str) -> list[tuple[int, str, float, float, float]]:
        if config_id == "sharur_9_1_6":
            return [
                (0, "L", 0.34, 0.14, 0.22),
                (2, "C", 0.50, 0.10, 0.22),
                (1, "R", 0.66, 0.14, 0.22),
                (3, "LFE", 0.50, 0.23, 0.10),
                (4, "Lw", 0.20, 0.34, 0.22),
                (10, "Ltf", 0.36, 0.34, 0.92),
                (11, "Rtf", 0.64, 0.34, 0.92),
                (5, "Rw", 0.80, 0.34, 0.22),
                (8, "Ls", 0.10, 0.56, 0.24),
                (12, "Ltm", 0.36, 0.56, 0.92),
                (13, "Rtm", 0.64, 0.56, 0.92),
                (9, "Rs", 0.90, 0.56, 0.24),
                (14, "Ltr", 0.36, 0.76, 0.92),
                (15, "Rtr", 0.64, 0.76, 0.92),
                (6, "Lrs", 0.28, 0.87, 0.22),
                (7, "Rrs", 0.72, 0.87, 0.22),
            ]
        return [
            (0, "L", 0.28, 0.14, 0.22),
            (2, "C", 0.50, 0.10, 0.22),
            (1, "R", 0.72, 0.14, 0.22),
            (3, "LFE", 0.50, 0.24, 0.10),
            (6, "SL", 0.10, 0.56, 0.22),
            (7, "SR", 0.90, 0.56, 0.22),
            (4, "RL", 0.28, 0.86, 0.22),
            (5, "RR", 0.72, 0.86, 0.22),
        ]


class RawMonitorDialog(DotBackdropDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Raw 16ch Monitor")
        self.setWindowFlags(
            QtCore.Qt.Window
            | QtCore.Qt.WindowTitleHint
            | QtCore.Qt.WindowSystemMenuHint
            | QtCore.Qt.WindowMinimizeButtonHint
            | QtCore.Qt.WindowCloseButtonHint
        )
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setMinimumSize(760, 310)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(section_label("Raw 16ch Monitor"))

        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(7)
        self.tiles: list[RawChannelTile] = []
        names = tuple(CHANNEL_LAYOUTS["sharur_9_1_6"]["names"])
        for index, name in enumerate(names):
            tile = RawChannelTile(str(name), index)
            grid.addWidget(tile, index // 4, index % 4)
            self.tiles.append(tile)
        layout.addWidget(card(grid), 1)

    def set_levels(self, peaks: object, rms_values: object) -> None:
        for tile in self.tiles:
            peak = float(peaks[tile.source_index]) if tile.source_index < len(peaks) else 0.0
            rms = float(rms_values[tile.source_index]) if tile.source_index < len(rms_values) else 0.0
            tile.set_levels(peak, rms)


class RouteProbeWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(object, str)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, output_path: Path, device_id: int | None) -> None:
        super().__init__()
        self.output_path = output_path
        self.device_id = device_id

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            report = run_probe(20.0, 1e-4, self.device_id)
            self.output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            self.finished.emit(report, str(self.output_path))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


DETAIL_SECTIONS = (
    (
        "Session",
        (
            ("Render", "Starts or stops the live stereo render path."),
            ("Output keep-alive", "Keeps the selected output awake while rendering is stopped."),
            ("Smart Switching", "Follows matching saved profiles when the Windows output changes."),
            ("Auto-start on Boot", "Controls the Windows startup launcher."),
        ),
    ),
    (
        "Route And Profiles",
        (
            ("Input / Output", "Fixed multichannel capture into the selected stereo playback device."),
            ("Saved Profiles", "Stores route, gain, layout, PEQ, correction, and swap state."),
            ("Profile Control", "Creates, updates, renames, loads, and deletes saved profiles."),
        ),
    ),
    (
        "Gain And Field",
        (
            ("Preamp", "Sets renderer headroom before PEQ and output limiting."),
            ("7.1", "Uses the compact 7.1 monitor field."),
            ("9.1.6 Monitor", "Uses the full 16-channel monitor field."),
            ("Room View", "Switches between 3D and top-down channel views."),
        ),
    ),
    (
        "PEQ And Correction",
        (
            ("User PEQ", "Applies shared stereo PEQ before output swap and correction."),
            ("Speaker EQ", "Applies independent left/right correction after output swap."),
            ("L/R Swap", "Swaps physical stereo outputs while preserving correction assignment."),
            ("Signal Order", "Downmix, preamp, user PEQ, swap, speaker EQ, limiter, output."),
        ),
    ),
    (
        "Tools",
        (
            ("7.1 Upmix", "Enables the 7.1 fill stage."),
            ("9.1.6 Upmix", "Enables the height-field generation stage."),
            ("Raw Monitor", "Opens raw 16-channel peak/RMS monitoring."),
        ),
    ),
)


def build_details_body() -> QtWidgets.QWidget:
    body = QtWidgets.QWidget()
    body.setObjectName("rendererDetailsBody")
    body_layout = QtWidgets.QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 4, 0)
    body_layout.setSpacing(10)

    for title, rows in DETAIL_SECTIONS:
        section = QtWidgets.QVBoxLayout()
        section.setContentsMargins(12, 11, 12, 12)
        section.setSpacing(7)
        section.addWidget(section_label(title))

        for name, detail in rows:
            row_widget = QtWidgets.QWidget()
            row_widget.setObjectName("detailsRow")
            row_widget.setMinimumHeight(24)
            row_layout = QtWidgets.QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 1, 0, 1)
            row_layout.setSpacing(14)

            name_label = QtWidgets.QLabel(name)
            name_label.setObjectName("detailsName")
            name_label.setFixedWidth(158)
            name_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            name_label.setMinimumHeight(22)
            name_label.setStyleSheet(f"color:{TEXT}; font-weight:650; background-color: transparent; padding: 0px;")

            detail_label = QtWidgets.QLabel(detail)
            detail_label.setObjectName("detailsDescription")
            detail_label.setWordWrap(True)
            detail_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            detail_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
            detail_label.setMinimumHeight(22)
            detail_label.setStyleSheet(f"color:{MID}; font-size:11px; background-color: transparent; padding: 0px;")

            row_layout.addWidget(name_label, 0)
            row_layout.addWidget(detail_label, 1)
            section.addWidget(row_widget)

        body_layout.addWidget(card(section))

    body_layout.addStretch()
    return body


class RendererWindow(QtWidgets.QWidget):
    IDLE_ROOM_INTERVAL_MS = RoomVisualizer.IDLE_ANIMATION_INTERVAL_MS
    AUDIO_SAFE_ROOM_INTERVAL_MS = RoomVisualizer.AUDIO_SAFE_ANIMATION_INTERVAL_MS

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("rendererRoot")
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setMinimumSize(1120, 925)
        self.resize(1212, self.minimumHeight())
        self.setStyleSheet(BASE_STYLE)
        self._set_icon()
        self.setMouseTracking(True)
        self._closing_with_animation = False
        self._shown_with_animation = False
        self._fade_animation: QtCore.QPropertyAnimation | None = None
        self._backdrop_phase = 0.0
        self.setWindowOpacity(0.0)

        self.engine = AudioEngine()
        self.settings = load_settings()
        self._settings_need_audio_recovery = (
            int(self.settings.get("baseline_recovery_version", 0) or 0) < BASELINE_RECOVERY_VERSION
        )
        self.surround_fill_enabled = self._audio_recovery_bool("surround_fill_enabled", False)
        self.upmix_9_1_6_enabled = self._audio_recovery_bool("upmix_9_1_6_enabled", False)
        self.channel_sanity_enabled = False
        self.sound_enhancer_enabled = self._audio_recovery_bool("sound_enhancer_enabled", False)
        self.audio_stability = DEFAULT_STREAM_PROFILE
        self.keep_output_awake_enabled = bool(self.settings.get("keep_output_awake", False))
        self.sample_rate_mode = normalize_sample_rate_mode(self.settings.get("sample_rate_mode", DEFAULT_SAMPLE_RATE_MODE))
        self.engine.processor.set_surround_fill_enabled(self.surround_fill_enabled)
        self.engine.processor.set_upmix_9_1_6_enabled(self.upmix_9_1_6_enabled)
        self.engine.processor.set_channel_sanity_enabled(False)
        self.engine.processor.set_sound_enhancer_enabled(self.sound_enhancer_enabled)
        self.engine.processor.set_user_volume(1.0)
        self.all_devices = list_devices()
        self.devices = [dev for dev in self.all_devices if dev.hostapi == WASAPI_HOSTAPI]
        self.device_by_id = {dev.id: dev for dev in self.devices}
        self._device_signature = self._make_device_signature(self.all_devices)
        self.presets = load_presets(self.settings, self.devices)
        self._recover_loaded_presets()
        saved_active = str(self.settings.get("active_preset_id") or "")
        self.active_preset_id = saved_active if any(preset.id == saved_active for preset in self.presets) else ""
        self.channel_config = str(self.settings.get("channel_config") or DEFAULT_CHANNEL_CONFIG)
        if self.channel_config not in CHANNEL_LAYOUTS:
            self.channel_config = DEFAULT_CHANNEL_CONFIG
        self.engine.processor.set_monitor_layout(self.channel_config)
        self._restoring = False
        self._last_default_output_id: int | None = None
        self._manual_override_default_id: int | None = None
        self._force_auto_start = bool(
            self.settings.get(
                "resume_on_launch",
                self.settings.get("was_running", False),
            )
        )
        self._app_root = Path(__file__).resolve().parents[1]
        self._device_poll_count = 0
        self.raw_monitor_dialog: RawMonitorDialog | None = None
        self._probe_thread: QtCore.QThread | None = None
        self._probe_worker: RouteProbeWorker | None = None
        self._probe_restore_running = False
        self._last_callback_status_count = 0
        self._silent_input_started_at: float | None = None
        self._last_audio_recovery_at = -RECOVERY_COOLDOWN_SECONDS
        self._peq_generation = 0
        self._last_peq_report = PeqParseReport()
        self._peq_apply_timer = QtCore.QTimer(self)
        self._peq_apply_timer.setSingleShot(True)
        self._peq_apply_timer.setInterval(260)
        self._peq_apply_timer.timeout.connect(lambda: self._apply_peq_routing_state(persist=True))

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content = QtWidgets.QWidget()
        content.setObjectName("content")
        shell = QtWidgets.QVBoxLayout(content)
        shell.setContentsMargins(14, 8, 14, 14)
        shell.setSpacing(0)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.addTab(self._build_main_tab(), "Renderer")
        self.tabs.addTab(self._build_presets_tab(), "Presets")
        self.tabs.tabBar().setFixedHeight(56)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.setCornerWidget(self._build_header_controls(), QtCore.Qt.TopRightCorner)
        shell.addWidget(self.tabs, 1)
        root.addWidget(content)

        self._apply_launch_preset()
        self._sync_input_device_presentation()
        self._wire_events()
        self._sync_keep_output_awake()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(40)

        self.device_timer = QtCore.QTimer(self)
        self.device_timer.timeout.connect(self.poll_devices)
        self.device_timer.start(1500)

        self.backdrop_timer = QtCore.QTimer(self)
        self.backdrop_timer.timeout.connect(self._advance_backdrop)
        self.backdrop_timer.start(70)

        QtCore.QTimer.singleShot(300, self._auto_start_if_needed)

    def _sync_visual_performance(self, rendering: bool) -> None:
        rendering = bool(rendering)
        room_interval = self.AUDIO_SAFE_ROOM_INTERVAL_MS if rendering else self.IDLE_ROOM_INTERVAL_MS
        if hasattr(self, "room_visualizer"):
            self.room_visualizer.set_animation_interval(room_interval)

    def _advance_backdrop(self) -> None:
        if not self.isVisible() or self.isMinimized():
            return
        self._backdrop_phase = (self._backdrop_phase + 0.022) % math.tau
        page = self.findChild(QtWidgets.QWidget, "mainPage")
        if page is not None and page.isVisible():
            page.update()
            page_rect = QtCore.QRect(page.mapTo(self, QtCore.QPoint(0, 0)), page.size())
            exposed_region = QtGui.QRegion(self.rect()) - QtGui.QRegion(page_rect)
            if not exposed_region.isEmpty():
                self.update(exposed_region)
            return
        self.update()

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        paint_region = QtGui.QRegion(event.rect().intersected(self.rect()))
        page = self.findChild(QtWidgets.QWidget, "mainPage")
        if page is not None and page.isVisible():
            page_rect = QtCore.QRect(page.mapTo(self, QtCore.QPoint(0, 0)), page.size())
            paint_region -= QtGui.QRegion(page_rect)

        cursor = self.mapFromGlobal(QtGui.QCursor.pos())
        for paint_bounds in paint_region.rects():
            paint_spatial_backdrop(
                painter,
                self.rect(),
                self._backdrop_phase,
                cursor=cursor,
                lower_balance=True,
                paint_bounds=paint_bounds,
            )
        painter.end()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_windows_dark_titlebar()
        if self._shown_with_animation:
            return
        self._shown_with_animation = True
        self._animate_opacity(0.0, 1.0, 180, QtCore.QEasingCurve.OutCubic)

    def closeEvent(self, event) -> None:
        if not self._closing_with_animation:
            event.ignore()
            self._closing_with_animation = True
            self._persist_state(was_running=self.engine.snapshot().running)
            self._close_raw_monitor_dialog()
            self.engine.close()
            self._animate_opacity(self.windowOpacity(), 0.0, 130, QtCore.QEasingCurve.InCubic, self.close)
            return
        super().closeEvent(event)

    def _animate_opacity(
        self,
        start: float,
        end: float,
        duration_ms: int,
        easing: QtCore.QEasingCurve.Type,
        finished: object | None = None,
    ) -> None:
        animation = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(duration_ms)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(easing)
        if finished is not None:
            animation.finished.connect(finished)
        self._fade_animation = animation
        animation.start()

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    @staticmethod
    def _logo_asset_path() -> Path:
        return Path(__file__).resolve().parents[1] / "assets" / "downmix_renderer_logo.png"

    @staticmethod
    def _icon_asset_path() -> Path:
        root = Path(__file__).resolve().parents[1]
        icon_path = root / "assets" / "downmix_renderer_logo.ico"
        return icon_path if icon_path.exists() else root / "assets" / "downmix_renderer_logo.png"

    def _set_icon(self) -> None:
        icon_path = self._icon_asset_path()
        if icon_path.exists():
            self.setWindowIcon(QtGui.QIcon(str(icon_path)))

    def _apply_windows_dark_titlebar(self) -> None:
        apply_windows_dark_titlebar(self)

    def _audio_recovery_bool(self, key: str, default: bool) -> bool:
        if self._settings_need_audio_recovery:
            return default
        return bool(self.settings.get(key, default))

    def _audio_recovery_profile(self) -> str:
        if self._settings_need_audio_recovery:
            return DEFAULT_STREAM_PROFILE
        return self._normalize_audio_stability(str(self.settings.get("audio_stability") or DEFAULT_STREAM_PROFILE))

    def _recover_loaded_presets(self) -> None:
        for preset in self.presets:
            if self._settings_need_audio_recovery:
                preset.surround_fill_enabled = False
                preset.upmix_9_1_6_enabled = False
            preset.channel_sanity_enabled = False
            preset.sound_enhancer_enabled = bool(getattr(preset, "sound_enhancer_enabled", False))
            preset.user_volume = 1.0
            preset.audio_stability = DEFAULT_STREAM_PROFILE

    def _build_header_controls(self) -> QtWidgets.QWidget:
        header = QtWidgets.QWidget()
        header.setObjectName("headerControls")
        header.setFixedHeight(56)
        header.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        layout = QtWidgets.QHBoxLayout(header)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(8)
        layout.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.header_status = QtWidgets.QLabel("Shared WASAPI | Ready")
        self.header_status.setObjectName("heroStatus")
        self.header_status.setAlignment(QtCore.Qt.AlignCenter)
        self.header_status.setFixedHeight(32)
        self.header_status.setMinimumWidth(212)
        self.header_status.setMaximumWidth(252)
        self.header_status.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.header_status)

        self.info_button = InfoButton()
        layout.addWidget(self.info_button)
        self.github_button = HeaderIconButton("github", "Open project on GitHub")
        layout.addWidget(self.github_button)
        return header

    def _logo_pixmap(self, width: int, height: int) -> QtGui.QPixmap:
        pixmap = QtGui.QPixmap(width, height)
        pixmap.fill(QtCore.Qt.transparent)
        logo = QtGui.QPixmap(str(self._logo_asset_path()))
        if logo.isNull():
            return pixmap
        scaled = logo.scaled(width, height, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        painter = QtGui.QPainter(pixmap)
        painter.drawPixmap((width - scaled.width()) // 2, (height - scaled.height()) // 2, scaled)
        painter.end()
        return pixmap

    def _build_main_tab(self) -> QtWidgets.QWidget:
        tab = SpatialPage()
        tab.setObjectName("mainPage")
        grid = QtWidgets.QGridLayout(tab)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        route_card = self._build_route_card()
        route_card.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(self._build_transport_card(), 0)
        volume_card = self._build_volume_card()
        volume_card.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        left.addWidget(volume_card, 0)
        left.addWidget(self._build_keep_awake_card(), 0)
        meter_card = self._build_meter_card()
        meter_card.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        left.addWidget(meter_card, 0)

        center = QtWidgets.QVBoxLayout()
        center.setSpacing(10)
        center.addWidget(self._build_channels_card(), 1)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._build_diagnostics_card(), 1)

        left_column = QtWidgets.QWidget()
        left_column.setObjectName("rendererLeftColumn")
        left_column.setLayout(left)
        left_column.setMinimumWidth(292)
        left_column.setMaximumWidth(348)
        left_column.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        center_column = QtWidgets.QWidget()
        center_column.setObjectName("rendererCenterColumn")
        center_column.setLayout(center)
        center_column.setMinimumWidth(390)
        center_column.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        right_column = QtWidgets.QWidget()
        right_column.setObjectName("rendererRightColumn")
        right_column.setLayout(right)
        right_column.setMinimumWidth(328)
        right_column.setMaximumWidth(420)
        right_column.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        grid.addWidget(route_card, 0, 0, 1, 3)
        grid.addWidget(left_column, 1, 0)
        grid.addWidget(center_column, 1, 1)
        grid.addWidget(right_column, 1, 2)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setRowStretch(0, 0)
        grid.setRowStretch(1, 1)
        return tab

    def _build_presets_tab(self) -> QtWidgets.QWidget:
        tab = SpatialPage()
        tab.setObjectName("presetsPage")
        root = QtWidgets.QVBoxLayout(tab)
        root.setContentsMargins(8, 2, 8, 8)
        root.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        scroll.viewport().setObjectName("transparentViewport")
        scroll.viewport().setAttribute(QtCore.Qt.WA_TranslucentBackground)

        body = QtWidgets.QWidget()
        body.setObjectName("presetsBody")
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 4, 6)
        layout.setSpacing(8)

        profile_manager = self._build_profile_manager_card()
        profile_manager.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        peq_card = self._build_peq_routing_card()
        self.peq_routing_card = peq_card
        peq_card.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        layout.setAlignment(QtCore.Qt.AlignTop)
        layout.addWidget(profile_manager)
        layout.addSpacing(2)
        layout.addWidget(peq_card, 1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self._rebuild_preset_buttons()
        return tab

    def _build_profile_manager_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        profile_column = QtWidgets.QVBoxLayout()
        profile_column.setSpacing(7)
        profile_column.addWidget(section_label("Saved Profiles"))

        preset_scroller = QtWidgets.QScrollArea()
        preset_scroller.setObjectName("profileListScroll")
        preset_scroller.setWidgetResizable(True)
        preset_scroller.setFrameShape(QtWidgets.QFrame.NoFrame)
        preset_scroller.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        preset_scroller.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        preset_scroller.viewport().setObjectName("transparentViewport")
        preset_scroller.viewport().setAttribute(QtCore.Qt.WA_TranslucentBackground)
        preset_scroller.setMinimumHeight(78)
        preset_scroller.setMaximumHeight(86)
        preset_scroller.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        preset_container = QtWidgets.QWidget()
        preset_container.setObjectName("presetListContainer")
        self.preset_grid_columns = 3
        self.preset_buttons_layout = QtWidgets.QGridLayout(preset_container)
        self.preset_buttons_layout.setContentsMargins(0, 0, 4, 0)
        self.preset_buttons_layout.setHorizontalSpacing(7)
        self.preset_buttons_layout.setVerticalSpacing(7)
        preset_scroller.setWidget(preset_container)
        profile_column.addWidget(preset_scroller)
        layout.addLayout(profile_column, 5)

        control_column = QtWidgets.QVBoxLayout()
        control_column.setSpacing(7)
        control_column.addWidget(section_label("Profile Control"))

        self.preset_name_edit = QtWidgets.QLineEdit()
        self.preset_name_edit.setObjectName("profileNameInput")
        self.preset_name_edit.setPlaceholderText("Profile name")
        self.preset_name_edit.setMinimumHeight(36)
        control_column.addWidget(self.preset_name_edit)

        actions_widget = QtWidgets.QWidget()
        actions_widget.setObjectName("profileActions")
        actions = QtWidgets.QHBoxLayout(actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(7)
        self.new_preset_button = QtWidgets.QPushButton("New")
        self.save_preset_button = QtWidgets.QPushButton("Update")
        self.delete_preset_button = QtWidgets.QPushButton("Delete")
        for button in (self.new_preset_button, self.save_preset_button, self.delete_preset_button):
            button.setObjectName("profileAction")
            button.setMinimumHeight(34)
            button.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
            actions.addWidget(button)
        control_column.addWidget(actions_widget)
        control_column.addStretch(1)
        layout.addLayout(control_column, 3)

        frame = QtWidgets.QFrame()
        frame.setObjectName("profileManagerCard")
        frame.setProperty("presetSurface", True)
        frame.setLayout(layout)
        frame.setMinimumHeight(126)
        frame.setMaximumHeight(146)
        return frame

    def _build_peq_routing_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(section_label("Output Routing And PEQ"))

        route_row = QtWidgets.QHBoxLayout()
        route_row.setSpacing(10)

        swap_layout = QtWidgets.QVBoxLayout()
        swap_layout.setContentsMargins(10, 8, 10, 8)
        swap_layout.setSpacing(5)
        swap_layout.addWidget(section_label("Left / Right Channel Swap"))
        self.lr_swap_checkbox = SwitchCheckBox("Swap physical L/R outputs")
        self.lr_swap_checkbox.setChecked(bool(self.settings.get("lr_swap_enabled", False)))
        self.lr_swap_checkbox.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        swap_layout.addWidget(self.lr_swap_checkbox)
        swap_helper = QtWidgets.QLabel(
            "Swaps the final physical stereo outputs. Speaker correction mapping follows the active channel assignment."
        )
        swap_helper.setObjectName("peqHelper")
        swap_helper.setWordWrap(True)
        swap_layout.addWidget(swap_helper)
        self.lr_swap_panel = self._peq_panel(swap_layout)
        self.lr_swap_panel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        route_row.addWidget(self.lr_swap_panel, 1)

        self.channel_trim_panel = self._build_trim_panel()
        self.channel_trim_panel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        for panel in (self.lr_swap_panel, self.channel_trim_panel):
            panel.setFixedHeight(103)
        route_row.addWidget(self.channel_trim_panel, 1)
        layout.addLayout(route_row)

        self.speaker_mapping_panel = self._build_speaker_mapping_panel()
        self.speaker_mapping_panel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.speaker_mapping_panel)

        eq_row = QtWidgets.QHBoxLayout()
        eq_row.setSpacing(10)
        global_peq_panel = self._build_peq_editor_panel("User / Global PEQ", "global")
        speaker_eq_panel = self._build_peq_editor_panel("Speaker EQ / L-R Correction", "speaker")
        for panel in (global_peq_panel, speaker_eq_panel):
            panel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        eq_row.addWidget(global_peq_panel, 1)
        eq_row.addWidget(speaker_eq_panel, 1)
        layout.addLayout(eq_row)

        footer = QtWidgets.QLabel(
            "DSP Order: Matrix/Downmix -> Master Preamp -> User/Global PEQ -> L/R Swap -> "
            "Speaker EQ/L-R Correction -> Channel Trim -> Sound Enhancer -> Limiter/Output."
        )
        footer.setObjectName("peqHelper")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        return card(layout, preset_surface=True)

    def _build_speaker_mapping_panel(self) -> QtWidgets.QFrame:
        mapping_layout = QtWidgets.QVBoxLayout()
        mapping_layout.setContentsMargins(10, 8, 10, 8)
        mapping_layout.setSpacing(5)
        mapping_layout.addWidget(section_label("Speaker EQ Channel Mapping"))
        mapping_helper = QtWidgets.QLabel(
            "Speaker EQ is applied after L/R swap. Swap off maps CH:0 to left and CH:1 to right; "
            "swap on maps CH:1 to left and CH:0 to right."
        )
        mapping_helper.setObjectName("peqHelper")
        mapping_helper.setWordWrap(True)
        mapping_layout.addWidget(mapping_helper)
        return self._peq_panel(mapping_layout)

    def _build_trim_panel(self) -> QtWidgets.QFrame:
        panel_layout = QtWidgets.QVBoxLayout()
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(6)
        panel_layout.addWidget(section_label("Channel Trim"))

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(14)
        self.trim_left_edit = TrimLineEdit(self.settings.get("trim_left_db", 0.0))
        self.trim_right_edit = TrimLineEdit(self.settings.get("trim_right_db", 0.0))
        for label_text, editor in (("TRIM L", self.trim_left_edit), ("TRIM R", self.trim_right_edit)):
            group = QtWidgets.QWidget()
            group.setObjectName("routeColumn")
            group_layout = QtWidgets.QHBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(6)
            label = QtWidgets.QLabel(label_text)
            label.setObjectName("section")
            label.setFixedWidth(46)
            label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            suffix = QtWidgets.QLabel("dB")
            suffix.setObjectName("peqHelper")
            suffix.setFixedWidth(22)
            suffix.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            editor.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            group_layout.addWidget(label)
            group_layout.addWidget(editor, 1)
            group_layout.addWidget(suffix)
            controls.addWidget(group, 1)
        panel_layout.addLayout(controls)
        trim_helper = QtWidgets.QLabel(
            "Quick fine-tuning for output level L/R imbalance. If Speaker EQ or L/R Correction is enabled, "
            "do not use the channel trim setting."
        )
        trim_helper.setObjectName("peqHelper")
        trim_helper.setWordWrap(True)
        panel_layout.addWidget(trim_helper)
        panel_layout.addStretch(1)
        return self._peq_panel(panel_layout)

    def _build_peq_editor_panel(self, title: str, kind: str) -> QtWidgets.QFrame:
        panel_layout = QtWidgets.QVBoxLayout()
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(6)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(section_label(title), 1)
        enabled = SwitchCheckBox("Enable")
        enabled.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        header.addWidget(enabled, 0)
        visibility_button = QtWidgets.QPushButton("Hide")
        visibility_button.setObjectName("peqAction")
        visibility_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        header.addWidget(visibility_button, 0)
        panel_layout.addLayout(header)

        body = QtWidgets.QWidget()
        body.setObjectName("globalPeqBody" if kind == "global" else "speakerPeqBody")
        body_layout = QtWidgets.QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)

        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(8)
        load_button = QtWidgets.QPushButton("Load Text")
        clear_button = QtWidgets.QPushButton("Clear")
        for button in (load_button, clear_button):
            button.setObjectName("peqAction")
            button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        actions.addWidget(load_button)
        actions.addWidget(clear_button)
        actions.addStretch(1)
        body_layout.addLayout(actions)

        editor = QtWidgets.QPlainTextEdit()
        editor.setObjectName("peqText")
        editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        editor.setMinimumHeight(82)
        editor.setPlaceholderText(
            "Paste PEQ text here."
            if kind == "global"
            else "Paste stereo correction text here. CH:0 and CH:1 are mapped per swap state."
        )
        body_layout.addWidget(editor, 1)
        panel_layout.addWidget(body, 1)

        status = QtWidgets.QLabel("Bypassed")
        status.setObjectName("peqStatus")
        status.setWordWrap(True)
        panel_layout.addWidget(status)

        if kind == "global":
            self.global_peq_checkbox = enabled
            self.global_peq_load_button = load_button
            self.global_peq_clear_button = clear_button
            self.global_peq_text = editor
            self.global_peq_status_label = status
            self.global_peq_visibility_button = visibility_button
            self.global_peq_body = body
        else:
            self.speaker_eq_checkbox = enabled
            self.speaker_eq_load_button = load_button
            self.speaker_eq_clear_button = clear_button
            self.speaker_eq_text = editor
            self.speaker_eq_status_label = status
            self.speaker_eq_visibility_button = visibility_button
            self.speaker_peq_body = body
        return self._peq_panel(panel_layout)

    @staticmethod
    def _peq_panel(layout: QtWidgets.QLayout) -> QtWidgets.QFrame:
        panel = QtWidgets.QFrame()
        panel.setObjectName("peqPanel")
        panel.setLayout(layout)
        return panel

    def _build_presets_card(self, full: bool = False) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(section_label("Saved Profiles"))

        preset_scroller = QtWidgets.QScrollArea()
        preset_scroller.setWidgetResizable(True)
        preset_scroller.setFrameShape(QtWidgets.QFrame.NoFrame)
        preset_scroller.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        preset_scroller.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        preset_scroller.setMinimumHeight(220 if full else 92)
        if not full:
            preset_scroller.setMaximumHeight(188)
            preset_scroller.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        else:
            preset_scroller.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        preset_container = QtWidgets.QWidget()
        self.preset_buttons_layout = QtWidgets.QVBoxLayout(preset_container)
        self.preset_buttons_layout.setContentsMargins(0, 0, 4, 0)
        self.preset_buttons_layout.setSpacing(6)
        preset_scroller.setWidget(preset_container)
        layout.addWidget(preset_scroller)

        self.preset_name_edit = QtWidgets.QLineEdit()
        self.preset_name_edit.setPlaceholderText("Profile name")
        layout.addWidget(self.preset_name_edit)

        actions = QtWidgets.QHBoxLayout()
        self.new_preset_button = QtWidgets.QPushButton("New")
        self.save_preset_button = QtWidgets.QPushButton("Update")
        self.delete_preset_button = QtWidgets.QPushButton("Delete")
        for button in (self.new_preset_button, self.save_preset_button, self.delete_preset_button):
            button.setObjectName("ghost")
        actions.addWidget(self.new_preset_button)
        actions.addWidget(self.save_preset_button)
        actions.addWidget(self.delete_preset_button)
        layout.addLayout(actions)
        self._rebuild_preset_buttons()
        return card(layout, preset_surface=True)

    def _build_route_card(self) -> QtWidgets.QFrame:
        device_box_height = 44
        sample_rate_value_width = 100
        sample_rate_segment_width = sample_rate_value_width + 118
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.input_combo = QtWidgets.QComboBox()
        self.input_combo.setObjectName("fixedInputSelector")
        self.output_combo = RouteGlassCombo()
        self.sample_rate_combo = RouteGlassCombo()
        for mode in SAMPLE_RATE_MODES:
            self.sample_rate_combo.addItem(SAMPLE_RATE_LABELS[mode], mode)
        self._set_combo_data(self.sample_rate_combo, self.sample_rate_mode)
        for combo in (self.input_combo, self.output_combo, self.sample_rate_combo):
            combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(10)
            combo.setFixedHeight(device_box_height)
            combo.setMinimumHeight(device_box_height)
            combo.setMaximumHeight(device_box_height)
            combo.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.sample_rate_combo.setFixedWidth(sample_rate_value_width)
        self.sample_rate_combo.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        for dev in renderer_input_devices(self.devices):
            self.input_combo.addItem(self._short_device_label(dev, "input"), dev.id)
        for dev in renderer_output_devices(self.devices):
            self.output_combo.addItem(self._short_device_label(dev, "output"), dev.id)

        self.input_fixed_label = RouteValueLabel("No WASAPI input device")
        self.input_fixed_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.input_fixed_label.setMinimumWidth(0)
        self.input_fixed_label.setFixedHeight(device_box_height)
        self.input_fixed_label.setMinimumHeight(device_box_height)
        self.input_fixed_label.setMaximumHeight(device_box_height)
        self.input_fixed_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.input_combo.hide()
        self._sync_input_device_presentation()

        input_label = QtWidgets.QLabel("Input device")
        input_label.setObjectName("routeEyebrow")

        output_label = QtWidgets.QLabel("Output device")
        output_label.setObjectName("routeEyebrow")
        sample_rate_label = QtWidgets.QLabel("Sample rate")
        sample_rate_label.setObjectName("routeEyebrow")
        self.refresh_devices_button = RouteRefreshButton()
        self.refresh_devices_button.setFixedWidth(48)
        self.refresh_devices_button.setFixedHeight(device_box_height)
        self.refresh_devices_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        def route_segment(
            label: QtWidgets.QLabel,
            control: QtWidgets.QWidget,
            minimum_width: int = 0,
            fixed_width: bool = False,
            label_width: int = 88,
        ) -> QtWidgets.QFrame:
            segment = QtWidgets.QFrame()
            segment.setObjectName("routeSegment")
            horizontal_policy = QtWidgets.QSizePolicy.Fixed if fixed_width else QtWidgets.QSizePolicy.Ignored
            segment.setSizePolicy(horizontal_policy, QtWidgets.QSizePolicy.Fixed)
            segment.setFixedHeight(device_box_height)
            if minimum_width:
                segment.setMinimumWidth(minimum_width)
                if fixed_width:
                    segment.setFixedWidth(minimum_width)
                    control.setMinimumWidth(0)
                else:
                    control.setMinimumWidth(minimum_width)
            segment_layout = QtWidgets.QHBoxLayout(segment)
            segment_layout.setContentsMargins(12, 0, 10, 0)
            segment_layout.setSpacing(8)
            label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            label.setFixedWidth(label_width)
            label.setFixedHeight(device_box_height)
            label.setFont(QtGui.QFont("Segoe UI", 8, QtGui.QFont.DemiBold))
            control.setSizePolicy(horizontal_policy, QtWidgets.QSizePolicy.Fixed)
            segment_layout.addWidget(label, 0)
            segment_layout.addWidget(control, 1)
            return segment

        layout.addWidget(route_segment(input_label, self.input_fixed_label), 1)
        layout.addWidget(route_segment(output_label, self.output_combo), 1)
        layout.addWidget(
            route_segment(
                sample_rate_label,
                self.sample_rate_combo,
                sample_rate_segment_width,
                fixed_width=True,
                label_width=88,
            ),
            0,
        )
        layout.addWidget(self.refresh_devices_button, 0)

        frame = QtWidgets.QFrame()
        frame.setObjectName("routeLane")
        frame.setLayout(layout)
        return frame

    def _build_volume_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(12, 11, 12, 12)
        layout.setSpacing(9)
        layout.addWidget(section_label("Gain / Monitor"))

        self.preamp_value = value_label()
        self.preamp_slider = self._slider(-20, 0)
        self.preamp_slider.setObjectName("preampSlider")
        self.preamp_slider.setMinimumHeight(26)
        self.preamp_value.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.preamp_value.setMinimumWidth(40)

        slider_grid = QtWidgets.QGridLayout()
        slider_grid.setHorizontalSpacing(10)
        slider_grid.setVerticalSpacing(5)
        slider_grid.addWidget(QtWidgets.QLabel("Preamp"), 0, 0)
        slider_grid.addWidget(self.preamp_slider, 0, 1)
        slider_grid.addWidget(self.preamp_value, 0, 2)
        slider_grid.setColumnStretch(1, 1)
        layout.addLayout(slider_grid)
        layout.addSpacing(4)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(8)
        self.mode_buttons: dict[str, QtWidgets.QPushButton] = {}
        for config_id, config in CHANNEL_LAYOUTS.items():
            button = QtWidgets.QPushButton(str(config["label"]))
            button.setObjectName("mode")
            button.setProperty("active", config_id == self.channel_config)
            button.setMinimumHeight(36)
            button.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
            button.clicked.connect(lambda checked=False, cid=config_id: self.set_channel_config(cid))
            self.mode_buttons[config_id] = button
            mode_row.addWidget(button)
        layout.addLayout(mode_row)
        layout.addSpacing(2)

        self.surround_fill_checkbox = SwitchCheckBox("7.1 Upmix")
        self.surround_fill_checkbox.setChecked(self.surround_fill_enabled)

        self.upmix916_checkbox = SwitchCheckBox("9.1.6 Upmix")
        self.upmix916_checkbox.setChecked(self.upmix_9_1_6_enabled)

        self.sound_enhancer_checkbox = SwitchCheckBox("Sound Enhancer")
        self.sound_enhancer_checkbox.setChecked(self.sound_enhancer_enabled)
        self.sound_enhancer_checkbox.setToolTip("Boost laptop-speaker loudness with protected limiting")

        for checkbox in (self.surround_fill_checkbox, self.upmix916_checkbox, self.sound_enhancer_checkbox):
            checkbox.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)

        toggle_grid = QtWidgets.QGridLayout()
        toggle_grid.setHorizontalSpacing(12)
        toggle_grid.setVerticalSpacing(11)
        toggle_grid.addWidget(self.surround_fill_checkbox, 0, 0)
        toggle_grid.addWidget(self.upmix916_checkbox, 0, 1)
        toggle_grid.addWidget(self.sound_enhancer_checkbox, 1, 0, 1, 2)
        layout.addLayout(toggle_grid)
        return card(layout)

    def _build_transport_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(12, 11, 12, 12)
        layout.setSpacing(9)
        layout.addWidget(section_label("Session"))

        self.render_toggle_button = SessionRenderToggle()
        self._set_status("Standby", "neutral")
        layout.addWidget(self.render_toggle_button)

        self.smart_switch_checkbox = SwitchCheckBox("Smart Switching")
        self.smart_switch_checkbox.setChecked(bool(self.settings.get("smart_switch_enabled", True)))
        self.system_boot_checkbox = SwitchCheckBox("Auto-start on Boot")
        self.system_boot_checkbox.setChecked(
            bool(self.settings.get("system_boot_autostart", False) or is_system_autostart_enabled(self._app_root))
        )
        for checkbox in (self.smart_switch_checkbox, self.system_boot_checkbox):
            checkbox.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)

        toggle_grid = QtWidgets.QGridLayout()
        toggle_grid.setHorizontalSpacing(10)
        toggle_grid.setVerticalSpacing(7)
        toggle_grid.addWidget(self.smart_switch_checkbox, 0, 0)
        toggle_grid.addWidget(self.system_boot_checkbox, 1, 0)
        layout.addLayout(toggle_grid)
        return card(layout)

    def _build_keep_awake_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(2)

        self.keep_awake_checkbox = SwitchCheckBox("Keep output awake")
        self.keep_awake_checkbox.setChecked(self.keep_output_awake_enabled)
        self.keep_awake_checkbox.setMinimumHeight(28)
        self.keep_awake_checkbox.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.keep_awake_checkbox)

        helper = QtWidgets.QLabel("Silent stream to selected output")
        helper.setObjectName("keepAwakeHelper")
        helper.setWordWrap(True)
        helper.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        helper_shell = QtWidgets.QWidget()
        helper_shell.setObjectName("keepAwakeHelperShell")
        helper_shell.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        helper_layout = QtWidgets.QVBoxLayout(helper_shell)
        helper_layout.setContentsMargins(0, 0, 0, 0)
        helper_layout.setSpacing(0)
        helper_layout.addWidget(helper)
        layout.addWidget(helper_shell)
        frame = card(layout)
        frame.setObjectName("keepAwakeCard")
        frame.setMinimumHeight(76)
        frame.setMaximumHeight(82)
        frame.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        return frame

    def _build_channels_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(7)
        self.channel_section = section_label("Channel Field")
        layout.addWidget(self.channel_section)

        self.room_visualizer = RoomVisualizer()
        self.room_visualizer.set_channel_config(self.channel_config)
        layout.addWidget(self.room_visualizer, 0)

        self.channel_tiles_panel = QtWidgets.QWidget()
        self.channel_tiles_panel.setObjectName("channelTilesPanel")
        self.channel_tiles_panel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.channel_grid = QtWidgets.QGridLayout()
        self.channel_grid.setContentsMargins(0, 0, 0, 0)
        self.channel_grid.setSpacing(5)
        self.channel_tiles_panel.setLayout(self.channel_grid)
        self.tiles: list[ChannelTile] = []
        layout.addWidget(self.channel_tiles_panel, 0)
        self._rebuild_channel_tiles()
        return card(layout)

    def _build_meter_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)
        layout.addWidget(section_label("Stereo sum output meter"))
        self.stereo_sum_meter = StereoSumMeter()
        self.stereo_sum_meter.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.stereo_sum_meter, 0)
        frame = card(layout)
        frame.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        return frame

    def _build_diagnostics_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QGridLayout()
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(7)
        layout.addWidget(section_label("Diagnostics"), 0, 0, 1, 2)

        self.diag_labels: dict[str, QtWidgets.QLabel] = {}
        keys = ("Preset", "Route", "Channels", "Layout", "Stream", "Limiter", "Enhancer", "Upmix", "Active", "Output")
        for row, key in enumerate(keys, start=1):
            name = QtWidgets.QLabel(key)
            name.setStyleSheet(f"color:{DIM}; background-color:#000000; padding:7px 0px;")
            value = value_label()
            value.setStyleSheet(
                f"color:{TEXT}; font-family:Consolas, monospace; font-size:11px; "
                "background-color:#000000; padding:7px 0px;"
            )
            value.setWordWrap(True)
            value.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
            self.diag_labels[key] = value
            layout.addWidget(name, row, 0)
            layout.addWidget(value, row, 1)

        tools = QtWidgets.QHBoxLayout()
        tools.setSpacing(8)
        self.raw_monitor_button = QtWidgets.QPushButton("Raw Monitor")
        for button in (self.raw_monitor_button,):
            button.setObjectName("rawMonitor")
            button.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        tools.addWidget(self.raw_monitor_button)
        layout.addLayout(tools, len(keys) + 1, 0, 1, 2)
        return card(layout)

    def _wire_events(self) -> None:
        self.info_button.clicked.connect(self.show_feature_help)
        self.github_button.clicked.connect(self.open_github)
        self.render_toggle_button.clicked.connect(self._toggle_render_session)
        self.new_preset_button.clicked.connect(self.create_preset)
        self.save_preset_button.clicked.connect(self.save_active_preset)
        self.delete_preset_button.clicked.connect(self.delete_active_preset)
        self.raw_monitor_button.clicked.connect(self.open_raw_monitor)
        self.refresh_devices_button.clicked.connect(self.refresh_devices)
        self.surround_fill_checkbox.toggled.connect(self.update_surround_fill)
        self.upmix916_checkbox.toggled.connect(self.update_upmix_9_1_6)
        self.sound_enhancer_checkbox.toggled.connect(self.update_sound_enhancer)
        self.keep_awake_checkbox.toggled.connect(self.update_keep_output_awake)
        self.system_boot_checkbox.toggled.connect(self.set_system_boot_autostart)
        self.smart_switch_checkbox.toggled.connect(lambda checked: self._persist_state(was_running=self.engine.snapshot().running))
        self.preamp_slider.valueChanged.connect(self.update_preamp)
        self.sample_rate_combo.currentIndexChanged.connect(self.update_sample_rate_mode)
        self.output_combo.currentIndexChanged.connect(self._manual_route_changed)
        self.lr_swap_checkbox.toggled.connect(self._schedule_peq_apply)
        self.global_peq_checkbox.toggled.connect(self._schedule_peq_apply)
        self.speaker_eq_checkbox.toggled.connect(self._schedule_peq_apply)
        self.global_peq_text.textChanged.connect(self._schedule_peq_apply)
        self.speaker_eq_text.textChanged.connect(self._schedule_peq_apply)
        self.trim_left_edit.valueChanged.connect(lambda value: self.update_channel_trim())
        self.trim_right_edit.valueChanged.connect(lambda value: self.update_channel_trim())
        self.global_peq_load_button.clicked.connect(lambda: self._load_peq_text(self.global_peq_text))
        self.speaker_eq_load_button.clicked.connect(lambda: self._load_peq_text(self.speaker_eq_text))
        self.global_peq_clear_button.clicked.connect(self.global_peq_text.clear)
        self.speaker_eq_clear_button.clicked.connect(self.speaker_eq_text.clear)
        self.global_peq_visibility_button.clicked.connect(lambda: self._toggle_peq_editor_visibility("global"))
        self.speaker_eq_visibility_button.clicked.connect(lambda: self._toggle_peq_editor_visibility("speaker"))

    def show_feature_help(self) -> None:
        dialog = DotBackdropDialog(self)
        dialog.setWindowTitle("Renderer Details")
        dialog.setMinimumSize(760, 620)
        dialog.resize(800, 660)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        heading = QtWidgets.QLabel("Renderer Details")
        heading.setObjectName("title")
        layout.addWidget(heading)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        body = build_details_body()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec_()

    def open_github(self) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(GITHUB_URL))

    def _slider(self, minimum: int, maximum: int) -> QtWidgets.QSlider:
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setMinimum(minimum)
        slider.setMaximum(maximum)
        slider.setMinimumHeight(26)
        slider.setSingleStep(1)
        slider.setPageStep(10 if maximum > 100 else 1)
        return slider

    @staticmethod
    def _slider_to_volume(value: int) -> float:
        return min(1.0, max(0.0, value / USER_VOLUME_SLIDER_MAX))

    @staticmethod
    def _volume_to_slider(value: float) -> int:
        return int(round(min(1.0, max(0.0, float(value))) * USER_VOLUME_SLIDER_MAX))

    def _label_value_row(self, label: str, value: QtWidgets.QLabel) -> QtWidgets.QLayout:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        row.addStretch()
        row.addWidget(value)
        return row

    def _short_device_label(self, device: AudioDevice, mode: str) -> str:
        if mode == "input":
            channels = device.max_input_channels
            if "vb-audio" in device.name.casefold() or "cable output" in device.name.casefold():
                return "CABLE Input"
            return f"{device.name} ({channels}ch in)"
        return device.name

    def _rebuild_preset_buttons(self) -> None:
        while self.preset_buttons_layout.count():
            item = self.preset_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        columns = max(1, int(getattr(self, "preset_grid_columns", 1)))
        for index, preset in enumerate(self.presets):
            button = QtWidgets.QPushButton(preset.name)
            button.setObjectName("preset")
            button.setProperty("active", preset.id == self.active_preset_id)
            button.setFixedHeight(34)
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            button.clicked.connect(lambda checked=False, pid=preset.id: self.apply_preset(pid, start_after=True, manual=True))
            if isinstance(self.preset_buttons_layout, QtWidgets.QGridLayout):
                self.preset_buttons_layout.addWidget(button, index // columns, index % columns)
            else:
                self.preset_buttons_layout.addWidget(button)
        if not self.presets:
            empty = QtWidgets.QLabel("No presets saved")
            empty.setStyleSheet(f"color:{DIM}; padding: 6px 2px;")
            if isinstance(self.preset_buttons_layout, QtWidgets.QGridLayout):
                self.preset_buttons_layout.addWidget(empty, 0, 0, 1, columns)
            else:
                self.preset_buttons_layout.addWidget(empty)

    def _current_peq_fields(self) -> dict[str, object]:
        return {
            "lr_swap_enabled": bool(self.lr_swap_checkbox.isChecked()) if hasattr(self, "lr_swap_checkbox") else False,
            "global_peq_enabled": bool(self.global_peq_checkbox.isChecked()) if hasattr(self, "global_peq_checkbox") else False,
            "global_peq_text": self.global_peq_text.toPlainText() if hasattr(self, "global_peq_text") else "",
            "speaker_eq_enabled": bool(self.speaker_eq_checkbox.isChecked()) if hasattr(self, "speaker_eq_checkbox") else False,
            "speaker_eq_text": self.speaker_eq_text.toPlainText() if hasattr(self, "speaker_eq_text") else "",
            "trim_left_db": self.trim_left_edit.value_db() if hasattr(self, "trim_left_edit") else 0.0,
            "trim_right_db": self.trim_right_edit.value_db() if hasattr(self, "trim_right_edit") else 0.0,
        }

    def _set_peq_controls_from_values(
        self,
        *,
        lr_swap_enabled: bool = False,
        global_peq_enabled: bool = False,
        global_peq_text: str = "",
        speaker_eq_enabled: bool = False,
        speaker_eq_text: str = "",
        trim_left_db: float = 0.0,
        trim_right_db: float = 0.0,
    ) -> None:
        if not all(
            hasattr(self, name)
            for name in (
                "lr_swap_checkbox",
                "global_peq_checkbox",
                "speaker_eq_checkbox",
                "global_peq_text",
                "speaker_eq_text",
            )
        ):
            return
        blockers = [
            QtCore.QSignalBlocker(self.lr_swap_checkbox),
            QtCore.QSignalBlocker(self.global_peq_checkbox),
            QtCore.QSignalBlocker(self.speaker_eq_checkbox),
            QtCore.QSignalBlocker(self.global_peq_text),
            QtCore.QSignalBlocker(self.speaker_eq_text),
        ]
        self.lr_swap_checkbox.setChecked(bool(lr_swap_enabled))
        self.global_peq_checkbox.setChecked(bool(global_peq_enabled))
        self.speaker_eq_checkbox.setChecked(bool(speaker_eq_enabled))
        self.global_peq_text.setPlainText(str(global_peq_text or ""))
        self.speaker_eq_text.setPlainText(str(speaker_eq_text or ""))
        del blockers
        self._set_trim_controls_from_values(trim_left_db=trim_left_db, trim_right_db=trim_right_db)

    def _set_trim_controls_from_values(self, *, trim_left_db: float = 0.0, trim_right_db: float = 0.0) -> None:
        if not all(hasattr(self, name) for name in ("trim_left_edit", "trim_right_edit")):
            return
        blockers = [
            QtCore.QSignalBlocker(self.trim_left_edit),
            QtCore.QSignalBlocker(self.trim_right_edit),
        ]
        self.trim_left_edit.set_value_db(trim_left_db)
        self.trim_right_edit.set_value_db(trim_right_db)
        del blockers
        self._apply_trim_state(persist=False)

    def _set_peq_controls_from_settings(self) -> None:
        self._set_peq_controls_from_values(
            lr_swap_enabled=bool(self.settings.get("lr_swap_enabled", False)),
            global_peq_enabled=bool(self.settings.get("global_peq_enabled", False)),
            global_peq_text=str(self.settings.get("global_peq_text") or ""),
            speaker_eq_enabled=bool(self.settings.get("speaker_eq_enabled", False)),
            speaker_eq_text=str(self.settings.get("speaker_eq_text") or ""),
            trim_left_db=clamp_trim_db(self.settings.get("trim_left_db", 0.0)),
            trim_right_db=clamp_trim_db(self.settings.get("trim_right_db", 0.0)),
        )

    def _apply_trim_state(self, persist: bool) -> None:
        if not all(hasattr(self, name) for name in ("trim_left_edit", "trim_right_edit")):
            return
        left = self.trim_left_edit.value_db()
        right = self.trim_right_edit.value_db()
        self.engine.processor.set_channel_trim_db(left, right)
        if persist and not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def update_channel_trim(self) -> None:
        self._apply_trim_state(persist=True)

    def _schedule_peq_apply(self, *args: object) -> None:
        if self._restoring:
            return
        self._peq_apply_timer.start(260)

    def _apply_peq_routing_state(self, persist: bool) -> None:
        if not all(hasattr(self, name) for name in ("global_peq_text", "speaker_eq_text", "lr_swap_checkbox")):
            return
        fields = self._current_peq_fields()
        self._peq_generation += 1
        config, report = build_runtime_config(
            global_text=str(fields["global_peq_text"]),
            global_enabled=bool(fields["global_peq_enabled"]),
            speaker_text=str(fields["speaker_eq_text"]),
            speaker_enabled=bool(fields["speaker_eq_enabled"]),
            lr_swap_enabled=bool(fields["lr_swap_enabled"]),
            sample_rate=float(self._resolved_sample_rate_for_current_route()),
            generation=self._peq_generation,
        )
        self._last_peq_report = report
        self.engine.processor.set_peq_config(config)
        self._update_peq_status_labels(config, report)
        if persist and not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def _update_peq_status_labels(self, config, report: PeqParseReport) -> None:
        if not hasattr(self, "global_peq_status_label"):
            return
        warning_suffix = ""
        state = "neutral"
        if report.warnings:
            warning_suffix = f" | {len(report.warnings)} warning(s): {report.warnings[0]}"
            state = "warning"

        global_status = "Bypassed"
        if config.global_cascade.active:
            global_status = f"Active: {report.global_filter_count} filter(s)"
            if report.global_filter_count == 0:
                global_status = "Active: preamp only"
        elif config.global_cascade.enabled:
            global_status = "Enabled: no valid filters"

        speaker_status = "Bypassed"
        if config.speaker_enabled:
            if config.speaker_left.active or config.speaker_right.active:
                speaker_status = (
                    f"Active: left {report.speaker_left_filter_count}, "
                    f"right {report.speaker_right_filter_count} filter(s)"
                )
            else:
                speaker_status = "Enabled: no valid filters"
            if config.lr_swap_enabled:
                speaker_status += " | swap mapping on"
        elif config.lr_swap_enabled:
            speaker_status = "Speaker EQ bypassed | L/R swap on"

        self.global_peq_status_label.setText(global_status + warning_suffix)
        self.speaker_eq_status_label.setText(speaker_status + warning_suffix)
        for label in (self.global_peq_status_label, self.speaker_eq_status_label):
            label.setProperty("status", state)
            label.style().unpolish(label)
            label.style().polish(label)

    def _load_peq_text(self, editor: QtWidgets.QPlainTextEdit) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load PEQ Text",
            "",
            "PEQ text files (*.txt *.peq *.cfg);;All files (*.*)",
        )
        if not path:
            return
        source = Path(path)
        last_error: Exception | None = None
        for encoding in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                editor.setPlainText(source.read_text(encoding=encoding))
                return
            except UnicodeError as exc:
                last_error = exc
        try:
            editor.setPlainText(source.read_text(errors="replace"))
        except Exception as exc:
            detail = last_error or exc
            self._set_status(f"PEQ load failed: {detail}", "error")

    def _toggle_peq_editor_visibility(self, kind: str) -> None:
        if kind == "global":
            body = getattr(self, "global_peq_body", None)
            button = getattr(self, "global_peq_visibility_button", None)
        else:
            body = getattr(self, "speaker_peq_body", None)
            button = getattr(self, "speaker_eq_visibility_button", None)
        if body is None or button is None:
            return
        next_visible = not body.isVisible()
        body.setVisible(next_visible)
        button.setText("Hide" if next_visible else "Show")

    def _apply_launch_preset(self) -> None:
        active = self._preset_by_id(self.active_preset_id)
        if active is not None:
            self.apply_preset(active.id, start_after=False, manual=False)
            return

        active_output = default_wasapi_output(self.all_devices)
        matched = match_preset_for_output(self.presets, active_output, self.devices)
        saved_output = find_saved_device(self.devices, self.settings.get("output_device"), "output")
        saved_match = match_preset_for_output(self.presets, saved_output, self.devices)
        preset = matched or saved_match or self._first_available_preset()
        if preset:
            self.apply_preset(preset.id, start_after=False, manual=False)
        else:
            self._restore_fallback_state()

    def _restore_fallback_state(self) -> None:
        self._restoring = True
        input_pick = find_saved_device(self.devices, self.settings.get("input_device"), "input") or preferred_input(self.devices)
        output_pick = find_saved_device(self.devices, self.settings.get("output_device"), "output") or preferred_output(self.devices)
        self._set_combo_device(self.input_combo, input_pick)
        self._sync_input_device_presentation()
        self._set_combo_device(self.output_combo, output_pick)
        self.preamp_slider.setValue(int(self.settings.get("preamp_db", DEFAULT_PREAMP_DB)))
        self.surround_fill_checkbox.setChecked(self._audio_recovery_bool("surround_fill_enabled", False))
        self.upmix916_checkbox.setChecked(self._audio_recovery_bool("upmix_9_1_6_enabled", False))
        self.sound_enhancer_checkbox.setChecked(self._audio_recovery_bool("sound_enhancer_enabled", False))
        self.keep_awake_checkbox.setChecked(bool(self.settings.get("keep_output_awake", False)))
        self._set_sample_rate_selection(self.settings.get("sample_rate_mode", DEFAULT_SAMPLE_RATE_MODE))
        self.update_preamp(int(self.preamp_slider.value()))
        self.engine.processor.set_user_volume(1.0)
        self.update_surround_fill(self.surround_fill_checkbox.isChecked())
        self.update_upmix_9_1_6(self.upmix916_checkbox.isChecked())
        self.update_channel_sanity(False)
        self.update_sound_enhancer(self.sound_enhancer_checkbox.isChecked())
        self.audio_stability = DEFAULT_STREAM_PROFILE
        self._set_peq_controls_from_settings()
        self._apply_peq_routing_state(persist=False)
        self._restoring = False
        self._persist_state(was_running=bool(self.settings.get("was_running", False)))

    def apply_preset(self, preset_id: str, start_after: bool, manual: bool = False) -> None:
        preset = self._preset_by_id(preset_id)
        if preset is None:
            return
        if manual:
            active_output = default_wasapi_output(self.all_devices)
            self._manual_override_default_id = active_output.id if active_output else self._last_default_output_id
        was_running = self.engine.snapshot().running
        input_pick, output_pick, missing_devices = self._resolve_preset_route(preset)
        self._restoring = True
        self.active_preset_id = preset.id
        self._set_combo_device(self.input_combo, input_pick)
        self._sync_input_device_presentation()
        self._set_combo_device(self.output_combo, output_pick)
        self.preamp_slider.setValue(int(preset.preamp_db))
        self.surround_fill_checkbox.setChecked(bool(preset.surround_fill_enabled))
        self.upmix916_checkbox.setChecked(bool(preset.upmix_9_1_6_enabled))
        self.sound_enhancer_checkbox.setChecked(bool(preset.sound_enhancer_enabled))
        self._set_sample_rate_selection(preset.sample_rate_mode)
        self.update_preamp(int(self.preamp_slider.value()))
        self.engine.processor.set_user_volume(1.0)
        self.update_surround_fill(self.surround_fill_checkbox.isChecked())
        self.update_upmix_9_1_6(self.upmix916_checkbox.isChecked())
        self.update_channel_sanity(False)
        self.update_sound_enhancer(self.sound_enhancer_checkbox.isChecked())
        self.audio_stability = DEFAULT_STREAM_PROFILE
        self.set_channel_config(preset.channel_config, persist=False)
        self._set_peq_controls_from_values(
            lr_swap_enabled=preset.lr_swap_enabled,
            global_peq_enabled=preset.global_peq_enabled,
            global_peq_text=preset.global_peq_text,
            speaker_eq_enabled=preset.speaker_eq_enabled,
            speaker_eq_text=preset.speaker_eq_text,
            trim_left_db=preset.trim_left_db,
            trim_right_db=preset.trim_right_db,
        )
        self._apply_peq_routing_state(persist=False)
        self._apply_trim_state(persist=False)
        self._restoring = False
        self._rebuild_preset_buttons()
        self._sync_keep_output_awake()

        if missing_devices:
            if was_running:
                self.engine.stop()
            self._set_status(f"Preset missing: {', '.join(missing_devices)}", "warning")
            self._persist_state(was_running=False)
            return

        self._persist_state(was_running=was_running)
        if start_after or was_running:
            self.start_audio()

    def create_preset(self) -> None:
        name = self.preset_name_edit.text().strip()
        if not name:
            name = f"Preset {len(self.presets) + 1}"
        preset = preset_from_current(
            name=name,
            input_device=self._selected_device(self.input_combo),
            output_device=self._selected_device(self.output_combo),
            preamp_db=int(self.preamp_slider.value()),
            user_volume=1.0,
            channel_config=self.channel_config,
            surround_fill_enabled=self.surround_fill_checkbox.isChecked(),
            upmix_9_1_6_enabled=self.upmix916_checkbox.isChecked(),
            channel_sanity_enabled=False,
            sound_enhancer_enabled=self.sound_enhancer_checkbox.isChecked(),
            audio_stability=DEFAULT_STREAM_PROFILE,
            sample_rate_mode=self._selected_sample_rate_mode(),
            **self._current_peq_fields(),
        )
        self.presets.append(preset)
        self.active_preset_id = preset.id
        self.preset_name_edit.clear()
        self._rebuild_preset_buttons()
        self._persist_state(was_running=self.engine.snapshot().running)

    def save_active_preset(self) -> None:
        preset = self._preset_by_id(self.active_preset_id)
        if preset is None:
            self.create_preset()
            return
        new_name = self.preset_name_edit.text().strip()
        if new_name:
            preset.name = new_name
        update_preset_from_current(
            preset,
            input_device=self._selected_device(self.input_combo),
            output_device=self._selected_device(self.output_combo),
            preamp_db=int(self.preamp_slider.value()),
            user_volume=1.0,
            channel_config=self.channel_config,
            surround_fill_enabled=self.surround_fill_checkbox.isChecked(),
            upmix_9_1_6_enabled=self.upmix916_checkbox.isChecked(),
            channel_sanity_enabled=False,
            sound_enhancer_enabled=self.sound_enhancer_checkbox.isChecked(),
            audio_stability=DEFAULT_STREAM_PROFILE,
            sample_rate_mode=self._selected_sample_rate_mode(),
            **self._current_peq_fields(),
        )
        if new_name:
            self.preset_name_edit.clear()
        self._rebuild_preset_buttons()
        self._persist_state(was_running=self.engine.snapshot().running)

    def delete_active_preset(self) -> None:
        preset = self._preset_by_id(self.active_preset_id)
        if preset is None:
            return
        was_running = self.engine.snapshot().running
        self.presets = [item for item in self.presets if item.id != preset.id]
        next_preset = self._smart_switch_preset(default_wasapi_output(self.all_devices)) or self._first_available_preset()
        if next_preset:
            self.apply_preset(next_preset.id, start_after=was_running, manual=False)
        else:
            self.active_preset_id = ""
            self._rebuild_preset_buttons()
            self._restore_fallback_state()

    def set_system_boot_autostart(self, enabled: bool) -> None:
        ok, detail = set_system_autostart(enabled, Path(__file__).resolve().parents[1])
        if not ok:
            self.system_boot_checkbox.blockSignals(True)
            self.system_boot_checkbox.setChecked(is_system_autostart_enabled(self._app_root))
            self.system_boot_checkbox.blockSignals(False)
            self._set_status(f"Boot autostart: {detail}", "warning")
        self._persist_state(was_running=self.engine.snapshot().running)

    def set_channel_config(self, config_id: str, persist: bool = True) -> None:
        if config_id not in CHANNEL_LAYOUTS:
            config_id = DEFAULT_CHANNEL_CONFIG
        self.channel_config = config_id
        self.engine.processor.set_monitor_layout(self.channel_config)
        for button_id, button in self.mode_buttons.items():
            button.setProperty("active", button_id == config_id)
            button.style().unpolish(button)
            button.style().polish(button)
        self._rebuild_channel_tiles()
        if hasattr(self, "room_visualizer"):
            self.room_visualizer.set_channel_config(self.channel_config)
        if persist and not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def _rebuild_channel_tiles(self) -> None:
        if not hasattr(self, "channel_grid"):
            return
        while self.channel_grid.count():
            item = self.channel_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.tiles = []
        layout = CHANNEL_LAYOUTS[self.channel_config]
        names = tuple(layout["names"])
        indices = tuple(layout["indices"])
        columns = 4
        rows = max(1, (len(names) + columns - 1) // columns)
        for column in range(columns):
            self.channel_grid.setColumnStretch(column, 1)
        for row in range(4):
            self.channel_grid.setRowStretch(row, 0)
        for row in range(rows):
            self.channel_grid.setRowStretch(row, 1)
        for index, (name, source_index) in enumerate(zip(names, indices)):
            tile = ChannelTile(str(name), int(source_index))
            self.channel_grid.addWidget(tile, index // columns, index % columns)
            self.tiles.append(tile)

    def _auto_start_if_needed(self) -> None:
        if self._force_auto_start:
            self.start_audio()

    def refresh_devices(self) -> None:
        was_running = self.engine.snapshot().running
        try:
            fresh_all = list_devices(force_refresh=True)
        except Exception as exc:
            self._set_status(f"Device refresh failed: {exc}", "warning")
            return

        signature = self._make_device_signature(fresh_all)
        route_changed = self._refresh_device_lists(fresh_all, signature)
        if route_changed:
            self._recover_after_device_refresh(was_running)
        self._set_status("Devices refreshed", "running" if self.engine.snapshot().running else "neutral")

    def poll_devices(self) -> None:
        self._device_poll_count += 1
        force_refresh = (
            self._device_poll_count % DEVICE_FORCE_REFRESH_INTERVAL == 0
            and self._can_force_device_refresh()
        )
        was_running = self.engine.snapshot().running
        route_changed = False
        try:
            fresh_all = list_devices(force_refresh=force_refresh)
        except Exception:
            return

        signature = self._make_device_signature(fresh_all)
        if signature != self._device_signature:
            route_changed = self._refresh_device_lists(fresh_all, signature)

        active_output = default_wasapi_output(fresh_all)
        active_id = active_output.id if active_output else None
        if self._last_default_output_id is None:
            self._last_default_output_id = active_id
        if active_id != self._last_default_output_id:
            self._last_default_output_id = active_id
            self._manual_override_default_id = None

        if self._preset_by_id(self.active_preset_id) is not None:
            self._guard_missing_active_route()
            if route_changed:
                self._recover_after_device_refresh(was_running)
            return

        if not getattr(self, "smart_switch_checkbox", None) or not self.smart_switch_checkbox.isChecked():
            if route_changed:
                self._recover_after_device_refresh(was_running)
            return
        if active_id is not None and active_id == self._manual_override_default_id:
            if route_changed:
                self._recover_after_device_refresh(was_running)
            return
        preset = self._smart_switch_preset(active_output)
        if preset is None:
            self._guard_missing_active_route()
            if route_changed:
                self._recover_after_device_refresh(was_running)
            return
        if preset.id == self.active_preset_id:
            if route_changed:
                self._recover_after_device_refresh(was_running)
            return
        self.apply_preset(preset.id, start_after=self.engine.snapshot().running or self._force_auto_start, manual=False)

    def _can_force_device_refresh(self) -> bool:
        if self._probe_thread is not None and self._probe_thread.isRunning():
            return False
        snapshot = self.engine.snapshot()
        return not snapshot.running or self.engine.uses_native_backend

    def _refresh_device_lists(self, fresh_all: list[AudioDevice], signature: tuple[tuple[object, ...], ...]) -> bool:
        current_input = self._selected_device(self.input_combo)
        current_output = self._selected_device(self.output_combo)
        input_identity = current_input.identity("input") if current_input else self.settings.get("input_device")
        output_identity = current_output.identity("output") if current_output else self.settings.get("output_device")
        before_route = (self._route_device_signature(current_input), self._route_device_signature(current_output))

        self.all_devices = fresh_all
        self.devices = [dev for dev in fresh_all if dev.hostapi == WASAPI_HOSTAPI]
        self.device_by_id = {dev.id: dev for dev in self.devices}
        self._device_signature = signature

        self._restoring = True
        self._rebuild_device_combo(self.input_combo, renderer_input_devices(self.devices), "input")
        self._rebuild_device_combo(self.output_combo, renderer_output_devices(self.devices), "output")

        active_preset = self._preset_by_id(self.active_preset_id)
        if active_preset is not None:
            input_pick, output_pick, _ = self._resolve_preset_route(active_preset)
        else:
            input_pick = find_saved_device(self.devices, input_identity, "input") or preferred_input(self.devices)
            output_pick = find_saved_device(self.devices, output_identity, "output") or preferred_output(self.devices)

        self._set_combo_device(self.input_combo, input_pick)
        self._sync_input_device_presentation()
        self._set_combo_device(self.output_combo, output_pick)
        self._restoring = False
        self._sync_keep_output_awake()
        after_route = (self._route_device_signature(input_pick), self._route_device_signature(output_pick))
        return before_route != after_route

    def _rebuild_device_combo(self, combo: QtWidgets.QComboBox, devices: list[AudioDevice], mode: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        for dev in devices:
            combo.addItem(self._short_device_label(dev, mode), dev.id)
        combo.setCurrentIndex(-1)
        combo.blockSignals(False)

    def _sync_input_device_presentation(self) -> None:
        if not hasattr(self, "input_fixed_label"):
            return
        text = self.input_combo.currentText().strip()
        if not text and self.input_combo.count():
            text = self.input_combo.itemText(0)
        self.input_fixed_label.setText(text or "No WASAPI input device")
        self._sync_route_control_geometry()

    def _sync_route_control_geometry(self) -> None:
        if not all(hasattr(self, name) for name in ("input_fixed_label", "input_combo", "output_combo")):
            return
        device_box_height = 44
        widgets = [self.input_fixed_label, self.input_combo, self.output_combo]
        if hasattr(self, "sample_rate_combo"):
            widgets.append(self.sample_rate_combo)
        if hasattr(self, "refresh_devices_button"):
            widgets.append(self.refresh_devices_button)
        for widget in widgets:
            widget.setMinimumHeight(device_box_height)
            widget.setMaximumHeight(device_box_height)

    @staticmethod
    def _make_device_signature(devices: list[AudioDevice]) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (
                dev.id,
                dev.name,
                dev.hostapi,
                dev.max_input_channels,
                dev.max_output_channels,
                dev.default_samplerate,
                dev.native_endpoint_id,
                dev.native_ambiguous,
            )
            for dev in devices
        )

    def _set_combo_device(self, combo: QtWidgets.QComboBox, device: AudioDevice | None) -> bool:
        if device is None:
            combo.setCurrentIndex(-1)
            return False
        for row in range(combo.count()):
            if combo.itemData(row) == device.id:
                combo.setCurrentIndex(row)
                return True
        combo.setCurrentIndex(-1)
        return False

    @staticmethod
    def _set_combo_data(combo: QtWidgets.QComboBox, value: object) -> bool:
        for row in range(combo.count()):
            if combo.itemData(row) == value:
                combo.setCurrentIndex(row)
                return True
        if combo.count():
            combo.setCurrentIndex(0)
        return False

    def _set_audio_stability_selection(self, profile: str) -> None:
        self.audio_stability = DEFAULT_STREAM_PROFILE

    @staticmethod
    def _route_device_signature(device: AudioDevice | None) -> tuple[object, ...] | None:
        if device is None:
            return None
        return (
            device.id,
            device.name,
            device.hostapi,
            device.max_input_channels,
            device.max_output_channels,
            device.default_samplerate,
            device.native_endpoint_id,
            device.native_direction,
            device.native_ambiguous,
        )

    def _selected_device(self, combo: QtWidgets.QComboBox) -> AudioDevice | None:
        device_id = combo.currentData()
        return self.device_by_id.get(int(device_id)) if device_id is not None else None

    def _selected_audio_stability(self) -> str:
        return DEFAULT_STREAM_PROFILE

    def _selected_sample_rate_mode(self) -> str:
        if hasattr(self, "sample_rate_combo"):
            return normalize_sample_rate_mode(self.sample_rate_combo.currentData())
        return normalize_sample_rate_mode(getattr(self, "sample_rate_mode", DEFAULT_SAMPLE_RATE_MODE))

    def _set_sample_rate_selection(self, sample_rate_mode: object) -> None:
        self.sample_rate_mode = normalize_sample_rate_mode(sample_rate_mode)
        if not hasattr(self, "sample_rate_combo"):
            return
        self.sample_rate_combo.blockSignals(True)
        self._set_combo_data(self.sample_rate_combo, self.sample_rate_mode)
        self.sample_rate_combo.blockSignals(False)

    def _resolved_sample_rate_for_current_route(self) -> int:
        return resolve_sample_rate(
            self._selected_sample_rate_mode(),
            self._selected_device(self.input_combo) if hasattr(self, "input_combo") else None,
            self._selected_device(self.output_combo) if hasattr(self, "output_combo") else None,
        )

    @staticmethod
    def _normalize_audio_stability(value: str) -> str:
        if value in {"legacy_low", "low_latency", "low", "raw_mode"}:
            return "raw"
        if value in {"normal", "balanced", "safe", "stable", "ultra_mode"}:
            return "ultra"
        return value if value in STREAM_PROFILES else DEFAULT_STREAM_PROFILE

    def _preset_by_id(self, preset_id: str) -> Preset | None:
        return next((preset for preset in self.presets if preset.id == preset_id), None)

    def _resolve_preset_route(self, preset: Preset) -> tuple[AudioDevice | None, AudioDevice | None, list[str]]:
        input_pick = find_saved_device(self.devices, preset.input_device, "input")
        output_pick = find_saved_device(self.devices, preset.output_device, "output")
        missing: list[str] = []

        if input_pick is None:
            input_pick = preferred_input(self.devices)
        if input_pick is None:
            missing.append("fixed input device")

        if preset.output_device is None:
            output_pick = preferred_output(self.devices)
        elif output_pick is None:
            missing.append(f"output {self._saved_device_name(preset.output_device)}")

        return input_pick, output_pick, missing

    def _preset_has_available_route(self, preset: Preset | None) -> bool:
        if preset is None:
            return False
        _, _, missing = self._resolve_preset_route(preset)
        return not missing

    def _available_preset(self, preset: Preset | None) -> Preset | None:
        return preset if self._preset_has_available_route(preset) else None

    def _first_available_preset(self) -> Preset | None:
        return next((preset for preset in self.presets if self._preset_has_available_route(preset)), None)

    def _smart_switch_preset(self, active_output: AudioDevice | None) -> Preset | None:
        if active_output is None:
            return None
        return match_preset_for_output(self.presets, active_output, self.devices)

    def _preset_for_current_route(self) -> Preset | None:
        current_input = self._selected_device(self.input_combo)
        current_output = self._selected_device(self.output_combo)
        if current_input is None or current_output is None:
            return None
        for preset in self.presets:
            preset_input = find_saved_device(self.devices, preset.input_device, "input")
            preset_output = find_saved_device(self.devices, preset.output_device, "output")
            if preset_input and preset_output and preset_input.id == current_input.id and preset_output.id == current_output.id:
                return preset
        return None

    def _guard_missing_active_route(self) -> None:
        active = self._preset_by_id(self.active_preset_id)
        if active is None:
            return
        _, _, missing = self._resolve_preset_route(active)
        if not missing:
            return
        if self.engine.snapshot().running:
            self.engine.stop()
        self._set_status(f"Preset missing: {', '.join(missing)}", "warning")
        self._persist_state(was_running=False)

    def _recover_after_device_refresh(self, was_running: bool) -> None:
        if not was_running or not self.engine.snapshot().running:
            return
        input_device = self._selected_device(self.input_combo)
        output_device = self._selected_device(self.output_combo)
        if input_device is None or output_device is None:
            self.engine.stop()
            self._set_status("Route unavailable after device change", "warning")
            self._persist_state(was_running=False)
            return
        self.start_audio()

    @staticmethod
    def _saved_device_name(saved: dict[str, object] | None) -> str:
        if not isinstance(saved, dict):
            return "device"
        return str(saved.get("name") or "device")

    def _manual_route_changed(self) -> None:
        if self._restoring:
            return
        active_output = default_wasapi_output(self.all_devices)
        self._manual_override_default_id = active_output.id if active_output else self._last_default_output_id
        running = self.engine.snapshot().running
        self._persist_state(was_running=running)
        self._sync_keep_output_awake()
        if running:
            self.start_audio()

    def update_preamp(self, value: int) -> None:
        self.engine.processor.set_preamp_db(value)
        self.preamp_value.setText(f"{value:+d} dB")
        if not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def update_user_volume(self, value: int) -> None:
        self.engine.processor.set_user_volume(1.0)
        if not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def update_surround_fill(self, enabled: bool) -> None:
        self.surround_fill_enabled = bool(enabled)
        self.engine.processor.set_surround_fill_enabled(self.surround_fill_enabled)
        if not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def update_upmix_9_1_6(self, enabled: bool) -> None:
        self.upmix_9_1_6_enabled = bool(enabled)
        self.engine.processor.set_upmix_9_1_6_enabled(self.upmix_9_1_6_enabled)
        if not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def update_sound_enhancer(self, enabled: bool) -> None:
        self.sound_enhancer_enabled = bool(enabled)
        self.engine.processor.set_sound_enhancer_enabled(self.sound_enhancer_enabled)
        if not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def update_keep_output_awake(self, enabled: bool) -> None:
        self.keep_output_awake_enabled = bool(enabled)
        self._sync_keep_output_awake()
        if not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def _sync_keep_output_awake(self) -> None:
        if not hasattr(self, "keep_awake_checkbox"):
            return
        self.keep_output_awake_enabled = bool(self.keep_awake_checkbox.isChecked())
        self.engine.set_keep_output_awake(
            self.keep_output_awake_enabled,
            self._selected_device(self.output_combo),
            sample_rate=self._resolved_sample_rate_for_current_route(),
        )

    def update_sample_rate_mode(self, *args: object) -> None:
        self.sample_rate_mode = self._selected_sample_rate_mode()
        self._apply_peq_routing_state(persist=False)
        self._sync_keep_output_awake()
        if self._restoring:
            return
        running = self.engine.snapshot().running
        self._persist_state(was_running=running)
        if running:
            self.start_audio()

    def update_channel_sanity(self, enabled: bool) -> None:
        self.channel_sanity_enabled = False
        self.engine.processor.set_channel_sanity_enabled(False)
        if not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def update_audio_stability(self, *args: object) -> None:
        self.audio_stability = DEFAULT_STREAM_PROFILE
        if self._restoring:
            return
        running = self.engine.snapshot().running
        self._persist_state(was_running=running)
        if running:
            self.start_audio()

    def _reset_callback_window(self) -> None:
        self._last_callback_status_count = 0

    def _fallback_non_normal_on_warning(self, snapshot) -> bool:
        self._last_callback_status_count = snapshot.callback_status_count
        return False

    def _maybe_recover_audio_stream(self, snapshot) -> bool:
        now = monotonic()
        if now - self._last_audio_recovery_at < RECOVERY_COOLDOWN_SECONDS:
            return False

        status_text = f"{getattr(snapshot, 'status', '')} {getattr(snapshot, 'callback_status', '')}".casefold()
        invalid_markers = (
            "audclnt_e_device_invalidated",
            "device invalidated",
            "stream invalidated",
            "rerouted",
            "interruption",
            "disconnected",
            "unplugged",
        )
        if any(marker in status_text for marker in invalid_markers):
            return self._recover_audio_stream("Audio route recovered", now)

        if not getattr(snapshot, "running", False):
            self._silent_input_started_at = None
            if self._force_auto_start and any(marker in status_text for marker in ("stopped", "failed", "lost")):
                return self._recover_audio_stream("Audio stream restarted", now)
            return False

        dsp = snapshot.dsp
        master_volume = float(getattr(dsp, "master_volume", 1.0))
        if bool(getattr(dsp, "master_muted", False)) or master_volume <= 0.001:
            self._silent_input_started_at = None
            return False

        try:
            raw_peak = max(abs(float(value)) for value in getattr(dsp, "raw_channel_levels", ()))
        except Exception:
            raw_peak = 0.0
        output_peak = max(abs(float(getattr(dsp, "left_meter", 0.0))), abs(float(getattr(dsp, "right_meter", 0.0))))

        if raw_peak >= RECOVERY_INPUT_ACTIVITY_THRESHOLD and output_peak <= RECOVERY_OUTPUT_SILENCE_THRESHOLD:
            if self._silent_input_started_at is None:
                self._silent_input_started_at = now
                return False
            if now - self._silent_input_started_at >= IDLE_RECOVERY_SECONDS:
                return self._recover_audio_stream("Audio stream self-healed", now)
            return False

        self._silent_input_started_at = None
        return False

    def _recover_audio_stream(self, status: str, now: float | None = None) -> bool:
        self._silent_input_started_at = None
        self._last_audio_recovery_at = monotonic() if now is None else now
        self._set_status(status, "warning")
        self.start_audio()
        return True

    def _toggle_render_session(self) -> None:
        if self.engine.snapshot().running:
            self.stop_audio()
        else:
            self.start_audio()

    def start_audio(self) -> None:
        input_device = self._selected_device(self.input_combo)
        output_device = self._selected_device(self.output_combo)
        if input_device is None or output_device is None:
            self._set_status("No WASAPI route", "error")
            return
        try:
            self._apply_peq_routing_state(persist=False)
            requested_profile = DEFAULT_STREAM_PROFILE
            sample_rate_mode = self._selected_sample_rate_mode()
            self.engine.start(input_device, output_device, requested_profile, sample_rate_mode=sample_rate_mode)
            actual_profile = self.engine.snapshot().stream_profile
            if actual_profile != requested_profile:
                self._set_audio_stability_selection(actual_profile)
                self._set_status(f"{STREAM_PROFILES[requested_profile]} unavailable; using {STREAM_PROFILES[actual_profile]}", "warning")
            else:
                self._set_status("Running", "running")
            self._force_auto_start = True
            self._reset_callback_window()
            self._persist_state(was_running=True)
        except Exception as exc:
            self._set_status(str(exc), "error")
            self._sync_keep_output_awake()
            self._persist_state(was_running=False)

    def stop_audio(self) -> None:
        self.engine.stop()
        self._sync_keep_output_awake()
        self._set_status("Stopped", "stopped")
        self._force_auto_start = False
        self._persist_state(was_running=False, auto_start=False)

    def update_ui(self) -> None:
        volume = self.engine.poll_volume()
        snapshot = self.engine.snapshot()
        dsp = snapshot.dsp
        self._update_header_status(snapshot)
        self._sync_visual_performance(snapshot.running)
        if self._maybe_recover_audio_stream(snapshot):
            return
        if self._fallback_non_normal_on_warning(snapshot):
            return

        for tile in self.tiles:
            level = float(dsp.channel_levels[tile.source_index]) if tile.source_index < len(dsp.channel_levels) else 0.0
            tile.set_level(level)
        if hasattr(self, "room_visualizer"):
            self.room_visualizer.set_levels(dsp.channel_levels)

        if self.raw_monitor_dialog is not None and self.raw_monitor_dialog.isVisible():
            self.raw_monitor_dialog.set_levels(dsp.raw_channel_levels, dsp.raw_channel_rms)

        self.stereo_sum_meter.set_levels(dsp.left_meter, dsp.right_meter)
        sys_text = "Muted" if volume.muted else f"{volume.scalar * 100:.1f}%"
        source = volume.source if volume.available else "unavailable"

        if snapshot.running:
            if dsp.clipping:
                self._set_status("Limiting", "warning")
            else:
                self._set_status("Running", "running")

        active_preset = self._preset_by_id(self.active_preset_id)
        self.diag_labels["Preset"].setText(active_preset.name if active_preset else "--")
        self.diag_labels["Route"].setText(snapshot.route)
        self.diag_labels["Channels"].setText(f"{self.channel_config_label()} | {snapshot.input_channels or '--'} in -> 2 out")
        self.diag_labels["Layout"].setText(self._layout_diagnostic_text(dsp))
        if snapshot.stream_latency:
            in_latency, out_latency = snapshot.stream_latency
            profile_label = STREAM_PROFILES.get(snapshot.stream_profile, snapshot.stream_profile)
            rate_label = f"{snapshot.sample_rate / 1000:g} kHz"
            if snapshot.sample_rate_mode == DEFAULT_SAMPLE_RATE_MODE:
                rate_label = f"Auto {rate_label}"
            stream_text = f"{profile_label} | {rate_label} | {in_latency * 1000:.1f}/{out_latency * 1000:.1f} ms | CPU {snapshot.cpu_load:.2f}"
        else:
            stream_text = "--"
        if snapshot.callback_status_count:
            stream_text = f"{stream_text} | {snapshot.callback_status_count}x {snapshot.callback_status}"
        self.diag_labels["Stream"].setText(stream_text)
        self.diag_labels["Limiter"].setText(f"{dsp.limiter_gain:.3f}" + (" clip" if dsp.clipping else ""))
        enhancer_text = "off"
        if dsp.sound_enhancer_enabled:
            enhancer_text = f"{dsp.sound_enhancer_gain:.3f}x"
            if dsp.sound_enhancer_gain < 1.0:
                enhancer_text += " protected"
        self.diag_labels["Enhancer"].setText(enhancer_text)
        fill_parts = []
        if dsp.surround_fill_enabled:
            fill_parts.append("7.1 upmix active" if dsp.surround_fill_active else "7.1 upmix armed")
        else:
            fill_parts.append("7.1 upmix off")
        if dsp.upmix_9_1_6_enabled:
            fill_parts.append("9.1.6 active" if dsp.upmix_9_1_6_active else "9.1.6 armed")
        else:
            fill_parts.append("9.1.6 off")
        fill_parts.append(self._peq_diagnostic_text())
        self.diag_labels["Upmix"].setText(" | ".join(fill_parts) if fill_parts else "off")
        active = [tile.name for tile in self.tiles if tile.display_level > 0.01]
        self.diag_labels["Active"].setText(", ".join(active) if active else "--")
        keep_awake = "keep-awake on" if self.keep_output_awake_enabled else "keep-awake off"
        output_name = self.output_combo.currentText().split("  [", 1)[0] if hasattr(self, "output_combo") else "--"
        self.diag_labels["Output"].setText(f"{output_name or '--'} | Windows {sys_text} ({source}) | {keep_awake}")

    def _update_header_status(self, snapshot) -> None:
        if not hasattr(self, "header_status"):
            return
        if snapshot.running:
            self.header_status.setText("Shared WASAPI | ULTRA Mode")
        else:
            self.header_status.setText("Shared WASAPI | Ready")

    def channel_config_label(self) -> str:
        return str(CHANNEL_LAYOUTS[self.channel_config]["label"])

    def _peq_diagnostic_text(self) -> str:
        if not hasattr(self, "lr_swap_checkbox"):
            return "PEQ off | Swap off"
        report = self._last_peq_report
        parts: list[str] = []
        if self.global_peq_checkbox.isChecked():
            parts.append(f"User PEQ {report.global_filter_count}")
        else:
            parts.append("User PEQ off")
        if self.speaker_eq_checkbox.isChecked():
            parts.append(f"Speaker L/R {report.speaker_left_filter_count}/{report.speaker_right_filter_count}")
        else:
            parts.append("Speaker EQ off")
        parts.append("Swap on" if self.lr_swap_checkbox.isChecked() else "Swap off")
        return " | ".join(parts)

    def _layout_diagnostic_text(self, dsp) -> str:
        if self.channel_config == "sharur_9_1_6":
            if dsp.upmix_9_1_6_enabled:
                return "9.1.6 monitor | upmix on | label-mapped bed + generated field"
            return "9.1.6 monitor | upmix off | label-mapped bed"
        return "7.1 monitor | FL FR FC LFE BL BR SL SR"

    def open_raw_monitor(self) -> None:
        if self.raw_monitor_dialog is None:
            self.raw_monitor_dialog = RawMonitorDialog(None)
            self.raw_monitor_dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        dsp = self.engine.snapshot().dsp
        self.raw_monitor_dialog.set_levels(dsp.raw_channel_levels, dsp.raw_channel_rms)
        self.raw_monitor_dialog.show()
        self.raw_monitor_dialog.raise_()
        self.raw_monitor_dialog.activateWindow()

    def _close_raw_monitor_dialog(self) -> None:
        dialog = self.raw_monitor_dialog
        if dialog is None:
            return
        dialog.hide()
        dialog.close()
        self.raw_monitor_dialog = None

    def start_route_probe(self) -> None:
        if self._probe_thread is not None and self._probe_thread.isRunning():
            return

        input_device = self._selected_device(self.input_combo)
        self._probe_restore_running = self.engine.snapshot().running
        if self._probe_restore_running:
            self.engine.stop()

        output_path = Path(__file__).resolve().parents[1] / "route_probe_live.json"
        if hasattr(self, "route_probe_button"):
            self.route_probe_button.setEnabled(False)
        if "Output" in self.diag_labels:
            self.diag_labels["Output"].setText("Route probe running...")
        self._set_status("Probe running", "warning")

        thread = QtCore.QThread(self)
        worker = RouteProbeWorker(output_path, input_device.id if input_device else None)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._finish_route_probe)
        worker.failed.connect(self._fail_route_probe)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_route_probe)
        self._probe_thread = thread
        self._probe_worker = worker
        thread.start()

    def _finish_route_probe(self, report: object, path: str) -> None:
        capture = report.get("capture", {}) if isinstance(report, dict) else {}
        truth = str(capture.get("truth", "unknown"))
        peaks = capture.get("peaks", [])
        likely_fill = bool(capture.get("likely_windows_channel_fill", False))
        peak_sl = float(peaks[6]) if isinstance(peaks, list) and len(peaks) > 6 else 0.0
        peak_sr = float(peaks[7]) if isinstance(peaks, list) and len(peaks) > 7 else 0.0
        fill_note = " | fill-like" if likely_fill else ""
        if "Output" in self.diag_labels:
            self.diag_labels["Output"].setText(
                f"{truth}{fill_note} | idx6 SL {peak_sl:.5f} | idx7 SR {peak_sr:.5f} | {Path(path).name}"
            )
        status = "running" if truth == "channels_above_8_detected" else "warning"
        self._set_status("Probe saved", status)
        if self._probe_restore_running:
            self.start_audio()

    def _fail_route_probe(self, detail: str) -> None:
        if "Output" in self.diag_labels:
            self.diag_labels["Output"].setText(f"Probe failed | {detail}")
        self._set_status("Probe failed", "error")
        if self._probe_restore_running:
            self.start_audio()

    def _cleanup_route_probe(self) -> None:
        if hasattr(self, "route_probe_button"):
            self.route_probe_button.setEnabled(True)
        self._probe_thread = None
        self._probe_worker = None

    def _set_status(self, text: str, status: str) -> None:
        self._status_text = text
        self._status_state = status
        self._sync_render_toggle()

    def _sync_render_toggle(self) -> None:
        if not hasattr(self, "render_toggle_button"):
            return
        try:
            rendering = bool(self.engine.snapshot().running)
        except Exception:
            rendering = False
        self.render_toggle_button.set_rendering(rendering)

    def _persist_state(self, was_running: bool, auto_start: bool | None = None) -> None:
        input_device = self._selected_device(self.input_combo)
        output_device = self._selected_device(self.output_combo)
        peq_fields = self._current_peq_fields()
        should_resume = bool(was_running if auto_start is None else auto_start)
        save_settings(
            {
                "app_name": APP_DISPLAY_NAME,
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "preset_schema_version": PRESET_SCHEMA_VERSION,
                "input_device": input_device.identity("input") if input_device else None,
                "output_device": output_device.identity("output") if output_device else None,
                "preamp_db": int(self.preamp_slider.value()) if hasattr(self, "preamp_slider") else DEFAULT_PREAMP_DB,
                "user_volume": 1.0,
                "channel_config": self.channel_config,
                "active_preset_id": self.active_preset_id,
                "presets": [preset.to_dict() for preset in self.presets],
                "was_running": bool(was_running),
                "auto_start": should_resume,
                "resume_on_launch": should_resume,
                "smart_switch_enabled": bool(self.smart_switch_checkbox.isChecked()) if hasattr(self, "smart_switch_checkbox") else True,
                "surround_fill_enabled": bool(self.surround_fill_checkbox.isChecked()) if hasattr(self, "surround_fill_checkbox") else False,
                "upmix_9_1_6_enabled": bool(self.upmix916_checkbox.isChecked()) if hasattr(self, "upmix916_checkbox") else False,
                "channel_sanity_enabled": False,
                "sound_enhancer_enabled": bool(self.sound_enhancer_checkbox.isChecked()) if hasattr(self, "sound_enhancer_checkbox") else False,
                "audio_stability": DEFAULT_STREAM_PROFILE,
                "sample_rate_mode": self._selected_sample_rate_mode(),
                "keep_output_awake": bool(self.keep_awake_checkbox.isChecked()) if hasattr(self, "keep_awake_checkbox") else False,
                "system_boot_autostart": bool(self.system_boot_checkbox.isChecked()) if hasattr(self, "system_boot_checkbox") else False,
                **peq_fields,
            }
        )


def apply_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        return


def main() -> int:
    apply_windows_app_user_model_id()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    icon_path = RendererWindow._icon_asset_path()
    if icon_path.exists():
        app.setWindowIcon(QtGui.QIcon(str(icon_path)))
    app.setStyle("Fusion")
    window = RendererWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
