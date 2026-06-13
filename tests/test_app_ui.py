from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtGui, QtWidgets
from PyQt5 import QtCore

from downmix_renderer.app import (
    BASELINE_RECOVERY_VERSION,
    BASE_STYLE,
    DEVICE_FORCE_REFRESH_INTERVAL,
    GITHUB_URL,
    RawMonitorDialog,
    RendererWindow,
    RouteGlassCombo,
    RoomVisualizer,
    SpatialPage,
    StereoSumMeter,
    SwitchCheckBox,
    TrimLineEdit,
    build_details_body,
    clamp_trim_db,
)
from downmix_renderer.constants import APP_DISPLAY_NAME
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
            patch("downmix_renderer.app.list_devices", return_value=available_devices),
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

    def test_main_renderer_page_has_no_scroll_area(self) -> None:
        window = self.make_window()
        main = window.findChild(QtWidgets.QWidget, "mainPage")

        self.assertIsNotNone(main)
        self.assertEqual(window.minimumSize(), QtCore.QSize(1120, 925))
        self.assertEqual(window.size(), QtCore.QSize(1212, 925))
        self.assertIsInstance(main, SpatialPage)
        self.assertEqual(main.findChildren(QtWidgets.QScrollArea), [])
        layout = main.layout()
        self.assertEqual(layout.columnStretch(0), 0)
        self.assertEqual(layout.columnStretch(1), 1)
        self.assertEqual(layout.columnStretch(2), 0)

    def test_spatial_page_draws_live_finalised_v3_backdrop_layer(self) -> None:
        window = self.make_window()
        page = window.findChild(QtWidgets.QWidget, "mainPage")

        with patch("downmix_renderer.app.paint_spatial_backdrop") as paint_backdrop:
            page.paintEvent(QtGui.QPaintEvent(page.rect()))

        paint_backdrop.assert_called_once()
        call = paint_backdrop.call_args
        self.assertEqual(call.args[1], window.rect())
        self.assertEqual(call.args[2], window._backdrop_phase)
        self.assertTrue(call.kwargs["lower_balance"])
        self.assertAlmostEqual(call.kwargs["intensity"], 0.44)
        self.assertTrue(call.kwargs["cinematic_depth"])
        self.assertIsInstance(call.kwargs["cursor"], QtCore.QPoint)

    def test_visual_motion_keeps_production_backdrop_cadence_while_rendering(self) -> None:
        window = self.make_window()

        sync_visual_performance = getattr(window, "_sync_visual_performance", None)
        self.assertIsNotNone(sync_visual_performance)

        self.assertEqual(window.backdrop_timer.interval(), 70)
        self.assertLess(window.room_visualizer.animation_timer.interval(), window.AUDIO_SAFE_ROOM_INTERVAL_MS)

        sync_visual_performance(rendering=True)

        self.assertEqual(window.backdrop_timer.interval(), 70)
        self.assertEqual(window.room_visualizer.animation_timer.interval(), window.AUDIO_SAFE_ROOM_INTERVAL_MS)

        sync_visual_performance(rendering=False)

        self.assertEqual(window.backdrop_timer.interval(), 70)
        self.assertEqual(window.room_visualizer.animation_timer.interval(), window.IDLE_ROOM_INTERVAL_MS)

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
        page = window.findChild(QtWidgets.QWidget, "mainPage")
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
        self.assertIsInstance(call.kwargs["cursor"], QtCore.QPoint)

    def test_window_backdrop_skips_region_covered_by_live_spatial_page(self) -> None:
        window = self.make_window()
        window.show()
        self.addCleanup(window.hide)
        page = window.findChild(QtWidgets.QWidget, "mainPage")
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
        page = window.findChild(QtWidgets.QWidget, "mainPage")
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
        self.assertIsNotNone(window.raw_monitor_button)
        self.assertIsNotNone(window.refresh_devices_button)
        self.assertIsNotNone(window.smart_switch_checkbox)
        self.assertIsNotNone(window.surround_fill_checkbox)
        self.assertIsNotNone(window.upmix916_checkbox)
        self.assertIsNotNone(window.keep_awake_checkbox)
        self.assertIsNotNone(window.sample_rate_combo)
        self.assertEqual(
            [window.sample_rate_combo.itemData(row) for row in range(window.sample_rate_combo.count())],
            ["auto", "48000", "96000", "192000"],
        )
        self.assertIsInstance(window.stereo_sum_meter, StereoSumMeter)
        self.assertIsNotNone(window.info_button)
        self.assertEqual(window.info_button.text(), "")
        self.assertEqual(window.info_button.toolTip(), "Renderer details")
        self.assertEqual(window.surround_fill_checkbox.text(), "7.1 Upmix")
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

    def test_keep_output_awake_card_uses_compact_header_layout(self) -> None:
        window = self.make_window()

        card = window.findChild(QtWidgets.QFrame, "keepAwakeCard")

        self.assertIsNotNone(card)
        self.assertEqual(window.keep_awake_checkbox.text(), "Keep output awake")
        self.assertEqual(window.keep_awake_checkbox.minimumHeight(), 30)
        self.assertEqual(card.minimumHeight(), 86)
        self.assertEqual(card.maximumHeight(), 96)

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
        window.resize(1190, 735)
        window.show()
        self.app.processEvents()

        self.assertTrue(window.sample_rate_combo.isVisible())
        self.assertGreaterEqual(window.sample_rate_combo.width(), 124)
        self.assertLessEqual(window.sample_rate_combo.width(), 144)
        self.assertEqual(
            [window.sample_rate_combo.itemText(index) for index in range(window.sample_rate_combo.count())],
            ["Auto", "48 kHz", "96 kHz", "192 kHz"],
        )

    def test_route_dropdown_popups_use_themed_route_views(self) -> None:
        window = self.make_window()

        for combo in (window.output_combo, window.sample_rate_combo):
            self.assertIsInstance(combo, RouteGlassCombo)
            self.assertEqual(combo.objectName(), "routeGlassCombo")
            self.assertEqual(combo.view().objectName(), "routeGlassPopup")
            self.assertEqual(combo.view().frameShape(), QtWidgets.QFrame.NoFrame)
            self.assertGreaterEqual(combo.maxVisibleItems(), 6)
            self.assertIn("QListView#routeGlassPopup", combo.view().styleSheet())
            self.assertIn("rgba(3, 3, 3, 250)", combo.view().styleSheet())

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

        self.assertEqual(widths, {88})
        self.assertLessEqual(max(tops) - min(tops), 1)
        self.assertLessEqual(max(centers) - min(centers), 1)
        self.assertGreaterEqual(window.sample_rate_combo.width(), 124)
        self.assertLessEqual(window.sample_rate_combo.width(), 144)
        self.assertGreater(window.output_combo.width(), window.sample_rate_combo.width())

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

    def test_header_keeps_premium_renderer_and_presets_tabs(self) -> None:
        window = self.make_window()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.hide)
        window.show()
        self.app.processEvents()

        self.assertEqual(window.tabs.tabText(0), "Renderer")
        self.assertEqual(window.tabs.tabText(1), "Presets")
        self.assertEqual(window.tabs.currentIndex(), 0)
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
        self.assertEqual(window.github_button.width(), 34)
        self.assertEqual(window.github_button.height(), 34)
        self.assertGreaterEqual(window.github_button.geometry().top(), 8)

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

    def test_renderer_columns_align_at_launch(self) -> None:
        window = self.make_window()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.hide)
        window.show()
        self.app.processEvents()

        left = window.findChild(QtWidgets.QWidget, "rendererLeftColumn")
        center = window.findChild(QtWidgets.QWidget, "rendererCenterColumn")
        right = window.findChild(QtWidgets.QWidget, "rendererRightColumn")

        self.assertIsNotNone(left)
        self.assertIsNotNone(center)
        self.assertIsNotNone(right)
        self.assertAlmostEqual(left.geometry().bottom(), center.geometry().bottom(), delta=1)
        self.assertAlmostEqual(right.geometry().bottom(), center.geometry().bottom(), delta=1)
        last_left_widget = left.layout().itemAt(left.layout().count() - 1).widget()
        self.assertIn(window.stereo_sum_meter, last_left_widget.findChildren(StereoSumMeter))
        meter_bottom = window.stereo_sum_meter.geometry().y() + window.stereo_sum_meter.height()
        self.assertGreaterEqual(last_left_widget.height(), meter_bottom + 12)

    def test_presets_page_fits_default_launch_without_outer_scroll(self) -> None:
        window = self.make_window()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.hide)
        window.resize(window.minimumSize())
        window.show()
        window.tabs.setCurrentIndex(1)
        self.app.processEvents()

        presets_page = window.findChild(QtWidgets.QWidget, "presetsPage")
        outer_scrolls = [
            scroll for scroll in presets_page.findChildren(QtWidgets.QScrollArea)
            if scroll.parentWidget() is presets_page
        ]
        self.assertEqual(len(outer_scrolls), 1)
        self.assertEqual(outer_scrolls[0].verticalScrollBar().maximum(), 0)

    def test_channel_field_uses_premium_room_visualizer(self) -> None:
        window = self.make_window()

        self.assertIsInstance(window.room_visualizer, RoomVisualizer)
        self.assertEqual(window.room_visualizer.speaker_count, 8)
        self.assertEqual(len(window.tiles), 8)

        window.set_channel_config("sharur_9_1_6")
        self.assertEqual(window.room_visualizer.speaker_count, 16)
        self.assertEqual(len(window.tiles), 16)
        self.assertEqual(window.room_visualizer.minimumHeight(), RoomVisualizer.FIXED_HEIGHT)
        self.assertEqual(window.room_visualizer.maximumHeight(), RoomVisualizer.FIXED_HEIGHT)
        self.assertEqual(RoomVisualizer.FIXED_HEIGHT, 360)

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

    def test_stereo_sum_meter_card_stays_compact(self) -> None:
        window = self.make_window()
        window.show()
        self.app.processEvents()

        meter_card = window.stereo_sum_meter.parentWidget()

        self.assertEqual(window.stereo_sum_meter.sizePolicy().verticalPolicy(), QtWidgets.QSizePolicy.Fixed)
        self.assertEqual(meter_card.sizePolicy().verticalPolicy(), QtWidgets.QSizePolicy.Fixed)
        self.assertLessEqual(window.stereo_sum_meter.minimumHeight(), 232)

    def test_stereo_meter_is_under_keep_awake_in_left_column(self) -> None:
        window = self.make_window()
        left = window.findChild(QtWidgets.QWidget, "rendererLeftColumn")
        right = window.findChild(QtWidgets.QWidget, "rendererRightColumn")
        visible_text = "\n".join(label.text() for label in window.findChildren(QtWidgets.QLabel))

        self.assertIsNotNone(left)
        self.assertIsNotNone(right)
        self.assertIn(window.stereo_sum_meter, left.findChildren(StereoSumMeter))
        self.assertNotIn(window.stereo_sum_meter, right.findChildren(StereoSumMeter))
        self.assertIn(window.raw_monitor_button, right.findChildren(QtWidgets.QPushButton))
        self.assertNotIn("OUTPUT KEEP-ALIVE", visible_text)

    def test_session_status_has_distinct_premium_treatment(self) -> None:
        window = self.make_window()

        self.assertEqual(window.render_toggle_button.objectName(), "sessionRenderToggle")
        self.assertGreaterEqual(window.render_toggle_button.minimumHeight(), 42)
        self.assertEqual(window.render_toggle_button.text(), "Render")
        self.assertFalse(hasattr(window, "status_label"))
        self.assertFalse(hasattr(window, "start_button"))
        self.assertFalse(hasattr(window, "stop_button"))
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

    def test_presets_page_builds_peq_controls_with_profile_labels(self) -> None:
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
        section_text = "\n".join(label.text() for label in window.findChild(QtWidgets.QWidget, "presetsPage").findChildren(QtWidgets.QLabel, "section"))
        self.assertIn("SAVED PROFILES", section_text)
        self.assertIn("PROFILE CONTROL", section_text)
        self.assertIn("OUTPUT ROUTING AND PEQ", section_text)
        self.assertIn("CHANNEL TRIM", section_text)
        self.assertIn("SPEAKER EQ CHANNEL MAPPING", section_text)
        self.assertEqual(window.tabs.tabText(1), "Presets")
        self.assertEqual(window.lr_swap_panel.geometry().top(), window.channel_trim_panel.geometry().top())
        self.assertAlmostEqual(window.lr_swap_panel.width(), window.channel_trim_panel.width(), delta=1)
        self.assertEqual(window.lr_swap_panel.height(), window.channel_trim_panel.height())
        self.assertGreater(window.channel_trim_panel.geometry().left(), window.lr_swap_panel.geometry().right())
        self.assertGreater(window.speaker_mapping_panel.geometry().top(), window.channel_trim_panel.geometry().bottom())
        self.assertEqual(window.speaker_mapping_panel.geometry().left(), window.lr_swap_panel.geometry().left())
        self.assertGreater(window.speaker_mapping_panel.width(), window.lr_swap_panel.width() + window.channel_trim_panel.width())
        presets_body = window.findChild(QtWidgets.QWidget, "presetsBody")
        self.assertLessEqual(presets_body.height() - window.peq_routing_card.geometry().bottom(), 8)

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
        row_192 = next(row for row in range(window.sample_rate_combo.count()) if window.sample_rate_combo.itemData(row) == "192000")
        window.sample_rate_combo.setCurrentIndex(row_192)
        window._apply_peq_routing_state(persist=True)

        self.assertTrue(saved[-1]["lr_swap_enabled"])
        self.assertTrue(saved[-1]["global_peq_enabled"])
        self.assertEqual(saved[-1]["global_peq_text"], "Preamp: -3 dB")
        self.assertTrue(saved[-1]["speaker_eq_enabled"])
        self.assertEqual(saved[-1]["speaker_eq_text"], "CH:0\nPreamp: -6 dB")
        self.assertEqual(saved[-1]["trim_left_db"], -2.5)
        self.assertEqual(saved[-1]["trim_right_db"], -6.0)
        self.assertEqual(saved[-1]["sample_rate_mode"], "192000")

        window.preset_name_edit.setText("Corrected")
        window.create_preset()
        preset = window.presets[-1]
        self.assertTrue(preset.lr_swap_enabled)
        self.assertEqual(preset.global_peq_text, "Preamp: -3 dB")
        self.assertEqual(preset.speaker_eq_text, "CH:0\nPreamp: -6 dB")
        self.assertEqual(preset.trim_left_db, -2.5)
        self.assertEqual(preset.trim_right_db, -6.0)
        self.assertEqual(preset.sample_rate_mode, "192000")

        window._set_peq_controls_from_values()
        window.sample_rate_combo.setCurrentIndex(0)
        window.apply_preset(preset.id, start_after=False)

        self.assertTrue(window.lr_swap_checkbox.isChecked())
        self.assertTrue(window.global_peq_checkbox.isChecked())
        self.assertEqual(window.global_peq_text.toPlainText(), "Preamp: -3 dB")
        self.assertTrue(window.speaker_eq_checkbox.isChecked())
        self.assertEqual(window.speaker_eq_text.toPlainText(), "CH:0\nPreamp: -6 dB")
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
        button_texts = [button.text() for button in window.findChildren(QtWidgets.QPushButton, "preset")]
        self.assertIn("New Name", button_texts)

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
        self.assertIn("Speaker L/R 1/0", text)
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
        self.assertEqual(windows["RL"][0], 4)
        self.assertEqual(windows["RR"][0], 5)
        self.assertEqual(windows["SL"][0], 6)
        self.assertEqual(windows["SR"][0], 7)
        self.assertLess(windows["SL"][2], windows["RL"][2])
        self.assertLess(windows["SR"][2], windows["RR"][2])

        sharur = {label: (source_index, x, y, z) for source_index, label, x, y, z in RoomVisualizer._speakers_for_config("sharur_9_1_6")}
        self.assertEqual(sharur["Lw"][0], 4)
        self.assertEqual(sharur["Rw"][0], 5)
        self.assertEqual(sharur["Lrs"][0], 6)
        self.assertEqual(sharur["Rrs"][0], 7)
        self.assertEqual(sharur["Ls"][0], 8)
        self.assertEqual(sharur["Rs"][0], 9)
        self.assertEqual(sharur["Ltf"][0], 10)
        self.assertEqual(sharur["Ltm"][0], 12)
        self.assertEqual(sharur["Ltr"][0], 14)
        self.assertLess(sharur["Lw"][2], sharur["Ls"][2])
        self.assertLess(sharur["Ls"][2], sharur["Lrs"][2])

    def test_channel_field_mode_buttons_rebuild_tiles_and_visualizer(self) -> None:
        window = self.make_window()

        self.assertEqual(window.mode_buttons["windows_7_1"].text(), "7.1 Monitor")
        self.assertEqual(window.mode_buttons["sharur_9_1_6"].text(), "9.1.6 Monitor")

        window.mode_buttons["sharur_9_1_6"].click()
        self.app.processEvents()

        self.assertEqual(window.channel_config, "sharur_9_1_6")
        self.assertEqual(window.room_visualizer.speaker_count, 16)
        self.assertEqual([tile.name for tile in window.tiles], [
            "FL", "FR", "FC", "LFE", "BL", "BR", "BLC", "BRC",
            "SL", "SR", "TFL", "TFR", "TSL", "TSR", "TBL", "TBR",
        ])
        self.assertFalse(bool(window.mode_buttons["windows_7_1"].property("active")))
        self.assertTrue(bool(window.mode_buttons["sharur_9_1_6"].property("active")))

        window.mode_buttons["windows_7_1"].click()
        self.app.processEvents()

        self.assertEqual(window.channel_config, "windows_7_1")
        self.assertEqual(window.room_visualizer.speaker_count, 8)
        self.assertEqual([tile.name for tile in window.tiles], ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"])
        self.assertTrue(bool(window.mode_buttons["windows_7_1"].property("active")))
        self.assertFalse(bool(window.mode_buttons["sharur_9_1_6"].property("active")))

    def test_toggles_use_custom_white_black_switch_control(self) -> None:
        window = self.make_window()

        for checkbox in (
            window.smart_switch_checkbox,
            window.system_boot_checkbox,
            window.surround_fill_checkbox,
            window.upmix916_checkbox,
            window.keep_awake_checkbox,
        ):
            self.assertIsInstance(checkbox, SwitchCheckBox)
            self.assertEqual(checkbox.objectName(), "switchControl")
            self.assertNotIn("ON", checkbox.text())
            self.assertNotIn("OFF", checkbox.text())

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

    def test_chrome_visuals_match_finalised_v3_palette(self) -> None:
        self.assertNotIn("rgba(99, 199, 255, 42)", BASE_STYLE)
        self.assertNotIn("rgba(111, 240, 160, 28)", BASE_STYLE)
        self.assertIn("background-color: #030303;", BASE_STYLE)
        self.assertIn("border: 1px solid #1d1d1d;", BASE_STYLE)
        self.assertIn("stop:0 rgba(2, 2, 2, 228)", BASE_STYLE)
        self.assertIn("border: 1px solid rgba(255, 255, 255, 24);", BASE_STYLE)
        self.assertIn("QFrame#routeLane", BASE_STYLE)
        self.assertIn("QFrame#card:hover", BASE_STYLE)

    def test_raw_monitor_uses_premium_dialog(self) -> None:
        window = self.make_window()

        dialog = RawMonitorDialog(window)
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.windowTitle(), "Raw 16ch Monitor")
        self.assertEqual(len(dialog.tiles), 16)

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

    def test_audio_stability_control_is_hidden_and_ultra_is_internal_default(self) -> None:
        window = self.make_window()

        self.assertFalse(hasattr(window, "stability_combo"))
        self.assertEqual(window._selected_audio_stability(), "ultra")

    def test_renderer_details_rows_are_wrapped_and_aligned(self) -> None:
        body = build_details_body()
        self.addCleanup(body.deleteLater)

        rows = body.findChildren(QtWidgets.QWidget, "detailsRow")
        names = body.findChildren(QtWidgets.QLabel, "detailsName")
        descriptions = body.findChildren(QtWidgets.QLabel, "detailsDescription")

        self.assertGreaterEqual(len(rows), 18)
        self.assertEqual(len(names), len(descriptions))
        self.assertTrue(all(label.minimumWidth() == 158 and label.maximumWidth() == 158 for label in names))
        self.assertTrue(all(label.wordWrap() for label in descriptions))
        self.assertTrue(all(row.layout().spacing() >= 12 for row in rows))
        name_text = {label.text() for label in names}
        self.assertIn("7.1 Upmix", name_text)
        self.assertIn("Output keep-alive", name_text)
        self.assertIn("User PEQ", name_text)
        self.assertIn("Speaker EQ", name_text)
        self.assertIn("L/R Swap", name_text)
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

    def test_running_renderer_restarts_when_selected_route_format_changes(self) -> None:
        input_96k = with_samplerate(fake_input(), 96000)
        output = fake_output()
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
            patch("downmix_renderer.app.list_devices", return_value=[input_96k, output]),
            patch("downmix_renderer.app.default_wasapi_output", return_value=output),
        ):
            window.poll_devices()

        self.assertEqual(restart_rates, [96000])

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
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})
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
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})
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

    def test_previous_running_session_resumes_on_launch(self) -> None:
        window = self.make_window(
            {
                "baseline_recovery_version": BASELINE_RECOVERY_VERSION,
                "was_running": True,
                "auto_start": False,
            }
        )

        self.assertTrue(window._force_auto_start)

    def test_system_boot_autostart_uses_existing_startup_helper(self) -> None:
        window = self.make_window({"baseline_recovery_version": BASELINE_RECOVERY_VERSION})

        with patch("downmix_renderer.app.set_system_autostart", return_value=(True, "OK")) as helper:
            window.set_system_boot_autostart(True)

        helper.assert_called_once()
        self.assertIs(helper.call_args.args[0], True)


if __name__ == "__main__":
    unittest.main()
