from __future__ import annotations

import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtGui, QtWidgets
from PyQt5 import QtCore

from downmix_renderer.app import (
    APP_DEFAULT_WINDOW_SIZE,
    BASELINE_RECOVERY_VERSION,
    BASE_STYLE,
    DEVICE_FORCE_REFRESH_INTERVAL,
    DEVICE_POLL_INTERVAL_MS,
    DotBackdropDialog,
    GITHUB_URL,
    ICON_BIG,
    ICON_SMALL,
    DiagnosticsDialog,
    RawMonitorDialog,
    RendererWindow,
    RouteGlassCombo,
    RawChannelTile,
    BedInputVisualizer,
    CapsuleInputVisualizer,
    RoomVisualizer,
    SpatialPage,
    StereoSumMeter,
    SessionRenderToggle,
    SwitchCheckBox,
    ViewStyleCombo,
    VIEW_VISUALIZER_CAPSULE,
    VIEW_VISUALIZER_CLUSTER,
    VIEW_METER_COLOR_STOPS,
    VIEW_NODE_GROUP_COLORS,
    VIEW_SUM_METER_COLOR_STOPS,
    VIEW_SUM_METER_PEAK_YELLOW,
    ChannelTile,
    VUMeter,
    TrimLineEdit,
    WM_SETICON,
    _view_capsule_drive_for_db,
    _view_capsule_palette_for_db,
    _view_node_color,
    _view_oled_signal_color,
    _view_sum_meter_color_for_db,
    apply_windows_window_icons,
    build_details_body,
    clamp_trim_db,
    configure_qt_scaling,
    destroy_windows_icon_handles,
)
from downmix_renderer.constants import APP_DISPLAY_NAME, CHANNEL_LAYOUTS
from downmix_renderer.devices import AudioDevice
from downmix_renderer.presets import preset_from_current


def fake_input() -> AudioDevice:
    return AudioDevice(
        id=1,
        name="CABLE Output (VB-Audio Virtual Cable)",
        hostapi="Windows WASAPI",
        max_input_channels=16,
        max_output_channels=0,
        default_samplerate=48000,
        default_low_input_latency=0.003,
        default_low_output_latency=0.0,
        default_high_input_latency=0.010,
        default_high_output_latency=0.0,
    )


def fake_output() -> AudioDevice:
    return AudioDevice(
        id=2,
        name="Speakers (Realtek(R) Audio)",
        hostapi="Windows WASAPI",
        max_input_channels=0,
        max_output_channels=2,
        default_samplerate=48000,
        default_low_input_latency=0.0,
        default_low_output_latency=0.003,
        default_high_input_latency=0.0,
        default_high_output_latency=0.010,
    )


def fake_usb_output() -> AudioDevice:
    return AudioDevice(
        id=3,
        name="Headphones (Qudelix-5K)",
        hostapi="Windows WASAPI",
        max_input_channels=0,
        max_output_channels=2,
        default_samplerate=48000,
        default_low_input_latency=0.0,
        default_low_output_latency=0.003,
        default_high_input_latency=0.0,
        default_high_output_latency=0.010,
    )


def fake_cable_playback_output() -> AudioDevice:
    return AudioDevice(
        id=4,
        name="CABLE Input (VB-Audio Virtual Cable)",
        hostapi="Windows WASAPI",
        max_input_channels=0,
        max_output_channels=16,
        default_samplerate=48000,
        default_low_input_latency=0.0,
        default_low_output_latency=0.003,
        default_high_input_latency=0.0,
        default_high_output_latency=0.010,
    )


def fake_named_output(device_id: int, name: str) -> AudioDevice:
    return AudioDevice(
        id=device_id,
        name=name,
        hostapi="Windows WASAPI",
        max_input_channels=0,
        max_output_channels=2,
        default_samplerate=48000,
        default_low_input_latency=0.0,
        default_low_output_latency=0.003,
        default_high_input_latency=0.0,
        default_high_output_latency=0.010,
    )


def fake_endpoint_output(device_id: int, name: str, endpoint_id: str) -> AudioDevice:
    return AudioDevice(
        id=device_id,
        name=name,
        hostapi="Windows WASAPI",
        max_input_channels=0,
        max_output_channels=2,
        default_samplerate=48000,
        default_low_input_latency=0.0,
        default_low_output_latency=0.003,
        default_high_input_latency=0.0,
        default_high_output_latency=0.010,
        native_endpoint_id=endpoint_id,
        native_direction="output",
    )


def with_samplerate(device: AudioDevice, samplerate: int) -> AudioDevice:
    return AudioDevice(
        id=device.id,
        name=device.name,
        hostapi=device.hostapi,
        max_input_channels=device.max_input_channels,
        max_output_channels=device.max_output_channels,
        default_samplerate=samplerate,
        default_low_input_latency=device.default_low_input_latency,
        default_low_output_latency=device.default_low_output_latency,
        default_high_input_latency=device.default_high_input_latency,
        default_high_output_latency=device.default_high_output_latency,
        native_endpoint_id=device.native_endpoint_id,
        native_direction=device.native_direction,
        native_is_default=device.native_is_default,
        native_ambiguous=device.native_ambiguous,
    )


class AppUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_window(
        self,
        settings: dict[str, object] | None = None,
        saved_settings: list[dict[str, object]] | None = None,
        devices: list[AudioDevice] | None = None,
        default_output: AudioDevice | None = None,
        list_devices_side_effect: object | None = None,
    ) -> RendererWindow:
        available_devices = devices or [fake_input(), fake_output()]
        default_output = default_output or next(
            (dev for dev in available_devices if dev.max_output_channels >= 2),
            fake_output(),
        )
        def save_capture(payload: dict[str, object]) -> None:
            if saved_settings is not None:
                saved_settings.append(dict(payload))

        patchers = [
            patch.dict(os.environ, {"DOWNMIX_RENDERER_AUDIO_BACKEND": "python"}, clear=False),
            patch("downmix_renderer.app.list_devices", side_effect=list_devices_side_effect)
            if list_devices_side_effect is not None
            else patch("downmix_renderer.app.list_devices", return_value=available_devices),
            patch("downmix_renderer.app.default_wasapi_output", return_value=default_output),
            patch("downmix_renderer.app.load_settings", return_value=settings or {}),
            patch("downmix_renderer.app.save_settings", save_capture),
            patch("downmix_renderer.app.is_system_autostart_enabled", return_value=False),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        window = RendererWindow()
        def cleanup_window() -> None:
            for timer_name in ("timer", "device_timer", "backdrop_timer", "_peq_apply_timer"):
                timer = getattr(window, timer_name, None)
                if timer is not None:
                    timer.stop()
            window.hide()
            window.engine.close()
            window.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup_window)
        return window

    def test_revamped_window_uses_wide_view_and_advanced_pages(self) -> None:
        window = self.make_window()
        view = window.findChild(QtWidgets.QWidget, "viewPage")
        advanced = window.findChild(QtWidgets.QWidget, "advancedPage")

        self.assertIsInstance(view, SpatialPage)
        self.assertIsInstance(advanced, SpatialPage)
        self.assertEqual(window.minimumSize(), APP_DEFAULT_WINDOW_SIZE)
        self.assertEqual(window.maximumSize(), APP_DEFAULT_WINDOW_SIZE)
        self.assertEqual(window.size(), APP_DEFAULT_WINDOW_SIZE)
        self.assertGreater(window.width(), window.height() * 1.5)
        self.assertIsNone(window.findChild(QtWidgets.QWidget, "mainPage"))
        self.assertIsNone(window.findChild(QtWidgets.QWidget, "presetsPage"))

    def test_launch_survives_initial_device_enumeration_failure(self) -> None:
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            list_devices_side_effect=RuntimeError("device api unavailable"),
        )

        self.assertEqual(window.all_devices, [])
        self.assertEqual(window.devices, [])
        self.assertEqual(window.input_combo.count(), 0)
        self.assertEqual(window.output_combo.count(), 0)
        self.assertEqual(window._status_state, "warning")
        self.assertIn("Device scan failed", window._status_text)

    def test_auto_start_waits_for_route_after_initial_device_scan_failure(self) -> None:
        cable_output = fake_cable_playback_output()
        fresh_devices = [fake_input(), cable_output]
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "was_running": True,
            },
            default_output=cable_output,
            list_devices_side_effect=RuntimeError("device api unavailable"),
        )
        starts: list[bool] = []
        window.start_audio = lambda: starts.append(True)

        window._auto_start_if_needed()
        self.assertEqual(starts, [])
        self.assertTrue(window._force_auto_start)

        window._apply_device_poll_result(fresh_devices, was_running=False)

        self.assertEqual(starts, [True])

    def test_close_waits_for_active_device_inventory_worker(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})
        window._closing_with_animation = True
        thread = QtCore.QThread(window)
        window._device_poll_thread = thread
        thread.start()
        def stop_thread() -> None:
            if thread.isRunning():
                thread.quit()
                thread.wait(1000)

        self.addCleanup(stop_thread)
        event = QtGui.QCloseEvent()

        window.closeEvent(event)

        self.assertFalse(event.isAccepted())
        thread.quit()
        self.assertTrue(thread.wait(1000))
        window._device_poll_thread = None

    def test_spatial_page_draws_live_finalised_v3_backdrop_layer(self) -> None:
        window = self.make_window()
        page = window.findChild(QtWidgets.QWidget, "viewPage")

        with patch("downmix_renderer.app.paint_spatial_backdrop") as paint_backdrop:
            page.paintEvent(QtGui.QPaintEvent(page.rect()))

        paint_backdrop.assert_called_once()
        call = paint_backdrop.call_args
        self.assertEqual(call.args[1], window.rect())
        self.assertEqual(call.args[2], window._backdrop_phase)
        self.assertTrue(call.kwargs["lower_balance"])
        self.assertAlmostEqual(call.kwargs["intensity"], 0.52)
        self.assertTrue(call.kwargs["cinematic_depth"])
        self.assertIsInstance(call.kwargs["cursor"], QtCore.QPoint)

    def test_visual_motion_throttles_backdrop_cadence_while_rendering(self) -> None:
        window = self.make_window()

        sync_visual_performance = getattr(window, "_sync_visual_performance", None)
        self.assertIsNotNone(sync_visual_performance)

        self.assertEqual(window.backdrop_timer.interval(), window.IDLE_BACKDROP_INTERVAL_MS)

        sync_visual_performance(rendering=True)

        self.assertEqual(window.backdrop_timer.interval(), window.AUDIO_SAFE_BACKDROP_INTERVAL_MS)

        sync_visual_performance(rendering=False)

        self.assertEqual(window.backdrop_timer.interval(), window.IDLE_BACKDROP_INTERVAL_MS)

    def test_backdrop_phase_advance_matches_finalised_v3(self) -> None:
        window = self.make_window()
        window.show()
        self.addCleanup(window.hide)

        start = window._backdrop_phase
        window._sync_visual_performance(rendering=True)
        window._advance_backdrop()

        self.assertAlmostEqual(window._backdrop_phase, start + 0.022)

    def test_backdrop_advance_updates_page_and_exposed_chrome_only(self) -> None:
        window = self.make_window()
        window.show()
        self.addCleanup(window.hide)
        window.tabs.setCurrentIndex(1)
        self.app.processEvents()
        page = window.findChild(QtWidgets.QWidget, "advancedPage")
        self.assertIsNotNone(page)
        page_rect = QtCore.QRect(page.mapTo(window, QtCore.QPoint(0, 0)), page.size())
        expected_region = QtGui.QRegion(window.rect()) - QtGui.QRegion(page_rect)

        with patch.object(window, "update") as root_update, patch.object(page, "update") as page_update:
            window._advance_backdrop()

        page_update.assert_called_once_with()
        root_update.assert_called_once()
        self.assertEqual(root_update.call_args.args[0].rects(), expected_region.rects())

    def test_window_paints_live_cursor_reactive_backdrop(self) -> None:
        window = self.make_window()
        window.resize(640, 480)

        with patch("downmix_renderer.app.paint_spatial_backdrop") as paint_backdrop:
            window.paintEvent(QtGui.QPaintEvent(window.rect()))

        self.assertEqual(paint_backdrop.call_count, 1)
        call = paint_backdrop.call_args
        self.assertEqual(call.args[1], window.rect())
        self.assertEqual(call.args[2], window._backdrop_phase)
        self.assertTrue(call.kwargs["lower_balance"])
        self.assertAlmostEqual(call.kwargs["intensity"], 0.52)
        self.assertTrue(call.kwargs["cinematic_depth"])
        self.assertIsInstance(call.kwargs["cursor"], QtCore.QPoint)

    def test_window_backdrop_skips_region_covered_by_live_spatial_page(self) -> None:
        window = self.make_window()
        window.show()
        self.addCleanup(window.hide)
        page = window.findChild(QtWidgets.QWidget, "viewPage")
        self.assertIsNotNone(page)
        page_rect = QtCore.QRect(page.mapTo(window, QtCore.QPoint(0, 0)), page.size())

        with patch("downmix_renderer.app.paint_spatial_backdrop") as paint_backdrop:
            window.paintEvent(QtGui.QPaintEvent(window.rect()))

        self.assertGreater(paint_backdrop.call_count, 0)
        for call in paint_backdrop.call_args_list:
            paint_bounds = call.kwargs["paint_bounds"]
            self.assertFalse(paint_bounds.intersects(page_rect), paint_bounds)

    def test_spatial_page_limits_live_backdrop_to_paint_event_rect(self) -> None:
        window = self.make_window()
        window.show()
        self.addCleanup(window.hide)
        page = window.findChild(QtWidgets.QWidget, "viewPage")
        self.assertIsNotNone(page)
        dirty_rect = QtCore.QRect(24, 28, 180, 120)
        expected_bounds = QtCore.QRect(page.mapTo(window, dirty_rect.topLeft()), dirty_rect.size())

        with patch("downmix_renderer.app.paint_spatial_backdrop") as paint_backdrop:
            page.paintEvent(QtGui.QPaintEvent(dirty_rect))

        paint_backdrop.assert_called_once()
        self.assertEqual(paint_backdrop.call_args.kwargs["paint_bounds"], expected_bounds)

    def test_visible_main_controls_are_constructed(self) -> None:
        window = self.make_window()

        self.assertIsNotNone(window.system_boot_checkbox)
        self.assertIsNotNone(window.diagnostics_button)
        self.assertIsNotNone(window.raw_monitor_button)
        self.assertIsNotNone(window.refresh_devices_button)
        self.assertIsNotNone(window.smart_switch_checkbox)
        self.assertIsNotNone(window.surround_fill_checkbox)
        self.assertIsNotNone(window.upmix916_checkbox)
        self.assertIsNotNone(window.sound_enhancer_checkbox)
        self.assertIsNotNone(window.keep_awake_checkbox)
        self.assertIsNotNone(window.sample_rate_combo)
        self.assertEqual(
            [window.sample_rate_combo.itemData(row) for row in range(window.sample_rate_combo.count())],
            ["auto", "48000", "96000", "192000"],
        )
        self.assertIsInstance(window.bed_input_visualizer, BedInputVisualizer)
        self.assertIsInstance(window.capsule_input_visualizer, CapsuleInputVisualizer)
        self.assertIsInstance(window.view_profile_combo, ViewStyleCombo)
        self.assertEqual(window.view_profile_combo.currentText(), "-")
        self.assertIsInstance(window.view_visualizer_combo, ViewStyleCombo)
        self.assertEqual(window.view_visualizer_combo.currentText(), "Spatial")
        self.assertFalse(hasattr(window, "stereo_sum_meter"))
        self.assertIsNotNone(window.info_button)
        self.assertEqual(window.info_button.text(), "")
        self.assertEqual(window.info_button.toolTip(), "Renderer details")
        self.assertEqual(window.surround_fill_checkbox.text(), "7.1 Upmix")
        self.assertEqual(window.sound_enhancer_checkbox.text(), "Sound Enhancer")
        self.assertFalse(hasattr(window, "sound_enhancer_helper"))
        self.assertFalse(hasattr(window, "route_probe_button"))
        self.assertFalse(hasattr(window, "stability_combo"))
        self.assertFalse(hasattr(window, "channel_sanity_checkbox"))
        self.assertFalse(hasattr(window, "user_volume_slider"))

    def test_fixed_input_is_shown_without_visible_dropdown(self) -> None:
        window = self.make_window()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.hide)

        self.assertIsNotNone(window.input_fixed_label)
        self.assertEqual(window.input_fixed_label.text(), "CABLE Input")
        self.assertTrue(window.input_combo.isHidden())
        self.assertEqual(window.output_combo.currentText(), "Speakers (Realtek(R) Audio)")
        self.assertNotIn("48000", window.output_combo.currentText())
        self.assertNotIn("2ch", window.output_combo.currentText())
        self.assertEqual(window.input_fixed_label.minimumHeight(), window.output_combo.minimumHeight())

        window.show()
        self.app.processEvents()
        self.assertAlmostEqual(window.input_fixed_label.width(), window.output_combo.width(), delta=2)

    def test_keep_output_awake_defaults_off_and_persists_as_named_setting(self) -> None:
        saved: list[dict[str, object]] = []
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION}, saved)

        self.assertFalse(window.keep_awake_checkbox.isChecked())
        self.assertFalse(window.engine.keep_awake.active)

        class FakeOutputStream:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

            def start(self) -> None:
                return None

            def stop(self) -> None:
                return None

            def close(self) -> None:
                return None

        with patch("downmix_renderer.audio_engine.sd.OutputStream", FakeOutputStream):
            window.keep_awake_checkbox.setChecked(True)
            self.app.processEvents()

        self.assertTrue(saved)
        self.assertIs(saved[-1]["keep_output_awake"], True)
        self.assertEqual(saved[-1]["user_volume"], 1.0)
        self.assertIs(saved[-1]["channel_sanity_enabled"], False)
        self.assertEqual(saved[-1]["audio_stability"], "ultra")

    def test_sound_enhancer_defaults_off_loads_and_persists_as_named_setting(self) -> None:
        saved: list[dict[str, object]] = []
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "sound_enhancer_enabled": True,
            },
            saved,
        )

        self.assertTrue(window.sound_enhancer_checkbox.isChecked())
        self.assertTrue(window.engine.processor.snapshot().sound_enhancer_enabled)

        window.sound_enhancer_checkbox.setChecked(False)
        self.app.processEvents()

        self.assertTrue(saved)
        self.assertIs(saved[-1]["sound_enhancer_enabled"], False)
        self.assertFalse(window.engine.processor.snapshot().sound_enhancer_enabled)

    def test_keep_output_awake_is_consolidated_into_advanced_automation(self) -> None:
        window = self.make_window()
        advanced = window.findChild(QtWidgets.QWidget, "advancedPage")

        self.assertIn(window.keep_awake_checkbox, advanced.findChildren(SwitchCheckBox))
        self.assertEqual(window.keep_awake_checkbox.text(), "Keep output awake")
        self.assertEqual(window.keep_awake_checkbox.minimumHeight(), 28)
        self.assertIsNone(window.findChild(QtWidgets.QFrame, "keepAwakeCard"))
        self.assertIsNone(window.findChild(QtWidgets.QLabel, "keepAwakeHelper"))

    def test_sample_rate_selector_persists_manual_mode(self) -> None:
        saved: list[dict[str, object]] = []
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "sample_rate_mode": "192000",
            },
            saved,
        )

        self.assertEqual(window.sample_rate_combo.currentData(), "192000")
        row_96 = next(row for row in range(window.sample_rate_combo.count()) if window.sample_rate_combo.itemData(row) == "96000")
        window.sample_rate_combo.setCurrentIndex(row_96)
        self.app.processEvents()

        self.assertTrue(saved)
        self.assertEqual(saved[-1]["sample_rate_mode"], "96000")

    def test_start_audio_passes_selected_sample_rate_mode_to_engine(self) -> None:
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "sample_rate_mode": "96000",
            }
        )
        calls: list[tuple[AudioDevice, AudioDevice, str, str]] = []

        def fake_start(
            input_device: AudioDevice,
            output_device: AudioDevice,
            stream_profile: str,
            sample_rate_mode: str = "auto",
        ) -> None:
            calls.append((input_device, output_device, stream_profile, sample_rate_mode))

        window.engine.start = fake_start
        window.start_audio()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][3], "96000")

    def test_sample_rate_selector_is_visible_at_default_launch_size(self) -> None:
        window = self.make_window()
        window.resize(window.minimumSize())
        window.show()
        window.tabs.setCurrentIndex(0)
        self.app.processEvents()

        self.assertTrue(window.sample_rate_combo.isVisible())
        self.assertGreaterEqual(window.sample_rate_combo.width(), 94)
        self.assertLessEqual(window.sample_rate_combo.width(), 104)
        self.assertEqual(window.refresh_devices_button.text(), "")
        self.assertFalse(window.refresh_devices_button.icon().isNull())
        self.assertLessEqual(window.refresh_devices_button.width(), 50)
        self.assertEqual(
            [window.sample_rate_combo.itemText(index) for index in range(window.sample_rate_combo.count())],
            ["Auto", "48 kHz", "96 kHz", "192 kHz"],
        )

    def test_route_selector_surface_uses_card_tones_without_glass_sheen(self) -> None:
        def style_block(marker: str) -> str:
            start = BASE_STYLE.index(marker)
            end = BASE_STYLE.find("\nQ", start + 1)
            return BASE_STYLE[start:] if end == -1 else BASE_STYLE[start:end]

        route_style = "\n".join(
            style_block(marker)
            for marker in (
                "QFrame#routeLane {",
                "QFrame#routeSegment {",
                "QFrame#routeSegment:hover",
            )
        )

        self.assertNotIn("qlineargradient", route_style)
        self.assertNotIn("rgba(255, 255, 255", route_style)
        self.assertIn("background-color: #030303;", route_style)
        self.assertIn("border: 1px solid #1d1d1d;", route_style)

    def test_refresh_button_uses_clear_icon_and_fast_press_animation(self) -> None:
        window = self.make_window()
        button = window.refresh_devices_button

        self.assertEqual(button.__class__.__name__, "RouteRefreshButton")
        self.assertTrue(getattr(button, "has_premium_refresh_animation", False))
        self.assertEqual(getattr(button, "refresh_icon_style", ""), "css_spinner_fade9234")
        self.assertTrue(getattr(button, "uses_css_spinner_fade9234", False))
        self.assertFalse(getattr(button, "uses_chatgpt_style_spinner", True))
        self.assertEqual(getattr(button, "refresh_spinner_spoke_count", 0), 12)
        self.assertEqual(getattr(button, "refresh_spinner_blade_degrees", 0), 30)
        self.assertAlmostEqual(getattr(button, "refresh_spinner_blade_delay", 0.0), 0.083, places=3)
        self.assertAlmostEqual(getattr(button, "refresh_spinner_em_px", 0.0), 20.0, places=1)
        self.assertAlmostEqual(getattr(button, "refresh_spinner_static_em_px", 0.0), 16.0, places=1)
        self.assertAlmostEqual(getattr(button, "refresh_spinner_blade_left_em", 0.0), 0.4629, places=4)
        self.assertAlmostEqual(getattr(button, "refresh_spinner_blade_width_em", 0.0), 0.074, places=3)
        self.assertAlmostEqual(getattr(button, "refresh_spinner_blade_height_em", 0.0), 0.2777, places=4)
        self.assertAlmostEqual(getattr(button, "refresh_spinner_blade_radius_em", 0.0), 0.0555, places=4)
        self.assertAlmostEqual(getattr(button, "refresh_spinner_transform_origin_y_em", 0.0), -0.2222, places=4)
        self.assertEqual(getattr(button, "refresh_spin_degrees", 0), 360)
        self.assertFalse(getattr(button, "uses_refresh_pulse", True))
        self.assertTrue(getattr(button, "uses_refresh_animation_group", False))
        self.assertTrue(getattr(button, "refresh_press_feedback_enabled", False))
        self.assertTrue(getattr(button, "uses_refresh_wheel_morph", False))
        self.assertEqual(getattr(button, "refresh_wheel_morph_peak", 0.0), 1.0)
        self.assertEqual(getattr(button, "refresh_wheel_hold_start", -1.0), 0.0)
        self.assertEqual(getattr(button, "refresh_wheel_hold_end", 0.0), 1.0)
        self.assertEqual(getattr(button, "refresh_wheel_accent_color", ""), "#d8dcde")
        self.assertEqual(getattr(button, "refresh_spinner_base_color", ""), "#d8dcde")
        self.assertFalse(getattr(button, "refresh_wheel_tint_follows_morph", True))
        self.assertEqual(getattr(button, "refresh_easing_curve_name", ""), "Linear")
        self.assertEqual(getattr(button, "SPINNER_MINIMUM_VISIBLE_MS", 0), 720)
        self.assertEqual(getattr(button, "SPINNER_SETTLE_FADE_MS", -1), 0)
        self.assertEqual(getattr(button, "REFRESH_ANIMATION_MS", 0), getattr(button, "SPINNER_MINIMUM_VISIBLE_MS", -1))
        self.assertEqual(button._refresh_animation.duration(), 720)
        self.assertEqual(button._refresh_animation.easingCurve().type(), QtCore.QEasingCurve.Linear)
        self.assertEqual(button._refresh_press_animation.duration(), 88)

        button.resize(48, 44)
        for progress in (0.0, 0.5):
            button.refreshProgress = progress
            pixmap = QtGui.QPixmap(button.size())
            pixmap.fill(QtCore.Qt.transparent)
            button.render(pixmap)
            image = pixmap.toImage()
            spinner_pixels = 0
            for y in range(4, 40):
                for x in range(8, 40):
                    pixel = image.pixelColor(x, y)
                    if pixel.alpha() and pixel.red() >= 50 and pixel.green() >= 50 and pixel.blue() >= 50:
                        spinner_pixels += 1
            self.assertGreater(spinner_pixels, 20)

        button.animate_refresh()
        self.app.processEvents()

        self.assertGreater(button.refresh_progress, 0.0)
        self.assertGreater(button.refresh_press_depth, 0.0)
        button.refreshProgress = 0.5
        self.assertGreater(button.refresh_wheel_morph, 0.95)
        self.assertEqual(button.refresh_glyph_color().name(), "#d8dcde")
        button.refreshProgress = 0.66
        self.assertGreater(button.refresh_wheel_morph, 0.95)
        button.refreshProgress = 1.0
        self.assertLess(button.refresh_wheel_morph, 0.05)
        self.assertEqual(button.refresh_glyph_color().name(), "#d8dcde")
        self.assertEqual(button.text(), "")
        self.assertFalse(button.icon().isNull())
        button.cancel_refresh_animation()
        self.app.processEvents()
        self.assertEqual(button.refresh_progress, 0.0)
        self.assertEqual(button.refresh_press_depth, 0.0)
        self.assertEqual(button.refreshSettleAlpha, 0.0)

    def test_level_meters_keep_exact_values_with_smooth_visual_ballistics(self) -> None:
        for meter_class in (VUMeter, StereoSumMeter, ChannelTile, RawChannelTile):
            self.assertFalse(getattr(meter_class, "USES_INSTANT_METERING", True))
            self.assertGreater(getattr(meter_class, "METER_ATTACK"), getattr(meter_class, "METER_DECAY"))
            self.assertLess(getattr(meter_class, "METER_ATTACK"), 1.0)
            self.assertLess(getattr(meter_class, "METER_DECAY"), 0.2)

        vu = VUMeter("L")
        channel = ChannelTile("FL", 0)
        raw = RawChannelTile("FL", 0)
        stereo = StereoSumMeter()
        room = RoomVisualizer()
        for widget in (vu, channel, raw, stereo, room):
            self.addCleanup(widget.deleteLater)

        vu.set_level(0.25)
        channel.set_level(0.125)
        raw.set_levels(0.375, 0.125)
        stereo.set_levels(0.5, 0.75)
        room.set_levels([0.0002] + [0.0] * 15)

        self.assertEqual(vu.level, 0.25)
        self.assertLess(vu.display_level, vu.level)
        self.assertEqual(channel.level, 0.125)
        self.assertLess(channel.display_level, channel.level)
        self.assertEqual(raw.peak, 0.375)
        self.assertLess(raw.display_peak, raw.peak)
        self.assertEqual(raw.rms, 0.125)
        self.assertEqual(stereo.left_level, 0.5)
        self.assertEqual(stereo.right_level, 0.75)
        self.assertLess(stereo.left_display, stereo.left_level)
        self.assertLess(stereo.right_display, stereo.right_level)
        self.assertEqual(room.levels[0], 0.0002)
        self.assertLess(room.display_levels[0], room.levels[0])
        self.assertEqual(room.active_speaker_count, 1)
        self.assertEqual(RoomVisualizer.ACTIVE_THRESHOLD, 0.0001)

        channel.set_level(0.0)
        raw.set_levels(0.0, 0.0)
        stereo.set_levels(0.0, 0.0)
        room.set_levels([0.0] * 16)

        self.assertEqual(channel.level, 0.0)
        self.assertGreater(channel.display_level, 0.0)
        self.assertEqual(raw.peak, 0.0)
        self.assertGreater(raw.display_peak, 0.0)
        self.assertEqual(stereo.left_level, 0.0)
        self.assertGreater(stereo.left_display, 0.0)
        self.assertEqual(room.levels[0], 0.0)
        self.assertGreater(room.display_levels[0], 0.0)

    def test_view_visualizer_uses_macos_meter_stops_and_blue_height_family(self) -> None:
        self.assertEqual(
            [stop for stop, _color in VIEW_METER_COLOR_STOPS],
            [0.0, 38.0, 60.0, 72.0, 80.0, 88.0, 94.0, 100.0],
        )
        self.assertEqual(VIEW_SUM_METER_COLOR_STOPS[-1][1], VIEW_SUM_METER_PEAK_YELLOW)
        self.assertEqual(VIEW_SUM_METER_PEAK_YELLOW, (242, 190, 84))
        loud_sum_color = _view_sum_meter_color_for_db(0.0)
        self.assertEqual(
            (loud_sum_color.red(), loud_sum_color.green(), loud_sum_color.blue()),
            VIEW_SUM_METER_PEAK_YELLOW,
        )
        oled_sum_color = _view_oled_signal_color(loud_sum_color, 0.82)
        self.assertLess(oled_sum_color.red(), loud_sum_color.red())
        self.assertLess(oled_sum_color.green(), loud_sum_color.green())
        self.assertIn("_view_oled_signal_color", BedInputVisualizer._draw_sum_meter.__code__.co_names)
        self.assertNotIn("#74501b", BedInputVisualizer._draw_sum_meter.__code__.co_consts)
        self.assertEqual(BedInputVisualizer.NODE_VISUAL_IDLE_DB, BedInputVisualizer.METER_FLOOR_DB)
        self.assertEqual(BedInputVisualizer.INPUT_RENDER_BUCKET_DB, 0.5)
        self.assertEqual(BedInputVisualizer.METER_PEAK_HOLD_SECONDS, 0.008)
        self.assertEqual(BedInputVisualizer.METER_RELEASE_DB_PER_SECOND, 45.0)
        self.assertIn("DashLine", BedInputVisualizer._draw_node.__code__.co_names)
        self.assertIn("setDashPattern", BedInputVisualizer._draw_node.__code__.co_names)
        self.assertIn("_view_meter_fraction", BedInputVisualizer._draw_node.__code__.co_names)
        self.assertIn("_view_oled_signal_color", BedInputVisualizer._draw_node.__code__.co_names)
        self.assertNotIn("_view_capsule_drive_for_db", BedInputVisualizer._draw_node.__code__.co_names)
        for source_name in ("TFL", "TFR", "TBL", "TBR"):
            base = QtGui.QColor(VIEW_NODE_GROUP_COLORS[source_name])
            active = _view_node_color(source_name, -10.0)
            self.assertGreater(base.blue(), base.red() * 2)
            self.assertGreater(active.blue(), active.red())
            self.assertGreater(active.alpha(), 0)

        side = _view_node_color("SL", -24.0)
        middle_top = _view_node_color("TSL", -24.0)
        self.assertGreaterEqual(side.blue(), side.red())
        self.assertGreaterEqual(middle_top.blue(), middle_top.red())
        self.assertNotIn("_draw_header", BedInputVisualizer.paintEvent.__code__.co_names)

    def test_capsule_palette_uses_spatial_db_color_language(self) -> None:
        front_low = _view_capsule_palette_for_db("FL", -80.0)
        front_loud = _view_capsule_palette_for_db("FL", -1.0)
        lfe_loud = _view_capsule_palette_for_db("LFE", -1.0)
        top_loud = _view_capsule_palette_for_db("TFL", -1.0)

        self.assertIsNotNone(front_low)
        self.assertIsNotNone(front_loud)
        self.assertIsNotNone(lfe_loud)
        self.assertIsNotNone(top_loud)
        self.assertLess(_view_capsule_drive_for_db(-90.0), _view_capsule_drive_for_db(-12.0))
        self.assertGreater(front_loud[1].red(), front_low[1].red())
        self.assertGreater(front_loud[1].alpha(), front_low[1].alpha() + 40)
        self.assertGreater(front_loud[1].red(), front_loud[1].green())
        self.assertGreater(lfe_loud[1].green(), lfe_loud[1].red())
        self.assertGreater(top_loud[1].blue(), top_loud[1].red())
        self.assertGreater(front_loud[3].alpha(), front_low[3].alpha())
        self.assertGreater(front_loud[4].alpha(), front_low[4].alpha() + 40)

    def test_view_visualizer_adds_micro_motion_for_steady_generated_channels(self) -> None:
        visualizer = BedInputVisualizer("sharur_9_1_6")
        self.addCleanup(visualizer.deleteLater)
        levels = [0.0] * 16
        levels[10] = 0.2

        visualizer.set_levels(levels, 0.0, 0.0)
        phase = visualizer._motion_phase
        visualizer.set_levels(levels, 0.0, 0.0)

        self.assertNotEqual(visualizer._motion_phase, phase)
        self.assertEqual(visualizer.active_node_count, 1)

    def test_cluster_visualizer_uses_processed_upmix_levels_for_height_channels(self) -> None:
        visualizer = BedInputVisualizer("sharur_9_1_6")
        self.addCleanup(visualizer.deleteLater)
        levels = [0.0] * 16
        levels[10] = 0.42
        levels[12] = 0.31
        levels[14] = 0.22

        visualizer.set_levels(levels, 0.0, 0.0)

        mapping = {str(node["label"]): int(node["source_index"]) for node in visualizer.nodes}
        kind_by_label = {str(node["label"]): str(node["kind"]) for node in visualizer.nodes}
        self.assertEqual(mapping["Ltf"], 10)
        self.assertEqual(mapping["Ltm"], 12)
        self.assertEqual(mapping["Ltr"], 14)
        self.assertEqual(
            [kind_by_label[label] for label in ("Ltf", "Rtf", "Ltm", "Rtm", "Ltr", "Rtr")],
            ["top", "top", "top", "top", "top", "top"],
        )
        self.assertGreater(visualizer.node_display_db[10], BedInputVisualizer.METER_FLOOR_DB)
        self.assertGreater(visualizer.node_display_db[12], BedInputVisualizer.METER_FLOOR_DB)
        self.assertGreater(visualizer.node_display_db[14], BedInputVisualizer.METER_FLOOR_DB)

    def test_route_dropdown_popups_use_themed_route_views(self) -> None:
        window = self.make_window()

        for combo in (window.output_combo, window.sample_rate_combo, window.view_profile_combo, window.view_visualizer_combo):
            self.assertIsInstance(combo, RouteGlassCombo)
            self.assertEqual(combo.objectName(), "routeGlassCombo")
            self.assertEqual(combo.view().objectName(), "routeGlassPopup")
            self.assertEqual(combo.view().frameShape(), QtWidgets.QFrame.NoFrame)
            self.assertGreaterEqual(combo.maxVisibleItems(), 6)
            self.assertIn("QListView#routeGlassPopup", combo.view().styleSheet())
            self.assertIn("rgba(3, 3, 3, 250)", combo.view().styleSheet())
        self.assertIsInstance(window.view_profile_combo, ViewStyleCombo)
        self.assertEqual(window.view_profile_combo.currentText(), "-")
        self.assertEqual(window.view_profile_combo.parentWidget().objectName(), "viewProfileSelector")
        self.assertIsInstance(window.view_visualizer_combo, ViewStyleCombo)
        self.assertFalse(getattr(window.view_visualizer_combo, "has_selected_preview", True))
        self.assertEqual([window.view_visualizer_combo.itemText(row) for row in range(2)], ["Spatial", "Channels"])
        self.assertEqual(window.view_visualizer_combo.parentWidget().objectName(), "viewStyleSelector")

    def test_route_selector_labels_are_symmetrical(self) -> None:
        window = self.make_window()
        window.show()
        self.app.processEvents()

        labels = {
            label.text(): label
            for label in window.findChildren(QtWidgets.QLabel, "routeEyebrow")
            if label.text() in {"Input device", "Output device", "Sample rate"}
        }

        self.assertEqual(set(labels), {"Input device", "Output device", "Sample rate"})
        widths = {label.width() for label in labels.values()}
        tops = [label.mapTo(window, QtCore.QPoint(0, 0)).y() for label in labels.values()]
        centers = [label.mapTo(window, QtCore.QPoint(0, label.height() // 2)).y() for label in labels.values()]
        route_lane = window.findChild(QtWidgets.QFrame, "routeLane")
        self.assertIsNotNone(route_lane)
        view_mode_row = window.findChild(QtWidgets.QWidget, "viewModeRow")
        self.assertIsNotNone(view_mode_row)
        self.assertEqual(route_lane.findChildren(QtWidgets.QPushButton, "viewModeButton"), [])
        self.assertEqual(len(view_mode_row.findChildren(QtWidgets.QPushButton, "viewModeButton")), 2)
        self.assertNotIn("View", [label.text() for label in view_mode_row.findChildren(QtWidgets.QLabel, "routeEyebrow")])
        mode_layout = view_mode_row.layout()
        control_order = [
            mode_layout.itemAt(index).widget().objectName()
            for index in range(mode_layout.count())
            if mode_layout.itemAt(index).widget() is not None
        ]
        self.assertEqual(control_order, ["viewModeGroup", "viewProfileSelector", "viewStyleSelector"])
        self.assertEqual(window.view_visualizer_combo.width(), ViewStyleCombo.fixed_premium_width)
        self.assertEqual(window.view_profile_combo.width(), ViewStyleCombo.fixed_premium_width)
        route_layout = route_lane.layout()
        route_order: list[str] = []
        for index in range(route_layout.count()):
            widget = route_layout.itemAt(index).widget()
            if widget is window.render_toggle_button:
                route_order.append("Render")
                continue
            if widget is window.refresh_devices_button:
                route_order.append("Refresh devices")
                continue
            label = widget.findChild(QtWidgets.QLabel, "routeEyebrow") if widget is not None else None
            if label is not None:
                route_order.append(label.text())

        self.assertEqual(widths, {88})
        self.assertEqual(route_order, ["Input device", "Output device", "Sample rate", "Render", "Refresh devices"])
        self.assertLessEqual(max(tops) - min(tops), 1)
        self.assertLessEqual(max(centers) - min(centers), 1)
        self.assertGreaterEqual(window.sample_rate_combo.width(), 94)
        self.assertLessEqual(window.sample_rate_combo.width(), 104)
        self.assertGreater(window.output_combo.width(), window.sample_rate_combo.width() * 2)

    def test_route_dropdowns_show_available_items_without_scroll_spacing(self) -> None:
        devices = [fake_input(), fake_output(), fake_usb_output()]
        devices.extend(fake_named_output(10 + index, f"Monitor Output {index}") for index in range(20))
        window = self.make_window(devices=devices)
        window.show()
        self.app.processEvents()

        self.assertGreater(window.output_combo.count(), 6)
        for combo in (window.output_combo, window.sample_rate_combo):
            combo.showPopup()
            self.app.processEvents()
            popup = combo.view().window()
            desired_height = combo.count() * combo.POPUP_ITEM_HEIGHT + combo.POPUP_VERTICAL_PADDING
            private_scrollers = [
                child
                for child in popup.findChildren(QtWidgets.QWidget)
                if child.metaObject().className() == "QComboBoxPrivateScroller"
            ]

            self.assertGreaterEqual(combo.maxVisibleItems(), combo.count())
            self.assertLessEqual(combo.view().spacing(), 1)
            self.assertIn("min-height: 20px", combo.view().styleSheet())
            self.assertIn("padding: 2px 9px", combo.view().styleSheet())
            self.assertFalse(any(scroller.isVisible() for scroller in private_scrollers))
            if popup.height() >= desired_height:
                self.assertEqual(combo.view().verticalScrollBarPolicy(), QtCore.Qt.ScrollBarAlwaysOff)
                self.assertGreaterEqual(
                    combo.view().viewport().height(),
                    combo.count() * combo.POPUP_ITEM_HEIGHT,
                )
            combo.hidePopup()
            self.app.processEvents()

    def test_route_dropdowns_use_smoothed_item_feedback(self) -> None:
        window = self.make_window()

        for combo in (window.output_combo, window.sample_rate_combo):
            delegate = combo.view().itemDelegate()
            self.assertEqual(delegate.__class__.__name__, "RouteGlassItemDelegate")
            self.assertTrue(getattr(delegate, "has_smooth_feedback", False))
            self.assertTrue(getattr(delegate, "has_keyboard_navigation_feedback", False))
            self.assertTrue(getattr(combo, "has_premium_open_animation", False))
            self.assertTrue(getattr(combo, "has_arrow_motion_feedback", False))
            self.assertEqual(combo.focusPolicy(), QtCore.Qt.StrongFocus)
            self.assertLessEqual(combo.OPEN_ANIMATION_MS, 130)
            self.assertGreaterEqual(combo.OPEN_ANIMATION_MS, 100)
            self.assertLessEqual(combo.ARROW_ANIMATION_MS, 130)

            combo.showPopup()
            self.app.processEvents()
            self.assertGreater(combo.open_progress, 0.0)
            self.assertLessEqual(combo.open_progress, 1.0)
            combo.hidePopup()
            self.app.processEvents()
            self.assertLess(combo.open_progress, 1.0)

    def test_route_dropdown_releases_delegate_filters_before_qt_shutdown(self) -> None:
        combo = RouteGlassCombo()
        self.addCleanup(combo.deleteLater)
        delegate = combo._popup_delegate
        detach_calls: list[bool] = []
        delegate.detach = lambda: detach_calls.append(True)

        combo._release_popup_delegate()

        self.assertEqual(detach_calls, [True])
        self.assertIsNone(combo._popup_delegate)

    def test_saved_keep_output_awake_starts_silent_stream_when_renderer_is_stopped(self) -> None:
        opened: list[object] = []

        class FakeOutputStream:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs
                self.started = False
                self.stopped = False
                opened.append(self)

            def start(self) -> None:
                self.started = True

            def stop(self) -> None:
                self.stopped = True

            def close(self) -> None:
                return None

        with patch("downmix_renderer.audio_engine.sd.OutputStream", FakeOutputStream):
            window = self.make_window(
                {
                    "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                    "keep_output_awake": True,
                }
            )

        self.assertTrue(window.keep_awake_checkbox.isChecked())
        self.assertTrue(window.engine.keep_awake.active)
        self.assertEqual(opened[0].kwargs["device"], fake_output().id)
        self.assertEqual(opened[0].kwargs["channels"], 2)
        self.assertTrue(opened[0].started)

    def test_renderer_page_removes_large_downmix_renderer_title(self) -> None:
        window = self.make_window()
        visible_text = "\n".join(label.text() for label in window.findChildren(QtWidgets.QLabel))

        self.assertEqual(APP_DISPLAY_NAME, "Downmix Renderer")
        self.assertEqual(window.windowTitle(), "Downmix Renderer")
        self.assertIsNone(window.findChild(QtWidgets.QWidget, "rendererTitle"))
        self.assertNotIn("Downmix Renderer", visible_text)
        self.assertNotIn("Downmix Renderer " + "7.1", visible_text)
        self.assertNotIn("WASAPI stereo render path | 48 kHz | 256 samples", visible_text)

    def test_header_keeps_premium_view_and_advanced_tabs(self) -> None:
        window = self.make_window()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.hide)
        window.show()
        self.app.processEvents()

        self.assertEqual(window.tabs.tabText(0), "View")
        self.assertEqual(window.tabs.tabText(1), "Advanced")
        self.assertEqual(window.tabs.count(), 2)
        self.assertEqual(window.tabs.currentIndex(), 0)
        self.assertIs(window.tabs.currentWidget(), window.findChild(QtWidgets.QWidget, "viewPage"))
        self.assertEqual(window.header_status.text(), "Shared WASAPI | Ready")
        self.assertEqual(window.github_button.toolTip(), "Open project on GitHub")
        self.assertEqual(window.github_button.objectName(), "headerIconButton")
        self.assertFalse(hasattr(window, "get_started_button"))
        self.assertFalse(hasattr(window, "show_get_started"))
        self.assertEqual(GITHUB_URL, "https://github.com/prospeck/downmix-renderer-7.1-windows.git")
        self.assertFalse(hasattr(window, "header_rail"))
        self.assertIsNone(window.findChild(QtWidgets.QFrame, "navRail"))
        self.assertGreaterEqual(window.tabs.geometry().top(), 8)
        self.assertEqual(window.tabs.tabBar().height(), 56)
        self.assertEqual(window.info_button.width(), window.github_button.width())
        self.assertEqual(window.info_button.height(), window.github_button.height())
        self.assertEqual(window.github_button.width(), 34)
        self.assertEqual(window.github_button.height(), 34)
        self.assertGreaterEqual(window.github_button.geometry().top(), 8)

    def test_view_page_contains_reference_bed_visualizer(self) -> None:
        window = self.make_window({"channel_config": "sharur_9_1_6"})
        page = window.findChild(QtWidgets.QWidget, "viewPage")
        visualizer = window.bed_input_visualizer
        capsule = window.capsule_input_visualizer
        mapping = {str(node["label"]): int(node["source_index"]) for node in visualizer.nodes}
        capsule_mapping = {str(node["label"]): int(node["source_index"]) for node in capsule.nodes}

        self.assertIsNotNone(page)
        self.assertIsInstance(visualizer, BedInputVisualizer)
        self.assertIsInstance(capsule, CapsuleInputVisualizer)
        self.assertIn(visualizer, page.findChildren(BedInputVisualizer))
        self.assertIn(capsule, page.findChildren(CapsuleInputVisualizer))
        self.assertIs(window.visualizer_stack.currentWidget(), visualizer)
        self.assertEqual(window.view_visualizer_combo.currentData(), VIEW_VISUALIZER_CLUSTER)
        self.assertEqual(
            [window.view_visualizer_combo.itemData(row) for row in range(window.view_visualizer_combo.count())],
            [VIEW_VISUALIZER_CLUSTER, VIEW_VISUALIZER_CAPSULE],
        )
        self.assertEqual(len(visualizer.nodes), 16)
        self.assertEqual(
            mapping,
            {
                "L": 0,
                "R": 1,
                "C": 2,
                "LFE": 3,
                "Lw": 4,
                "Rw": 5,
                "Lrs": 6,
                "Rrs": 7,
                "Ls": 8,
                "Rs": 9,
                "Ltf": 10,
                "Rtf": 11,
                "Ltm": 12,
                "Rtm": 13,
                "Ltr": 14,
                "Rtr": 15,
            },
        )
        self.assertEqual(capsule_mapping, mapping)
        self.assertEqual(
            capsule.capsule_rows,
            (
                ("L", "R", "C", "LFE", "Ls", "Rs", "Lrs", "Rrs"),
                ("Lw", "Rw", "Ltf", "Rtf", "Ltm", "Rtm", "Ltr", "Rtr"),
            ),
        )
        self.assertEqual(CapsuleInputVisualizer.CAPSULE_WIDTH, 76.0)
        self.assertEqual(CapsuleInputVisualizer.CAPSULE_HEIGHT, 42.0)
        self.assertNotIn("Active bed inputs", "\n".join(label.text() for label in page.findChildren(QtWidgets.QLabel)))
        self.assertEqual(BedInputVisualizer.METER_FLOOR_DB, -160.0)
        self.assertEqual(BedInputVisualizer.SUM_METER_TICK_STEP_DB, 10)
        self.assertIn(window.output_combo, page.findChildren(QtWidgets.QComboBox))
        self.assertIn(window.render_toggle_button, page.findChildren(QtWidgets.QPushButton))
        self.assertFalse(hasattr(window, "start_render_button"))
        self.assertFalse(hasattr(window, "stop_render_button"))
        self.assertIsNone(window.findChild(QtWidgets.QFrame, "viewControlStrip"))
        self.assertIsNone(window.findChild(QtWidgets.QFrame, "viewModeSegment"))
        self.assertEqual(window.mode_buttons["windows_7_1"].text(), "7.1")
        self.assertEqual(window.mode_buttons["sharur_9_1_6"].text(), "9.1.6")

    def test_capsule_visualizer_keeps_active_signal_color_inside_capsule(self) -> None:
        visualizer = CapsuleInputVisualizer("sharur_9_1_6")
        self.addCleanup(visualizer.deleteLater)
        visualizer.resize(1000, 220)
        levels = [0.0] * 16
        levels[0] = 1.0
        visualizer.set_levels(levels, 0.0, 0.0)

        image = QtGui.QImage(visualizer.size(), QtGui.QImage.Format_ARGB32)
        image.fill(QtGui.QColor("#000000"))
        visualizer.render(image)

        content = QtCore.QRectF(visualizer.rect()).adjusted(18, 8, -18, -18)
        stage, _left_meter, _right_meter = visualizer._layout_rects(content)
        first_row = visualizer.capsule_rows[0]
        total_width = visualizer.CAPSULE_WIDTH * len(first_row) + visualizer.CAPSULE_GAP * (len(first_row) - 1)
        capsule_x = stage.center().x() - total_width / 2.0
        block_height = visualizer.CAPSULE_HEIGHT * 2.0 + visualizer.ROW_GAP
        capsule_y = stage.center().y() - block_height / 2.0
        sample_y = int(round(capsule_y + visualizer.CAPSULE_HEIGHT / 2.0))

        inside = image.pixelColor(int(round(capsule_x + 10.0)), sample_y)
        outside = image.pixelColor(int(round(capsule_x - 3.0)), sample_y)

        self.assertGreater(inside.red(), inside.green())
        self.assertGreater(inside.red(), inside.blue())
        self.assertLessEqual(outside.red(), max(outside.green(), outside.blue()) + 8)

    def test_capsule_visualizer_renders_louder_levels_with_more_energy(self) -> None:
        visualizer = CapsuleInputVisualizer("sharur_9_1_6")
        self.addCleanup(visualizer.deleteLater)
        visualizer.resize(1000, 220)

        def sampled_capsule_color(level: float) -> QtGui.QColor:
            levels = [0.0] * 16
            levels[0] = level
            visualizer.set_levels(levels, 0.0, 0.0)
            image = QtGui.QImage(visualizer.size(), QtGui.QImage.Format_ARGB32)
            image.fill(QtGui.QColor("#000000"))
            visualizer.render(image)
            content = QtCore.QRectF(visualizer.rect()).adjusted(18, 8, -18, -18)
            stage, _left_meter, _right_meter = visualizer._layout_rects(content)
            first_row = visualizer.capsule_rows[0]
            total_width = visualizer.CAPSULE_WIDTH * len(first_row) + visualizer.CAPSULE_GAP * (len(first_row) - 1)
            capsule_x = stage.center().x() - total_width / 2.0
            block_height = visualizer.CAPSULE_HEIGHT * 2.0 + visualizer.ROW_GAP
            capsule_y = stage.center().y() - block_height / 2.0
            return image.pixelColor(int(round(capsule_x + 10.0)), int(round(capsule_y + visualizer.CAPSULE_HEIGHT / 2.0)))

        quiet = sampled_capsule_color(0.001)
        loud = sampled_capsule_color(1.0)

        self.assertGreater(loud.red(), quiet.red() + 20)
        self.assertGreater(loud.red() + loud.green() + loud.blue(), quiet.red() + quiet.green() + quiet.blue() + 20)

    def test_spatial_visualizer_keeps_original_meter_fraction_response_with_oled_tone(self) -> None:
        visualizer = BedInputVisualizer("sharur_9_1_6")
        self.addCleanup(visualizer.deleteLater)
        visualizer.resize(1000, 260)

        def sampled_node_color(level: float) -> QtGui.QColor:
            levels = [0.0] * 16
            levels[0] = level
            visualizer.set_levels(levels, 0.0, 0.0)
            image = QtGui.QImage(visualizer.size(), QtGui.QImage.Format_ARGB32)
            image.fill(QtGui.QColor("#000000"))
            visualizer.render(image)
            content = QtCore.QRectF(visualizer.rect()).adjusted(18, 8, -18, -18)
            stage, _left_meter, _right_meter = visualizer._layout_rects(content)
            node = next(node for node in visualizer.nodes if str(node["label"]) == "L")
            point = QtCore.QPointF(
                stage.left() + float(node["x"]) * 0.01 * stage.width(),
                stage.top() + float(node["y"]) * 0.01 * stage.height(),
            )
            size = max(29.0, min(44.0, stage.width() * 0.052))
            return image.pixelColor(int(round(point.x() - size * 0.28)), int(round(point.y())))

        quiet = sampled_node_color(0.001)
        loud = sampled_node_color(1.0)

        self.assertGreater(loud.red(), quiet.red() + 4)
        self.assertLess(loud.green(), quiet.green())
        self.assertLess(loud.blue(), quiet.blue())

    def test_view_visualizer_selector_switches_stack_and_persists_choice(self) -> None:
        saved: list[dict[str, object]] = []
        window = self.make_window({"channel_config": "sharur_9_1_6"}, saved)

        self.assertIs(window.visualizer_stack.currentWidget(), window.bed_input_visualizer)

        window.view_visualizer_combo.setCurrentIndex(1)
        self.app.processEvents()

        self.assertEqual(window.view_visualizer_mode, VIEW_VISUALIZER_CAPSULE)
        self.assertIs(window.visualizer_stack.currentWidget(), window.capsule_input_visualizer)
        self.assertEqual(window.channel_config, "sharur_9_1_6")
        self.assertEqual(saved[-1]["view_visualizer_mode"], VIEW_VISUALIZER_CAPSULE)

        window.view_visualizer_combo.setCurrentIndex(0)
        self.app.processEvents()

        self.assertEqual(window.view_visualizer_mode, VIEW_VISUALIZER_CLUSTER)
        self.assertIs(window.visualizer_stack.currentWidget(), window.bed_input_visualizer)
        self.assertEqual(saved[-1]["view_visualizer_mode"], VIEW_VISUALIZER_CLUSTER)

    def test_saved_capsule_visualizer_mode_restores_without_changing_layout(self) -> None:
        window = self.make_window(
            {
                "channel_config": "windows_7_1",
                "view_visualizer_mode": VIEW_VISUALIZER_CAPSULE,
            }
        )

        self.assertEqual(window.view_visualizer_combo.currentData(), VIEW_VISUALIZER_CAPSULE)
        self.assertEqual(window.view_visualizer_combo.currentText(), "Channels")
        self.assertIs(window.visualizer_stack.currentWidget(), window.capsule_input_visualizer)
        self.assertEqual(window.channel_config, "windows_7_1")
        self.assertEqual(window.capsule_input_visualizer.capsule_rows, (("L", "R", "C", "LFE"), ("Ls", "Rs", "Lrs", "Rrs")))
        self.assertEqual(window.capsule_input_visualizer.CAPSULE_WIDTH, CapsuleInputVisualizer.CAPSULE_WIDTH)
        self.assertEqual(window.capsule_input_visualizer.CAPSULE_HEIGHT, CapsuleInputVisualizer.CAPSULE_HEIGHT)

    def test_view_page_updates_from_effective_dsp_channels_and_sum_meters(self) -> None:
        window = self.make_window({"channel_config": "sharur_9_1_6"})
        raw_levels = [0.0] * 16
        channel_levels = [0.0] * 16
        rms_values = [0.0] * 16
        channel_levels[10] = 0.5
        channel_levels[4] = 0.25
        raw_levels[0] = 0.75
        dsp = SimpleNamespace(
            channel_levels=channel_levels,
            channel_rms=rms_values,
            raw_channel_levels=raw_levels,
            raw_channel_rms=rms_values,
            left_meter=0.625,
            right_meter=1.0,
            limiter_gain=1.0,
            clipping=False,
            sound_enhancer_enabled=False,
            sound_enhancer_gain=1.0,
            surround_fill_enabled=False,
            surround_fill_active=False,
            upmix_9_1_6_enabled=False,
            upmix_9_1_6_active=False,
        )
        snapshot = SimpleNamespace(
            running=True,
            status="Running",
            route="Test route",
            input_channels=16,
            stream_latency=None,
            stream_profile="ultra",
            sample_rate=48000,
            sample_rate_mode="auto",
            callback_status_count=0,
            callback_status="",
            dsp_error_count=0,
            cpu_load=0.0,
            dsp=dsp,
        )
        volume = SimpleNamespace(muted=False, scalar=1.0, available=True, source="endpoint")
        window.engine.snapshot = lambda: snapshot
        window.engine.poll_volume = lambda: volume

        window.update_ui()

        visualizer = window.bed_input_visualizer
        capsule = window.capsule_input_visualizer
        self.assertEqual(visualizer.node_levels[10], 0.5)
        self.assertEqual(visualizer.node_levels[4], 0.25)
        self.assertGreater(visualizer.node_display_db[10], BedInputVisualizer.METER_FLOOR_DB)
        self.assertEqual(visualizer.active_node_count, 2)
        self.assertEqual(visualizer.left_level, 0.625)
        self.assertEqual(visualizer.right_level, 1.0)
        self.assertTrue(visualizer.right_clipping)
        self.assertFalse(visualizer.left_clipping)
        self.assertEqual(capsule.node_levels[10], visualizer.node_levels[10])
        self.assertEqual(capsule.node_levels[4], visualizer.node_levels[4])
        self.assertEqual(capsule.left_level, visualizer.left_level)
        self.assertEqual(capsule.right_level, visualizer.right_level)
        self.assertEqual(capsule.active_node_count, visualizer.active_node_count)

    def test_view_sum_clip_is_per_channel_and_only_latches_at_full_scale(self) -> None:
        visualizer = BedInputVisualizer("sharur_9_1_6")
        self.addCleanup(visualizer.deleteLater)

        visualizer.set_levels([0.0] * 16, 0.98, 0.4, clipping=True)
        self.assertFalse(visualizer.left_clipping)
        self.assertFalse(visualizer.right_clipping)

        visualizer.set_levels([0.0] * 16, 1.0, 0.4, clipping=False)
        self.assertTrue(visualizer.left_clipping)
        self.assertFalse(visualizer.right_clipping)

    def test_header_status_uses_shared_wasapi_wording(self) -> None:
        window = self.make_window()

        window._update_header_status(SimpleNamespace(running=False))
        self.assertEqual(window.header_status.text(), "Shared WASAPI | Ready")
        window._update_header_status(SimpleNamespace(running=True, stream_profile="ultra", callback_status_count=7))
        self.assertEqual(window.header_status.text(), "Shared WASAPI | ULTRA Mode")

        widgets = list(window.findChildren(QtWidgets.QLabel))
        widgets += list(window.findChildren(QtWidgets.QPushButton))
        visible_text = "\n".join(widget.text() for widget in widgets)
        visible_text += "\n".join(widget.toolTip() for widget in widgets)
        self.assertNotIn("Exclusive WASAPI", visible_text)
        self.assertNotIn("Get Started", visible_text)
        self.assertNotIn("Get started", visible_text)

    def test_advanced_page_consolidates_settings_diagnostics_and_presets(self) -> None:
        window = self.make_window()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.hide)
        window.show()
        window.tabs.setCurrentIndex(1)
        self.app.processEvents()

        advanced = window.findChild(QtWidgets.QWidget, "advancedPage")
        view = window.findChild(QtWidgets.QWidget, "viewPage")
        top_row = window.findChild(QtWidgets.QWidget, "advancedTopRow")
        profile_manager = window.findChild(QtWidgets.QFrame, "profileManagerCard")
        automation_card = window.smart_switch_checkbox.parentWidget()
        while automation_card is not None and automation_card.objectName() != "card":
            automation_card = automation_card.parentWidget()
        diagnostics = window.diagnostics_button.parentWidget()
        self.assertIn(window.preamp_slider, advanced.findChildren(QtWidgets.QSlider))
        self.assertIn(window.smart_switch_checkbox, advanced.findChildren(SwitchCheckBox))
        self.assertIn(window.diagnostics_button, advanced.findChildren(QtWidgets.QPushButton))
        self.assertIn(window.raw_monitor_button, advanced.findChildren(QtWidgets.QPushButton))
        self.assertIn(window.new_preset_button, advanced.findChildren(QtWidgets.QPushButton))
        self.assertNotIn(window.output_combo, advanced.findChildren(QtWidgets.QComboBox))
        self.assertIn(window.output_combo, view.findChildren(QtWidgets.QComboBox))
        self.assertIsNotNone(top_row)
        self.assertIsNotNone(profile_manager)
        self.assertIsNotNone(automation_card)
        self.assertIsNotNone(diagnostics)
        self.assertEqual([label.text() for label in diagnostics.findChildren(QtWidgets.QLabel, "section")], [])
        controls_card = window.preamp_slider.parentWidget()
        while controls_card is not None and controls_card.objectName() != "card":
            controls_card = controls_card.parentWidget()
        self.assertIsNotNone(controls_card)
        self.assertGreater(automation_card.geometry().left(), controls_card.geometry().right())
        self.assertGreater(profile_manager.geometry().left(), automation_card.geometry().right())
        self.assertGreater(diagnostics.geometry().left(), profile_manager.geometry().right())
        self.assertAlmostEqual(controls_card.height(), automation_card.height(), delta=8)
        self.assertAlmostEqual(controls_card.height(), profile_manager.height(), delta=8)
        self.assertAlmostEqual(diagnostics.height(), profile_manager.height(), delta=8)
        self.assertFalse(hasattr(window, "room_visualizer"))
        self.assertFalse(hasattr(window, "stereo_sum_meter"))

    def test_advanced_page_uses_one_outer_scroll(self) -> None:
        window = self.make_window()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.hide)
        window.resize(window.minimumSize())
        window.show()
        window.tabs.setCurrentIndex(1)
        self.app.processEvents()

        presets_page = window.findChild(QtWidgets.QWidget, "advancedPage")
        outer_scrolls = [
            scroll for scroll in presets_page.findChildren(QtWidgets.QScrollArea)
            if scroll.parentWidget() is presets_page
        ]
        self.assertEqual(len(outer_scrolls), 1)
        self.assertGreaterEqual(outer_scrolls[0].verticalScrollBar().maximum(), 0)

    def test_view_visualizer_replaces_renderer_channel_field(self) -> None:
        window = self.make_window()

        self.assertIsInstance(window.bed_input_visualizer, BedInputVisualizer)
        self.assertIsInstance(window.capsule_input_visualizer, CapsuleInputVisualizer)
        self.assertEqual(len(window.bed_input_visualizer.nodes), 8)
        self.assertEqual(len(window.capsule_input_visualizer.nodes), 8)
        self.assertEqual(window.tiles, [])

        window.set_channel_config("sharur_9_1_6")
        self.assertEqual(len(window.bed_input_visualizer.nodes), 16)
        self.assertEqual(len(window.capsule_input_visualizer.nodes), 16)
        self.assertEqual(
            window.capsule_input_visualizer.capsule_rows,
            (
                ("L", "R", "C", "LFE", "Ls", "Rs", "Lrs", "Rrs"),
                ("Lw", "Rw", "Ltf", "Rtf", "Ltm", "Rtm", "Ltr", "Rtr"),
            ),
        )
        self.assertFalse(hasattr(window, "room_visualizer"))

    def test_stereo_sum_meter_latches_clip_from_final_sample_peaks(self) -> None:
        meter = StereoSumMeter()
        self.addCleanup(meter.deleteLater)

        self.assertEqual(meter.CHANNEL_LABELS, ("Left", "Right"))
        self.assertEqual(meter.HELPER_TEXT, "Meters show recent sample-peak level of the final stereo output channels.")
        self.assertFalse(meter.SHOW_CLIP_BADGES)
        self.assertEqual(meter.HELPER_FONT_SIZE, 9)
        self.assertGreaterEqual(meter.CHANNEL_PANEL_HEIGHT, 88)
        self.assertGreaterEqual(meter.TICK_LABEL_OFFSET, 15)

        meter.set_levels(0.25, 0.75)
        self.assertFalse(meter.left_clipping)
        self.assertFalse(meter.right_clipping)

        meter.set_levels(1.0, 0.2)
        self.assertTrue(meter.left_clipping)
        self.assertFalse(meter.right_clipping)

    def test_view_stereo_sum_meters_are_integrated_into_visualizer(self) -> None:
        window = self.make_window()
        window.show()
        self.app.processEvents()

        self.assertEqual(window.bed_input_visualizer.left_level, 0.0)
        self.assertEqual(window.bed_input_visualizer.right_level, 0.0)
        self.assertFalse(hasattr(window, "stereo_sum_meter"))

    def test_route_and_meter_surfaces_live_only_on_view(self) -> None:
        window = self.make_window()
        view = window.findChild(QtWidgets.QWidget, "viewPage")
        advanced = window.findChild(QtWidgets.QWidget, "advancedPage")

        self.assertIn(window.output_combo, view.findChildren(QtWidgets.QComboBox))
        self.assertIn(window.bed_input_visualizer, view.findChildren(BedInputVisualizer))
        self.assertIn(window.capsule_input_visualizer, view.findChildren(CapsuleInputVisualizer))
        self.assertIn(window.view_profile_combo, view.findChildren(QtWidgets.QComboBox))
        self.assertIn(window.view_visualizer_combo, view.findChildren(QtWidgets.QComboBox))
        self.assertNotIn(window.output_combo, advanced.findChildren(QtWidgets.QComboBox))
        self.assertNotIn(window.view_profile_combo, advanced.findChildren(QtWidgets.QComboBox))
        self.assertNotIn(window.view_visualizer_combo, advanced.findChildren(QtWidgets.QComboBox))
        self.assertIn(window.profile_preset_combo, advanced.findChildren(QtWidgets.QComboBox))
        self.assertIn(window.raw_monitor_button, advanced.findChildren(QtWidgets.QPushButton))

    def test_view_session_status_has_distinct_premium_treatment(self) -> None:
        window = self.make_window()

        self.assertIsInstance(window.render_toggle_button, SessionRenderToggle)
        self.assertEqual(window.render_toggle_button.objectName(), "sessionRenderToggle")
        self.assertEqual(window.render_toggle_button.text(), "Render")
        self.assertEqual(window.render_toggle_button.width(), 176)
        self.assertFalse(hasattr(window, "view_render_status"))
        self.assertEqual(window.smart_switch_checkbox.objectName(), "switchControl")
        self.assertEqual(window.system_boot_checkbox.objectName(), "switchControl")

        calls: list[str] = []
        window.start_audio = lambda: calls.append("start")
        window.stop_audio = lambda: calls.append("stop")
        window.engine.snapshot = lambda: SimpleNamespace(running=False)
        window._toggle_render_session()
        window.engine.snapshot = lambda: SimpleNamespace(running=True)
        window._toggle_render_session()
        self.assertEqual(calls, ["start", "stop"])

    def test_advanced_page_builds_peq_controls_with_profile_labels(self) -> None:
        window = self.make_window()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.hide)
        window.show()
        window.tabs.setCurrentIndex(1)
        self.app.processEvents()

        self.assertEqual(window.lr_swap_checkbox.objectName(), "switchControl")
        self.assertEqual(window.global_peq_checkbox.objectName(), "switchControl")
        self.assertEqual(window.speaker_eq_checkbox.objectName(), "switchControl")
        self.assertEqual(window.global_peq_text.objectName(), "peqText")
        self.assertEqual(window.speaker_eq_text.objectName(), "peqText")
        self.assertEqual(window.global_peq_load_button.objectName(), "peqAction")
        self.assertEqual(window.speaker_eq_load_button.objectName(), "peqAction")
        section_labels = [
            label.text()
            for label in window.findChild(QtWidgets.QWidget, "advancedPage").findChildren(QtWidgets.QLabel, "section")
        ]
        section_text = "\n".join(section_labels)
        self.assertIn("AUDIO CONTROLS", section_labels)
        self.assertIn("SYSTEM AUTOMATION", section_labels)
        self.assertIn("PROFILES", section_labels)
        self.assertNotIn("DIAGNOSTICS", section_labels)
        self.assertNotIn("SESSION SNAPSHOT", section_labels)
        self.assertNotIn("SAVED PROFILES", section_text)
        self.assertNotIn("PROFILE CONTROL", section_text)
        self.assertIn("OUTPUT ROUTING AND PEQ", section_text)
        self.assertIn("CHANNEL TRIM", section_text)
        self.assertIn("L-R CORRECTION CHANNEL MAPPING", section_text)
        self.assertEqual(window.tabs.tabText(1), "Advanced")
        self.assertEqual(window.lr_swap_panel.geometry().top(), window.channel_trim_panel.geometry().top())
        self.assertAlmostEqual(window.lr_swap_panel.width(), window.channel_trim_panel.width(), delta=1)
        self.assertEqual(window.lr_swap_panel.height(), window.channel_trim_panel.height())
        self.assertGreater(window.channel_trim_panel.geometry().left(), window.lr_swap_panel.geometry().right())
        self.assertGreater(window.speaker_mapping_panel.geometry().top(), window.channel_trim_panel.geometry().bottom())
        self.assertEqual(window.speaker_mapping_panel.geometry().left(), window.lr_swap_panel.geometry().left())
        self.assertGreater(window.speaker_mapping_panel.width(), window.lr_swap_panel.width() + window.channel_trim_panel.width())
        presets_body = window.findChild(QtWidgets.QWidget, "advancedBody")
        self.assertLessEqual(presets_body.height() - window.peq_routing_card.geometry().bottom(), 8)
        swap_helper = next(
            label
            for label in window.lr_swap_panel.findChildren(QtWidgets.QLabel, "peqHelper")
            if label.text().startswith("Swaps")
        )
        trim_helper = next(
            label
            for label in window.channel_trim_panel.findChildren(QtWidgets.QLabel, "peqHelper")
            if label.text().startswith("Quick fine-tuning")
        )
        self.assertLessEqual(abs(trim_helper.geometry().top() - swap_helper.geometry().top()), 10)
        self.assertLessEqual(window.channel_trim_panel.height() - trim_helper.geometry().bottom(), 10)

    def test_advanced_page_uses_compact_profile_dropdown(self) -> None:
        first = preset_from_current("Qudelix Wired", fake_input(), fake_usb_output(), -6, 1.0, "windows_7_1")
        second = preset_from_current("Speakers", fake_input(), fake_output(), -8, 1.0, "windows_7_1")
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "preset_schema_version": 3,
                "active_preset_id": second.id,
                "presets": [first.to_dict(), second.to_dict()],
            },
            devices=[fake_input(), fake_output(), fake_usb_output()],
        )
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.hide)
        window.resize(window.minimumSize())
        window.show()
        window.tabs.setCurrentIndex(1)
        self.app.processEvents()

        manager = window.findChild(QtWidgets.QFrame, "profileManagerCard")
        selector = window.profile_preset_combo
        action_row = window.findChild(QtWidgets.QWidget, "profileActionRow")
        old_profile_scroll = window.findChild(QtWidgets.QScrollArea, "profileListScroll")
        old_preset_buttons = window.findChildren(QtWidgets.QPushButton, "preset")
        action_buttons = [window.new_preset_button, window.save_preset_button, window.delete_preset_button]

        self.assertIsNotNone(manager)
        self.assertIsInstance(selector, RouteGlassCombo)
        self.assertEqual(selector.objectName(), "routeGlassCombo")
        self.assertEqual(selector.parentWidget().objectName(), "routeSegment")
        self.assertIsNotNone(action_row)
        self.assertIsNone(old_profile_scroll)
        self.assertEqual(old_preset_buttons, [])
        self.assertEqual(manager.maximumHeight(), 174)
        self.assertEqual(selector.count(), 2)
        self.assertEqual(selector.currentData(), second.id)
        self.assertGreater(selector.width(), window.new_preset_button.width())
        self.assertGreaterEqual(window.preset_name_edit.width(), window.new_preset_button.width() * 2)
        self.assertEqual([button.minimumHeight() for button in action_buttons], [34, 34, 34])
        self.assertLess(abs(window.new_preset_button.width() - window.delete_preset_button.width()), 3)

        calls: list[tuple[str, bool, bool]] = []
        window.apply_preset = lambda preset_id, start_after, manual=False: calls.append((preset_id, start_after, manual))
        window._select_preset_from_combo(0)
        self.assertEqual(calls, [(first.id, True, True)])

    def test_view_page_profile_dropdown_syncs_saved_profiles(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})

        selector = window.view_profile_combo
        self.assertIsInstance(selector, ViewStyleCombo)
        self.assertEqual(selector.currentText(), "-")
        self.assertEqual(selector.count(), 1)
        self.assertFalse(selector.isEnabled())

        window.preset_name_edit.setText("Desk")
        window.create_preset()
        preset = window.presets[-1]

        self.assertTrue(selector.isEnabled())
        self.assertEqual(selector.count(), 1)
        self.assertEqual(selector.itemText(0), "Desk")
        self.assertEqual(selector.currentData(), preset.id)

        window.preset_name_edit.setText("Desk USB")
        window.save_active_preset()

        self.assertEqual(selector.itemText(selector.currentIndex()), "Desk USB")

        window.delete_active_preset()

        self.assertEqual(selector.currentText(), "-")
        self.assertEqual(selector.count(), 1)
        self.assertFalse(selector.isEnabled())

    def test_view_page_profile_dropdown_applies_selected_profile(self) -> None:
        first = preset_from_current("Qudelix Wired", fake_input(), fake_usb_output(), -6, 1.0, "windows_7_1")
        second = preset_from_current("Speakers", fake_input(), fake_output(), -8, 1.0, "windows_7_1")
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "preset_schema_version": 3,
                "active_preset_id": second.id,
                "presets": [first.to_dict(), second.to_dict()],
            },
            devices=[fake_input(), fake_output(), fake_usb_output()],
        )

        selector = window.view_profile_combo
        self.assertEqual([selector.itemText(index) for index in range(selector.count())], ["Qudelix Wired", "Speakers"])
        self.assertEqual(selector.currentData(), second.id)

        calls: list[tuple[str, bool, bool]] = []
        window.apply_preset = lambda preset_id, start_after, manual=False: calls.append((preset_id, start_after, manual))
        window._select_view_profile_from_combo(0)

        self.assertEqual(calls, [(first.id, True, True)])

    def test_peq_editors_can_hide_without_removing_state_or_creating_outer_scroll(self) -> None:
        window = self.make_window()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.hide)
        window.show()
        window.tabs.setCurrentIndex(1)
        self.app.processEvents()

        global_body = window.findChild(QtWidgets.QWidget, "globalPeqBody")
        speaker_body = window.findChild(QtWidgets.QWidget, "speakerPeqBody")
        presets_page = window.findChild(QtWidgets.QWidget, "advancedPage")
        outer_scroll = next(
            scroll for scroll in presets_page.findChildren(QtWidgets.QScrollArea)
            if scroll.parentWidget() is presets_page
        )

        self.assertIsNotNone(global_body)
        self.assertIsNotNone(speaker_body)
        self.assertEqual(window.global_peq_visibility_button.text(), "Hide")
        self.assertEqual(window.speaker_eq_visibility_button.text(), "Hide")

        window.global_peq_text.setPlainText("Preamp: -3 dB")
        window.global_peq_visibility_button.click()
        self.app.processEvents()

        self.assertFalse(global_body.isVisible())
        self.assertTrue(speaker_body.isVisible())
        self.assertEqual(window.global_peq_visibility_button.text(), "Show")
        self.assertEqual(window.global_peq_text.toPlainText(), "Preamp: -3 dB")
        self.assertGreaterEqual(outer_scroll.verticalScrollBar().maximum(), 0)

    def test_dsp_order_helper_uses_title_case_and_removes_unsupported_warning(self) -> None:
        window = self.make_window()
        helper_text = "\n".join(
            label.text()
            for label in window.findChild(QtWidgets.QWidget, "advancedPage").findChildren(QtWidgets.QLabel, "peqHelper")
        )

        self.assertIn("DSP Order:", helper_text)
        self.assertIn("Matrix/Downmix -> Master Preamp -> User/Global PEQ", helper_text)
        self.assertNotIn("Unsupported lines are ignored", helper_text)

    def test_peq_routing_state_persists_and_restores_from_preset(self) -> None:
        saved: list[dict[str, object]] = []
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION}, saved)

        window.trim_left_edit.set_value_db(-2.5)
        window.trim_right_edit.set_value_db(-6.0)
        window.lr_swap_checkbox.setChecked(True)
        window.global_peq_checkbox.setChecked(True)
        window.global_peq_text.setPlainText("Preamp: -3 dB")
        window.speaker_eq_checkbox.setChecked(True)
        window.speaker_eq_text.setPlainText("CH:0\nPreamp: -6 dB")
        window._set_peq_editor_visibility("global", False, persist=False)
        window._set_peq_editor_visibility("speaker", False, persist=False)
        row_192 = next(row for row in range(window.sample_rate_combo.count()) if window.sample_rate_combo.itemData(row) == "192000")
        window.sample_rate_combo.setCurrentIndex(row_192)
        window._apply_peq_routing_state(persist=True)

        self.assertTrue(saved[-1]["lr_swap_enabled"])
        self.assertTrue(saved[-1]["global_peq_enabled"])
        self.assertEqual(saved[-1]["global_peq_text"], "Preamp: -3 dB")
        self.assertFalse(saved[-1]["global_peq_visible"])
        self.assertTrue(saved[-1]["speaker_eq_enabled"])
        self.assertEqual(saved[-1]["speaker_eq_text"], "CH:0\nPreamp: -6 dB")
        self.assertFalse(saved[-1]["speaker_eq_visible"])
        self.assertEqual(saved[-1]["trim_left_db"], -2.5)
        self.assertEqual(saved[-1]["trim_right_db"], -6.0)
        self.assertEqual(saved[-1]["sample_rate_mode"], "192000")

        window.preset_name_edit.setText("Corrected")
        window.create_preset()
        preset = window.presets[-1]
        self.assertTrue(preset.lr_swap_enabled)
        self.assertEqual(preset.global_peq_text, "Preamp: -3 dB")
        self.assertFalse(preset.global_peq_visible)
        self.assertEqual(preset.speaker_eq_text, "CH:0\nPreamp: -6 dB")
        self.assertFalse(preset.speaker_eq_visible)
        self.assertEqual(preset.trim_left_db, -2.5)
        self.assertEqual(preset.trim_right_db, -6.0)
        self.assertEqual(preset.sample_rate_mode, "192000")

        window._set_peq_controls_from_values()
        window.sample_rate_combo.setCurrentIndex(0)
        window.apply_preset(preset.id, start_after=False)

        self.assertTrue(window.lr_swap_checkbox.isChecked())
        self.assertTrue(window.global_peq_checkbox.isChecked())
        self.assertEqual(window.global_peq_text.toPlainText(), "Preamp: -3 dB")
        self.assertFalse(window.global_peq_body.isVisible())
        self.assertEqual(window.global_peq_visibility_button.text(), "Show")
        self.assertTrue(window.speaker_eq_checkbox.isChecked())
        self.assertEqual(window.speaker_eq_text.toPlainText(), "CH:0\nPreamp: -6 dB")
        self.assertFalse(window.speaker_peq_body.isVisible())
        self.assertEqual(window.speaker_eq_visibility_button.text(), "Show")
        self.assertEqual(window.trim_left_edit.value_db(), -2.5)
        self.assertEqual(window.trim_right_edit.value_db(), -6.0)
        self.assertEqual(window.sample_rate_combo.currentData(), "192000")

    def test_trim_inputs_clamp_live_and_persist_globally(self) -> None:
        saved: list[dict[str, object]] = []
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION}, saved)

        self.assertEqual(clamp_trim_db("bad"), 0.0)
        self.assertEqual(clamp_trim_db("+2"), 0.0)
        self.assertEqual(clamp_trim_db("-99"), -24.0)

        editor = TrimLineEdit(0.0)
        self.addCleanup(editor.deleteLater)
        editor.setText("3")
        editor.normalize()
        self.assertEqual(editor.text(), "0")
        editor.setText("-99")
        editor.normalize()
        self.assertEqual(editor.text(), "-24")

        window.trim_left_edit.set_value_db(1.5)
        window.trim_right_edit.set_value_db(-99)
        window.update_channel_trim()

        self.assertTrue(saved)
        self.assertEqual(saved[-1]["trim_left_db"], 0.0)
        self.assertEqual(saved[-1]["trim_right_db"], -24.0)

    def test_profile_update_renames_active_preset(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})

        window.preset_name_edit.setText("Old Name")
        window.create_preset()
        preset = window.presets[-1]
        self.assertEqual(preset.name, "Old Name")

        window.preset_name_edit.setText("New Name")
        window.save_active_preset()

        self.assertEqual(preset.name, "New Name")
        selector = window.profile_preset_combo
        selector_texts = [selector.itemText(index) for index in range(selector.count())]
        self.assertIn("New Name", selector_texts)

    def test_user_visible_app_text_is_neutral(self) -> None:
        window = self.make_window()
        body = build_details_body()
        self.addCleanup(body.deleteLater)

        widgets = list(window.findChildren(QtWidgets.QLabel))
        widgets += list(window.findChildren(QtWidgets.QPushButton))
        widgets += list(body.findChildren(QtWidgets.QLabel))
        texts = [widget.text() for widget in widgets]
        texts.append(window.global_peq_text.placeholderText())
        texts.append(window.speaker_eq_text.placeholderText())
        visible_text = "\n".join(texts)

        for banned in ("Qudelix", "T71", "Equalizer APO", "Sharur"):
            self.assertNotIn(banned, visible_text)

    def test_renderer_details_dialog_is_tight_and_close_only(self) -> None:
        window = self.make_window()
        dialogs: list[DotBackdropDialog] = []

        def capture_exec(dialog: DotBackdropDialog) -> int:
            dialogs.append(dialog)
            return 0

        with patch.object(DotBackdropDialog, "exec_", capture_exec):
            window.show_feature_help()

        self.assertEqual(len(dialogs), 1)
        dialog = dialogs[0]
        self.addCleanup(dialog.deleteLater)
        self.assertLessEqual(dialog.minimumHeight(), 380)
        self.assertEqual(dialog.findChildren(QtWidgets.QDialogButtonBox), [])
        self.assertEqual([button.text() for button in dialog.findChildren(QtWidgets.QPushButton)], [])

    def test_diagnostics_include_compact_peq_and_swap_state(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})
        window.lr_swap_checkbox.setChecked(True)
        window.global_peq_checkbox.setChecked(True)
        window.global_peq_text.setPlainText("Filter 1: ON PK Fc 100 Hz Gain 1 dB Q 1")
        window.speaker_eq_checkbox.setChecked(True)
        window.speaker_eq_text.setPlainText("CH:0\nFilter 1: ON PK Fc 200 Hz Gain 1 dB Q 1")
        window._apply_peq_routing_state(persist=False)

        text = window._peq_diagnostic_text()

        self.assertIn("User PEQ 1", text)
        self.assertIn("L-R Correction 1/0", text)
        self.assertIn("Swap on", text)

    def test_room_visualizer_orientation_labels_are_top_view_only(self) -> None:
        visualizer = RoomVisualizer()
        self.addCleanup(visualizer.deleteLater)
        calls: list[QtCore.QRectF] = []

        def record_orientation(painter: QtGui.QPainter, room: QtCore.QRectF) -> None:
            calls.append(QtCore.QRectF(room))

        visualizer._draw_orientation_labels = record_orientation
        pixmap = QtGui.QPixmap(640, 360)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        visualizer._draw_3d_view(painter, QtCore.QRectF(0, 0, 640, 300))
        painter.end()
        self.assertEqual(calls, [])

        painter = QtGui.QPainter(pixmap)
        visualizer._draw_top_view(painter, QtCore.QRectF(0, 0, 640, 300))
        painter.end()
        self.assertEqual(len(calls), 1)

    def test_room_visualizer_uses_stable_room_aspect_and_clamped_camera(self) -> None:
        visualizer = RoomVisualizer()
        self.addCleanup(visualizer.deleteLater)

        for rect in (QtCore.QRectF(0, 0, 900, 220), QtCore.QRectF(0, 0, 260, 520)):
            room = visualizer._room_viewport(rect, 7, 5)
            self.assertAlmostEqual(room.width() / room.height(), RoomVisualizer.ROOM_ASPECT, places=2)
            self.assertGreaterEqual(room.left(), rect.left())
            self.assertLessEqual(room.right(), rect.right())

        visualizer._target_pitch = 999.0
        visualizer.camera_zoom = 999.0
        visualizer._smooth_camera(1.0)
        self.assertLessEqual(visualizer.camera_pitch, RoomVisualizer.MAX_PITCH)
        self.assertLessEqual(visualizer.camera_zoom, RoomVisualizer.MAX_ZOOM)

    def test_room_visualizer_uses_separate_windows_and_sharur_placements(self) -> None:
        windows = {label: (source_index, x, y, z) for source_index, label, x, y, z in RoomVisualizer._speakers_for_config("windows_7_1")}
        self.assertEqual(windows["LFE"][0], 3)
        self.assertAlmostEqual(windows["LFE"][1], 0.50)
        self.assertEqual(windows["BL"][0], 4)
        self.assertEqual(windows["BR"][0], 5)
        self.assertEqual(windows["SL"][0], 6)
        self.assertEqual(windows["SR"][0], 7)
        self.assertLess(windows["SL"][2], windows["BL"][2])
        self.assertLess(windows["SR"][2], windows["BR"][2])

        sharur = {label: (source_index, x, y, z) for source_index, label, x, y, z in RoomVisualizer._speakers_for_config("sharur_9_1_6")}
        self.assertEqual(sharur["BL"][0], 4)
        self.assertEqual(sharur["BR"][0], 5)
        self.assertEqual(sharur["BLC"][0], 6)
        self.assertEqual(sharur["BRC"][0], 7)
        self.assertEqual(sharur["SL"][0], 8)
        self.assertEqual(sharur["SR"][0], 9)
        self.assertEqual(sharur["TFL"][0], 10)
        self.assertEqual(sharur["TSL"][0], 12)
        self.assertEqual(sharur["TBL"][0], 14)
        self.assertLess(sharur["BL"][2], sharur["SL"][2])
        self.assertLess(sharur["SL"][2], sharur["BLC"][2])

    def test_view_mode_buttons_switch_visualizer_layout_without_replacing_widget(self) -> None:
        window = self.make_window()
        visualizer = window.bed_input_visualizer

        self.assertEqual(window.mode_buttons["windows_7_1"].text(), "7.1")
        self.assertEqual(window.mode_buttons["sharur_9_1_6"].text(), "9.1.6")

        window.mode_buttons["sharur_9_1_6"].click()
        self.app.processEvents()

        self.assertEqual(window.channel_config, "sharur_9_1_6")
        self.assertIs(window.bed_input_visualizer, visualizer)
        self.assertEqual(len(visualizer.nodes), 16)
        self.assertFalse(bool(window.mode_buttons["windows_7_1"].property("active")))
        self.assertTrue(bool(window.mode_buttons["sharur_9_1_6"].property("active")))

        window.mode_buttons["windows_7_1"].click()
        self.app.processEvents()

        self.assertEqual(window.channel_config, "windows_7_1")
        self.assertIs(window.bed_input_visualizer, visualizer)
        self.assertEqual(len(visualizer.nodes), 8)
        self.assertEqual(
            {str(node["label"]): int(node["source_index"]) for node in visualizer.nodes},
            {"L": 0, "R": 1, "C": 2, "LFE": 3, "Lrs": 4, "Rrs": 5, "Ls": 6, "Rs": 7},
        )
        self.assertTrue(bool(window.mode_buttons["windows_7_1"].property("active")))
        self.assertFalse(bool(window.mode_buttons["sharur_9_1_6"].property("active")))

    def test_toggles_use_production_green_switch_control(self) -> None:
        window = self.make_window()

        for checkbox in (
            window.smart_switch_checkbox,
            window.system_boot_checkbox,
            window.surround_fill_checkbox,
            window.upmix916_checkbox,
            window.sound_enhancer_checkbox,
            window.keep_awake_checkbox,
        ):
            self.assertIsInstance(checkbox, SwitchCheckBox)
            self.assertEqual(checkbox.objectName(), "switchControl")
            self.assertNotIn("ON", checkbox.text())
            self.assertNotIn("OFF", checkbox.text())

        self.assertEqual(window.sound_enhancer_checkbox.toolTip(), "Adds protected post-mix loudness when enabled")
        self.assertNotIn("laptop", window.sound_enhancer_checkbox.toolTip().casefold())
        switch_consts = SwitchCheckBox.paintEvent.__code__.co_consts
        self.assertIn("#173923", switch_consts)
        self.assertIn("#05080a", switch_consts)
        self.assertIn("#bfefff", switch_consts)

    def test_profile_hover_styles_are_neutral(self) -> None:
        self.assertNotIn("#1b2228", BASE_STYLE)
        self.assertIn("QPushButton#preset:hover", BASE_STYLE)
        self.assertIn("border-color: #777777", BASE_STYLE)
        def style_block(marker: str) -> str:
            start = BASE_STYLE.index(marker)
            end = BASE_STYLE.find("\nQ", start + 1)
            return BASE_STYLE[start:] if end == -1 else BASE_STYLE[start:end]

        profile_style = "\n".join(
            style_block(marker)
            for marker in (
                'QFrame#card[presetSurface="true"]',
                "QPushButton#preset {",
                "QPushButton#preset:hover",
                'QPushButton#preset[active="true"]',
                "QPushButton#ghost {",
                "QPushButton#ghost:hover",
            )
        ).lower()
        for blue in ("#45b7ff", "#0c1720", "#289dff", "#4ec9ff", "blue"):
            self.assertNotIn(blue, profile_style)

    def test_windows_shell_icons_are_sent_for_small_and_big_window_icons(self) -> None:
        window = self.make_window()
        icon_path = RendererWindow._icon_asset_path()
        load_sizes: list[tuple[int, int]] = []
        sent: list[tuple[int, int, int]] = []
        test_case = self

        class FakeUser32:
            def LoadImageW(self, instance, path, image_type, width, height, flags):
                test_case.assertIsNone(instance)
                test_case.assertEqual(Path(path), icon_path)
                load_sizes.append((width, height))
                return 1000 + len(load_sizes)

            def SendMessageW(self, hwnd, message, icon_kind, handle):
                sent.append((message, icon_kind, handle))
                return 0

        with (
            patch("downmix_renderer.app.sys.platform", "win32"),
            patch("downmix_renderer.app.ctypes.windll", SimpleNamespace(user32=FakeUser32())),
        ):
            handles = apply_windows_window_icons(window, icon_path)

        self.assertEqual(load_sizes, [(16, 16), (256, 256)])
        self.assertEqual(handles, [1001, 1002])
        self.assertEqual(sent, [(WM_SETICON, ICON_SMALL, 1001), (WM_SETICON, ICON_BIG, 1002)])

    def test_windows_shell_icon_cleanup_detaches_before_destroy(self) -> None:
        window = self.make_window()
        sent: list[tuple[int, int, object]] = []
        destroyed: list[int] = []

        class FakeUser32:
            def SendMessageW(self, hwnd, message, icon_kind, handle):
                sent.append((message, icon_kind, handle))
                return 1001 if icon_kind == ICON_SMALL else 1002

            def DestroyIcon(self, handle):
                destroyed.append(handle)
                return 1

        with (
            patch("downmix_renderer.app.sys.platform", "win32"),
            patch("downmix_renderer.app.ctypes.windll", SimpleNamespace(user32=FakeUser32())),
        ):
            destroy_windows_icon_handles([1001, 1002], window)

        self.assertEqual(sent, [(WM_SETICON, ICON_SMALL, None), (WM_SETICON, ICON_BIG, None)])
        self.assertEqual(destroyed, [1001, 1002])

    def test_chrome_visuals_match_finalised_v3_palette(self) -> None:
        self.assertNotIn("rgba(99, 199, 255, 42)", BASE_STYLE)
        self.assertNotIn("rgba(111, 240, 160, 28)", BASE_STYLE)
        self.assertIn("background-color: #030303;", BASE_STYLE)
        self.assertIn("border: 1px solid #1d1d1d;", BASE_STYLE)
        self.assertIn("QFrame#routeLane", BASE_STYLE)
        self.assertIn("QFrame#routeSegment", BASE_STYLE)
        self.assertIn("border-color: #363636;", BASE_STYLE)
        self.assertIn("QFrame#card:hover", BASE_STYLE)

    def test_raw_monitor_uses_premium_dialog(self) -> None:
        window = self.make_window()

        dialog = RawMonitorDialog(window)
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.windowTitle(), "Raw Monitor")
        self.assertEqual(len(dialog.tiles), 8)
        self.assertGreaterEqual(RawChannelTile.METER_ATTACK, 0.75)
        self.assertGreaterEqual(RawChannelTile.METER_DECAY, 0.18)
        self.assertIn("#344237", RawChannelTile.paintEvent.__code__.co_consts)
        self.assertIn("#68d98f", RawChannelTile.paintEvent.__code__.co_consts)
        self.assertEqual(window.raw_monitor_button.focusPolicy(), QtCore.Qt.NoFocus)

    def test_raw_monitor_tiles_match_view_source_mapping_for_all_layouts(self) -> None:
        window = self.make_window()
        dialog = RawMonitorDialog(window)
        self.addCleanup(dialog.deleteLater)

        for config_id in ("windows_7_1", "sharur_9_1_6"):
            window.set_channel_config(config_id)
            dialog.set_channel_config(config_id)
            view_indices = sorted(int(node["source_index"]) for node in window.bed_input_visualizer.nodes)
            self.assertEqual(sorted(tile.source_index for tile in dialog.tiles), view_indices)

        windows_mapping = {tile.name: tile.source_index for tile in dialog.tiles}
        self.assertEqual(windows_mapping["TFL"], 10)
        self.assertEqual(windows_mapping["TFR"], 11)
        self.assertEqual(windows_mapping["TSL"], 12)
        self.assertEqual(windows_mapping["TSR"], 13)
        self.assertEqual(windows_mapping["TBL"], 14)
        self.assertEqual(windows_mapping["TBR"], 15)

        window.set_channel_config("windows_7_1")
        dialog.set_channel_config("windows_7_1")
        windows_mapping = {tile.name: tile.source_index for tile in dialog.tiles}
        self.assertEqual(windows_mapping["SL"], 6)
        self.assertEqual(windows_mapping["SR"], 7)

    def test_view_nodes_and_raw_monitor_light_matching_source_channels(self) -> None:
        window = self.make_window()
        dialog = RawMonitorDialog(None)
        self.addCleanup(dialog.deleteLater)
        window.raw_monitor_dialog = dialog

        for config_id in ("windows_7_1", "sharur_9_1_6"):
            window.set_channel_config(config_id)
            dialog.set_channel_config(config_id)
            layout = CHANNEL_LAYOUTS[config_id]
            expected = list(zip(layout["names"], layout["indices"]))
            raw_mapping = [(tile.name, tile.source_index) for tile in dialog.tiles]
            self.assertEqual(raw_mapping, expected)
            self.assertEqual(
                sorted(int(node["source_index"]) for node in window.bed_input_visualizer.nodes),
                sorted(int(source_index) for source_index in layout["indices"]),
            )

            for name, source_index in expected:
                levels = [0.0] * 16
                rms_values = [0.0] * 16
                levels[source_index] = 0.5
                rms_values[source_index] = 0.25
                window.bed_input_visualizer.set_levels(levels, 0.0, 0.0)
                dialog.set_levels(levels, rms_values)

                lit_raw = [tile.name for tile in dialog.tiles if tile.peak > RoomVisualizer.ACTIVE_THRESHOLD]
                self.assertEqual(lit_raw, [name])
                self.assertEqual(window.bed_input_visualizer.active_node_count, 1)

    def test_raw_monitor_lights_processed_upmix_channels_like_channel_field(self) -> None:
        window = self.make_window()
        window.set_channel_config("sharur_9_1_6")
        dialog = RawMonitorDialog(None)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.addCleanup(dialog.hide)
        window.raw_monitor_dialog = dialog

        processed_levels = [0.0] * 16
        raw_levels = [0.0] * 16
        rms_values = [0.0] * 16
        processed_levels[10] = 0.42
        dsp = SimpleNamespace(
            channel_levels=processed_levels,
            channel_rms=rms_values,
            raw_channel_levels=raw_levels,
            raw_channel_rms=rms_values,
            left_meter=0.0,
            right_meter=0.0,
            limiter_gain=1.0,
            clipping=False,
            sound_enhancer_enabled=False,
            sound_enhancer_gain=1.0,
            surround_fill_enabled=False,
            surround_fill_active=False,
            upmix_9_1_6_enabled=True,
            upmix_9_1_6_active=True,
        )
        snapshot = SimpleNamespace(
            running=False,
            status="Stopped",
            route="--",
            input_channels=16,
            stream_latency=None,
            stream_profile="ultra",
            sample_rate=48000,
            sample_rate_mode="auto",
            callback_status_count=0,
            callback_status="",
            dsp_error_count=0,
            cpu_load=0.0,
            dsp=dsp,
        )
        volume = SimpleNamespace(muted=False, scalar=1.0, available=True, source="endpoint")
        window.engine.snapshot = lambda: snapshot
        window.engine.poll_volume = lambda: volume

        window.update_ui()

        raw_tile = next(tile for tile in dialog.tiles if tile.source_index == 10)
        self.assertGreater(window.bed_input_visualizer.node_display_db[10], BedInputVisualizer.METER_FLOOR_DB)
        self.assertGreater(raw_tile.display_peak, 0.0)
        self.assertEqual(raw_tile.peak, processed_levels[10])

    def test_update_ui_preserves_exact_meter_values_with_smoothed_display(self) -> None:
        window = self.make_window()
        dialog = RawMonitorDialog(None)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.addCleanup(dialog.hide)
        window.raw_monitor_dialog = dialog

        levels = [0.0] * 16
        rms_values = [0.0] * 16
        levels[0] = 0.0002
        levels[1] = 0.375
        rms_values[1] = 0.125
        dsp = SimpleNamespace(
            channel_levels=levels,
            channel_rms=rms_values,
            raw_channel_levels=[0.0] * 16,
            raw_channel_rms=[0.0] * 16,
            left_meter=0.625,
            right_meter=0.25,
            limiter_gain=1.0,
            clipping=False,
            sound_enhancer_enabled=False,
            sound_enhancer_gain=1.0,
            surround_fill_enabled=False,
            surround_fill_active=False,
            upmix_9_1_6_enabled=False,
            upmix_9_1_6_active=False,
        )
        snapshot = SimpleNamespace(
            running=True,
            status="Running",
            route="Test route",
            input_channels=16,
            stream_latency=None,
            stream_profile="ultra",
            sample_rate=48000,
            sample_rate_mode="auto",
            callback_status_count=0,
            callback_status="",
            dsp_error_count=0,
            cpu_load=0.0,
            dsp=dsp,
        )
        volume = SimpleNamespace(muted=False, scalar=1.0, available=True, source="endpoint")
        window.engine.snapshot = lambda: snapshot
        window.engine.poll_volume = lambda: volume

        window.update_ui()

        raw_tile = next(tile for tile in dialog.tiles if tile.source_index == 1)
        self.assertEqual(window.bed_input_visualizer.node_levels[1], 0.375)
        self.assertGreater(window.bed_input_visualizer.node_display_db[1], BedInputVisualizer.METER_FLOOR_DB)
        self.assertEqual(window.bed_input_visualizer.node_levels[0], 0.0002)
        self.assertGreater(window.bed_input_visualizer.node_display_db[0], BedInputVisualizer.METER_FLOOR_DB)
        self.assertEqual(window.bed_input_visualizer.active_node_count, 2)
        self.assertEqual(raw_tile.peak, 0.375)
        self.assertEqual(raw_tile.rms, 0.125)
        self.assertGreater(raw_tile.display_peak, 0.0)
        self.assertLess(raw_tile.display_peak, raw_tile.peak)
        self.assertEqual(window.bed_input_visualizer.left_level, 0.625)
        self.assertEqual(window.bed_input_visualizer.right_level, 0.25)
        self.assertGreater(window.bed_input_visualizer.left_display_db, BedInputVisualizer.METER_FLOOR_DB)
        self.assertGreater(window.bed_input_visualizer.right_display_db, BedInputVisualizer.METER_FLOOR_DB)
        self.assertIn("L", window.diag_labels["Active"].text())

    def test_diagnostics_window_is_independent_and_excludes_raw_monitor(self) -> None:
        window = self.make_window()
        window.diag_labels["Preset"].setText("Qudelix Wired")
        window.diag_labels["Output"].setText("Headphones | Windows 34.0%")

        window.open_diagnostics()
        dialog = window.diagnostics_dialog

        self.assertIsInstance(dialog, DiagnosticsDialog)
        self.assertEqual(dialog.minimumSize(), QtCore.QSize(560, 420))
        self.assertIsNone(dialog.parent())
        self.assertTrue(bool(dialog.windowFlags() & QtCore.Qt.Window))
        self.assertTrue(bool(dialog.windowFlags() & QtCore.Qt.WindowMinimizeButtonHint))
        self.assertEqual(dialog.windowModality(), QtCore.Qt.NonModal)
        self.assertEqual(dialog.diag_labels["Preset"].text(), "Qudelix Wired")
        self.assertEqual(dialog.diag_labels["Output"].text(), "Headphones | Windows 34.0%")
        self.assertEqual(dialog.findChildren(QtWidgets.QPushButton, "rawMonitor"), [])
        window._close_diagnostics_dialog()
        self.assertFalse(dialog.isVisible())

    def test_opened_raw_monitor_is_not_owned_by_main_window(self) -> None:
        window = self.make_window()

        window.open_raw_monitor()
        dialog = window.raw_monitor_dialog

        self.assertIsNotNone(dialog)
        self.assertIsNone(dialog.parent())
        self.assertTrue(bool(dialog.windowFlags() & QtCore.Qt.Window))
        window._close_raw_monitor_dialog()
        self.assertFalse(dialog.isVisible())

    def test_opened_raw_monitor_has_independent_window_controls(self) -> None:
        window = self.make_window()

        window.open_raw_monitor()
        dialog = window.raw_monitor_dialog

        self.assertIsNotNone(dialog)
        flags = dialog.windowFlags()
        self.assertIsNone(dialog.parent())
        self.assertTrue(bool(flags & QtCore.Qt.Window))
        self.assertTrue(bool(flags & QtCore.Qt.WindowTitleHint))
        self.assertTrue(bool(flags & QtCore.Qt.WindowMinimizeButtonHint))
        self.assertTrue(bool(flags & QtCore.Qt.WindowCloseButtonHint))
        self.assertEqual(dialog.windowModality(), QtCore.Qt.NonModal)
        window._close_raw_monitor_dialog()

    def test_minimizing_renderer_does_not_minimize_raw_monitor(self) -> None:
        window = self.make_window()
        window.show()
        self.addCleanup(window.hide)
        window.open_raw_monitor()
        dialog = window.raw_monitor_dialog

        self.assertIsNotNone(dialog)
        self.addCleanup(window._close_raw_monitor_dialog)
        dialog.show()
        self.app.processEvents()
        window.showMinimized()
        self.app.processEvents()

        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.isMinimized())

    def test_layout_switch_updates_open_raw_monitor_without_minimizing_or_moving_it(self) -> None:
        window = self.make_window()
        window.show()
        self.addCleanup(window.hide)
        window.open_raw_monitor()
        dialog = window.raw_monitor_dialog

        self.assertIsNotNone(dialog)
        self.addCleanup(window._close_raw_monitor_dialog)
        dialog.setGeometry(120, 140, 820, 360)
        dialog.showNormal()
        self.app.processEvents()
        prior_geometry = dialog.geometry()
        prior_state = dialog.windowState()

        window.set_channel_config("sharur_9_1_6")
        self.app.processEvents()

        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.isMinimized())
        self.assertEqual(dialog.geometry(), prior_geometry)
        self.assertEqual(dialog.windowState(), prior_state)
        self.assertEqual(len(dialog.tiles), 16)

    def test_audio_stability_control_is_hidden_and_ultra_is_internal_default(self) -> None:
        window = self.make_window()

        self.assertFalse(hasattr(window, "stability_combo"))
        self.assertEqual(window._selected_audio_stability(), "ultra")

    def test_renderer_details_are_compact_and_only_explain_high_signal_features(self) -> None:
        body = build_details_body()
        self.addCleanup(body.deleteLater)

        rows = body.findChildren(QtWidgets.QWidget, "detailsRow")
        names = body.findChildren(QtWidgets.QLabel, "detailsName")
        descriptions = body.findChildren(QtWidgets.QLabel, "detailsDescription")
        cards = body.findChildren(QtWidgets.QFrame, "card")

        self.assertEqual(len(cards), 1)
        self.assertEqual(len(rows), 6)
        self.assertEqual(len(names), len(descriptions))
        self.assertTrue(all(label.minimumWidth() == 150 and label.maximumWidth() == 150 for label in names))
        self.assertTrue(all(label.alignment() & QtCore.Qt.AlignTop for label in names))
        self.assertTrue(all(label.alignment() & QtCore.Qt.AlignTop for label in descriptions))
        self.assertTrue(all(label.wordWrap() for label in descriptions))
        self.assertTrue(all(row.layout().spacing() >= 12 for row in rows))
        name_text = [label.text() for label in names]
        description_text = " ".join(label.text() for label in descriptions)
        self.assertEqual(
            name_text,
            [
                "ULTRA Mode",
                "Sound Enhancer",
                "Upmix",
                "System Automation",
                "PEQ / Correction",
                "GitHub",
            ],
        )
        self.assertIn(
            "Shared WASAPI low-latency streaming with native callback-thread MMCSS, three-period buffering, "
            "sample-rate-aware period scaling, and automatic RAW fallback if an endpoint rejects the Ultra hint.",
            description_text,
        )
        self.assertIn(
            "Optional post-mix loudness support. It keeps routing and downmix math unchanged, "
            "then uses protected limiting when a track is already near full scale.",
            description_text,
        )
        self.assertNotIn("weak laptop speakers", description_text.casefold())
        self.assertNotIn("laptop speakers", description_text.casefold())
        self.assertIn("7.1 Upmix is a conservative surround fill helper, not a full creative cinematic upmix.", description_text)
        self.assertIn("9.1.6 Upmix adds controlled side/rear/height ambience", description_text)
        self.assertIn("Smart Switching follows the active Windows output", description_text)
        self.assertIn("Auto-start manages the current Startup shortcut", description_text)
        self.assertIn("Keep Output Awake holds the selected endpoint open with silence only while rendering is stopped.", description_text)
        self.assertIn("User / Global PEQ shapes overall tone.", description_text)
        self.assertIn("L-R Correction and swap adjust the selected output pair", description_text)
        self.assertIn("Open the project page for releases, source, issue history, and build notes.", description_text)
        self.assertNotIn("runs before", description_text.casefold())
        self.assertNotIn("runs after", description_text.casefold())
        for removed in (
            "Render",
            "Input / Output",
            "Saved Profiles",
            "Profile Control",
            "Preamp",
            "7.1 Upmix",
            "9.1.6 Monitor",
            "9.1.6 Upmix",
            "Room View",
            "Raw Monitor",
        ):
            self.assertNotIn(removed, name_text)
        self.assertNotIn("Channel Sanity", name_text)
        self.assertNotIn("Import Safety", name_text)
        self.assertNotIn("Audio Stability", name_text)
        self.assertNotIn("Probe 20", name_text)
        self.assertNotIn("Suite", name_text)

    def test_old_crackly_audio_settings_are_recovered_to_ultra_defaults(self) -> None:
        window = self.make_window(
            {
                "surround_fill_enabled": True,
                "upmix_9_1_6_enabled": True,
                "channel_sanity_enabled": True,
                "audio_stability": "balanced",
            }
        )

        self.assertFalse(window.surround_fill_checkbox.isChecked())
        self.assertFalse(window.upmix916_checkbox.isChecked())
        self.assertFalse(window.channel_sanity_enabled)
        self.assertFalse(window.engine.processor.snapshot().channel_sanity_enabled)
        self.assertEqual(window._selected_audio_stability(), "ultra")

    def test_legacy_low_latency_settings_are_hidden_behind_ultra_default(self) -> None:
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "audio_stability": "low_latency",
            }
        )

        self.assertEqual(window._selected_audio_stability(), "ultra")

    def test_legacy_normal_and_balanced_settings_are_migrated_to_ultra(self) -> None:
        for legacy in ("normal", "balanced", "safe", "stable"):
            window = self.make_window(
                {
                    "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                    "audio_stability": legacy,
                }
            )
            self.assertEqual(window._selected_audio_stability(), "ultra")

    def test_ultra_callback_warning_does_not_expose_or_switch_to_raw(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})
        window._set_audio_stability_selection("ultra")
        calls: list[bool] = []

        def fake_start_audio() -> None:
            calls.append(True)

        window.start_audio = fake_start_audio
        snapshot = SimpleNamespace(running=True, stream_profile="ultra", callback_status_count=1)

        self.assertFalse(window._fallback_non_normal_on_warning(snapshot))
        self.assertEqual(window._selected_audio_stability(), "ultra")
        self.assertEqual(calls, [])

    def test_device_refresh_adds_new_output_without_losing_current_selection(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})
        original = fake_output()
        fresh_devices = [fake_input(), original, fake_usb_output()]
        signature = window._make_device_signature(fresh_devices)

        window._refresh_device_lists(fresh_devices, signature)

        outputs = [window.output_combo.itemText(row) for row in range(window.output_combo.count())]
        self.assertTrue(any("Qudelix" in text for text in outputs))
        self.assertEqual(window.output_combo.currentData(), original.id)

    def test_refresh_devices_button_forces_immediate_reenumeration(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})
        original = fake_output()
        fresh_devices = [fake_input(), original, fake_usb_output()]
        calls: list[bool] = []

        def fake_list_devices(force_refresh: bool = False) -> list[AudioDevice]:
            calls.append(force_refresh)
            return fresh_devices

        with patch("downmix_renderer.app.list_devices", fake_list_devices):
            window.refresh_devices()

        outputs = [window.output_combo.itemText(row) for row in range(window.output_combo.count())]
        self.assertEqual(calls, [True])
        self.assertTrue(any("Qudelix" in text for text in outputs))
        self.assertEqual(window.output_combo.currentData(), original.id)

    def test_refresh_button_click_reenumerates_devices_without_blocking_ui_thread(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})
        original = fake_output()
        fresh_devices = [fake_input(), original, fake_usb_output()]
        calls: list[bool] = []

        def fake_list_devices(force_refresh: bool = False) -> list[AudioDevice]:
            calls.append(force_refresh)
            time.sleep(0.08)
            return fresh_devices

        with patch("downmix_renderer.app.list_devices", fake_list_devices):
            window.refresh_devices_button.click()
            self.assertIsNotNone(window._device_refresh_thread)

            progress_deadline = time.monotonic() + 0.3
            while window.refresh_devices_button.refresh_progress <= 0.0 and time.monotonic() < progress_deadline:
                self.app.processEvents()
                QtCore.QThread.msleep(5)
            self.assertGreater(window.refresh_devices_button.refresh_progress, 0.0)

            refresh_deadline = time.monotonic() + 2.0
            while window._device_refresh_thread is not None and time.monotonic() < refresh_deadline:
                self.app.processEvents()
                QtCore.QThread.msleep(10)
            self.assertIsNone(window._device_refresh_thread)

        outputs = [window.output_combo.itemText(row) for row in range(window.output_combo.count())]
        self.assertEqual(calls, [True])
        self.assertTrue(any("Qudelix" in text for text in outputs))
        self.assertEqual(window.output_combo.currentData(), original.id)

    def test_device_timer_poll_reenumerates_without_blocking_ui_thread(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})
        original = fake_output()
        fresh_devices = [fake_input(), original, fake_usb_output()]
        calls: list[bool] = []
        window._device_poll_count = DEVICE_FORCE_REFRESH_INTERVAL - 1

        def fake_list_devices(force_refresh: bool = False) -> list[AudioDevice]:
            calls.append(force_refresh)
            time.sleep(0.08)
            return fresh_devices

        with patch("downmix_renderer.app.list_devices", fake_list_devices):
            window._poll_devices_from_timer()
            self.assertIsNotNone(window._device_poll_thread)

            processed_events = False
            progress_deadline = time.monotonic() + 0.3
            while window._device_poll_thread is not None and time.monotonic() < progress_deadline:
                processed_events = True
                self.app.processEvents()
                QtCore.QThread.msleep(10)
            self.assertTrue(processed_events)

            refresh_deadline = time.monotonic() + 2.0
            while window._device_poll_thread is not None and time.monotonic() < refresh_deadline:
                self.app.processEvents()
                QtCore.QThread.msleep(10)
            self.assertIsNone(window._device_poll_thread)

        outputs = [window.output_combo.itemText(row) for row in range(window.output_combo.count())]
        self.assertEqual(calls, [True])
        self.assertTrue(any("Qudelix" in text for text in outputs))
        self.assertEqual(window.output_combo.currentData(), original.id)

    def test_forced_device_refresh_is_requested_periodically(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})
        calls: list[bool] = []

        def fake_list_devices(force_refresh: bool = False) -> list[AudioDevice]:
            calls.append(force_refresh)
            return [fake_input(), fake_output()]

        with patch("downmix_renderer.app.list_devices", fake_list_devices):
            for _ in range(DEVICE_FORCE_REFRESH_INTERVAL):
                window.poll_devices()

        self.assertIn(True, calls)
        self.assertLessEqual(window.device_timer.interval(), DEVICE_POLL_INTERVAL_MS)
        self.assertLessEqual(window.device_timer.interval(), 1000)

    def test_running_renderer_restarts_when_selected_route_format_changes(self) -> None:
        input_96k = with_samplerate(fake_input(), 96000)
        output = fake_output()
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "sample_rate_mode": "auto",
            }
        )
        restart_rates: list[int] = []
        window.engine._running = True

        def fake_start_audio() -> None:
            restart_rates.append(window._resolved_sample_rate_for_current_route())

        window.start_audio = fake_start_audio

        with (
            patch("downmix_renderer.app.list_devices", return_value=[input_96k, output, cable_playback]),
            patch("downmix_renderer.app.default_wasapi_output", return_value=cable_playback),
        ):
            window.poll_devices()

        self.assertEqual(restart_rates, [96000])

    def test_windows_direct_output_change_arms_lossless_handoff_without_immediate_stop(self) -> None:
        speakers = fake_output()
        cable_playback = fake_cable_playback_output()
        saved: list[dict[str, object]] = []
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            saved,
            devices=[fake_input(), speakers, cable_playback],
            default_output=cable_playback,
        )
        window.engine._running = True
        stop_calls: list[bool] = []

        def fake_stop(resume_keep_awake: bool = True) -> None:
            stop_calls.append(resume_keep_awake)
            window.engine._running = False

        window.engine.stop = fake_stop

        with patch("downmix_renderer.app.monotonic", return_value=10.0):
            handled = window._sync_renderer_with_windows_default_output(speakers, was_running=True)

        self.assertTrue(handled)
        self.assertEqual(stop_calls, [])
        self.assertFalse(window._paused_for_direct_output)
        self.assertIsNotNone(window._direct_output_handoff_generation)
        self.assertTrue(window._force_auto_start)
        self.assertEqual(window._status_text, "Direct output handoff")
        self.assertTrue(saved[-1]["resume_on_launch"])
        self.assertTrue(saved[-1]["was_running"])

    def test_direct_output_handoff_keeps_bridging_when_lossless_still_feeds_cable(self) -> None:
        speakers = fake_output()
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), speakers, cable_playback],
            default_output=cable_playback,
        )
        window.engine._running = True
        stop_calls: list[bool] = []

        def fake_stop(resume_keep_awake: bool = True) -> None:
            stop_calls.append(resume_keep_awake)
            window.engine._running = False

        window.engine.stop = fake_stop

        with patch("downmix_renderer.app.monotonic", return_value=20.0):
            window._sync_renderer_with_windows_default_output(speakers, was_running=True)

        active_cable_snapshot = SimpleNamespace(
            running=True,
            status="Running",
            callback_status="",
            callback_status_count=0,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.05] + [0.0] * 15,
                left_meter=0.05,
                right_meter=0.05,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with (
            patch("downmix_renderer.app.default_wasapi_output", return_value=speakers),
            patch("downmix_renderer.app.monotonic", return_value=22.0),
        ):
            self.assertFalse(window._maybe_pause_after_direct_output_handoff(active_cable_snapshot))

        self.assertEqual(stop_calls, [])
        self.assertIsNotNone(window._direct_output_handoff_generation)
        self.assertFalse(window._paused_for_direct_output)

    def test_lossless_handoff_retargets_bridge_to_new_windows_output_after_grace(self) -> None:
        speakers = fake_output()
        usb = fake_usb_output()
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), speakers, usb, cable_playback],
            default_output=cable_playback,
        )
        window.engine._running = True
        self.assertEqual(window.output_combo.currentData(), speakers.id)
        starts: list[tuple[int | None, bool]] = []

        def fake_start_audio(liveness_attempt: int = 0, preserve_direct_output_handoff: bool = False) -> None:
            starts.append((window.output_combo.currentData(), preserve_direct_output_handoff))
            window.engine._running = True

        window.start_audio = fake_start_audio

        with patch("downmix_renderer.app.monotonic", return_value=20.0):
            window._sync_renderer_with_windows_default_output(usb, was_running=True)

        active_cable_snapshot = SimpleNamespace(
            running=True,
            status="Running",
            callback_status="",
            callback_status_count=0,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.05] + [0.0] * 15,
                left_meter=0.05,
                right_meter=0.05,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with (
            patch("downmix_renderer.app.default_wasapi_output", return_value=usb),
            patch("downmix_renderer.app.monotonic", return_value=20.16),
        ):
            self.assertTrue(window._maybe_pause_after_direct_output_handoff(active_cable_snapshot))

        self.assertEqual(window.output_combo.currentData(), usb.id)
        self.assertEqual(starts, [(usb.id, True)])
        self.assertIsNotNone(window._direct_output_handoff_generation)
        self.assertIsNone(window._manual_override_default_id)

    def test_lossless_handoff_does_not_retarget_bridge_before_grace(self) -> None:
        speakers = fake_output()
        usb = fake_usb_output()
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), speakers, usb, cable_playback],
            default_output=cable_playback,
        )
        window.engine._running = True
        starts: list[str] = []
        window.start_audio = lambda liveness_attempt=0: starts.append("start")

        with patch("downmix_renderer.app.monotonic", return_value=30.0):
            window._sync_renderer_with_windows_default_output(usb, was_running=True)

        active_cable_snapshot = SimpleNamespace(
            running=True,
            status="Running",
            callback_status="",
            callback_status_count=0,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.05] + [0.0] * 15,
                left_meter=0.05,
                right_meter=0.05,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with (
            patch("downmix_renderer.app.default_wasapi_output", return_value=usb),
            patch("downmix_renderer.app.monotonic", return_value=30.04),
        ):
            self.assertFalse(window._maybe_pause_after_direct_output_handoff(active_cable_snapshot))

        self.assertEqual(window.output_combo.currentData(), speakers.id)
        self.assertEqual(starts, [])

    def test_direct_output_handoff_pauses_when_cable_goes_silent(self) -> None:
        speakers = fake_output()
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), speakers, cable_playback],
            default_output=cable_playback,
        )
        window.engine._running = True
        stop_calls: list[bool] = []

        def fake_stop(resume_keep_awake: bool = True) -> None:
            stop_calls.append(resume_keep_awake)
            window.engine._running = False

        window.engine.stop = fake_stop

        with patch("downmix_renderer.app.monotonic", return_value=30.0):
            window._sync_renderer_with_windows_default_output(speakers, was_running=True)

        silent_cable_snapshot = SimpleNamespace(
            running=True,
            status="Running",
            callback_status="",
            callback_status_count=0,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.0] * 16,
                left_meter=0.0,
                right_meter=0.0,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with (
            patch("downmix_renderer.app.default_wasapi_output", return_value=speakers),
            patch("downmix_renderer.app.monotonic", side_effect=[30.1, 30.7]),
        ):
            self.assertFalse(window._maybe_pause_after_direct_output_handoff(silent_cable_snapshot))
            self.assertTrue(window._maybe_pause_after_direct_output_handoff(silent_cable_snapshot))

        self.assertEqual(stop_calls, [False])
        self.assertTrue(window._paused_for_direct_output)
        self.assertIsNone(window._direct_output_handoff_generation)

    def test_windows_cable_output_change_resumes_renderer_after_auto_pause(self) -> None:
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), fake_output(), cable_playback],
            default_output=fake_output(),
        )
        window._paused_for_direct_output = True
        window._force_auto_start = True
        starts: list[str] = []
        scheduled: list[tuple[int, object]] = []

        window.start_audio = lambda: starts.append("start")

        def capture_resume(delay_ms: int, callback: object) -> None:
            scheduled.append((delay_ms, callback))

        with patch("downmix_renderer.app.QtCore.QTimer.singleShot", side_effect=capture_resume):
            handled = window._sync_renderer_with_windows_default_output(cable_playback, was_running=False)

        self.assertTrue(handled)
        self.assertFalse(window._paused_for_direct_output)
        self.assertEqual(starts, [])
        self.assertEqual(len(scheduled), 1)
        self.assertGreaterEqual(scheduled[0][0], 60)
        self.assertLessEqual(scheduled[0][0], 150)

        with patch("downmix_renderer.app.default_wasapi_output", return_value=cable_playback):
            scheduled[0][1]()

        self.assertEqual(starts, ["start"])

    def test_device_poll_does_not_bypass_direct_output_resume_settle_delay(self) -> None:
        speakers = fake_output()
        cable_playback = fake_cable_playback_output()
        devices = [fake_input(), speakers, cable_playback]
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=devices,
            default_output=cable_playback,
        )
        window._paused_for_direct_output = True
        window._force_auto_start = True
        starts: list[str] = []
        scheduled: list[tuple[int, object]] = []

        window.start_audio = lambda: starts.append("start")

        def capture_resume(delay_ms: int, callback: object) -> None:
            scheduled.append((delay_ms, callback))

        with patch("downmix_renderer.app.QtCore.QTimer.singleShot", side_effect=capture_resume):
            window._apply_device_poll_result(devices, was_running=False)

        self.assertEqual(starts, [])
        self.assertEqual(len(scheduled), 1)

    def test_watchdog_does_not_bypass_pending_direct_output_resume_delay(self) -> None:
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), fake_output(), cable_playback],
            default_output=cable_playback,
        )
        window._force_auto_start = True
        window._audio_start_generation = 9
        window._pending_direct_output_resume_generation = 9
        starts: list[str] = []
        window.start_audio = lambda: starts.append("start")
        snapshot = SimpleNamespace(
            running=False,
            status="Stopped",
            callback_status="",
            callback_status_count=0,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.0] * 16,
                left_meter=0.0,
                right_meter=0.0,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with patch("downmix_renderer.app.monotonic", return_value=70.0):
            self.assertFalse(window._maybe_recover_audio_stream(snapshot))

        self.assertEqual(starts, [])

    def test_repeated_default_output_switches_use_symmetric_pause_resume_path(self) -> None:
        speakers = fake_output()
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), speakers, cable_playback],
            default_output=cable_playback,
        )
        window.engine._running = True
        starts: list[int] = []
        stops: list[bool] = []

        def fake_stop(resume_keep_awake: bool = True) -> None:
            stops.append(resume_keep_awake)
            window.engine._running = False

        def fake_start(liveness_attempt: int = 0) -> None:
            starts.append(liveness_attempt)
            window.engine._running = True

        window.engine.stop = fake_stop
        window.start_audio = fake_start

        scheduled: list[tuple[int, object]] = []

        def capture_resume(delay_ms: int, callback: object) -> None:
            scheduled.append((delay_ms, callback))

        with patch("downmix_renderer.app.QtCore.QTimer.singleShot", side_effect=capture_resume):
            for _ in range(50):
                with patch("downmix_renderer.app.monotonic", return_value=10.0):
                    self.assertTrue(window._sync_renderer_with_windows_default_output(speakers, was_running=True))
                silent_cable_snapshot = SimpleNamespace(
                    running=True,
                    status="Running",
                    callback_status="",
                    callback_status_count=0,
                    dsp_error_count=0,
                    dsp=SimpleNamespace(
                        raw_channel_levels=[0.0] * 16,
                        left_meter=0.0,
                        right_meter=0.0,
                        master_volume=1.0,
                        master_muted=False,
                    ),
                )
                with (
                    patch("downmix_renderer.app.default_wasapi_output", return_value=speakers),
                    patch("downmix_renderer.app.monotonic", side_effect=[10.1, 10.7]),
                ):
                    self.assertFalse(window._maybe_pause_after_direct_output_handoff(silent_cable_snapshot))
                    self.assertTrue(window._maybe_pause_after_direct_output_handoff(silent_cable_snapshot))
                self.assertTrue(window._paused_for_direct_output)
                self.assertTrue(window._sync_renderer_with_windows_default_output(cable_playback, was_running=False))
                self.assertFalse(window._paused_for_direct_output)
                scheduled[-1][1]()

        self.assertEqual(stops, [False] * 50)
        self.assertEqual(starts, [0] * 50)
        self.assertEqual([delay for delay, _ in scheduled], [120] * 50)
        self.assertTrue(window._force_auto_start)

    def test_previous_running_session_waits_when_windows_default_is_direct_speaker_output(self) -> None:
        speakers = fake_output()
        cable_playback = fake_cable_playback_output()
        saved: list[dict[str, object]] = []
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "was_running": True,
            },
            saved,
            devices=[fake_input(), speakers, cable_playback],
            default_output=speakers,
        )
        starts: list[str] = []
        window.start_audio = lambda: starts.append("start")

        window._auto_start_if_needed()

        self.assertEqual(starts, [])
        self.assertTrue(window._paused_for_direct_output)
        self.assertTrue(saved[-1]["resume_on_launch"])

    def test_launch_prioritizes_active_preset_output_over_windows_default(self) -> None:
        realtek = fake_output()
        qudelix = fake_usb_output()
        realtek_preset = preset_from_current("Realtek", fake_input(), realtek, -6, 0.8, "windows_7_1")
        qudelix_preset = preset_from_current("Qudelix", fake_input(), qudelix, -3, 1.0, "sharur_9_1_6")
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "preset_schema_version": 3,
                "active_preset_id": realtek_preset.id,
                "presets": [realtek_preset.to_dict(), qudelix_preset.to_dict()],
            },
            devices=[fake_input(), realtek, qudelix],
            default_output=qudelix,
        )

        self.assertEqual(window.active_preset_id, realtek_preset.id)
        self.assertEqual(window.output_combo.currentData(), realtek.id)
        self.assertEqual(window.preamp_slider.value(), -6)

    def test_device_refresh_selects_active_preset_output_when_it_reappears(self) -> None:
        realtek = fake_output()
        qudelix = fake_usb_output()
        qudelix_preset = preset_from_current("Qudelix", fake_input(), qudelix, -3, 1.0, "sharur_9_1_6")
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "preset_schema_version": 3,
                "active_preset_id": qudelix_preset.id,
                "presets": [qudelix_preset.to_dict()],
            },
            devices=[fake_input(), realtek],
            default_output=realtek,
        )
        self.assertEqual(window.active_preset_id, qudelix_preset.id)

        fresh_devices = [fake_input(), realtek, qudelix]
        window._refresh_device_lists(fresh_devices, window._make_device_signature(fresh_devices))

        self.assertEqual(window.active_preset_id, qudelix_preset.id)
        self.assertEqual(window.output_combo.currentData(), qudelix.id)

    def test_device_refresh_does_not_fallback_when_active_preset_output_disappears(self) -> None:
        realtek = fake_output()
        qudelix = fake_usb_output()
        qudelix_preset = preset_from_current("Qudelix", fake_input(), qudelix, -3, 1.0, "sharur_9_1_6")
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "preset_schema_version": 3,
                "active_preset_id": qudelix_preset.id,
                "presets": [qudelix_preset.to_dict()],
            },
            devices=[fake_input(), realtek, qudelix],
            default_output=realtek,
        )
        self.assertEqual(window.output_combo.currentData(), qudelix.id)

        fresh_devices = [fake_input(), realtek]
        window._refresh_device_lists(fresh_devices, window._make_device_signature(fresh_devices))

        self.assertEqual(window.active_preset_id, qudelix_preset.id)
        self.assertIsNone(window.output_combo.currentData())

    def test_smart_switching_does_not_leave_active_preset_for_windows_default_output(self) -> None:
        realtek = fake_output()
        qudelix = fake_usb_output()
        devices = [fake_input(), realtek, qudelix]
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "auto_start": False,
                "was_running": False,
            },
            devices=devices,
            default_output=realtek,
        )
        realtek_preset = preset_from_current("Realtek", fake_input(), realtek, -6, 0.8, "windows_7_1")
        qudelix_preset = preset_from_current(
            "Qudelix",
            fake_input(),
            qudelix,
            -3,
            1.0,
            "sharur_9_1_6",
            upmix_9_1_6_enabled=True,
            trim_left_db=-2.5,
            trim_right_db=-6.0,
        )
        window.presets = [realtek_preset, qudelix_preset]
        window.apply_preset(realtek_preset.id, start_after=False, manual=True)
        window.smart_switch_checkbox.setChecked(True)

        with (
            patch("downmix_renderer.app.list_devices", return_value=devices),
            patch("downmix_renderer.app.default_wasapi_output", return_value=qudelix),
        ):
            window.poll_devices()

        self.assertEqual(window.active_preset_id, realtek_preset.id)
        self.assertEqual(window.output_combo.currentData(), realtek.id)
        self.assertEqual(window.preamp_slider.value(), -6)
        self.assertEqual(window.channel_config, "windows_7_1")
        self.assertFalse(window.upmix916_checkbox.isChecked())
        self.assertEqual(window.trim_left_edit.value_db(), 0.0)
        self.assertEqual(window.trim_right_edit.value_db(), 0.0)

    def test_smart_switching_applies_entire_matching_preset_when_no_preset_is_active(self) -> None:
        realtek = fake_output()
        qudelix = fake_usb_output()
        devices = [fake_input(), realtek, qudelix]
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "auto_start": False,
                "was_running": False,
            },
            devices=devices,
            default_output=realtek,
        )
        realtek_preset = preset_from_current("Realtek", fake_input(), realtek, -6, 0.8, "windows_7_1")
        qudelix_preset = preset_from_current(
            "Qudelix",
            fake_input(),
            qudelix,
            -3,
            1.0,
            "sharur_9_1_6",
            surround_fill_enabled=True,
            upmix_9_1_6_enabled=True,
            trim_left_db=-2.5,
            trim_right_db=-6.0,
            sample_rate_mode="192000",
        )
        window.presets = [realtek_preset, qudelix_preset]
        window.active_preset_id = ""
        window.smart_switch_checkbox.setChecked(True)

        with (
            patch("downmix_renderer.app.list_devices", return_value=devices),
            patch("downmix_renderer.app.default_wasapi_output", return_value=qudelix),
        ):
            window.poll_devices()

        self.assertEqual(window.active_preset_id, qudelix_preset.id)
        self.assertEqual(window.output_combo.currentData(), qudelix.id)
        self.assertEqual(window.preamp_slider.value(), -3)
        self.assertEqual(window.channel_config, "sharur_9_1_6")
        self.assertTrue(window.surround_fill_checkbox.isChecked())
        self.assertTrue(window.upmix916_checkbox.isChecked())
        self.assertEqual(window.trim_left_edit.value_db(), -2.5)
        self.assertEqual(window.trim_right_edit.value_db(), -6.0)
        self.assertEqual(window.sample_rate_combo.currentData(), "192000")

    def test_selected_preset_output_device_can_be_updated_in_place(self) -> None:
        realtek = fake_output()
        qudelix = fake_usb_output()
        devices = [fake_input(), realtek, qudelix]
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "auto_start": False,
                "was_running": False,
            },
            devices=devices,
            default_output=realtek,
        )
        preset = preset_from_current("Daily", fake_input(), realtek, -6, 1.0, "windows_7_1")
        window.presets = [preset]
        window.apply_preset(preset.id, start_after=False, manual=True)

        window._set_combo_device(window.output_combo, qudelix)
        self.app.processEvents()

        self.assertEqual(window.active_preset_id, preset.id)
        window.save_active_preset()

        self.assertEqual(len(window.presets), 1)
        self.assertEqual(window.presets[0].id, preset.id)
        self.assertIn("Qudelix", str(window.presets[0].output_device))

    def test_smart_switching_does_not_fallback_when_active_output_has_no_preset(self) -> None:
        realtek = fake_output()
        hdmi = AudioDevice(
            id=4,
            name="HDMI (Monitor Audio)",
            hostapi="Windows WASAPI",
            max_input_channels=0,
            max_output_channels=2,
            default_samplerate=48000,
            default_low_input_latency=0.0,
            default_low_output_latency=0.003,
            default_high_input_latency=0.0,
            default_high_output_latency=0.010,
        )
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), realtek, hdmi],
            default_output=realtek,
        )
        realtek_preset = preset_from_current("Realtek", fake_input(), realtek, -6, 1.0, "windows_7_1")
        window.presets = [realtek_preset]
        window._set_combo_device(window.output_combo, hdmi)

        self.assertIsNone(window._smart_switch_preset(hdmi))

    def test_fresh_launch_does_not_force_auto_start(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})

        self.assertFalse(window._force_auto_start)

    def test_idle_recovery_restarts_when_input_activity_has_silent_output(self) -> None:
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), fake_output(), cable_playback],
            default_output=cable_playback,
        )
        restarts: list[str] = []
        window.start_audio = lambda: restarts.append("restart")
        dsp = SimpleNamespace(
            raw_channel_levels=[0.04] + [0.0] * 15,
            left_meter=0.0,
            right_meter=0.0,
            master_volume=1.0,
            master_muted=False,
        )
        snapshot = SimpleNamespace(
            running=True,
            status="Running",
            callback_status="",
            callback_status_count=0,
            dsp_error_count=0,
            dsp=dsp,
        )

        with patch("downmix_renderer.app.monotonic", side_effect=[10.0, 11.0, 12.7]):
            self.assertFalse(window._maybe_recover_audio_stream(snapshot))
            self.assertFalse(window._maybe_recover_audio_stream(snapshot))
            self.assertTrue(window._maybe_recover_audio_stream(snapshot))

        self.assertEqual(restarts, ["restart"])

    def test_idle_recovery_restarts_immediately_on_invalidated_stream_status(self) -> None:
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), fake_output(), cable_playback],
            default_output=cable_playback,
        )
        restarts: list[str] = []
        window.start_audio = lambda: restarts.append("restart")
        snapshot = SimpleNamespace(
            running=True,
            status="AUDCLNT_E_DEVICE_INVALIDATED",
            callback_status="",
            callback_status_count=1,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.0] * 16,
                left_meter=0.0,
                right_meter=0.0,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with patch("downmix_renderer.app.monotonic", return_value=30.0):
            self.assertTrue(window._maybe_recover_audio_stream(snapshot))

        self.assertEqual(restarts, ["restart"])

    def test_stale_device_reroute_notification_does_not_restart_again(self) -> None:
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), fake_output(), cable_playback],
            default_output=cable_playback,
        )
        window._force_auto_start = True
        window._last_callback_status_count = 4
        restarts: list[str] = []
        window.start_audio = lambda: restarts.append("restart")
        snapshot = SimpleNamespace(
            running=True,
            status="Running (C++ ultra)",
            callback_status="device rerouted",
            callback_status_count=4,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.0] * 16,
                left_meter=0.0,
                right_meter=0.0,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with patch("downmix_renderer.app.monotonic", return_value=48.0):
            self.assertFalse(window._maybe_recover_audio_stream(snapshot))

        self.assertEqual(restarts, [])

    def test_new_device_reroute_notification_restarts_once(self) -> None:
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), fake_output(), cable_playback],
            default_output=cable_playback,
        )
        window._force_auto_start = True
        window._last_callback_status_count = 4
        restarts: list[str] = []
        window.start_audio = lambda: restarts.append("restart")
        snapshot = SimpleNamespace(
            running=True,
            status="Running (C++ ultra)",
            callback_status="device rerouted",
            callback_status_count=5,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.0] * 16,
                left_meter=0.0,
                right_meter=0.0,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with patch("downmix_renderer.app.monotonic", return_value=48.0):
            self.assertTrue(window._maybe_recover_audio_stream(snapshot))

        self.assertEqual(restarts, ["restart"])
        self.assertEqual(window._last_callback_status_count, 5)

    def test_new_device_reroute_notification_bypasses_idle_recovery_cooldown(self) -> None:
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), fake_output(), cable_playback],
            default_output=cable_playback,
        )
        window._force_auto_start = True
        window._last_audio_recovery_at = 40.0
        window._last_callback_status_count = 7
        restarts: list[str] = []
        window.start_audio = lambda: restarts.append("restart")
        snapshot = SimpleNamespace(
            running=True,
            status="Running (C++ ultra)",
            callback_status="device rerouted",
            callback_status_count=8,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.0] * 16,
                left_meter=0.0,
                right_meter=0.0,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with patch("downmix_renderer.app.monotonic", return_value=40.25):
            self.assertTrue(window._maybe_recover_audio_stream(snapshot))

        self.assertEqual(restarts, ["restart"])

    def test_new_device_stopped_notification_bypasses_idle_recovery_cooldown(self) -> None:
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), fake_output(), cable_playback],
            default_output=cable_playback,
        )
        window._force_auto_start = True
        window._last_audio_recovery_at = 40.0
        window._last_callback_status_count = 2
        restarts: list[str] = []
        window.start_audio = lambda: restarts.append("restart")
        snapshot = SimpleNamespace(
            running=False,
            status="Stopped",
            callback_status="device stopped",
            callback_status_count=3,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.0] * 16,
                left_meter=0.0,
                right_meter=0.0,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with patch("downmix_renderer.app.monotonic", return_value=40.25):
            self.assertTrue(window._maybe_recover_audio_stream(snapshot))

        self.assertEqual(restarts, ["restart"])

    def test_stale_device_stopped_notification_does_not_restart_again(self) -> None:
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), fake_output(), cable_playback],
            default_output=cable_playback,
        )
        window._force_auto_start = True
        window._last_callback_status_count = 3
        restarts: list[str] = []
        window.start_audio = lambda: restarts.append("restart")
        snapshot = SimpleNamespace(
            running=False,
            status="Stopped",
            callback_status="device stopped",
            callback_status_count=3,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.0] * 16,
                left_meter=0.0,
                right_meter=0.0,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with patch("downmix_renderer.app.monotonic", return_value=49.0):
            self.assertFalse(window._maybe_recover_audio_stream(snapshot))

        self.assertEqual(restarts, [])

    def test_recovery_pauses_instead_of_restarting_when_windows_default_is_direct_output(self) -> None:
        speakers = fake_output()
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), speakers, cable_playback],
            default_output=speakers,
        )
        window._force_auto_start = True
        window.engine._running = True
        restarts: list[str] = []
        stop_calls: list[bool] = []
        window.start_audio = lambda: restarts.append("restart")

        def fake_stop(resume_keep_awake: bool = True) -> None:
            stop_calls.append(resume_keep_awake)
            window.engine._running = False

        window.engine.stop = fake_stop
        snapshot = SimpleNamespace(
            running=True,
            status="AUDCLNT_E_DEVICE_INVALIDATED",
            callback_status="",
            callback_status_count=1,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.0] * 16,
                left_meter=0.0,
                right_meter=0.0,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with patch("downmix_renderer.app.monotonic", return_value=40.0):
            self.assertFalse(window._maybe_recover_audio_stream(snapshot))

        self.assertEqual(restarts, [])
        self.assertEqual(stop_calls, [])
        self.assertFalse(window._paused_for_direct_output)
        self.assertIsNotNone(window._direct_output_handoff_generation)

    def test_disabled_renderer_does_not_restart_from_stale_watchdog_status(self) -> None:
        speakers = fake_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), speakers, fake_cable_playback_output()],
            default_output=speakers,
        )
        window._force_auto_start = False
        restarts: list[str] = []
        window.start_audio = lambda: restarts.append("restart")
        snapshot = SimpleNamespace(
            running=False,
            status="AUDCLNT_E_DEVICE_INVALIDATED",
            callback_status="device invalidated",
            callback_status_count=1,
            dsp_error_count=0,
            dsp=SimpleNamespace(
                raw_channel_levels=[0.0] * 16,
                left_meter=0.0,
                right_meter=0.0,
                master_volume=1.0,
                master_muted=False,
            ),
        )

        with patch("downmix_renderer.app.monotonic", return_value=50.0):
            self.assertFalse(window._maybe_recover_audio_stream(snapshot))

        self.assertEqual(restarts, [])

    def test_liveness_failure_performs_direction_neutral_full_rebuild_once(self) -> None:
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), fake_output(), cable_playback],
            default_output=cable_playback,
        )
        window.engine._running = True
        window._audio_start_generation = 7
        starts: list[int] = []
        stops: list[bool] = []

        def fake_stop(resume_keep_awake: bool = True) -> None:
            stops.append(resume_keep_awake)
            window.engine._running = False

        def fake_start_audio(liveness_attempt: int = 0) -> None:
            starts.append(liveness_attempt)

        window.engine.stop = fake_stop
        window.start_audio = fake_start_audio

        window._verify_audio_liveness(7, baseline_callbacks=0, baseline_frames=0, attempt=0)

        self.assertEqual(stops, [False])
        self.assertEqual(starts, [1])
        self.assertEqual(window._liveness_rebuilds, 1)
        self.assertTrue(any("liveness_failed" in line for line in window._device_lifecycle_events))
        self.assertTrue(any("liveness_rebuild_teardown_complete" in line for line in window._device_lifecycle_events))

    def test_default_output_tracking_uses_endpoint_identity_not_only_portaudio_id(self) -> None:
        first = fake_endpoint_output(22, "Speakers (Realtek(R) Audio)", "{endpoint-a}")
        second = fake_endpoint_output(22, "Speakers (Realtek(R) Audio)", "{endpoint-b}")
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), first, second],
            default_output=first,
        )
        window._last_default_output_id = first.id
        window._last_default_output_signature = window._default_output_signature(first)
        window._manual_override_default_id = first.id
        window._manual_override_default_signature = window._default_output_signature(first)

        changed = window._observe_default_output(second)

        self.assertTrue(changed)
        self.assertEqual(window._last_default_output_id, second.id)
        self.assertEqual(window._last_default_output_signature, window._default_output_signature(second))
        self.assertIsNone(window._manual_override_default_id)
        self.assertIsNone(window._manual_override_default_signature)

    def test_stale_liveness_checks_do_not_touch_current_stream(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})
        window.engine._running = True
        window._audio_start_generation = 12
        stops: list[bool] = []
        starts: list[int] = []
        window.engine.stop = lambda resume_keep_awake=True: stops.append(resume_keep_awake)
        window.start_audio = lambda liveness_attempt=0: starts.append(liveness_attempt)

        window._verify_audio_liveness(11, baseline_callbacks=0, baseline_frames=0, attempt=0)

        self.assertEqual(stops, [])
        self.assertEqual(starts, [])
        self.assertTrue(any("liveness_stale" in line for line in window._device_lifecycle_events))

    def test_liveness_failure_pauses_instead_of_rebuilding_when_default_is_direct_output(self) -> None:
        speakers = fake_output()
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {"baseline_recovery_version": BASELINE_RECOVERY_VERSION},
            devices=[fake_input(), speakers, cable_playback],
            default_output=speakers,
        )
        window.engine._running = True
        window._force_auto_start = True
        window._audio_start_generation = 4
        stops: list[bool] = []
        starts: list[int] = []

        def fake_stop(resume_keep_awake: bool = True) -> None:
            stops.append(resume_keep_awake)
            window.engine._running = False

        window.engine.stop = fake_stop
        window.start_audio = lambda liveness_attempt=0: starts.append(liveness_attempt)

        with patch("downmix_renderer.app.monotonic", return_value=60.0):
            window._verify_audio_liveness(4, baseline_callbacks=0, baseline_frames=0, attempt=0)

        self.assertEqual(stops, [])
        self.assertEqual(starts, [])
        self.assertFalse(window._paused_for_direct_output)
        self.assertIsNotNone(window._direct_output_handoff_generation)
        self.assertTrue(window._force_auto_start)

    def test_previous_running_session_resumes_on_launch(self) -> None:
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "was_running": True,
                "auto_start": False,
            }
        )

        self.assertTrue(window._force_auto_start)

    def test_launch_autostart_timer_does_not_interrupt_first_manual_output_switch(self) -> None:
        speakers = fake_output()
        usb = fake_usb_output()
        cable_playback = fake_cable_playback_output()
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "was_running": True,
            },
            devices=[fake_input(), speakers, usb, cable_playback],
            default_output=speakers,
        )
        starts: list[str] = []
        stops: list[bool] = []

        def fake_start_audio() -> None:
            starts.append(window.output_combo.currentText())
            window.engine._running = True

        def fake_stop(resume_keep_awake: bool = True) -> None:
            stops.append(resume_keep_awake)
            window.engine._running = False

        window.start_audio = fake_start_audio
        window.engine.stop = fake_stop
        window.engine._running = True
        window._force_auto_start = True

        window._set_combo_device(window.output_combo, usb)
        window._auto_start_if_needed()

        self.assertEqual(starts, ["Headphones (Qudelix-5K)"])
        self.assertEqual(stops, [])
        self.assertFalse(window._paused_for_direct_output)

    def test_system_boot_autostart_uses_existing_startup_helper(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})

        with patch("downmix_renderer.app.set_system_autostart", return_value=(True, "OK")) as helper:
            window.set_system_boot_autostart(True)

        helper.assert_called_once()
        self.assertIs(helper.call_args.args[0], True)

    def test_saved_system_boot_autostart_repairs_stale_registration_on_launch(self) -> None:
        with patch("downmix_renderer.app.set_system_autostart", return_value=(True, "OK")) as helper:
            window = self.make_window(
                {
                    "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                    "system_boot_autostart": True,
                }
            )
            window._sync_system_boot_autostart_after_launch()

        helper.assert_called_once_with(True, window._app_root)

    def test_qt_scaling_configuration_sets_dpi_environment_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QT_ENABLE_HIGHDPI_SCALING", None)
            os.environ.pop("QT_AUTO_SCREEN_SCALE_FACTOR", None)

            configure_qt_scaling()

            self.assertEqual(os.environ["QT_ENABLE_HIGHDPI_SCALING"], "1")
            self.assertEqual(os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"], "1")


if __name__ == "__main__":
    unittest.main()
