#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SFS Pack Tool v2.3.6-PyQt —— PyQt5 + SiliconUI 界面。

界面层只负责「长相与交互」，业务流程（导出 / 并入 / 剥离 / 汉化）全部在
`sfs_pack_tool_logic.py` 里，Tk 旧界面（legacy/）与本界面共用同一份逻辑。

为什么换掉 Tkinter：
  * Tk 没有真正的圆角、阴影、动画与高 DPI 支持，控件外观停在 2005 年；
  * SiliconUI 提供圆角卡片、按压回弹、渐变主题色，配深色配色后观感接近现代桌面应用。
"""

from __future__ import annotations

import ctypes
import os
import re
import sys
import tempfile
import threading
import traceback
import webbrowser
from pathlib import Path

from PyQt5.QtCore import QByteArray, QPoint, QRectF, QSize, Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap,
)
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSplitter,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from siui.components.button import SiPushButtonRefactor
from siui.components.container import SiPanelCard
from siui.components.editbox import SiCapsuleLineEdit
from siui.components.label import SiLabelRefactor
from siui.components.progress_bar_ import SiProgressBarRefactor
from siui.components.widgets.button import SiSwitch
from siui.core import SiColor, SiGlobal

from sfs_pack_tool_logic import (  # noqa: F401  (部分名字是给 test_core_smoke 用的)
    DEFAULT_AUTHOR, LOG_DIR, OFFICIAL_LOC_KEYS, PLATFORM_KEYS, PLATFORM_NAMES, TEXT,
    VERSION, VERSION_TITLE, LogicMixin, UnityPy, _zh2en, analyze_pack, app_data_dir,
    clean_cache_items, count_bundle_parts, extract_texts, human_size, load_settings,
    messagebox, resolve_toolkit_root, resource_path, save_settings, scan_cache,
    set_ui_hooks, strip_pack, write_translation,
)

# --------------------------------------------------------------------------- #
# 配色（与 SiliconUI 的 DarkColorGroup 完全一致，避免两套灰互相打架）
# --------------------------------------------------------------------------- #
BG_WINDOW = "#1C191F"
BG_PANEL = "#25222A"
BG_CARD_FORE = "#332E38"
BG_CARD_BACK = "#1C191F"
BORDER = "#2E2836"
ACCENT = "#855198"
ACCENT_LIGHT = "#C58BC2"
TEXT_A = "#E5E5E5"
TEXT_B = "#DFDFDF"
TEXT_C = "#C7C7C7"
TEXT_D = "#AFAFAF"
TEXT_E = "#979797"
DANGER = "#B4506A"

# 历史上被写进配置的老作者名：启动时自动换成 DEFAULT_AUTHOR
LEGACY_AUTHORS = {"〈A Future star汉化〉", "A Future star(汉化)", "A Future star汉化"}

APP_STYLE = f"""
QWidget {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
    font-size: 13px;
    color: {TEXT_C};
}}
QToolTip {{
    background-color: #4C4554;
    color: {TEXT_A};
    border: 1px solid #5C5566;
    padding: 6px 8px;
    border-radius: 6px;
}}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #4A4354; border-radius: 4px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: #5E5669; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #4A4354; border-radius: 4px; min-width: 28px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

QPlainTextEdit#log {{
    background: {BG_CARD_BACK};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT_C};
    font-family: "Cascadia Mono", "Consolas", "JetBrains Mono";
    font-size: 12px;
    padding: 8px 10px;
    selection-background-color: {ACCENT};
}}
QLabel#cardTitle {{ color: {TEXT_A}; font-size: 13px; font-weight: 600; }}
QLabel#pageTitle {{ color: {TEXT_A}; font-size: 20px; font-weight: 700; }}
QLabel#pageSubtitle {{ color: {TEXT_E}; font-size: 12px; }}
QLabel#hint {{ color: {TEXT_E}; font-size: 11px; }}
QLabel#pathLabel {{ color: {TEXT_D}; font-size: 12px; }}
QLabel#status {{ color: {TEXT_D}; font-size: 12px; }}
QLabel#chip {{
    color: {ACCENT_LIGHT}; background: rgba(133, 81, 152, 0.18);
    border: 1px solid rgba(197, 139, 194, 0.35);
    border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;
}}
QLabel#dim {{ color: {TEXT_E}; }}
"""

NAV_STYLE = f"""
QToolButton#nav {{
    color: {TEXT_C};
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 10px 12px;
    text-align: left;
    font-size: 13px;
}}
QToolButton#nav:hover {{ background: {BG_PANEL}; color: {TEXT_A}; }}
QToolButton#nav:checked {{
    background: {BG_CARD_FORE}; color: #FFFFFF; font-weight: 600;
}}
QToolButton#navSmall {{
    color: {TEXT_E}; background: transparent; border: none;
    border-radius: 8px; padding: 7px 12px; text-align: left; font-size: 12px;
}}
QToolButton#navSmall:hover {{ color: {TEXT_A}; background: {BG_PANEL}; }}
"""


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
class Var:
    """模仿 tk 的 StringVar，业务层代码可以原样使用 .get() / .set()。"""

    def __init__(self, value="", on_change=None):
        self._value = value
        self._on_change = on_change

    def get(self):
        return self._value

    def set(self, value):
        value = "" if value is None else str(value)
        changed = value != self._value
        self._value = value
        if changed and self._on_change is not None:
            self._on_change(value)


class BVar:
    """模仿 tk 的 BooleanVar。"""

    def __init__(self, value=False, on_change=None):
        self._value = bool(value)
        self._on_change = on_change

    def get(self):
        return self._value

    def set(self, value):
        value = bool(value)
        changed = value != self._value
        self._value = value
        if changed and self._on_change is not None:
            self._on_change(value)


def _iconpack():
    return SiGlobal.siui.iconpack


def si_icon(name: str, color: str = TEXT_C, size: int = 18) -> QIcon:
    """按名字取 SiliconUI 内置的 Fluent 图标并渲染成 QIcon。

    图标包里的名字不带尺寸段（`ic_fluent_info_filled`），而官方示例经常写
    `ic_fluent_info_16_filled`——后者在包里根本不存在，直接 get() 会抛 KeyError，
    于是图标静默消失。这里两种写法都试一遍。
    """
    pack = _iconpack()
    candidates = [name]
    stripped = re.sub(r"_\d+_", "_", name)
    if stripped != name:
        candidates.append(stripped)
    data = None
    for candidate in candidates:
        try:
            data = pack.get(candidate, color)
        except Exception:
            continue
        if data:
            break
    if not data:
        return QIcon()
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(data))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    pm.setDevicePixelRatio(2.0)
    return QIcon(pm)


class Panel(QWidget):
    """圆角纯色面板（自己画，比 QSS 的 border-radius 更干净）。"""

    def __init__(self, parent=None, bg=BG_PANEL, radius=12, border=None, margins=(0, 0, 0, 0)):
        super().__init__(parent)
        self._bg = QColor(bg)
        self._radius = radius
        self._border = QColor(border) if border else None
        # 注意：一个 widget 只能有一个布局。这里的布局对外暴露成 self.lay，
        # 外部必须往它里面加控件，再 setLayout 一次会静默失败（控件堆在 0,0）。
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(*margins)
        self.lay.setSpacing(0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._border is not None:
            painter.setPen(QPen(self._border, 1))
        else:
            painter.setPen(Qt.NoPen)
        painter.setBrush(self._bg)
        painter.drawRoundedRect(rect, self._radius, self._radius)


class Btn(SiPushButtonRefactor):
    """SiliconUI 按钮：圆角、按下回弹、hover 高亮，带主色/次级/危险三档。"""

    KIND_NORMAL = "normal"
    KIND_ACCENT = "accent"
    KIND_GHOST = "ghost"
    KIND_DANGER = "danger"

    _PALETTE = {
        KIND_NORMAL: ("#4C4554", "#3A3442", "#DFDFDF"),
        KIND_ACCENT: ("#6E4A80", "#52336B", "#FFFFFF"),
        KIND_GHOST: ("#332E38", "#3F3947", "#C7C7C7"),
        KIND_DANGER: ("#6B3140", "#4F2430", "#F0D5DB"),
    }

    def __init__(self, text="", parent=None, kind=KIND_NORMAL, icon_name=None,
                 height=38, min_width=0, tooltip=""):
        super().__init__(parent)
        self._kind = kind
        self._height = height
        self._min_width = min_width
        self.setMinimumHeight(height)
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(QFont("Microsoft YaHei UI", 10))
        self.style_data.border_radius = 9
        self.style_data.border_inner_radius = 7
        self.style_data.border_height = 3
        self.style_data.icon_text_gap = 6
        if icon_name:
            self.setIcon(si_icon(icon_name, "#DFDFDF", 16))
            self.setIconSize(QSize(15, 15))
        self.setText(text)
        bg, _shadow, text_color = self._PALETTE.get(
            kind, self._PALETTE[self.KIND_NORMAL])
        self.setColors(bg, text_color)
        if tooltip:
            self.setToolTip(tooltip)

    def setText(self, text):  # noqa: N802  (Qt 命名)
        super().setText(text)
        self._adjust_width()

    def _adjust_width(self):
        metrics = QFontMetrics(self.font())
        need = metrics.horizontalAdvance(self.text()) + 34
        if self.icon().isNull() is False:
            need += 22
        self.setMinimumWidth(max(self._min_width, need))

    def setColors(self, bg, text_color):
        self.style_data.button_color = QColor(bg)
        self.style_data.text_color = QColor(text_color)
        shadow = QColor(bg).darker(150)
        self.style_data.background_color = shadow
        self.update()

    def setEnabled(self, enabled):  # noqa: N802
        super().setEnabled(enabled)
        if not enabled:
            self.style_data.button_color = QColor("#2A2530")
            self.style_data.background_color = QColor("#1C191F")
            self.style_data.text_color = QColor("#6A6273")
        else:
            bg, _shadow, text_color = self._PALETTE.get(
                self._kind, self._PALETTE[self.KIND_NORMAL])
            self.style_data.button_color = QColor(bg)
            self.style_data.background_color = QColor(bg).darker(150)
            self.style_data.text_color = QColor(text_color)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self.update()


class ToggleRow(QWidget):
    """一行「开关 + 说明文字」。"""

    def __init__(self, text="", parent=None, value=False, hint=""):
        super().__init__(parent)
        self.var = BVar(value)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.switch = SiSwitch(self)
        self.switch.colorGroup().assign(SiColor.SWITCH_DEACTIVATE, "#847B90")
        self.switch.colorGroup().assign(SiColor.SWITCH_ACTIVATE, ACCENT)
        self.switch.setChecked(value)
        self.switch.reloadStyleSheet()
        self.switch.toggled.connect(self._on_toggled)
        lay.addWidget(self.switch)
        self.label = QLabel(text, self)
        self.label.setStyleSheet(f"color: {TEXT_C}; font-size: 13px;")
        lay.addWidget(self.label)
        if hint:
            hint_label = QLabel(hint, self)
            hint_label.setObjectName("hint")
            lay.addWidget(hint_label)
        lay.addStretch(1)
        if self.switch.isChecked() != value:
            # setChecked 只有在值变化时才发信号，初次同步手动触发一次
            self.switch._toggle_handler(value)
            self.switch._checked = value

    def _on_toggled(self, checked):
        self.var.set(checked)

    def setChecked(self, checked):  # noqa: N802
        self.switch.blockSignals(True)
        self.switch.setChecked(checked)
        self.switch.blockSignals(False)
        self.var._value = bool(checked)

    def isChecked(self):  # noqa: N802
        return self.switch.isChecked()

    def setText(self, text):  # noqa: N802
        self.label.setText(text)


class SectionCard(SiPanelCard):
    """带标题的卡片：SiliconUI 的立体底面 + 自己的竖向布局。"""

    def __init__(self, title="", parent=None):
        super().__init__(parent, SiPanelCard.TopToBottom)
        self.style_data.border_radius_fore = 9
        self.style_data.border_radius_back = 12

        self._holder = QWidget(self)
        self.lay = QVBoxLayout(self._holder)
        self.lay.setContentsMargins(15, 10, 15, 12)
        self.lay.setSpacing(6)
        # 卡片必须撑到内容的最小高度：否则窗口不够高时 Qt 会把卡片压扁，
        # 内部控件就互相叠在一起（字号一大立刻出现）。
        self.lay.setSizeConstraint(QVBoxLayout.SetMinimumSize)

        self.title_label = QLabel(title, self._holder)
        self.title_label.setObjectName("cardTitle")
        if title:
            self.lay.addWidget(self.title_label)

        SiPanelCard.addWidget(self, self._holder)   # 走父类，避免被下面的覆盖方法吞掉
        self.layout().setStretchFactor(self.stretchWidget(), 0)
        self.layout().setStretchFactor(self._holder, 1)

    def addWidget(self, widget, *args, **kwargs):  # noqa: N802
        self.lay.addWidget(widget)

    def addLayout(self, layout):  # noqa: N802
        self.lay.addLayout(layout)


class ElidedLabel(QLabel):
    """单行、超长中间省略的标签（路径很长时不撑破布局）。"""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self._eliding = False
        # QLabel 一旦命中带 background 的样式表，Qt 会给它打开 WA_StyledBackground，
        # 于是整块矩形被涂成窗体底色（深色条上出现一块更黑的砖）。这里明确关掉。
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):  # noqa: N802
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._apply_elide()

    def text(self):  # noqa: N802
        return self._full_text

    def _apply_elide(self):
        # 必须防重入：setText 会改变 sizeHint → 触发 resizeEvent → 又回来 elide，
        # 文字长度一变就可能来回抖动成死循环（切英文那次直接卡住不动）。
        if self._eliding:
            return
        self._eliding = True
        try:
            metrics = QFontMetrics(self.font())
            width = max(80, self.width() - 2)
            super().setText(metrics.elidedText(self._full_text, Qt.ElideMiddle, width))
        finally:
            self._eliding = False

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._apply_elide()


class LogView(QPlainTextEdit):
    """只读日志：等宽字体、按内容自动上色。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("log")
        self.setReadOnly(True)
        self.setMaximumBlockCount(3000)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setMinimumHeight(64)

    def append_colored(self, text: str):
        from html import escape
        lowered = text
        if "[!]" in lowered or "失败" in lowered or "错误" in lowered:
            color = "#E08A9B"
        elif text.startswith("[回滚]") or text.startswith("[预览]"):
            color = ACCENT_LIGHT
        elif text.startswith("[增量]") or text.startswith("[探测]"):
            color = "#8FB8D8"
        elif "✓" in text or "完成" in text:
            color = "#8FCB9B"
        else:
            color = TEXT_C
        self.appendHtml(f'<span style="color:{color};">{escape(text)}</span>')
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


