from __future__ import annotations

import sys
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

from .audio_engine import AudioEngine
from .constants import (
    APP_DISPLAY_NAME,
    BLOCK_SIZE,
    CHANNEL_LAYOUTS,
    DEFAULT_CHANNEL_CONFIG,
    DEFAULT_PREAMP_DB,
    SAMPLE_RATE,
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
from .dsp import linear_to_db
from .presets import (
    PRESET_SCHEMA_VERSION,
    Preset,
    load_presets,
    match_preset_for_output,
    preset_from_current,
    update_preset_from_current,
)
from .settings import load_settings, save_settings
from .startup import is_system_autostart_enabled, set_system_autostart

BLACK = "#000000"
PANEL = "#030303"
PANEL_LIFT = "#080808"
PANEL_SOFT = "#0f0f0f"
BORDER = "#181818"
BORDER_HOT = "#f2f2f2"
TEXT = "#eeeeee"
MID = "#b7b7b7"
DIM = "#747474"
WARN = "#d8b15d"
ERROR = "#f26d6d"
SUCCESS = "#68d98f"
STOPPED = "#b06a6a"
APP_HEADING = "Downmix Renderer 7.1"

BASE_STYLE = f"""
QWidget {{
    background-color: {BLACK};
    color: {TEXT};
    font-family: Segoe UI, Inter, Arial;
    font-size: 12px;
}}
QLabel#title {{
    color: {TEXT};
    font-size: 21px;
    font-weight: 650;
}}
QLabel#subtitle {{
    color: {DIM};
    font-size: 11px;
    font-weight: 500;
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
QFrame#card {{
    background-color: {PANEL};
    border: 1px solid #141414;
    border-radius: 8px;
}}
QFrame#titlebar {{
    background-color: #000000;
    border: none;
}}
QComboBox {{
    background-color: {BLACK};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 7px 10px;
    min-height: 31px;
    color: {TEXT};
}}
QComboBox:hover {{
    border-color: #444444;
}}
QComboBox QAbstractItemView {{
    background-color: {BLACK};
    border: 1px solid {BORDER};
    selection-background-color: #f2f2f2;
    selection-color: #000000;
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
    border-color: #777777;
}}
QPushButton {{
    background-color: {BLACK};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 8px 13px;
    min-height: 31px;
    color: {TEXT};
    font-weight: 600;
}}
QPushButton:hover {{
    border-color: #5c5c5c;
    background-color: #050505;
}}
QPushButton:pressed {{
    background-color: #0d0d0d;
}}
QPushButton#preset {{
    color: {MID};
    text-align: left;
}}
QPushButton#preset[active="true"] {{
    color: #000000;
    background-color: #e8e8e8;
    border-color: #e8e8e8;
}}
QPushButton#ghost {{
    color: {MID};
}}
QPushButton#window {{
    border: none;
    border-radius: 0px;
    min-width: 42px;
    min-height: 30px;
    padding: 0px;
    color: {MID};
    background-color: #000000;
}}
QPushButton#window:hover {{
    color: {TEXT};
    background-color: #101010;
}}
QPushButton#windowClose {{
    border: none;
    border-radius: 0px;
    min-width: 42px;
    min-height: 30px;
    padding: 0px;
    color: {MID};
    background-color: #000000;
}}
QPushButton#windowClose:hover {{
    color: #ff8a8a;
    background-color: #140606;
}}
QPushButton#start {{
    color: {SUCCESS};
    border-color: #274634;
}}
QPushButton#stop {{
    color: {STOPPED};
    border-color: #4b2020;
}}
QPushButton#mode {{
    color: {MID};
    padding-left: 10px;
    padding-right: 10px;
}}
QPushButton#mode[active="true"] {{
    color: #000000;
    background-color: #e8e8e8;
    border-color: #e8e8e8;
}}
QSlider::groove:horizontal {{
    height: 3px;
    background: #1d1d1d;
    border-radius: 1px;
}}
QSlider::sub-page:horizontal {{
    background: #f1f1f1;
    border-radius: 1px;
}}
QSlider::handle:horizontal {{
    background: #ffffff;
    border: 1px solid #000000;
    width: 15px;
    height: 15px;
    margin: -6px 0;
    border-radius: 7px;
}}
QCheckBox {{
    color: {MID};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 34px;
    height: 18px;
    border-radius: 9px;
    background: #111111;
    border: 1px solid #202020;
}}
QCheckBox::indicator:checked {{
    background: #ffffff;
    border-color: #ffffff;
}}
"""


def section_label(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text.upper())
    label.setObjectName("section")
    return label


def value_label(text: str = "--") -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("value")
    return label


def card(layout: QtWidgets.QLayout) -> QtWidgets.QFrame:
    frame = QtWidgets.QFrame()
    frame.setObjectName("card")
    frame.setLayout(layout)
    shadow = QtWidgets.QGraphicsDropShadowEffect(frame)
    shadow.setBlurRadius(18)
    shadow.setOffset(0, 1)
    shadow.setColor(QtGui.QColor(255, 255, 255, 8))
    frame.setGraphicsEffect(shadow)
    return frame


class TitleBar(QtWidgets.QFrame):
    def __init__(self, window: "RendererWindow") -> None:
        super().__init__(window)
        self.window = window
        self._drag_pos: QtCore.QPoint | None = None
        self.setObjectName("titlebar")
        self.setFixedHeight(34)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(6)

        icon = QtWidgets.QLabel()
        icon.setFixedSize(18, 18)
        icon.setPixmap(window._logo_pixmap(18, 18))
        layout.addWidget(icon)

        title = QtWidgets.QLabel(APP_DISPLAY_NAME)
        title.setStyleSheet(f"color:{TEXT}; font-size:11px; font-weight:600;")
        layout.addWidget(title)
        layout.addStretch()

        minimize = QtWidgets.QPushButton("-")
        maximize = QtWidgets.QPushButton("[]")
        close = QtWidgets.QPushButton("x")
        for button in (minimize, maximize):
            button.setObjectName("window")
        close.setObjectName("windowClose")
        minimize.clicked.connect(window.showMinimized)
        maximize.clicked.connect(window.toggle_maximize)
        close.clicked.connect(window.close)
        layout.addWidget(minimize)
        layout.addWidget(maximize)
        layout.addWidget(close)

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & QtCore.Qt.LeftButton:
            if self.window.isMaximized():
                self.window.showNormal()
                self._drag_pos = QtCore.QPoint(self.window.width() // 2, 16)
            self.window.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event) -> None:
        self.window.toggle_maximize()


class VUMeter(QtWidgets.QWidget):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label
        self.level = 0.0
        self.display_level = 0.0
        self.peak = 0.0
        self.setMinimumSize(44, 225)
        self.setMaximumWidth(54)

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


class ChannelTile(QtWidgets.QWidget):
    def __init__(self, name: str, source_index: int) -> None:
        super().__init__()
        self.name = name
        self.source_index = source_index
        self.level = 0.0
        self.display_level = 0.0
        self.setMinimumSize(72, 58)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

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

        bg = "#f2f2f2" if active else "#030303"
        border = "#ffffff" if active else BORDER
        text = "#000000" if active else MID
        painter.setPen(QtGui.QPen(QtGui.QColor(border), 1))
        painter.setBrush(QtGui.QColor(bg))
        painter.drawRoundedRect(1, 1, width - 2, height - 2, 6, 6)

        painter.setPen(QtGui.QColor(text))
        painter.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))
        painter.drawText(0, 7, width, 17, QtCore.Qt.AlignCenter, self.name)

        bar = QtCore.QRectF(9, height - 15, width - 18, 4)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#1c1c1c" if not active else "#c8c8c8"))
        painter.drawRoundedRect(bar, 2, 2)
        if self.display_level > 0.002:
            fill = QtCore.QRectF(bar.left(), bar.top(), bar.width() * self.display_level, bar.height())
            painter.setBrush(QtGui.QColor("#000000" if active else "#ffffff"))
            painter.drawRoundedRect(fill, 2, 2)

        painter.setPen(QtGui.QColor("#1c1c1c" if active else DIM))
        painter.setFont(QtGui.QFont("Consolas", 7))
        db_text = f"{linear_to_db(self.level):.0f} dB" if self.level > 0.001 else "--"
        painter.drawText(0, 28, width, 12, QtCore.Qt.AlignCenter, db_text)


