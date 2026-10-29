"""Shared readable typography for the desktop and its dialogs."""
import os
from string import Template
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication


THEMES = {
    'light': dict(window='#f1f5f9', surface='#ffffff', text='#172b43', muted='#52657b',
        accent='#174ca1', info_bg='#eaf2ff', info_text='#173d70', border='#ced9e5',
        edge='#b7c6d7', hover_border='#3066b7', focus='#2563eb', disabled='#596a7d',
        disabled_bg='#edf1f5', disabled_border='#d7dee7', primary='#205acb',
        primary_hover='#17479f', primary_disabled='#526989', primary_text='#ffffff',
        selection='#d8e8ff', selected_text='#103b7c', alternate='#eef3f9',
        header='#eaf0f7', header_border='#c4d2e2', tab='#e8eef6', progress='#c7ddff',
        tooltip='#172b43', tooltip_text='#ffffff'),
    'dark': dict(window='#111827', surface='#1f2937', text='#f1f5f9', muted='#b8c7da',
        accent='#93c5fd', info_bg='#243b58', info_text='#dbeafe', border='#52647b',
        edge='#667b96', hover_border='#93c5fd', focus='#93c5fd', disabled='#a7b5c7',
        disabled_bg='#263243', disabled_border='#52647b', primary='#205acb',
        primary_hover='#17479f', primary_disabled='#354968', primary_text='#ffffff',
        selection='#294d78', selected_text='#ffffff', alternate='#263243',
        header='#2b3a50', header_border='#667b96', tab='#263243', progress='#294d78',
        tooltip='#e2e8f0', tooltip_text='#172b43'),
}


def system_theme():
    return 'dark' if QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark else 'light'


def selected_theme():
    mode = QSettings('SWLAB', 'PracticeEvaluation').value('theme_mode', 'system')
    return mode if mode in ('system', 'light', 'dark') else 'system'


def _system_theme_changed(*args):
    app = QApplication.instance()
    if app.property('swlab_theme_mode') == 'system':
        apply_theme(app.font().pointSize(), mode='system')


def apply_theme(points=None, persist=False, mode=None):
    settings = QSettings('SWLAB', 'PracticeEvaluation')
    try:
        points = int(points or settings.value('font_points', 12))
    except (TypeError, ValueError):
        points = 12
    points = points if points in (12, 14, 16) else 12
    mode = selected_theme() if mode is None else mode
    mode = mode if mode in ('system', 'light', 'dark') else 'system'
    app = QApplication.instance()
    resolved = system_theme() if mode == 'system' else mode
    colors = THEMES[resolved]
    app.setProperty('swlab_theme_mode', mode)
    app.setProperty('swlab_resolved_theme', resolved)
    if not app.property('swlab_theme_connected'):
        app.styleHints().colorSchemeChanged.connect(_system_theme_changed)
        app.setProperty('swlab_theme_connected', True)
    # Keep native OS colors from leaking into popup views and child windows.
    if app.style().objectName().lower() != 'fusion':
        app.setStyle('Fusion')
    palette = QPalette()
    roles = dict(Window='window', WindowText='text', Base='surface', AlternateBase='alternate',
        Text='text', Button='surface', ButtonText='text', Highlight='selection',
        HighlightedText='selected_text', ToolTipBase='tooltip', ToolTipText='tooltip_text',
        PlaceholderText='muted', Link='accent', LinkVisited='accent', Light='surface',
        Midlight='disabled_bg', Mid='edge', Dark='muted', Shadow='window')
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        for role, token in roles.items():
            palette.setColor(group, getattr(QPalette.ColorRole, role), QColor(colors[token]))
    for role in ('Text', 'WindowText', 'ButtonText', 'PlaceholderText'):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role), QColor(colors['disabled']))
    app.setPalette(palette)
    if os.name == 'nt' and not app.property('swlab_fonts_loaded'):
        windows_dir = os.environ.get('WINDIR')
        if windows_dir:
            QFontDatabase.addApplicationFont(os.path.join(windows_dir, 'Fonts', 'malgun.ttf'))
        app.setProperty('swlab_fonts_loaded', True)
    app.setFont(QFont('Malgun Gothic' if os.name == 'nt' else 'Sans Serif', points))
    app.setStyleSheet(Template('''
        QWidget { color: $text; }
        QMainWindow, QDialog { background: $window; }
        QLabel#pageTitle { font-size: 20pt; font-weight: 700; }
        QLabel#muted { color: $muted; }
        QLabel#selectionCount { font-weight: 700; color: $accent; }
        QLabel#verificationStatus { background: $info_bg; color: $info_text; padding: 8px; border-radius: 5px; }
        QGroupBox { background: $surface; border: 1px solid $border; border-radius: 8px;
                    margin-top: 10px; padding: 10px; padding-top: 14px; font-weight: 600; }
        QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; }
        QPushButton, QToolButton { background: $surface; border: 1px solid $edge;
            border-radius: 6px; padding: 7px 12px; min-height: 22px; }
        QPushButton:hover, QToolButton:hover { background: $info_bg; border-color: $hover_border; }
        QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus { border: 2px solid $focus; }
        QPushButton:disabled { color: $disabled; background: $disabled_bg; border-color: $disabled_border; }
        QPushButton#primary { background: $primary; color: $primary_text; border: 1px solid $primary;
            font-weight: 700; padding: 10px 20px; min-height: 30px; }
        QPushButton#primary:hover { background: $primary_hover; }
        QPushButton#primary:disabled { background: $primary_disabled; }
        QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { background: $surface; border: 1px solid $edge;
            border-radius: 5px; padding: 6px; min-height: 24px; }
        QComboBox::drop-down { width: 24px; }
        QComboBox QAbstractItemView { background: $surface; color: $text;
            selection-background-color: $selection; selection-color: $selected_text; }
        QAbstractItemView, QTextEdit, QPlainTextEdit { background: $surface; color: $text;
            alternate-background-color: $alternate;
            border: 1px solid $border; border-radius: 5px; selection-background-color: $selection; selection-color: $selected_text; }
        QListWidget::item { padding: 8px; min-height: 24px; }
        QListWidget::item:selected { background: $selection; color: $selected_text; }
        QTableView::item:selected { background: $selection; color: $selected_text; }
        QHeaderView::section { background: $header; padding: 8px; border: none;
            border-bottom: 1px solid $header_border; font-weight: 600; }
        QTabBar::tab { padding: 10px 18px; background: $tab; border: 1px solid $border; }
        QTabBar::tab:selected { background: $surface; border-bottom: 3px solid $primary; }
        QTabWidget::pane { border: 1px solid $border; background: $surface; }
        QProgressBar { border: 1px solid $border; border-radius: 5px; text-align: center;
            min-height: 26px; background: $surface; color: $text; }
        QProgressBar::chunk { background: $progress; border-radius: 4px; }
        QMenuBar, QMenu { background: $surface; color: $text; }
        QMenu::item:selected, QMenuBar::item:selected { background: $selection; color: $selected_text; }
        QToolTip { background: $tooltip; color: $tooltip_text; padding: 6px; }
    ''').substitute(colors))
    if persist:
        settings.setValue('font_points', points)
        settings.setValue('theme_mode', mode)
    return points
