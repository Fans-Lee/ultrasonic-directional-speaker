"""Visual tokens shared by the desktop control surface.

The UI deliberately keeps styling in one place so view widgets can focus on
rendering state and emitting intents.  Object properties are used instead of
widget-specific inline styles, which also keeps status updates from changing
the visual language of the rest of the application.
"""

APP_STYLESHEET = """
* {
    color: #e5edf8;
}

QMainWindow {
    background: #0b1220;
}

QWidget#appRoot {
    background: #0b1220;
}

QWidget#visualWorkspace {
    background: #101a2d;
    border: 1px solid #24324a;
    border-radius: 14px;
}

QWidget#sidebar, QWidget#sidebarContent,
QScrollArea, QScrollArea::viewport {
    background: #0b1220;
    border: none;
}

QLabel[role="eyebrow"] {
    color: #67e8f9;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.3px;
}

QLabel[role="app-title"] {
    color: #f8fbff;
    font-size: 22px;
    font-weight: 700;
}

QLabel[role="app-subtitle"] {
    color: #8da2bd;
    font-size: 12px;
}

QLabel[role="section-title"] {
    color: #f4f8ff;
    font-size: 16px;
    font-weight: 700;
}

QLabel[role="section-subtitle"] {
    color: #8da2bd;
    font-size: 11px;
}

QWidget[card="true"] {
    background: #121e31;
    border: 1px solid #263752;
    border-radius: 12px;
}

QFrame[role="inset"] {
    background: #0d1728;
    border: 1px solid #22324b;
    border-radius: 9px;
}

QLabel[role="metric-label"] {
    color: #8da2bd;
    font-size: 12px;
}

QLabel[role="metric-value"] {
    color: #e8f1fc;
    font-weight: 600;
}

QLabel[role="helper"] {
    color: #91a6c1;
    font-size: 12px;
}

QLabel[role="status"] {
    color: #a7f3d0;
    font-weight: 600;
}

QLabel[role="message"] {
    background: #0d1728;
    border: 1px solid #253955;
    border-radius: 8px;
    color: #c6d4e6;
    padding: 9px 10px;
}

QLabel[role="message"][error="true"] {
    background: #351725;
    border-color: #7f2840;
    color: #fecdd3;
}

QFrame[role="separator"] {
    color: #2a3b56;
    background: #2a3b56;
    max-height: 1px;
}

QPushButton {
    background: #1c2a40;
    border: 1px solid #344966;
    border-radius: 8px;
    color: #e8f1fc;
    font-weight: 600;
    padding: 0 14px;
}

QPushButton:hover:enabled {
    background: #273b58;
    border-color: #4b6b93;
}

QPushButton:pressed:enabled {
    background: #162237;
}

QPushButton:disabled {
    background: #162134;
    border-color: #24334c;
    color: #657894;
}

QPushButton[kind="primary"] {
    background: #0e7490;
    border-color: #22b8d4;
    color: white;
}

QPushButton[kind="primary"]:hover:enabled {
    background: #0f89a8;
    border-color: #67e8f9;
}

/*
 * The kind selector above is more specific than QPushButton:disabled.
 * Restate the disabled presentation at the same specificity so a disabled
 * start/stop control is visibly unavailable instead of retaining its action
 * colour.  This makes the single actionable button clear for both tracking
 * and the audio link.
 */
QPushButton[kind="primary"]:disabled,
QPushButton[kind="danger"]:disabled {
    background: #162134;
    border-color: #24334c;
    color: #657894;
}

QPushButton[kind="danger"] {
    background: #7f1d36;
    border-color: #b43658;
    color: #fff1f3;
}

QPushButton[kind="danger"]:hover:enabled {
    background: #9f294b;
    border-color: #fb7185;
}

QComboBox {
    background: #0d1728;
    border: 1px solid #304460;
    border-radius: 7px;
    color: #e5edf8;
    min-height: 30px;
    padding: 0 30px 0 9px;
}

QComboBox:hover:enabled, QComboBox:focus {
    border-color: #22b8d4;
}

QComboBox:disabled {
    background: #121d2e;
    border-color: #253650;
    color: #657894;
}

QComboBox::drop-down {
    background: transparent;
    border: none;
    width: 28px;
}

QComboBox::down-arrow {
    image: none;
}

QComboBox QAbstractItemView {
    background: #17243a;
    border: 1px solid #36506f;
    color: #e5edf8;
    selection-background-color: #0e7490;
    selection-color: white;
    outline: none;
}

QCheckBox#boostToggle {
    background: #17263a;
    border: 1px solid #49617f;
    border-radius: 7px;
    color: #cbd9e9;
    font-weight: 600;
    padding: 6px 9px;
    spacing: 9px;
}

QCheckBox#boostToggle[boost="on"] {
    background: #0b4e5d;
    border-color: #2dd4bf;
    color: #ccfbf1;
}

QCheckBox#boostToggle::indicator {
    width: 18px;
    height: 18px;
    background: #0a1424;
    border: 2px solid #7b93b2;
    border-radius: 4px;
}

QCheckBox#boostToggle::indicator:checked {
    background: #14b8a6;
    border-color: #99f6e4;
}

QTabWidget::pane {
    border: none;
    background: transparent;
    top: -1px;
}

QTabBar {
    background: #101a2d;
}

QTabBar::tab {
    background: #0d1728;
    border: 1px solid #263a56;
    border-bottom: 3px solid #263a56;
    border-radius: 7px 7px 3px 3px;
    color: #aabbd1;
    font-weight: 600;
    min-width: 88px;
    padding: 9px 13px 8px;
    margin-right: 5px;
}

QTabBar::tab:hover {
    background: #172d46;
    border-color: #46749d;
    color: #e0f2fe;
}

QTabBar::tab:selected {
    background: #1b415f;
    border-color: #38bdf8;
    border-bottom-color: #67e8f9;
    color: #ffffff;
}

QScrollArea {
    background: transparent;
    border: none;
}

QScrollBar:vertical {
    background: #142238;
    border: 1px solid #2e4967;
    border-radius: 6px;
    width: 12px;
    margin: 1px 0;
}

QScrollBar::handle:vertical {
    background: #5b82ad;
    border: 1px solid #93c5fd;
    border-radius: 5px;
    min-height: 54px;
}

QScrollBar::handle:vertical:hover {
    background: #7ba8d8;
    border-color: #dbeafe;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: #142238;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QToolTip {
    background: #17243a;
    border: 1px solid #36506f;
    border-radius: 5px;
    color: #f8fbff;
    padding: 4px 6px;
}
"""