class Dialog(QDialog):
    """圆角深色对话框基类（无系统标题栏，可拖动）。"""

    def __init__(self, parent=None, title="", width=560):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(title)
        self.setModal(True)
        self._drag_pos = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        self.panel = Panel(self, bg=BG_PANEL, radius=14, border=BORDER)
        outer.addWidget(self.panel)

        box = self.panel.lay
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        header = QWidget(self.panel)
        header.setFixedHeight(46)
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(18, 6, 10, 0)
        hlay.setSpacing(8)
        self.title_label = QLabel(title, header)
        self.title_label.setStyleSheet(
            f"color: {TEXT_A}; font-size: 15px; font-weight: 600;")
        hlay.addWidget(self.title_label)
        hlay.addStretch(1)
        close_btn = QToolButton(header)
        close_btn.setIcon(si_icon("ic_fluent_dismiss_16_filled", TEXT_D, 16))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QToolButton{border:none;border-radius:8px;padding:6px;}"
            f"QToolButton:hover{{background:{BG_CARD_FORE};}}")
        close_btn.clicked.connect(self.reject)
        hlay.addWidget(close_btn)
        box.addWidget(header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(18, 4, 18, 6)
        self.body.setSpacing(10)
        box.addLayout(self.body, 1)

        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(18, 8, 18, 16)
        self.footer.setSpacing(10)
        self.footer.addStretch(1)
        box.addLayout(self.footer)

        self.setMinimumWidth(width)
        self.setMaximumWidth(max(width, 760) if width < 700 else width)

        header.installEventFilter(self)
        self._header = header

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self._header:
            if event.type() == event.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                return True
            if event.type() == event.MouseMove and self._drag_pos is not None:
                self.move(event.globalPos() - self._drag_pos)
                return True
            if event.type() == event.MouseButtonRelease:
                self._drag_pos = None
                return True
        return super().eventFilter(obj, event)

    def add_button(self, text, callback=None, kind=Btn.KIND_NORMAL, default=False):
        btn = Btn(text, self.panel, kind=kind, height=36)
        if callback is not None:
            btn.clicked.connect(callback)
        self.footer.addWidget(btn)
        if default:
            btn.setDefault(True)
        return btn


class MsgBox(Dialog):
    """统一的提示框，替代 tk 的 messagebox（系统弹窗在深色界面里太刺眼）。"""

    KINDS = {
        "info": (ACCENT, "ic_fluent_info_16_filled"),
        "warning": ("#C79A5B", "ic_fluent_warning_16_filled"),
        "error": (DANGER, "ic_fluent_error_circle_16_filled"),
        "question": (ACCENT, "ic_fluent_question_circle_16_filled"),
    }

    def __init__(self, parent, title, message, kind="info", ask=False,
                 ok_text="确定", cancel_text="取消"):
        super().__init__(parent, title, width=520)
        color, icon_name = self.KINDS.get(kind, self.KINDS["info"])
        self.result_value = False

        row = QHBoxLayout()
        row.setSpacing(12)
        icon_label = QLabel(self.panel)
        icon_label.setPixmap(si_icon(icon_name, color, 22).pixmap(22, 22))
        icon_label.setFixedWidth(24)
        row.addWidget(icon_label, 0, Qt.AlignTop)

        text_label = QLabel(message, self.panel)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_label.setStyleSheet(f"color: {TEXT_C}; font-size: 13px; line-height: 150%;")
        text_label.setMinimumWidth(400)
        row.addWidget(text_label, 1)
        self.body.addLayout(row)

        if ask:
            self.add_button(cancel_text, self.reject, kind=Btn.KIND_GHOST)
            self.add_button(ok_text, self._accept, kind=Btn.KIND_ACCENT, default=True)
        else:
            self.add_button(ok_text, self._accept, kind=Btn.KIND_ACCENT, default=True)

    def _accept(self):
        self.result_value = True
        self.accept()

    def exec_modal(self) -> bool:
        self.adjustSize()
        self.exec_()
        return self.result_value


# --------------------------------------------------------------------------- #
# 主界面
# --------------------------------------------------------------------------- #
class App(QMainWindow, LogicMixin):
    """SFS Pack Tool 主窗口。"""

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        locale = self.settings.get("language", "zh")
        self.locale = locale if locale in TEXT else "zh"

        self.input_file = ""
        self.translation_file = ""
        self.logs: list[str] = []

        # 作者名迁移：老版本存的是空串或「〈A Future star汉化〉」，统一纠正成默认作者
        saved_author = str(self.settings.get("author", "") or "").strip()
        if not saved_author or saved_author in LEGACY_AUTHORS:
            saved_author = DEFAULT_AUTHOR
        self.author_var = Var(saved_author)
        self.toolkit_dir_var = Var(self.settings.get("toolkit_dir", ""))
        self.package_dir_var = Var(self.settings.get("package_dir", ""))
        self.extract_output_var = Var(self.settings.get("extract_output", ""))
        self.strip_output_var = Var(self.settings.get("strip_output", ""))

        saved_platforms = self.settings.get("strip_platforms")
        if not isinstance(saved_platforms, list) or not saved_platforms:
            legacy = self.settings.get("strip_platform", "WindowsBuild")
            saved_platforms = [legacy] if legacy in PLATFORM_KEYS else ["WindowsBuild"]
        self.strip_platform_vars = {
            key: BVar(key in saved_platforms) for key in PLATFORM_KEYS}
        self.install_var = BVar(bool(self.settings.get("install_to_toolkit", False)))
        self.incremental_var = BVar(bool(self.settings.get("incremental_export", False)))

        self._busy = False
        self._busy_name = ""
        self._progress_value = 0.0
        self._progress_label = ""
        self._determinate = False
        self._busy_buttons: list[Btn] = []
        self._strip_auto_name = ""
        self._export_busy = False

        # 主线程回调桥（后台线程 -> 界面线程）
        self._bridge = _UiBridge()
        set_ui_hooks(
            info=lambda title, message: self._ui(
                lambda: MsgBox(self, title, message, "info").exec_modal()),
            warning=lambda title, message: self._ui(
                lambda: MsgBox(self, title, message, "warning").exec_modal()),
            error=lambda title, message: self._ui(
                lambda: MsgBox(self, title, message, "error").exec_modal()),
            askyesno=lambda title, message: self._ask_sync(title, message),
        )

        self._diag_log = None
        try:
            import sfs_pack_toolbox as _toolbox
            self._diag_log = _toolbox.DiagnosticLog(
                LOG_DIR, app_version=VERSION,
                keep_days=int(self.settings.get("log_keep_days", 30)))
        except Exception:
            self._diag_log = None

        self.setWindowTitle(self.settings_window_title())
        self.setStyleSheet(APP_STYLE)
        self.setWindowIcon(self._app_icon())
        self.setMinimumSize(1000, 640)

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(90)
        self._progress_timer.timeout.connect(self._tick_progress)

        self._build_shell()
        self.build_ui()
        self._restore_geometry()
        self._enable_dark_titlebar()

    # ---------------- 基础 ----------------
    def settings_window_title(self) -> str:
        return TEXT[self.locale]["window"]

    def _app_icon(self) -> QIcon:
        for candidate in (resource_path("assets/SFS_Pack_Tool_v22.ico"),
                          Path(__file__).resolve().parent / "SFS_Pack_Tool_v22.ico"):
            if candidate.is_file():
                return QIcon(str(candidate))
        return QIcon()

    def _enable_dark_titlebar(self) -> None:
        """让系统标题栏跟随深色主题（Win10 1809+ / Win11）。"""
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())
            value = ctypes.c_int(1)
            for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
        except Exception:
            pass

    def t(self, key: str, **kwargs) -> str:
        return TEXT[self.locale][key].format(**kwargs)

    def _translation_label_text(self) -> str:
        if self.translation_file:
            return self.t("translation_selected_label", name=Path(self.translation_file).name)
        return self.t("translation_none")

    # ---------------- 线程 <->
    def _ui(self, fn):
        """把回调排到界面线程执行（后台线程收尾时窗口可能已销毁，静默忽略）。"""
        try:
            self._bridge.invoke.emit(fn)
        except (RuntimeError, TypeError):
            return None

    def _ask_sync(self, title: str, message: str) -> bool:
        """同步询问（仅主线程调用安全）。"""
        if threading.current_thread() is threading.main_thread():
            return MsgBox(self, title, message, "question", ask=True).exec_modal()
        result = {"value": False}
        done = threading.Event()

        def ask():
            try:
                result["value"] = MsgBox(self, title, message, "question", ask=True).exec_modal()
            finally:
                done.set()

        self._ui(ask)
        done.wait(120)
        return result["value"]

    # ---------------- 外观骨架 ----------------
    def _build_shell(self) -> None:
        central = QWidget(self)
        central.setStyleSheet(f"background: {BG_WINDOW};")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 顶部标题区 ----
        header = QWidget(central)
        header.setFixedHeight(74)
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(22, 14, 18, 6)
        hlay.setSpacing(12)

        logo = QLabel(header)
        icon = self._app_icon()
        logo.setPixmap(icon.pixmap(30, 30))
        logo.setFixedSize(34, 34)
        hlay.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        self.header_title = QLabel(self.t("title"), header)
        self.header_title.setStyleSheet(
            f"color: {TEXT_A}; font-size: 19px; font-weight: 700; letter-spacing: 0.4px;")
        self.header_sub = QLabel(self.t("subtitle"), header)
        self.header_sub.setStyleSheet(f"color: {TEXT_E}; font-size: 12px;")
        title_box.addWidget(self.header_title)
        title_box.addWidget(self.header_sub)
        hlay.addLayout(title_box)
        hlay.addStretch(1)

        self.lang_btn = Btn(self.t("english") if self.locale == "zh" else self.t("chinese"),
                            header, kind=Btn.KIND_GHOST, height=32, min_width=74,
                            icon_name="ic_fluent_translate_16_filled", tooltip=self.t("language"))
        self.lang_btn.clicked.connect(self.toggle_language)
        hlay.addWidget(self.lang_btn)

        self.settings_btn = Btn(self.t("menu_settings"), header, kind=Btn.KIND_GHOST,
                                height=32, min_width=88,
                                icon_name="ic_fluent_settings_16_filled")
        self.settings_btn.clicked.connect(self.show_settings)
        hlay.addWidget(self.settings_btn)
        outer.addWidget(header)

        # ---- 主体：左侧导航 + 右侧内容 ----
        main_row = QWidget(central)
        mlay = QHBoxLayout(main_row)
        mlay.setContentsMargins(18, 8, 18, 14)
        mlay.setSpacing(14)

        self.sidebar = Panel(main_row, bg=BG_PANEL, radius=12, border=BORDER,
                             margins=(10, 14, 10, 12))
        self.sidebar.setFixedWidth(206)
        self.nav_layout = self.sidebar.lay
        self.nav_layout.setContentsMargins(10, 14, 10, 12)
        self.nav_layout.setSpacing(4)
        mlay.addWidget(self.sidebar)

        right = QWidget(main_row)
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(10)
        mlay.addWidget(right, 1)

        # ---- 输入文件栏：三页共用，切页时始终可见 ----
        # 以前它只挂在「还原」页里，切到汉化/剥离就看不到当前选的是哪个包了。
        self.input_bar = Panel(right, bg=BG_PANEL, radius=12, border=BORDER)
        self.input_bar.setFixedHeight(70)
        input_bar_lay = self.input_bar.lay
        input_bar_lay.setContentsMargins(14, 9, 14, 9)
        bar_row = QHBoxLayout()
        bar_row.setSpacing(10)

        self.pick_pack_btn = Btn(self.t("select_pack"), self.input_bar,
                                 kind=Btn.KIND_ACCENT,
                                 icon_name="ic_fluent_folder_open_16_filled")
        self.pick_pack_btn.clicked.connect(self.pick_input)
        bar_row.addWidget(self.pick_pack_btn)

        self.pick_json_btn = Btn(self.t("select_translation"), self.input_bar,
                                 kind=Btn.KIND_GHOST,
                                 icon_name="ic_fluent_document_text_16_filled")
        self.pick_json_btn.clicked.connect(self.pick_translation)
        bar_row.addWidget(self.pick_json_btn)

        bar_row.addSpacing(6)

        info_col = QVBoxLayout()
        info_col.setSpacing(1)
        self.input_label = ElidedLabel(self.input_file or self.t("no_pack"), self.input_bar)
        self.input_label.setObjectName("pathLabel")
        self.input_label.setFrameShape(QFrame.NoFrame)
        self.translation_label = ElidedLabel(self._translation_label_text(), self.input_bar)
        self.translation_label.setObjectName("hint")
        self.translation_label.setFrameShape(QFrame.NoFrame)
        info_col.addWidget(self.input_label)
        info_col.addWidget(self.translation_label)
        bar_row.addLayout(info_col, 1)

        input_bar_lay.addLayout(bar_row)
        rlay.addWidget(self.input_bar)

        # 页面区 + 日志区：不用 QSplitter，固定高度更可预测
        # （splitter 在「子控件最小高度之和 > 可用高度」时会把日志区挤到可视区外）
        self.pages = QStackedWidget(right)
        rlay.addWidget(self.pages, 1)

        # ---- 日志区 ----
        self.log_panel = Panel(right, bg=BG_PANEL, radius=12, border=BORDER)
        self.log_panel.setFixedHeight(252)
        log_box = self.log_panel.lay
        log_box.setContentsMargins(14, 10, 14, 12)
        log_box.setSpacing(8)
        log_head = QHBoxLayout()
        log_head.setSpacing(8)
        self.log_title = QLabel(self.t("log_title"), self.log_panel)
        self.log_title.setObjectName("cardTitle")
        log_head.addWidget(self.log_title)
        log_head.addStretch(1)
        self.clear_log_btn = Btn(self.t("clear_log"), self.log_panel, kind=Btn.KIND_GHOST,
                                 height=30, icon_name="ic_fluent_eraser_16_filled")
        self.clear_log_btn.clicked.connect(self._clear_log)
        log_head.addWidget(self.clear_log_btn)
        self.cache_btn = Btn(self.t("clear_cache"), self.log_panel, kind=Btn.KIND_GHOST,
                             height=30, icon_name="ic_fluent_broom_16_filled")
        self.cache_btn.clicked.connect(self.show_cache_dialog)
        self._register_busy_button(self.cache_btn)
        log_head.addWidget(self.cache_btn)
        log_box.addLayout(log_head)
        self.log_view = LogView(self.log_panel)
        log_box.addWidget(self.log_view, 1)
        rlay.addWidget(self.log_panel)

        outer.addWidget(main_row, 1)

        # ---- 底部：进度条 + 状态 ----
        bottom = QWidget(central)
        bottom.setFixedHeight(46)
        blay = QHBoxLayout(bottom)
        blay.setContentsMargins(24, 4, 24, 10)
        blay.setSpacing(14)
        self.progress = SiProgressBarRefactor(bottom)
        self.progress.setMinimumWidth(260)
        self.progress.setMaximum(1000)
        self.progress.progressColor = QColor("#A46FBB")
        self.progress.setState(SiProgressBarRefactor.State.Processing)
        blay.addWidget(self.progress, 1)
        self.status_label = QLabel(self.t("progress_idle"), bottom)
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_label.setMinimumWidth(280)
        blay.addWidget(self.status_label)
        outer.addWidget(bottom)

    # ---------------- 界面内容（切语言时整段重建）----------------
    def build_ui(self) -> None:
        self._busy_buttons = []
        self.setWindowTitle(self.t("window"))
        self.header_title.setText(self.t("title"))
        self.header_sub.setText(self.t("subtitle"))
        self.lang_btn.setText(self.t("english") if self.locale == "zh" else self.t("chinese"))
        self.settings_btn.setText(self.t("menu_settings"))
        self.clear_log_btn.setText(self.t("clear_log"))
        if hasattr(self, "log_title"):
            self.log_title.setText(self.t("log_title"))
        if hasattr(self, "pick_pack_btn"):
            self.pick_pack_btn.setText(self.t("select_pack"))
            self.pick_json_btn.setText(self.t("select_translation"))
            self.input_label.setText(self.input_file or self.t("no_pack"))
            self.translation_label.setText(self._translation_label_text())
        self.cache_btn.setText(self.t("clear_cache"))

        while self.pages.count():
            page = self.pages.widget(0)
            self.pages.removeWidget(page)
            page.setParent(None)      # 立刻停止绘制，别等 deleteLater
            page.deleteLater()

        self._build_sidebar()

        self.pages.addWidget(self._wrap_scroll(self._page_restore()))
        self.pages.addWidget(self._wrap_scroll(self._page_translate()))
        self.pages.addWidget(self._wrap_scroll(self._page_strip()))
        self.pages.setCurrentIndex(max(0, min(self._nav_index, 2)))

        if not self.logs:
            self.log(self.t("ready"))
        else:
            self.refresh_logs()
        if self._busy:
            self.set_busy(True, self._busy_name)
        else:
            self.set_progress(0.0, self.t("progress_idle"))

    def _build_sidebar(self) -> None:
        while self.nav_layout.count():
            item = self.nav_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_index = getattr(self, "_nav_index", 0)

        def short(text: str) -> str:
            """导航项去掉「①②③ 」前缀：有图标了，序号只留给页面大标题。"""
            return re.sub(r"^\s*(?:[①②③④⑤]|\d+[.、])\s*", "", text)

        nav_specs = [
            ("restore", short(self.t("tab_restore")), "ic_fluent_arrow_download_16_filled"),
            ("translate", short(self.t("tab_translate")), "ic_fluent_text_font_16_filled"),
            ("strip", short(self.t("tab_strip")), "ic_fluent_cut_16_filled"),
        ]
        for index, (_key, text, icon_name) in enumerate(nav_specs):
            btn = QToolButton(self.sidebar)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setChecked(index == self._nav_index)
            btn.setText("  " + text)
            btn.setIcon(si_icon(icon_name, TEXT_C, 17))
            btn.setIconSize(QSize(17, 17))
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setFixedHeight(40)
            btn.setStyleSheet(NAV_STYLE)
            btn.clicked.connect(lambda _c=False, i=index: self.switch_page(i))
            self._nav_group.addButton(btn, index)
            self.nav_layout.addWidget(btn)

        self.nav_layout.addStretch(1)

        for text, icon_name, slot in (
                (self.t("menu_tutorial_open"), "ic_fluent_book_question_mark_16_filled",
                 self.open_tutorial),
                (self.t("menu_author_open"), "ic_fluent_people_16_filled", self.show_about_author),
                (self.t("menu_about_open"), "ic_fluent_info_16_filled", self.show_about_app),
        ):
            btn = QToolButton(self.sidebar)
            btn.setObjectName("navSmall")
            btn.setText("  " + text)
            btn.setIcon(si_icon(icon_name, TEXT_E, 15))
            btn.setIconSize(QSize(15, 15))
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setFixedHeight(32)
            btn.setStyleSheet(NAV_STYLE)
            btn.clicked.connect(slot)
            self.nav_layout.addWidget(btn)

    def switch_page(self, index: int) -> None:
        self._nav_index = index
        self.pages.setCurrentIndex(index)
        if hasattr(self, "_nav_group"):
            button = self._nav_group.button(index)
            if button is not None:
                button.setChecked(True)

    @staticmethod
    def _page_container() -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(12)
        return page

    @staticmethod
    def _wrap_scroll(page: QWidget) -> QScrollArea:
        """把一页内容包进滚动区：窗口拉小时滚动，而不是把卡片压扁。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background: transparent; border: none;}"
                             "QScrollArea > QWidget > QWidget{background: transparent;}")
        scroll.viewport().setStyleSheet("background: transparent;")
        scroll.setWidget(page)
        return scroll

    def _page_header(self, title_key: str, subtitle_key: str) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel(self.t(title_key) if title_key in TEXT[self.locale] else title_key)
        title.setObjectName("pageTitle")
        box.addWidget(title)
        if subtitle_key and subtitle_key in TEXT[self.locale]:
            sub = QLabel(self.t(subtitle_key))
            sub.setObjectName("pageSubtitle")
            sub.setWordWrap(True)
            box.addWidget(sub)
        return box

    # ---- ① 还原 ----
    def _page_restore(self) -> QWidget:
        page = self._page_container()
        lay = page.layout()
        lay.addLayout(self._page_header("tab_restore", "tab_hint"))

        # 导出工程卡片
        card_export = SectionCard(self.t("export_frame"))
        tk_row = QHBoxLayout()
        tk_row.setSpacing(10)
        self.toolkit_edit = SiCapsuleLineEdit(card_export, self.t("toolkit_dir"))
        self.toolkit_edit.setText(self.toolkit_dir_var.get())
        self.toolkit_edit.setMinimumHeight(46)
        self.toolkit_edit.textChanged.connect(self.toolkit_dir_var.set)
        self.toolkit_dir_var._on_change = self._sync_toolkit_edit
        tk_row.addWidget(self.toolkit_edit, 1)
        pick_tk = Btn(self.t("select_toolkit"), card_export, kind=Btn.KIND_GHOST,
                      icon_name="ic_fluent_folder_search_16_filled", min_width=96)
        pick_tk.clicked.connect(self.pick_toolkit_dir)
        tk_row.addWidget(pick_tk)
        card_export.addLayout(tk_row)

        for key in ("builtin_ripper_hint", "toolkit_hint"):
            if key in TEXT[self.locale]:
                hint = QLabel(self.t(key), card_export)
                hint.setObjectName("hint")
                hint.setWordWrap(True)
                card_export.addWidget(hint)

        action_row = QHBoxLayout()
        action_row.setSpacing(12)
        self.install_toggle = ToggleRow(self.t("install_opt"), card_export,
                                        value=self.install_var.get())
        self.install_toggle.switch.toggled.connect(self.save_user_settings)
        action_row.addWidget(self.install_toggle, 1)
        self.export_btn = Btn(self.t("export"), card_export, kind=Btn.KIND_ACCENT,
                              height=40, min_width=112,
                              icon_name="ic_fluent_arrow_export_16_filled")
        self.export_btn.clicked.connect(self.start_export)
        self._register_busy_button(self.export_btn)
        action_row.addWidget(self.export_btn)
        card_export.addLayout(action_row)
        lay.addWidget(card_export)

        # 保险与预览卡片
        card_safety = SectionCard(self.t("safety_frame"))
        hint = QLabel(self.t("safety_hint"), card_safety)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        card_safety.addWidget(hint)
        safety_row = QHBoxLayout()
        safety_row.setSpacing(10)
        for text_key, icon_name, slot, kind in (
                ("preview_merge", "ic_fluent_eye_16_filled", self.start_preview, Btn.KIND_NORMAL),
                ("restore_backup", "ic_fluent_arrow_undo_16_filled",
                 self.show_restore_dialog, Btn.KIND_NORMAL),
                ("batch", "ic_fluent_stack_16_filled", self.start_batch, Btn.KIND_NORMAL),
        ):
            btn = Btn(self.t(text_key), card_safety, kind=kind, icon_name=icon_name)
            btn.clicked.connect(slot)
            self._register_busy_button(btn)
            safety_row.addWidget(btn)
        safety_row.addStretch(1)
        card_safety.addLayout(safety_row)
        lay.addWidget(card_safety)

        lay.addStretch(1)
        return page

    def _sync_toolkit_edit(self, value: str) -> None:
        if hasattr(self, "toolkit_edit") and self.toolkit_edit.text() != value:
            self.toolkit_edit.setText(value)

    # ---- ② 汉化 ----
    def _page_translate(self) -> QWidget:
        page = self._page_container()
        lay = page.layout()
        lay.addLayout(self._page_header("tab_translate", "tab_hint"))

        card = SectionCard(self.t("translator_frame"))
        author_row = QHBoxLayout()
        author_row.setSpacing(10)
        self.author_edit = SiCapsuleLineEdit(card, self.t("author"))
        self.author_edit.setText(self.author_var.get())
        self.author_edit.setMinimumHeight(46)
        self.author_edit.textChanged.connect(self.author_var.set)
        author_row.addWidget(self.author_edit, 1)
        card.addLayout(author_row)

        out_row = QHBoxLayout()
        out_row.setSpacing(10)
        self.extract_edit = SiCapsuleLineEdit(card, self.t("extract_path"))
        self.extract_edit.setText(self.extract_output_var.get())
        self.extract_edit.setMinimumHeight(46)
        self.extract_edit.setPlaceholderText("texts_to_translate.json")
        self.extract_edit.textChanged.connect(self.extract_output_var.set)
        out_row.addWidget(self.extract_edit, 1)
        pick_out = Btn(self.t("select_json_path"), card, kind=Btn.KIND_GHOST,
                       icon_name="ic_fluent_folder_open_16_filled")
        pick_out.clicked.connect(self.pick_extract_output)
        out_row.addWidget(pick_out)
        card.addLayout(out_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        extract_btn = Btn(self.t("extract"), card, kind=Btn.KIND_NORMAL,
                          icon_name="ic_fluent_arrow_download_16_filled")
        extract_btn.clicked.connect(lambda: self.run_async(
            lambda log: extract_texts(self.input_file, self.extract_output_var.get().strip(),
                                      self.t, log),
            task_key="progress_extract"))
        self._register_busy_button(extract_btn)
        btn_row.addWidget(extract_btn)

        write_btn = Btn(self.t("write"), card, kind=Btn.KIND_ACCENT,
                        icon_name="ic_fluent_save_16_filled")
        write_btn.clicked.connect(lambda: self.run_async(
            lambda log: write_translation(self.input_file, self.translation_file,
                                          self.author_var.get(), self.t, log),
            task_key="progress_write"))
        self._register_busy_button(write_btn)
        btn_row.addWidget(write_btn)
        btn_row.addStretch(1)
        card.addLayout(btn_row)
        lay.addWidget(card)
        lay.addStretch(1)
        return page

    # ---- ③ 剥离 ----
    def _page_strip(self) -> QWidget:
        page = self._page_container()
        lay = page.layout()
        lay.addLayout(self._page_header("tab_strip", "strip_hint"))

        card = SectionCard(self.t("strip_frame"))
        plat_row = QHBoxLayout()
        plat_row.setSpacing(18)
        label = QLabel(self.t("target_platform"), card)
        label.setStyleSheet(f"color: {TEXT_C};")
        plat_row.addWidget(label)
        self._platform_toggles = {}
        for key in PLATFORM_KEYS:
            toggle = ToggleRow(PLATFORM_NAMES[key], card, value=self.strip_platform_vars[key].get())
            self.strip_platform_vars[key]._on_change = self._make_platform_sync(key, toggle)
            toggle.switch.toggled.connect(self._make_platform_toggled(key, toggle))
            self._platform_toggles[key] = toggle
            plat_row.addWidget(toggle)
        plat_row.addStretch(1)
        card.addLayout(plat_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        analyze_btn = Btn(self.t("analyze"), card, kind=Btn.KIND_NORMAL,
                          icon_name="ic_fluent_clipboard_search_16_filled")
        analyze_btn.clicked.connect(lambda: self.run_async(
            lambda log: analyze_pack(
                self.input_file, self.t, log,
                progress=lambda frac, key="": self.set_progress(
                    frac, self.t(key) if key else "")),
            task_key="progress_analyze", determinate=True))
        self._register_busy_button(analyze_btn)
        action_row.addWidget(analyze_btn)

        strip_btn = Btn(self.t("strip"), card, kind=Btn.KIND_ACCENT, min_width=124,
                        icon_name="ic_fluent_subtract_circle_16_filled")
        strip_btn.clicked.connect(self.start_strip)
        self._register_busy_button(strip_btn)
        action_row.addWidget(strip_btn)
        action_row.addStretch(1)
        card.addLayout(action_row)

        out_row = QHBoxLayout()
        out_row.setSpacing(10)
        self.strip_edit = SiCapsuleLineEdit(card, self.t("select_strip_output"))
        self.strip_edit.setText(self.strip_output_var.get())
        self.strip_edit.setMinimumHeight(46)
        self.strip_edit.textChanged.connect(self.strip_output_var.set)
        self.strip_output_var._on_change = self._sync_strip_edit
        out_row.addWidget(self.strip_edit, 1)
        pick_strip = Btn(self.t("pick_strip_output"), card, kind=Btn.KIND_GHOST,
                         icon_name="ic_fluent_save_16_filled")
        pick_strip.clicked.connect(self.pick_strip_output)
        out_row.addWidget(pick_strip)
        card.addLayout(out_row)
        lay.addWidget(card)
        lay.addStretch(1)
        return page

    def _make_platform_toggled(self, key, toggle):
        def handler(checked):
            self.strip_platform_vars[key]._value = bool(checked)
            self._on_platform_toggle()
        return handler

    def _make_platform_sync(self, key, toggle):
        def handler(value):
            if toggle.isChecked() != bool(value):
                toggle.setChecked(bool(value))
        return handler

    def _sync_strip_edit(self, value):
        if hasattr(self, "strip_edit") and self.strip_edit.text() != value:
            self.strip_edit.setText(value)

    # ---------------- 日志 ----------------
    def _clear_log(self) -> None:
        self.logs.clear()
        if hasattr(self, "log_view"):
            self.log_view.clear()

    def refresh_logs(self) -> None:
        if not hasattr(self, "log_view"):
            return
        self.log_view.clear()
        for line in self.logs:
            self.log_view.append_colored(line)

    def log(self, message: str) -> None:
        dlog = getattr(self, "_diag_log", None)
        if dlog is not None:
            try:
                dlog.info(message)
            except Exception:
                pass

        def append():
            self.logs.append(message)
            if len(self.logs) > 1200:
                self.logs[: len(self.logs) - 1200] = []
            if hasattr(self, "log_view"):
                try:
                    self.log_view.append_colored(message)
                except RuntimeError:
                    pass

        self._ui(append)

    def tlog(self, message: str) -> None:
        if self.locale == "en":
            message = _zh2en(message)
        self.log(message)

    # ---------------- 进度 / 忙碌锁 ----------------
    def _register_busy_button(self, button):
        self._busy_buttons.append(button)
        return button

    def _tick_progress(self):
        if not self._busy or self._determinate:
            return
        self._progress_value = (self._progress_value + 1.6) % 96.0
        self.progress.setValue(int(self._progress_value * 10))

    def set_busy(self, busy: bool, name: str = "") -> None:
        self._busy = busy
        self._busy_name = name if busy else ""
        for button in self._busy_buttons:
            try:
                button.setEnabled(not busy)
            except RuntimeError:
                continue
        if busy:
            self._determinate = False
            self._progress_value = 0.0
            self._progress_label = self.t("busy_running", name=name)
            self._progress_timer.start()
        else:
            self._progress_timer.stop()
            self._determinate = False
            self._progress_value = 0.0
            self.progress.setValue(0)
            self._progress_label = self.t("progress_idle")
        self.status_label.setText(self._progress_label)

    def set_progress(self, fraction: float, label: str = "") -> None:
        def apply():
            self._determinate = True
            self._progress_value = max(0.0, min(1.0, fraction)) * 100.0
            self.progress.setValue(int(self._progress_value * 10))
            if label:
                self._progress_label = label
            self.status_label.setText(self._progress_label)
        self._ui(apply)

    def run_async(self, operation, *, task_key: str = "", determinate: bool = False) -> None:
        if self._busy:
            self.log(self.t("busy_running",
                            name=self._busy_name or self.t("progress_idle")))
            return
        name = self.t(task_key) if task_key else self.t("progress_idle")
        self.set_busy(True, name)
        self._determinate = determinate
        if determinate:
            self.set_progress(0.0, name)

        def worker():
            try:
                operation(self.log)
            except Exception as exc:
                self.log(self.t("processing_failed", error=exc))
                traceback.print_exc()
            finally:
                self._ui(lambda: self.set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    # ---------------- 语言 / 设置持久化 ----------------
    def toggle_language(self) -> None:
        self.locale = "en" if self.locale == "zh" else "zh"
        self.save_user_settings()
        self.build_ui()

    def save_user_settings(self) -> None:
        save_settings({
            "language": self.locale,
            "author": self.author_var.get(),
            "toolkit_dir": self.toolkit_dir_var.get().strip(),
            "package_dir": self.package_dir_var.get().strip(),
            "extract_output": self.extract_output_var.get().strip(),
            "strip_output": self.strip_output_var.get().strip(),
            "strip_platforms": self.selected_strip_platforms(),
            "strip_platform": (self.selected_strip_platforms() or ["WindowsBuild"])[0],
            "install_to_toolkit": bool(self.install_var.get()),
            "incremental_export": bool(self.incremental_var.get()),
            "repair_engine_17": bool(self.settings.get("repair_engine_17", False)),
            "geometry": self.settings.get("geometry", ""),
        })

    def _restore_geometry(self) -> None:
        geo = self.settings.get("geometry")
        if isinstance(geo, str) and re.match(r"^\d{3,}x\d{3,}([+-]-?\d+){1,2}$", geo):
            self.setGeometry(*self._parse_geometry(geo))
        else:
            self.resize(1160, 880)
            screen = QApplication.desktop().availableGeometry(self)
            self.move((screen.width() - self.width()) // 2,
                      max(0, (screen.height() - self.height()) // 2 - 20))

    @staticmethod
    def _parse_geometry(geo: str):
        match = re.match(r"^(\d+)x(\d+)([+-]-?\d+)?([+-]-?\d+)?$", geo)
        if not match:
            return 0, 0, 1120, 800
        width, height = int(match.group(1)), int(match.group(2))
        x = int(match.group(3)) if match.group(3) else 60
        y = int(match.group(4)) if match.group(4) else 60
        return x, y, width, height

    def closeEvent(self, event):  # noqa: N802
        if self._busy:
            answer = MsgBox(self, self.t("menu_settings") if False else self.t("title"),
                            self.t("busy_running", name=self._busy_name),
                            "question", ask=True, ok_text=self.t("about_close"),
                            cancel_text=self.t("settings_cancel")).exec_modal()
            if not answer:
                event.ignore()
                return
        if self.isMaximized() is False:
            geo = self.geometry()
            self.settings["geometry"] = f"{geo.width()}x{geo.height()}+{geo.x()}+{geo.y()}"
        self.save_user_settings()
        dlog = getattr(self, "_diag_log", None)
        if dlog is not None:
            try:
                dlog.close(extra={
                    "输入包": Path(self.input_file).name if self.input_file else "(未选择)",
                    "Toolkit": self.toolkit_dir_var.get().strip() or "(未选择)",
                })
            except Exception:
                pass
        event.accept()

    # ---------------- 文件选择 ----------------
    def pick_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("select_pack"), "", "SFS Pack (*.pack);;所有文件 (*.*)")
        if not path:
            return
        self.input_file = path
        if hasattr(self, "input_label"):
            self.input_label.setText(path)
        if not self.extract_output_var.get().strip():
            self.extract_output_var.set(str(Path(path).with_name("texts_to_translate.json")))
            if hasattr(self, "extract_edit"):
                self.extract_edit.setText(self.extract_output_var.get())
        cur_strip = self.strip_output_var.get().strip()
        if not cur_strip or cur_strip == self._strip_auto_name:
            new_strip = str(Path(path).with_name(self.default_strip_output_name()))
            self.strip_output_var.set(new_strip)
            self._strip_auto_name = new_strip
        self.log(self.t("selected_pack", name=Path(path).name))

    def pick_translation(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("select_translation"), "", "JSON (*.json);;所有文件 (*.*)")
        if path:
            self.translation_file = path
            if hasattr(self, "translation_label"):
                self.translation_label.setText(self._translation_label_text())
            self.log(self.t("selected_translation", name=Path(path).name))

    def pick_extract_output(self) -> None:
        initial = self.extract_output_var.get().strip()
        if not initial:
            initial = (str(Path(self.input_file).with_name("texts_to_translate.json"))
                       if self.input_file else "texts_to_translate.json")
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("select_json_path"), initial, "JSON (*.json);;所有文件 (*.*)")
        if path:
            self.extract_output_var.set(path)
            if hasattr(self, "extract_edit"):
                self.extract_edit.setText(path)
            self.save_user_settings()

    def pick_toolkit_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.t("select_toolkit"),
                                                self.toolkit_dir_var.get() or "")
        if not path:
            return
        resolved = resolve_toolkit_root(path)
        if resolved is not None:
            if str(resolved) != str(Path(path).resolve()):
                self.log(self.t("toolkit_root_fixed", path=str(resolved)))
            path = str(resolved)
        self.toolkit_dir_var.set(path)
        self.save_user_settings()
        self.log(self.t("selected_toolkit", path=path))

    def pick_strip_output(self) -> None:
        if self.input_file:
            default_name = self.default_strip_output_name()
        else:
            default_name = "stripped.pack"
        current = self.strip_output_var.get().strip()
        start_dir = str(Path(current).parent) if current else ""
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("pick_strip_output"), str(Path(start_dir) / default_name if start_dir else default_name),
            "SFS Pack (*.pack);;所有文件 (*.*)")
        if path:
            self.strip_output_var.set(path)
            self.log(self.t("strip_output_set", path=path))
            self.save_user_settings()

    # ---------------- 平台勾选 ----------------
    def selected_strip_platforms(self) -> list[str]:
        return [key for key in PLATFORM_KEYS if self.strip_platform_vars[key].get()]

    def default_strip_output_name(self) -> str:
        keys = self.selected_strip_platforms() or ["WindowsBuild"]
        return "-".join([Path(self.input_file).stem]
                        + [PLATFORM_NAMES.get(k, k) for k in keys]) + ".pack"

    def _on_platform_toggle(self) -> None:
        self.save_user_settings()
        if not self.input_file:
            return
        cur = self.strip_output_var.get().strip()
        if not cur or cur == self._strip_auto_name:
            new = str(Path(self.input_file).with_name(self.default_strip_output_name()))
            self.strip_output_var.set(new)
            self._strip_auto_name = new

    # ---------------- 剥离 / 预览 / 批量 / 探测 ----------------
    def start_strip(self) -> None:
        if not self.input_file:
            MsgBox(self, self.t("no_pack_title"), self.t("strip_no_pack"), "warning").exec_modal()
            return
        keys = self.selected_strip_platforms()
        if not keys:
            MsgBox(self, self.t("no_pack_title"), self.t("strip_none_selected"),
                   "warning").exec_modal()
            return
        output = self.strip_output_var.get().strip()
        if not output:
            output = str(Path(self.input_file).with_name(self.default_strip_output_name()))
        self.save_user_settings()
        self.run_async(
            lambda log: strip_pack(
                self.input_file, output, keys, self.t, log,
                progress=lambda frac, key="": self.set_progress(
                    frac, self.t(key) if key else "")),
            task_key="progress_strip", determinate=True)

    def start_preview(self) -> None:
        if not self.input_file or not self.toolkit_dir_var.get().strip():
            MsgBox(self, self.t("no_pack_title"), self.t("preview_need_dirs"),
                   "warning").exec_modal()
            return
        toolkit_dir = self.toolkit_dir_var.get().strip()
        if not Path(toolkit_dir).is_dir():
            MsgBox(self, self.t("need_toolkit"), self.t("need_toolkit_text"),
                   "error").exec_modal()
            return
        input_path = Path(self.input_file)
        stage_root = Path(tempfile.gettempdir()) / "SFS_Pack_Stage"
        export_dir = stage_root / f"{input_path.stem}_export"
        merge_dir = export_dir.with_name(f"{export_dir.name}_新增合并包")

        def _run(log):
            log(self.t("preview_start"))
            try:
                import sfs_pack_toolbox as toolbox
                if not merge_dir.is_dir():
                    log(self.t("preview_fail", error="还没有合并包，请先整包导出一次"))
                    return
                preview = toolbox.preview_merge(merge_dir, toolkit_dir)
                for line in toolbox.format_preview(preview):
                    log(line)
                if not preview.get("ok"):
                    log(self.t("preview_fail", error=preview.get("error", "")))
                    return
                summary = preview["summary"]
                log(self.t("preview_done"))
                self._ui(lambda: MsgBox(
                    self, self.t("preview_title"),
                    self.t("preview_body", add=summary["add"], replace=summary["replace"],
                           skip=summary["skip"], parts_added=summary["parts_added"]),
                    "info").exec_modal())
            except Exception as exc:
                log(self.t("preview_fail", error=exc))

        self.run_async(_run, task_key="progress_preview")

    def start_probe(self) -> None:
        toolkit_dir = self.toolkit_dir_var.get().strip()
        if not toolkit_dir or not Path(toolkit_dir).is_dir():
            MsgBox(self, self.t("need_toolkit"), self.t("need_toolkit_text"),
                   "error").exec_modal()
            return

        def _run(log):
            try:
                import sfs_pack_toolbox as toolbox
                info = toolbox.probe_toolkit_version(toolkit_dir)
                if not info.get("ok"):
                    log(self.t("probe_fail", error=info.get("error", "")))
                    self._ui(lambda: MsgBox(self, self.t("probe_title"),
                                            info.get("error", ""), "warning").exec_modal())
                    return
                log(self.t("probe_log",
                           unity=info["unity_version"] or "?",
                           toolkit=info["toolkit_version"] or "?",
                           files=info["script_files"],
                           fp=(info["fingerprint"] or "?")[:12]))
                body = self.t("probe_body",
                              unity=info["unity_version"] or "?",
                              toolkit=info["toolkit_version"] or "?",
                              files=info["script_files"],
                              fp=info["fingerprint"] or "?")
                self._ui(lambda: MsgBox(self, self.t("probe_title"), body, "info").exec_modal())
            except Exception as exc:
                log(self.t("probe_fail", error=exc))

        self.run_async(_run, task_key="progress_probe")

    def start_batch(self) -> None:
        if self._busy:
            self.log(self.t("busy_running", name=self._busy_name))
            return
        toolkit_dir = self.toolkit_dir_var.get().strip()
        if not toolkit_dir or not Path(toolkit_dir).is_dir():
            MsgBox(self, self.t("need_toolkit"), self.t("need_toolkit_text"),
                   "error").exec_modal()
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.t("batch_pick"), "", "SFS Pack (*.pack);;所有文件 (*.*)")
        if not paths:
            return
        packs = [Path(p) for p in paths]
        stage_root = Path(tempfile.gettempdir()) / "SFS_Pack_Stage"

        def _run(log):
            import sfs_pack_toolbox as toolbox
            plan = toolbox.BatchPlan(packs, stage_root, log=log)

            def executor(item, _log):
                self._export_one(item.pack, _log, item.output)
                return True

            summary = plan.run(executor)
            for line in plan.summary_lines():
                log(line)
            log(self.t("batch_result", ok=summary["ok"], failed=summary["failed"],
                       skipped=summary["skipped"]))
            self._ui(lambda: MsgBox(
                self, self.t("batch_title"),
                self.t("batch_body", ok=summary["ok"], failed=summary["failed"]),
                "info").exec_modal())

        self.run_async(_run, task_key="progress_batch")

    # ---------------- 导出 ----------------
    def start_export(self) -> None:
        if getattr(self, "_export_busy", False):
            self.log(self.t("export_busy"))
            return
        if not self.input_file:
            MsgBox(self, self.t("no_pack_title"), self.t("select_pack_first"),
                   "warning").exec_modal()
            return
        input_path = Path(self.input_file).resolve()
        stage_root = Path(tempfile.gettempdir()) / "SFS_Pack_Stage"
        stage_root.mkdir(parents=True, exist_ok=True)
        output_path = stage_root / f"{input_path.stem}_export"
        output = str(output_path)
        toolkit_dir = self.toolkit_dir_var.get().strip()
        if not toolkit_dir or not Path(toolkit_dir).is_dir():
            MsgBox(self, self.t("need_toolkit"), self.t("need_toolkit_text"),
                   "error").exec_modal()
            return
        resolved = resolve_toolkit_root(toolkit_dir)
        if resolved is None:
            MsgBox(self, self.t("need_toolkit_invalid"), self.t("need_toolkit_invalid_text"),
                   "error").exec_modal()
            return
        if str(resolved) != str(Path(toolkit_dir).resolve()):
            toolkit_dir = str(resolved)
            self.toolkit_dir_var.set(toolkit_dir)
            self.log(self.t("toolkit_root_fixed", path=toolkit_dir))
        package_dir = self.package_dir_var.get().strip()
        self.save_user_settings()

        if self.incremental_var.get():
            try:
                import sfs_pack_toolbox as toolbox
                try:
                    fingerprint = toolbox.probe_toolkit_version(toolkit_dir).get("fingerprint", "")
                except Exception:
                    fingerprint = ""
                plan = toolbox.incremental_plan(
                    input_path, toolkit_dir, self._export_index_path(),
                    toolkit_fingerprint=fingerprint)
                if plan["action"] == "skip":
                    self.log(self.t("incremental_skip", reason=plan["reason"]))
                    self.log(self.t("incremental_skip_hint"))
                    return
                self.log(self.t("incremental_full", reason=plan["reason"]))
            except Exception as exc:
                self.log(self.t("incremental_check_fail", error=exc))

        self._export_busy = True
        if getattr(self, "export_btn", None) is not None:
            self.export_btn.setEnabled(False)
            self.export_btn.setText(self.t("export_running"))

        def _run(log):
            try:
                import shutil
                shutil.rmtree(output, ignore_errors=True)
                self.export_project(log, output, toolkit_dir, bool(self.install_var.get()))
                self.repair_toolkit(log, toolkit_dir, package_dir)
            finally:
                self._ui(_done)

        def _done():
            self._export_busy = False
            if getattr(self, "export_btn", None) is not None:
                self.export_btn.setEnabled(True)
                self.export_btn.setText(self.t("export"))

        self.run_async(_run, task_key="progress_export", determinate=True)

    # ---------------- 回滚 / 日志目录 ----------------
    def show_restore_dialog(self) -> None:
        toolkit_dir = self.toolkit_dir_var.get().strip()
        if not toolkit_dir or not Path(toolkit_dir).is_dir():
            MsgBox(self, self.t("need_toolkit"), self.t("need_toolkit_text"),
                   "error").exec_modal()
            return
        try:
            import sfs_pack_toolbox as toolbox
            backups = toolbox.list_backups(toolkit_dir)
        except Exception as exc:
            MsgBox(self, self.t("restore_title"), self.t("restore_fail", error=exc),
                   "error").exec_modal()
            return
        if not backups:
            MsgBox(self, self.t("restore_title"), self.t("restore_none"), "info").exec_modal()
            return

        dialog = Dialog(self, self.t("restore_title"), width=600)
        hint = QLabel(self.t("restore_hint"), dialog.panel)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        dialog.body.addWidget(hint)
        pick = QLabel(self.t("restore_pick"), dialog.panel)
        pick.setStyleSheet(f"color: {TEXT_C};")
        dialog.body.addWidget(pick)

        listing = QListWidget(dialog.panel)
        listing.setStyleSheet(f"""
            QListWidget {{
                background: {BG_CARD_BACK}; border: 1px solid {BORDER};
                border-radius: 8px; color: {TEXT_C}; padding: 6px;
            }}
            QListWidget::item {{ padding: 7px 8px; border-radius: 6px; }}
            QListWidget::item:selected {{ background: {BG_CARD_FORE}; color: #FFFFFF; }}
        """)
        listing.setMinimumHeight(240)
        for entry in backups:
            listing.addItem(QListWidgetItem(entry.display))
        listing.setCurrentRow(0)
        dialog.body.addWidget(listing)

        def do_restore(dry_run: bool):
            row = listing.currentRow()
            if row < 0:
                return
            entry = backups[row]
            result = toolbox.restore_backup(
                toolkit_dir, entry, dry_run=dry_run, safety_backup=True, log=self.tlog)
            if dry_run:
                self.log(self.t("restore_log_dry", n=result.get("would_restore", 0)))
            else:
                self.log(self.t("restore_log_done", n=result.get("restored", 0),
                                skip=result.get("skipped", 0)))
                dialog.accept()

        dialog.add_button(self.t("about_close"), dialog.reject, kind=Btn.KIND_GHOST)
        dialog.add_button(self.t("restore_dryrun"), lambda: do_restore(True))
        dialog.add_button(self.t("restore_apply"), lambda: do_restore(False),
                          kind=Btn.KIND_ACCENT, default=True)
        dialog.exec_()

    def open_log_dir(self) -> None:
        path = LOG_DIR
        if not path.is_dir():
            MsgBox(self, self.t("restore_title"),
                   self.t("log_dir_missing", path=str(path)), "info").exec_modal()
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # noqa: S606
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(path)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            self.log(self.t("restore_fail", error=exc))

    # ---------------- 清理缓存 ----------------
    def show_cache_dialog(self) -> None:
        if self._busy:
            self.log(self.t("cache_busy"))
            return
        toolkit_dir = self.toolkit_dir_var.get().strip()
        items = scan_cache(toolkit_dir)
        if not items:
            MsgBox(self, self.t("cache_title"), self.t("cache_scan_none"), "info").exec_modal()
            return

        dialog = Dialog(self, self.t("cache_title"), width=660)
        hint = QLabel(self.t("cache_hint"), dialog.panel)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        dialog.body.addWidget(hint)

        checks: dict[str, QCheckBox] = {}
        for item in items:
            box = QCheckBox(
                f"{self.t(item['label_key'])}\n    {human_size(item['size'])}   {item['path']}",
                dialog.panel)
            box.setChecked(not item["risky"])
            box.setStyleSheet(f"""
                QCheckBox {{ color: {TEXT_C}; spacing: 9px; padding: 4px 0; }}
                QCheckBox::indicator {{
                    width: 16px; height: 16px; border-radius: 4px;
                    border: 1px solid {TEXT_E}; background: transparent;
                }}
                QCheckBox::indicator:checked {{
                    background: {ACCENT}; border: 1px solid {ACCENT};
                }}
            """)
            checks[item["key"]] = box
            dialog.body.addWidget(box)

        def do_clean():
            keys = {key for key, box in checks.items() if box.isChecked()}
            if not keys:
                MsgBox(self, self.t("cache_title"), self.t("cache_none_selected"),
                       "warning").exec_modal()
                return
            chosen = [item for item in items if item["key"] in keys]
            total = sum(item["size"] for item in chosen)
            if not MsgBox(self, self.t("cache_title"),
                          self.t("cache_confirm", n=len(chosen), size=human_size(total)),
                          "question", ask=True).exec_modal():
                return
            dialog.accept()
            self.run_async(lambda log: self._clean_cache_worker(chosen, keys, log),
                           task_key="progress_cache")

        dialog.add_button(self.t("about_close"), dialog.reject, kind=Btn.KIND_GHOST)
        dialog.add_button(self.t("clear_cache"), do_clean, kind=Btn.KIND_ACCENT)
        dialog.exec_()

    def _clean_cache_worker(self, chosen: list[dict], keys: set, log) -> None:
        freed, errors = clean_cache_items(chosen, keys)
        for err in errors:
            log(f"[!] {err}")
        message = self.t("cache_done", size=human_size(freed))
        self.set_progress(1.0, message)
        log(message)
        self._ui(lambda: MsgBox(self, self.t("cache_title"), message, "info").exec_modal())

    # ---------------- 设置 ----------------
    def show_settings(self) -> None:
        current_mode = str(self.settings.get("asset_ripper_mode", "bundled"))
        if current_mode not in ("bundled", "version", "custom"):
            current_mode = "bundled"

        dialog = Dialog(self, self.t("settings_title"), width=640)
        hint = QLabel(self.t("settings_hint"), dialog.panel)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        dialog.body.addWidget(hint)

        # --- AssetRipper ---
        card = SectionCard(self.t("settings_section_ripper"), dialog.panel)
        mode_label = QLabel(self.t("settings_ripper_mode"), card)
        mode_label.setStyleSheet(f"color: {TEXT_C};")
        card.addWidget(mode_label)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_group = QButtonGroup(dialog)
        mode_buttons = {}
        for index, (value, key) in enumerate((
                ("bundled", "settings_ripper_bundled"),
                ("version", "settings_ripper_version"),
                ("custom", "settings_ripper_custom"))):
            button = Btn(self.t(key), card,
                         kind=Btn.KIND_ACCENT if value == current_mode else Btn.KIND_GHOST,
                         height=34)
            button.setCheckable(True)
            button.setChecked(value == current_mode)
            button._mode_value = value
            mode_buttons[value] = button
            mode_group.addButton(button, index)
            mode_row.addWidget(button)
        mode_row.addStretch(1)
        card.addLayout(mode_row)

        ver_row = QHBoxLayout()
        ver_row.setSpacing(10)
        ver_edit = SiCapsuleLineEdit(card, self.t("settings_ripper_ver_label"))
        ver_edit.setText(str(self.settings.get("asset_ripper_version", "") or ""))
        ver_edit.setMinimumHeight(44)
        ver_row.addWidget(ver_edit, 1)
        card.addLayout(ver_row)

        path_row = QHBoxLayout()
        path_row.setSpacing(10)
        path_edit = SiCapsuleLineEdit(card, self.t("settings_ripper_path_label"))
        path_edit.setText(str(self.settings.get("asset_ripper_path", "") or ""))
        path_edit.setMinimumHeight(44)
        path_row.addWidget(path_edit, 1)
        pick_exe = Btn("…", card, kind=Btn.KIND_GHOST, min_width=44)

        def choose_exe():
            chosen, _ = QFileDialog.getOpenFileName(
                self, self.t("settings_ripper_path_label"), "",
                "Executable (*.exe);;所有文件 (*.*)")
            if chosen:
                path_edit.setText(chosen)
                select_mode("custom")

        pick_exe.clicked.connect(choose_exe)
        path_row.addWidget(pick_exe)
        card.addLayout(path_row)

        note = QLabel(self.t("settings_ripper_note"), card)
        note.setObjectName("hint")
        note.setWordWrap(True)
        card.addWidget(note)
        dialog.body.addWidget(card)

        # --- 日志 ---
        log_card = SectionCard(self.t("settings_section_log"), dialog.panel)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(10)
        dir_label = QLabel(self.t("settings_log_dir_label"), log_card)
        dir_label.setStyleSheet(f"color: {TEXT_C};")
        dir_row.addWidget(dir_label)
        dir_value = QLabel(str(LOG_DIR), log_card)
        dir_value.setObjectName("dim")
        dir_value.setWordWrap(True)
        dir_row.addWidget(dir_value, 1)
        log_card.addLayout(dir_row)

        log_row = QHBoxLayout()
        log_row.setSpacing(10)
        open_dir_btn = Btn(self.t("settings_open_log_dir"), log_card, kind=Btn.KIND_GHOST,
                           height=34, icon_name="ic_fluent_folder_open_16_filled")
        open_dir_btn.clicked.connect(self.open_log_dir)
        log_row.addWidget(open_dir_btn)
        days_edit = SiCapsuleLineEdit(log_card, self.t("settings_keep_days"))
        days_edit.setText(str(self.settings.get("log_keep_days", 30)))
        days_edit.setFixedWidth(200)
        days_edit.setMinimumHeight(44)
        log_row.addWidget(days_edit)
        log_row.addStretch(1)
        log_card.addLayout(log_row)
        dialog.body.addWidget(log_card)

        # --- 高级 ---
        adv_card = SectionCard(self.t("settings_section_adv"), dialog.panel)
        incr_toggle = ToggleRow(self.t("settings_incremental"), adv_card,
                                value=bool(self.settings.get("incremental_export", False)))
        adv_card.addWidget(incr_toggle)
        repair17_toggle = ToggleRow(self.t("settings_repair_engine_17"), adv_card,
                                    value=bool(self.settings.get("repair_engine_17", False)))
        adv_card.addWidget(repair17_toggle)
        probe_btn = Btn(self.t("settings_probe"), adv_card, kind=Btn.KIND_NORMAL,
                        icon_name="ic_fluent_pulse_16_filled")
        probe_btn.clicked.connect(self.start_probe)
        self._register_busy_button(probe_btn)
        probe_row = QHBoxLayout()
        probe_row.addWidget(probe_btn)
        probe_row.addStretch(1)
        adv_card.addLayout(probe_row)
        dialog.body.addWidget(adv_card)

        def select_mode(value: str):
            mode_buttons[value].setChecked(True)
            for key, button in mode_buttons.items():
                button.setColors(*(("#6E4A80", "#FFFFFF") if key == value
                                   else ("#332E38", "#C7C7C7")))
            ver_edit.setEnabled(value == "version")
            path_edit.setEnabled(value == "custom")
            pick_exe.setEnabled(value == "custom")

        for value, button in mode_buttons.items():
            button.clicked.connect(lambda _c=False, v=value: select_mode(v))
        select_mode(current_mode)

        def apply_settings():
            if mode_buttons["version"].isChecked():
                mode = "version"
            elif mode_buttons["custom"].isChecked():
                mode = "custom"
            else:
                mode = "bundled"
            version_text = ver_edit.text().strip()
            path_text = path_edit.text().strip()
            if mode == "version":
                if not version_text:
                    MsgBox(self, self.t("settings_title"),
                           self.t("settings_ripper_need_version"), "warning").exec_modal()
                    return
                if not re.fullmatch(r"[0-9]+(\.[0-9]+)*", version_text):
                    MsgBox(self, self.t("settings_title"),
                           self.t("settings_ripper_bad_version"), "warning").exec_modal()
                    return
            if mode == "custom":
                if not path_text:
                    MsgBox(self, self.t("settings_title"),
                           self.t("settings_ripper_need_path"), "warning").exec_modal()
                    return
                if not Path(path_text).is_file():
                    MsgBox(self, self.t("settings_title"),
                           self.t("settings_ripper_bad_path", path=path_text),
                           "warning").exec_modal()
                    return
            try:
                days = int(days_edit.text().strip() or "30")
            except ValueError:
                days = -1
            if not (1 <= days <= 3650):
                MsgBox(self, self.t("settings_title"),
                       self.t("settings_keep_days_bad"), "warning").exec_modal()
                return

            self.settings.update({
                "asset_ripper_mode": mode,
                "asset_ripper_version": version_text,
                "asset_ripper_path": path_text,
                "log_keep_days": days,
            })
            self.incremental_var.set(bool(incr_toggle.isChecked()))
            self.settings["repair_engine_17"] = bool(repair17_toggle.isChecked())
            self.save_user_settings()

            if mode == "version":
                summary = self.t("settings_ripper_summary_version", version=version_text)
            elif mode == "custom":
                summary = self.t("settings_ripper_summary_custom", path=path_text)
            else:
                summary = self.t("settings_ripper_summary_bundled")
            self.log(self.t("settings_saved", summary=summary))
            try:
                import sfs_pack_toolbox as toolbox
                self._diag_log = toolbox.DiagnosticLog(
                    LOG_DIR, app_version=VERSION, keep_days=days)
            except Exception:
                pass
            dialog.accept()

        dialog.add_button(self.t("settings_cancel"), dialog.reject, kind=Btn.KIND_GHOST)
        dialog.add_button(self.t("settings_apply"), apply_settings,
                          kind=Btn.KIND_ACCENT, default=True)
        dialog.exec_()

    # ---------------- 关于 ----------------
    def open_tutorial(self) -> None:
        tutorial = resource_path("tutorial.html")
        if not tutorial.is_file():
            tutorial = Path(__file__).resolve().parent / "tutorial.html"
        if tutorial.is_file():
            webbrowser.open(tutorial.as_uri())
        else:
            MsgBox(self, self.t("menu_tutorial"), self.t("tutorial_missing"),
                   "info").exec_modal()

    def show_about_author(self) -> None:
        MsgBox(self, self.t("about_author_title"),
               self.t("about_author_text") + "\n\n" + self.t("link_qq") + "\n"
               + self.t("qq_hint"), "info").exec_modal()

    def show_about_app(self) -> None:
        MsgBox(self, self.t("about_app_title"), self.t("about_app_text"), "info").exec_modal()


class _UiBridge(QObject):
    """后台线程 -> 主线程的函数调用队列。"""

    invoke = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.invoke.connect(self._run, Qt.QueuedConnection)

    @staticmethod
    def _run(fn):
        try:
            fn()
        except RuntimeError:
            pass
        except Exception:
            traceback.print_exc()


def main() -> int:
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "AFuturestar.SFSPackTool.2.3.6-PyQt")
        except (AttributeError, OSError):
            pass
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("SFS Pack Tool")
    font = QFont("Microsoft YaHei UI", 10)
    font.setPixelSize(13)
    app.setFont(font)

    window = App()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