class RendererWindow(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Window)
        self.setMinimumSize(1160, 720)
        self.setStyleSheet(BASE_STYLE)
        self._set_icon()
        self._closing_with_animation = False
        self._shown_with_animation = False
        self._fade_animation: QtCore.QPropertyAnimation | None = None
        self.setWindowOpacity(0.0)

        self.engine = AudioEngine()
        self.settings = load_settings()
        self.all_devices = list_devices()
        self.devices = [dev for dev in self.all_devices if dev.hostapi == WASAPI_HOSTAPI]
        self.device_by_id = {dev.id: dev for dev in self.devices}
        self._device_signature = self._make_device_signature(self.all_devices)
        self.presets = load_presets(self.settings, self.devices)
        saved_active = str(self.settings.get("active_preset_id") or "")
        self.active_preset_id = saved_active if any(preset.id == saved_active for preset in self.presets) else ""
        self.channel_config = str(self.settings.get("channel_config") or DEFAULT_CHANNEL_CONFIG)
        if self.channel_config not in CHANNEL_LAYOUTS:
            self.channel_config = DEFAULT_CHANNEL_CONFIG
        self._restoring = False
        self._last_default_output_id: int | None = None
        self._manual_override_default_id: int | None = None
        self._force_auto_start = bool(self.settings.get("auto_start", True) or self.settings.get("was_running", False))

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(TitleBar(self))

        shell = QtWidgets.QVBoxLayout()
        shell.setContentsMargins(18, 16, 18, 18)
        shell.setSpacing(12)
        shell.addLayout(self._build_header())

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(12)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(self._build_presets_card())
        left.addWidget(self._build_route_card())
        left.addWidget(self._build_volume_card())
        left.addWidget(self._build_transport_card())
        left.addStretch()
        body.addLayout(left, 4)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._build_channels_card())
        right.addWidget(self._build_meter_card())
        right.addWidget(self._build_diagnostics_card())
        body.addLayout(right, 7)
        shell.addLayout(body)
        root.addLayout(shell)

        self._apply_launch_preset()
        self._wire_events()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(40)

        self.device_timer = QtCore.QTimer(self)
        self.device_timer.timeout.connect(self.poll_devices)
        self.device_timer.start(1500)

        QtCore.QTimer.singleShot(300, self._auto_start_if_needed)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._shown_with_animation:
            return
        self._shown_with_animation = True
        self._animate_opacity(0.0, 1.0, 180, QtCore.QEasingCurve.OutCubic)

    def closeEvent(self, event) -> None:
        if not self._closing_with_animation:
            event.ignore()
            self._closing_with_animation = True
            self._persist_state(was_running=self.engine.snapshot().running)
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

    def _set_icon(self) -> None:
        icon_path = Path(__file__).resolve().parents[1] / "assets" / "tarans_renderer_icon.svg"
        if icon_path.exists():
            self.setWindowIcon(QtGui.QIcon(str(icon_path)))

    def _build_header(self) -> QtWidgets.QLayout:
        layout = QtWidgets.QHBoxLayout()
        mark = QtWidgets.QLabel()
        mark.setFixedSize(34, 34)
        mark.setPixmap(self._logo_pixmap(34, 34))
        layout.addWidget(mark)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(0)
        title = QtWidgets.QLabel(APP_HEADING)
        title.setObjectName("title")
        subtitle = QtWidgets.QLabel("WASAPI stereo render path | 48 kHz | 256 samples")
        subtitle.setObjectName("subtitle")
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        layout.addLayout(text_col)
        layout.addStretch()
        return layout

    def _logo_pixmap(self, width: int, height: int) -> QtGui.QPixmap:
        pixmap = QtGui.QPixmap(width, height)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#ffffff"))
        size = width // 5
        gap = max(2, width // 16)
        centers = [
            (width // 2, gap + size),
            (width // 2 - size - gap, height // 2),
            (width // 2 + size + gap, height // 2),
            (width // 2, height - gap - size),
        ]
        for cx, cy in centers:
            points = [
                QtCore.QPoint(cx, cy - size),
                QtCore.QPoint(cx + size, cy),
                QtCore.QPoint(cx, cy + size),
                QtCore.QPoint(cx - size, cy),
            ]
            painter.drawPolygon(QtGui.QPolygon(points))
        painter.end()
        return pixmap

    def _build_presets_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setSpacing(9)
        layout.addWidget(section_label("Presets"))

        self.preset_buttons_layout = QtWidgets.QVBoxLayout()
        self.preset_buttons_layout.setSpacing(6)
        layout.addLayout(self.preset_buttons_layout)

        self.preset_name_edit = QtWidgets.QLineEdit()
        self.preset_name_edit.setPlaceholderText("Preset name")
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
        return card(layout)

    def _build_route_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(section_label("WASAPI Route"))

        self.input_combo = QtWidgets.QComboBox()
        self.output_combo = QtWidgets.QComboBox()

        for dev in renderer_input_devices(self.devices):
            self.input_combo.addItem(self._short_device_label(dev, "input"), dev.id)
        for dev in renderer_output_devices(self.devices):
            self.output_combo.addItem(self._short_device_label(dev, "output"), dev.id)

        layout.addWidget(QtWidgets.QLabel("Input"))
        layout.addWidget(self.input_combo)
        layout.addWidget(QtWidgets.QLabel("Output"))
        layout.addWidget(self.output_combo)
        return card(layout)

    def _build_volume_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(section_label("Gain"))

        self.preamp_value = value_label()
        self.preamp_slider = self._slider(-20, 0)
        layout.addLayout(self._label_value_row("Preamp", self.preamp_value))
        layout.addWidget(self.preamp_slider)

        self.user_volume_value = value_label()
        self.user_volume_slider = self._slider(0, 100)
        layout.addLayout(self._label_value_row("Suite Volume", self.user_volume_value))
        layout.addWidget(self.user_volume_slider)

        mode_row = QtWidgets.QHBoxLayout()
        self.mode_buttons: dict[str, QtWidgets.QPushButton] = {}
        for config_id, config in CHANNEL_LAYOUTS.items():
            button = QtWidgets.QPushButton(str(config["label"]))
            button.setObjectName("mode")
            button.setProperty("active", config_id == self.channel_config)
            button.clicked.connect(lambda checked=False, cid=config_id: self.set_channel_config(cid))
            self.mode_buttons[config_id] = button
            mode_row.addWidget(button)
        layout.addLayout(mode_row)
        return card(layout)

    def _build_transport_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(section_label("Session"))

        buttons = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("Start")
        self.start_button.setObjectName("start")
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.setObjectName("stop")
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)

        self.status_label = value_label("Standby")
        self._set_status("Standby", "neutral")
        layout.addWidget(self.status_label)

        self.smart_switch_checkbox = QtWidgets.QCheckBox("Smart preset switching")
        self.smart_switch_checkbox.setChecked(bool(self.settings.get("smart_switch_enabled", True)))
        layout.addWidget(self.smart_switch_checkbox)

        self.system_boot_checkbox = QtWidgets.QCheckBox("Auto Start Renderer on System Boot")
        self.system_boot_checkbox.setChecked(bool(self.settings.get("system_boot_autostart", False) or is_system_autostart_enabled()))
        layout.addWidget(self.system_boot_checkbox)
        return card(layout)

    def _build_channels_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setSpacing(10)
        self.channel_section = section_label("Channel Field")
        layout.addWidget(self.channel_section)

        self.channel_grid = QtWidgets.QGridLayout()
        self.channel_grid.setSpacing(7)
        self.tiles: list[ChannelTile] = []
        layout.addLayout(self.channel_grid)
        self._rebuild_channel_tiles()
        return card(layout)

    def _build_meter_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(section_label("Stereo Output"))

        meter_row = QtWidgets.QHBoxLayout()
        meter_row.setSpacing(12)
        self.left_meter = VUMeter("L")
        self.right_meter = VUMeter("R")
        meter_row.addWidget(self.left_meter)
        meter_row.addWidget(self.right_meter)

        readouts = QtWidgets.QVBoxLayout()
        readouts.setSpacing(7)
        self.left_db = value_label("L: --")
        self.right_db = value_label("R: --")
        self.system_volume_label = value_label("Windows: --")
        readouts.addWidget(self.left_db)
        readouts.addWidget(self.right_db)
        readouts.addWidget(self.system_volume_label)
        readouts.addStretch()
        meter_row.addLayout(readouts)
        meter_row.addStretch()
        layout.addLayout(meter_row)
        return card(layout)

    def _build_diagnostics_card(self) -> QtWidgets.QFrame:
        layout = QtWidgets.QGridLayout()
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(7)
        layout.addWidget(section_label("Diagnostics"), 0, 0, 1, 2)

        self.diag_labels: dict[str, QtWidgets.QLabel] = {}
        for row, key in enumerate(("Preset", "Route", "Channels", "Limiter", "Active"), start=1):
            name = QtWidgets.QLabel(key)
            name.setStyleSheet(f"color:{DIM};")
            value = value_label()
            value.setWordWrap(True)
            self.diag_labels[key] = value
            layout.addWidget(name, row, 0)
            layout.addWidget(value, row, 1)
        return card(layout)

    def _wire_events(self) -> None:
        self.start_button.clicked.connect(self.start_audio)
        self.stop_button.clicked.connect(self.stop_audio)
        self.new_preset_button.clicked.connect(self.create_preset)
        self.save_preset_button.clicked.connect(self.save_active_preset)
        self.delete_preset_button.clicked.connect(self.delete_active_preset)
        self.system_boot_checkbox.toggled.connect(self.set_system_boot_autostart)
        self.smart_switch_checkbox.toggled.connect(lambda checked: self._persist_state(was_running=self.engine.snapshot().running))
        self.preamp_slider.valueChanged.connect(self.update_preamp)
        self.user_volume_slider.valueChanged.connect(self.update_user_volume)
        self.input_combo.currentIndexChanged.connect(self._manual_route_changed)
        self.output_combo.currentIndexChanged.connect(self._manual_route_changed)

    def _slider(self, minimum: int, maximum: int) -> QtWidgets.QSlider:
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setMinimum(minimum)
        slider.setMaximum(maximum)
        slider.setMinimumHeight(26)
        return slider

    def _label_value_row(self, label: str, value: QtWidgets.QLabel) -> QtWidgets.QLayout:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        row.addStretch()
        row.addWidget(value)
        return row

    def _short_device_label(self, device: AudioDevice, mode: str) -> str:
        channels = device.max_input_channels if mode == "input" else device.max_output_channels
        suffix = "in" if mode == "input" else "out"
        return f"{device.name}  [{channels}ch {suffix} | {device.default_samplerate} Hz]"

    def _rebuild_preset_buttons(self) -> None:
        while self.preset_buttons_layout.count():
            item = self.preset_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for preset in self.presets:
            button = QtWidgets.QPushButton(preset.name)
            button.setObjectName("preset")
            button.setProperty("active", preset.id == self.active_preset_id)
            button.clicked.connect(lambda checked=False, pid=preset.id: self.apply_preset(pid, start_after=True, manual=True))
            self.preset_buttons_layout.addWidget(button)
        if not self.presets:
            empty = QtWidgets.QLabel("No presets saved")
            empty.setStyleSheet(f"color:{DIM}; padding: 6px 2px;")
            self.preset_buttons_layout.addWidget(empty)

    def _apply_launch_preset(self) -> None:
        active_output = default_wasapi_output(self.all_devices)
        matched = match_preset_for_output(self.presets, active_output, self.devices)
        saved_output = find_saved_device(self.devices, self.settings.get("output_device"), "output")
        saved_match = match_preset_for_output(self.presets, saved_output, self.devices)
        preset = matched or self._preset_by_id(self.active_preset_id) or saved_match or (self.presets[0] if self.presets else None)
        if preset:
            self.apply_preset(preset.id, start_after=False, manual=False)
        else:
            self._restore_fallback_state()

    def _restore_fallback_state(self) -> None:
        self._restoring = True
        input_pick = find_saved_device(self.devices, self.settings.get("input_device"), "input") or preferred_input(self.devices)
        output_pick = find_saved_device(self.devices, self.settings.get("output_device"), "output") or preferred_output(self.devices)
        self._set_combo_device(self.input_combo, input_pick)
        self._set_combo_device(self.output_combo, output_pick)
        self.preamp_slider.setValue(int(self.settings.get("preamp_db", DEFAULT_PREAMP_DB)))
        self.user_volume_slider.setValue(int(float(self.settings.get("user_volume", 1.0)) * 100))
        self.update_preamp(int(self.preamp_slider.value()))
        self.update_user_volume(int(self.user_volume_slider.value()))
        self._restoring = False
        self._persist_state(was_running=bool(self.settings.get("was_running", False)))

    def apply_preset(self, preset_id: str, start_after: bool, manual: bool = False) -> None:
        preset = self._preset_by_id(preset_id)
        if preset is None:
            return
        if manual:
            active_output = default_wasapi_output(self.all_devices)
            self._manual_override_default_id = active_output.id if active_output else self._last_default_output_id
        self._restoring = True
        self.active_preset_id = preset.id
        input_pick = find_saved_device(self.devices, preset.input_device, "input") or preferred_input(self.devices)
        output_pick = find_saved_device(self.devices, preset.output_device, "output") or preferred_output(self.devices)
        self._set_combo_device(self.input_combo, input_pick)
        self._set_combo_device(self.output_combo, output_pick)
        self.preamp_slider.setValue(int(preset.preamp_db))
        self.user_volume_slider.setValue(int(round(min(1.0, max(0.0, preset.user_volume)) * 100)))
        self.update_preamp(int(self.preamp_slider.value()))
        self.update_user_volume(int(self.user_volume_slider.value()))
        self.set_channel_config(preset.channel_config, persist=False)
        self._restoring = False
        self._rebuild_preset_buttons()
        self._persist_state(was_running=self.engine.snapshot().running)

        if start_after or self.engine.snapshot().running:
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
            user_volume=self.user_volume_slider.value() / 100.0,
            channel_config=self.channel_config,
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
        update_preset_from_current(
            preset,
            input_device=self._selected_device(self.input_combo),
            output_device=self._selected_device(self.output_combo),
            preamp_db=int(self.preamp_slider.value()),
            user_volume=self.user_volume_slider.value() / 100.0,
            channel_config=self.channel_config,
        )
        self._rebuild_preset_buttons()
        self._persist_state(was_running=self.engine.snapshot().running)

    def delete_active_preset(self) -> None:
        preset = self._preset_by_id(self.active_preset_id)
        if preset is None:
            return
        self.presets = [item for item in self.presets if item.id != preset.id]
        self.active_preset_id = self.presets[0].id if self.presets else ""
        self._rebuild_preset_buttons()
        self._persist_state(was_running=self.engine.snapshot().running)

    def set_system_boot_autostart(self, enabled: bool) -> None:
        ok, detail = set_system_autostart(enabled, Path(__file__).resolve().parents[1])
        if not ok:
            self.system_boot_checkbox.blockSignals(True)
            self.system_boot_checkbox.setChecked(is_system_autostart_enabled())
            self.system_boot_checkbox.blockSignals(False)
            self._set_status(f"Boot autostart: {detail}", "warning")
        self._persist_state(was_running=self.engine.snapshot().running)

    def set_channel_config(self, config_id: str, persist: bool = True) -> None:
        if config_id not in CHANNEL_LAYOUTS:
            config_id = DEFAULT_CHANNEL_CONFIG
        self.channel_config = config_id
        for button_id, button in self.mode_buttons.items():
            button.setProperty("active", button_id == config_id)
            button.style().unpolish(button)
            button.style().polish(button)
        self._rebuild_channel_tiles()
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
        columns = 4 if len(names) <= 8 else 8
        for index, (name, source_index) in enumerate(zip(names, indices)):
            tile = ChannelTile(str(name), int(source_index))
            self.channel_grid.addWidget(tile, index // columns, index % columns)
            self.tiles.append(tile)

    def _auto_start_if_needed(self) -> None:
        if self._force_auto_start:
            self.start_audio()

    def poll_devices(self) -> None:
        try:
            fresh_all = list_devices()
        except Exception:
            return

        signature = self._make_device_signature(fresh_all)
        if signature != self._device_signature:
            self._refresh_device_lists(fresh_all, signature)

        active_output = default_wasapi_output(fresh_all)
        active_id = active_output.id if active_output else None
        if self._last_default_output_id is None:
            self._last_default_output_id = active_id
        if active_id != self._last_default_output_id:
            self._last_default_output_id = active_id
            self._manual_override_default_id = None

        if not getattr(self, "smart_switch_checkbox", None) or not self.smart_switch_checkbox.isChecked():
            return
        if active_id is not None and active_id == self._manual_override_default_id:
            return
        preset = match_preset_for_output(self.presets, active_output, self.devices)
        if preset is None or preset.id == self.active_preset_id:
            return
        self.apply_preset(preset.id, start_after=self.engine.snapshot().running or self._force_auto_start, manual=False)

    def _refresh_device_lists(self, fresh_all: list[AudioDevice], signature: tuple[tuple[object, ...], ...]) -> None:
        current_input = self._selected_device(self.input_combo)
        current_output = self._selected_device(self.output_combo)
        input_identity = current_input.identity("input") if current_input else self.settings.get("input_device")
        output_identity = current_output.identity("output") if current_output else self.settings.get("output_device")

        self.all_devices = fresh_all
        self.devices = [dev for dev in fresh_all if dev.hostapi == WASAPI_HOSTAPI]
        self.device_by_id = {dev.id: dev for dev in self.devices}
        self._device_signature = signature

        self._restoring = True
        self._rebuild_device_combo(self.input_combo, renderer_input_devices(self.devices), "input")
        self._rebuild_device_combo(self.output_combo, renderer_output_devices(self.devices), "output")
        self._set_combo_device(self.input_combo, find_saved_device(self.devices, input_identity, "input") or preferred_input(self.devices))
        self._set_combo_device(self.output_combo, find_saved_device(self.devices, output_identity, "output") or preferred_output(self.devices))
        self._restoring = False

    def _rebuild_device_combo(self, combo: QtWidgets.QComboBox, devices: list[AudioDevice], mode: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        for dev in devices:
            combo.addItem(self._short_device_label(dev, mode), dev.id)
        combo.blockSignals(False)

    @staticmethod
    def _make_device_signature(devices: list[AudioDevice]) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (dev.id, dev.name, dev.hostapi, dev.max_input_channels, dev.max_output_channels, dev.default_samplerate)
            for dev in devices
        )

    def _set_combo_device(self, combo: QtWidgets.QComboBox, device: AudioDevice | None) -> None:
        if device is None:
            return
        for row in range(combo.count()):
            if combo.itemData(row) == device.id:
                combo.setCurrentIndex(row)
                return

    def _selected_device(self, combo: QtWidgets.QComboBox) -> AudioDevice | None:
        device_id = combo.currentData()
        return self.device_by_id.get(int(device_id)) if device_id is not None else None

    def _preset_by_id(self, preset_id: str) -> Preset | None:
        return next((preset for preset in self.presets if preset.id == preset_id), None)

    def _manual_route_changed(self) -> None:
        if self._restoring:
            return
        active_output = default_wasapi_output(self.all_devices)
        self._manual_override_default_id = active_output.id if active_output else self._last_default_output_id
        running = self.engine.snapshot().running
        self._persist_state(was_running=running)
        if running:
            self.start_audio()

    def update_preamp(self, value: int) -> None:
        self.engine.processor.set_preamp_db(value)
        self.preamp_value.setText(f"{value:+d} dB")
        if not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def update_user_volume(self, value: int) -> None:
        scalar = min(1.0, max(0.0, value / 100.0))
        self.engine.processor.set_user_volume(scalar)
        self.user_volume_value.setText(f"{value:d}%")
        if not self._restoring:
            self._persist_state(was_running=self.engine.snapshot().running)

    def start_audio(self) -> None:
        input_device = self._selected_device(self.input_combo)
        output_device = self._selected_device(self.output_combo)
        if input_device is None or output_device is None:
            self._set_status("No WASAPI route", "error")
            return
        try:
            self.engine.start(input_device, output_device)
            self._set_status("Running", "running")
            self._force_auto_start = True
            self._persist_state(was_running=True)
        except Exception as exc:
            self._set_status(str(exc), "error")
            self._persist_state(was_running=False)

    def stop_audio(self) -> None:
        self.engine.stop()
        self._set_status("Stopped", "stopped")
        self._force_auto_start = False
        self._persist_state(was_running=False, auto_start=False)

    def update_ui(self) -> None:
        volume = self.engine.poll_volume()
        snapshot = self.engine.snapshot()
        dsp = snapshot.dsp

        for tile in self.tiles:
            level = float(dsp.channel_levels[tile.source_index]) if tile.source_index < len(dsp.channel_levels) else 0.0
            tile.set_level(level)

        self.left_meter.set_level(dsp.left_meter)
        self.right_meter.set_level(dsp.right_meter)
        self.left_db.setText(f"L: {linear_to_db(dsp.left_meter):+.1f} dB" if dsp.left_meter > 1e-5 else "L: --")
        self.right_db.setText(f"R: {linear_to_db(dsp.right_meter):+.1f} dB" if dsp.right_meter > 1e-5 else "R: --")
        sys_text = "Muted" if volume.muted else f"{volume.scalar * 100:.0f}%"
        source = volume.source if volume.available else "unavailable"
        self.system_volume_label.setText(f"Windows: {sys_text} ({source})")

        if snapshot.running:
            if dsp.clipping:
                self._set_status("Limiting", "warning")
            else:
                self._set_status("Running", "running")

        active_preset = self._preset_by_id(self.active_preset_id)
        self.diag_labels["Preset"].setText(active_preset.name if active_preset else "--")
        self.diag_labels["Route"].setText(snapshot.route)
        self.diag_labels["Channels"].setText(f"{self.channel_config_label()} | {snapshot.input_channels or '--'} in -> 2 out")
        self.diag_labels["Limiter"].setText(f"{dsp.limiter_gain:.3f}" + (" clip" if dsp.clipping else ""))
        active = [tile.name for tile in self.tiles if tile.level > 1e-4]
        self.diag_labels["Active"].setText(", ".join(active) if active else "--")

    def channel_config_label(self) -> str:
        return str(CHANNEL_LAYOUTS[self.channel_config]["label"])

    def _set_status(self, text: str, status: str) -> None:
        if (
            getattr(self, "_status_text", None) == text
            and getattr(self, "_status_state", None) == status
        ):
            return
        self._status_text = text
        self._status_state = status
        self.status_label.setText(text)
        self.status_label.setProperty("status", status)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _persist_state(self, was_running: bool, auto_start: bool | None = None) -> None:
        input_device = self._selected_device(self.input_combo)
        output_device = self._selected_device(self.output_combo)
        save_settings(
            {
                "app_name": APP_DISPLAY_NAME,
                "preset_schema_version": PRESET_SCHEMA_VERSION,
                "input_device": input_device.identity("input") if input_device else None,
                "output_device": output_device.identity("output") if output_device else None,
                "preamp_db": int(self.preamp_slider.value()) if hasattr(self, "preamp_slider") else DEFAULT_PREAMP_DB,
                "user_volume": self.user_volume_slider.value() / 100.0 if hasattr(self, "user_volume_slider") else 1.0,
                "channel_config": self.channel_config,
                "active_preset_id": self.active_preset_id,
                "presets": [preset.to_dict() for preset in self.presets],
                "was_running": bool(was_running),
                "auto_start": bool(self._force_auto_start if auto_start is None else auto_start),
                "smart_switch_enabled": bool(self.smart_switch_checkbox.isChecked()) if hasattr(self, "smart_switch_checkbox") else True,
                "system_boot_autostart": bool(self.system_boot_checkbox.isChecked()) if hasattr(self, "system_boot_checkbox") else False,
            }
        )


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    window = RendererWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
