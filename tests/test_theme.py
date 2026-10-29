import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit, QVBoxLayout
from ui_theme import apply_theme, selected_theme, THEMES


def luminance(color):
    c = QColor(color)
    channels = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
                for v in (c.redF(), c.greenF(), c.blueF())]
    return sum(v * weight for v, weight in zip(channels, (.2126, .7152, .0722)))


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / 'settings.ini'), QSettings.Format.IniFormat)
        self.mock_settings = patch('ui_theme.QSettings', return_value=self.settings)
        self.mock_settings.start()

    def tearDown(self):
        self.mock_settings.stop()
        apply_theme()
        self.temp.cleanup()

    def test_selection_and_font_survive_reload(self):
        apply_theme(14, mode='dark', persist=True)
        self.assertEqual(selected_theme(), 'dark')
        apply_theme(12, mode='light')
        self.assertEqual(apply_theme(), 14)
        self.assertEqual(self.app.property('swlab_resolved_theme'), 'dark')

    def test_system_changes_follow_only_when_selected(self):
        with patch('ui_theme.system_theme', return_value='light'):
            apply_theme(14, mode='system')
        with patch('ui_theme.system_theme', return_value='dark'):
            self.app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
        self.assertEqual(self.app.property('swlab_resolved_theme'), 'dark')
        self.assertEqual(self.app.font().pointSize(), 14)
        apply_theme(mode='light')
        with patch('ui_theme.system_theme', return_value='dark'):
            self.app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
        self.assertEqual(self.app.property('swlab_resolved_theme'), 'light')

    def test_existing_dialog_and_popup_update_without_losing_data(self):
        window = QDialog()
        layout = QVBoxLayout(window)
        entry = QLineEdit('유지할 입력값')
        combo = QComboBox(); combo.addItems(['하나', '둘']); combo.setCurrentIndex(1)
        layout.addWidget(entry); layout.addWidget(combo)
        window.show()
        try:
            for mode in ('dark', 'light', 'dark'):
                apply_theme(mode=mode)
                self.app.processEvents()
                combo.view().ensurePolished()
                for widget in (entry, combo.view()):
                    palette = widget.palette()
                    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
                        bg = palette.color(group, QPalette.ColorRole.Base)
                        self.assertEqual(bg.name(), THEMES[mode]['surface'])
                self.assertEqual(entry.text(), '유지할 입력값')
                self.assertEqual(combo.currentIndex(), 1)
        finally:
            window.close()

    def test_text_color_pairs_have_readable_contrast(self):
        pairs = [('text', 'surface'), ('text', 'window'), ('muted', 'window'),
                 ('selected_text', 'selection'), ('primary_text', 'primary'),
                 ('text', 'progress'), ('info_text', 'info_bg'),
                 ('tooltip_text', 'tooltip'), ('disabled', 'disabled_bg')]
        for mode, colors in THEMES.items():
            for foreground, background in pairs:
                with self.subTest(mode=mode, foreground=foreground, background=background):
                    light, dark = sorted([luminance(colors[foreground]), luminance(colors[background])], reverse=True)
                    self.assertGreaterEqual((light + .05) / (dark + .05), 4.5)

    def test_main_window_selector_applies_and_restores_choice(self):
        from gui import Gui
        with patch.object(Gui, 'refreshYearList'):
            window = Gui()
            try:
                window.themeMode.setCurrentIndex(window.themeMode.findData('dark'))
                self.assertEqual(selected_theme(), 'dark')
                window.fontSize.setCurrentIndex(window.fontSize.findData(16))
                self.assertEqual(self.app.property('swlab_resolved_theme'), 'dark')
                window.resize(1280, 800)
                self.app.processEvents()
                self.assertLessEqual(window.width(), 1280)
                self.assertLessEqual(window.height(), 800)
            finally:
                window.close()
            restored = Gui()
            try:
                self.assertEqual(restored.themeMode.currentData(), 'dark')
                self.assertEqual(restored.fontSize.currentData(), 16)
            finally:
                restored.close()
