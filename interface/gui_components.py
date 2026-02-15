"""
Pattern Project - GUI Components
Reusable widgets and utilities for the chat interface.

Components:
- ThemeManager: Light/dark theme support
- MarkdownRenderer: Full markdown to HTML conversion
- MessageWidget: Individual message with actions (copy, bookmark, collapse)
- SearchBar: In-conversation search
- CommandPalette: Quick command access
- NotificationManager: Toast notifications
- DraftManager: Auto-save/restore drafts
"""

import re
import html
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Callable, Any
from dataclasses import dataclass, field

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QScrollArea, QGraphicsOpacityEffect, QApplication, QShortcut,
    QListWidget, QListWidgetItem, QTextEdit, QSizePolicy
)
from PyQt5.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QObject, QSize
)
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QKeySequence, QClipboard, QTextCursor
)


# =============================================================================
# THEME SYSTEM
# =============================================================================

@dataclass
class Theme:
    """Color theme definition."""
    name: str
    background: str
    surface: str
    primary: str
    accent: str
    text: str
    text_dim: str
    user: str
    assistant: str
    system: str
    timestamp: str
    pulse: str
    action: str
    code_bg: str
    border: str
    success: str
    warning: str
    error: str
    user_bubble: str = ""  # Background color for user message bubbles


# Dark theme - Claude.ai inspired neutral warm palette
DARK_THEME = Theme(
    name="dark",
    background="#2b2b2b",
    surface="#313131",
    primary="#424242",
    accent="#d4a574",
    text="#e8e6e3",
    text_dim="#9a9892",
    user="#e8e6e3",
    assistant="#e8e6e3",
    system="#d4a574",
    timestamp="#7a7770",
    pulse="#c4a7e7",
    action="#c4a7e7",
    code_bg="#1e1e1e",
    border="#424240",
    success="#5bb98c",
    warning="#d4a574",
    error="#e07a6b",
    user_bubble="#3d3d3a",
)

# Light theme - Claude.ai inspired warm cream palette
LIGHT_THEME = Theme(
    name="light",
    background="#f5f3ef",
    surface="#ffffff",
    primary="#e8e4de",
    accent="#b35c2a",
    text="#2d2b28",
    text_dim="#6b6862",
    user="#2d2b28",
    assistant="#2d2b28",
    system="#b35c2a",
    timestamp="#9a9690",
    pulse="#7c3aed",
    action="#6b21a8",
    code_bg="#f0ece6",
    border="#d6d2cc",
    success="#3a8a5c",
    warning="#b35c2a",
    error="#c44a3a",
    user_bubble="#ede9e3",
)


class ThemeManager(QObject):
    """Manages application themes."""

    theme_changed = pyqtSignal(Theme)

    def __init__(self):
        super().__init__()
        self._current_theme = DARK_THEME
        self._themes = {
            "dark": DARK_THEME,
            "light": LIGHT_THEME,
        }

    @property
    def current(self) -> Theme:
        return self._current_theme

    def set_theme(self, name: str):
        """Switch to a named theme."""
        if name in self._themes:
            self._current_theme = self._themes[name]
            self.theme_changed.emit(self._current_theme)

    def toggle(self):
        """Toggle between light and dark themes."""
        new_name = "light" if self._current_theme.name == "dark" else "dark"
        self.set_theme(new_name)

    def get_stylesheet(self) -> str:
        """Generate stylesheet for current theme."""
        t = self._current_theme
        font_stack = "'Segoe UI', 'Helvetica Neue', 'Arial', sans-serif"
        return f"""
            QMainWindow {{
                background-color: {t.background};
                font-family: {font_stack};
            }}
            QFrame {{
                background-color: {t.surface};
                border: 1px solid {t.border};
                border-radius: 8px;
            }}
            QTextBrowser {{
                background-color: {t.background};
                color: {t.text};
                border: none;
                border-radius: 8px;
                padding: 16px;
                font-family: {font_stack};
            }}
            QLineEdit {{
                background-color: {t.surface};
                color: {t.text};
                border: 1px solid {t.border};
                border-radius: 18px;
                padding: 10px 16px;
                font-family: {font_stack};
            }}
            QLineEdit:focus {{
                border: 1px solid {t.accent};
            }}
            QTextEdit {{
                background-color: {t.surface};
                color: {t.text};
                border: 1px solid {t.border};
                border-radius: 18px;
                padding: 10px 16px;
                font-family: {font_stack};
            }}
            QTextEdit:focus {{
                border: 1px solid {t.accent};
            }}
            QPushButton {{
                background-color: {t.primary};
                color: {t.text};
                border: none;
                border-radius: 16px;
                padding: 8px 16px;
                font-family: {font_stack};
            }}
            QPushButton:hover {{
                background-color: {t.accent};
                color: {t.background};
            }}
            QPushButton:checked {{
                background-color: {t.accent};
                color: {t.background};
            }}
            QPushButton:disabled {{
                background-color: {t.text_dim};
                color: {t.surface};
            }}
            QLabel {{
                color: {t.text};
                background: transparent;
                border: none;
                font-family: {font_stack};
            }}
            QComboBox {{
                background-color: {t.surface};
                color: {t.text_dim};
                border: 1px solid {t.border};
                border-radius: 12px;
                padding: 4px 10px;
                min-width: 80px;
                font-family: {font_stack};
            }}
            QComboBox:hover {{
                border: 1px solid {t.accent};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {t.surface};
                color: {t.text};
                selection-background-color: {t.primary};
                font-family: {font_stack};
            }}
            QScrollBar:vertical {{
                background-color: transparent;
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {t.border};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {t.text_dim};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QListWidget {{
                background-color: {t.surface};
                color: {t.text};
                border: 1px solid {t.border};
                border-radius: 8px;
                font-family: {font_stack};
            }}
            QListWidget::item {{
                padding: 8px;
                border-radius: 4px;
            }}
            QListWidget::item:hover {{
                background-color: {t.primary};
            }}
            QListWidget::item:selected {{
                background-color: {t.accent};
            }}
            QCheckBox {{
                color: {t.text};
                font-family: {font_stack};
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid {t.border};
                background-color: {t.surface};
            }}
            QCheckBox::indicator:checked {{
                background-color: {t.accent};
                border-color: {t.accent};
            }}
        """


# Global theme manager instance
_theme_manager: Optional[ThemeManager] = None


def get_theme_manager() -> ThemeManager:
    """Get global theme manager."""
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager


# =============================================================================
# MARKDOWN RENDERER
# =============================================================================

class MarkdownRenderer:
    """Converts markdown to HTML for QTextBrowser display."""

    def __init__(self, theme: Theme):
        self.theme = theme

    def update_theme(self, theme: Theme):
        """Update renderer theme."""
        self.theme = theme

    def render(self, text: str, role: str = "assistant") -> str:
        """
        Convert markdown text to HTML.

        Supports:
        - Code blocks (```language ... ```)
        - Inline code (`code`)
        - Bold (**bold**)
        - Italic (_italic_)
        - Strikethrough (~~strike~~)
        - Action text (*action*) - for assistant messages
        - Headers (# ## ###)
        - Lists (- item, * item, 1. item)
        - Links [text](url)
        - Blockquotes (> quote)
        """
        # HTML escape first
        result = html.escape(text)

        if role == "assistant":
            # Process in order (code blocks first to protect their content)
            result = self._render_code_blocks(result)
            result = self._render_inline_code(result)
            result = self._render_headers(result)
            result = self._render_bold(result)
            result = self._render_italic(result)
            result = self._render_strikethrough(result)
            result = self._render_action_text(result)
            result = self._render_links(result)
            result = self._render_blockquotes(result)
            result = self._render_lists(result)
            result = self._render_pulse_command(result)

        # Collapse excessive newlines (3+ becomes 2) to prevent over-spacing
        result = re.sub(r'\n{3,}', '\n\n', result)
        # Convert newlines (do this last, after list processing)
        result = result.replace('\n', '<br/>')

        return result

    def _render_code_blocks(self, text: str) -> str:
        """Render fenced code blocks with syntax indication."""
        pattern = r'```(\w*)\n(.*?)```'

        def replace_block(match):
            lang = match.group(1) or "text"
            code = match.group(2).rstrip()

            # Style for code block
            block_style = (
                f"background-color: {self.theme.code_bg}; "
                f"border: 1px solid {self.theme.border}; "
                "border-radius: 8px; "
                "padding: 14px 16px; "
                "margin: 12px 0; "
                "font-family: 'Consolas', 'Monaco', 'Courier New', monospace; "
                "font-size: 13px; "
                "white-space: pre-wrap; "
                "display: block; "
                "overflow-x: auto;"
            )

            lang_style = (
                f"color: {self.theme.text_dim}; "
                "font-size: 10px; "
                "margin-bottom: 6px; "
                "display: block;"
            )

            return (
                f'<div style="{block_style}">'
                f'<span style="{lang_style}">{lang}</span>'
                f'{code}'
                f'</div>'
            )

        return re.sub(pattern, replace_block, text, flags=re.DOTALL)

    def _render_inline_code(self, text: str) -> str:
        """Render `inline code`."""
        pattern = r'`([^`\n]+)`'
        style = (
            f"background-color: {self.theme.code_bg}; "
            "padding: 2px 6px; "
            "border-radius: 4px; "
            "font-family: 'Consolas', 'Monaco', 'Courier New', monospace; "
            "font-size: 13px;"
        )
        return re.sub(pattern, rf'<span style="{style}">\1</span>', text)

    def _render_headers(self, text: str) -> str:
        """Render markdown headers."""
        # H3 (###)
        text = re.sub(
            r'^### (.+)$',
            rf'<h4 style="color: {self.theme.text}; margin: 16px 0 8px 0;">\1</h4>',
            text, flags=re.MULTILINE
        )
        # H2 (##)
        text = re.sub(
            r'^## (.+)$',
            rf'<h3 style="color: {self.theme.text}; margin: 20px 0 10px 0;">\1</h3>',
            text, flags=re.MULTILINE
        )
        # H1 (#)
        text = re.sub(
            r'^# (.+)$',
            rf'<h2 style="color: {self.theme.text}; margin: 24px 0 12px 0;">\1</h2>',
            text, flags=re.MULTILINE
        )
        return text

    def _render_bold(self, text: str) -> str:
        """Render **bold** text."""
        return re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)

    def _render_italic(self, text: str) -> str:
        """Render _italic_ text."""
        return re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'<i>\1</i>', text)

    def _render_strikethrough(self, text: str) -> str:
        """Render ~~strikethrough~~ text."""
        return re.sub(r'~~([^~]+)~~', r'<s>\1</s>', text)

    def _render_action_text(self, text: str) -> str:
        """Render *action text* with special color."""
        pattern = r'(?<!\*)\*(?!\*)([^*]+)\*(?!\*)'
        return re.sub(
            pattern,
            rf'<span style="color: {self.theme.action};">\1</span>',
            text
        )

    def _render_links(self, text: str) -> str:
        """Render [text](url) links."""
        pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        return re.sub(
            pattern,
            rf'<a href="\2" style="color: {self.theme.accent};">\1</a>',
            text
        )

    def _render_blockquotes(self, text: str) -> str:
        """Render > blockquotes."""
        pattern = r'^&gt; (.+)$'
        style = (
            f"border-left: 3px solid {self.theme.border}; "
            "padding-left: 14px; "
            f"color: {self.theme.text_dim}; "
            "margin: 12px 0;"
        )
        return re.sub(
            pattern,
            rf'<div style="{style}">\1</div>',
            text, flags=re.MULTILINE
        )

    def _render_lists(self, text: str) -> str:
        """Render bullet and numbered lists."""
        lines = text.split('\n')
        result = []
        list_buffer = []  # Buffer for current list HTML (joined without newlines)
        in_list = False
        list_type = None

        def flush_list():
            """Flush the list buffer to result as a single string (no internal newlines)."""
            nonlocal list_buffer, in_list, list_type
            if list_buffer:
                result.append(''.join(list_buffer))
                list_buffer = []
            in_list = False
            list_type = None

        for line in lines:
            # Bullet list (- or *)
            bullet_match = re.match(r'^(\s*)[*-] (.+)$', line)
            # Numbered list
            number_match = re.match(r'^(\s*)(\d+)\. (.+)$', line)

            if bullet_match:
                if not in_list or list_type != 'ul':
                    if in_list:
                        list_buffer.append('</ul>' if list_type == 'ul' else '</ol>')
                    list_buffer.append('<ul style="margin: 8px 0; padding-left: 24px;">')
                    in_list = True
                    list_type = 'ul'
                list_buffer.append(f'<li style="margin: 4px 0;">{bullet_match.group(2)}</li>')
            elif number_match:
                if not in_list or list_type != 'ol':
                    if in_list:
                        list_buffer.append('</ul>' if list_type == 'ul' else '</ol>')
                    list_buffer.append('<ol style="margin: 8px 0; padding-left: 24px;">')
                    in_list = True
                    list_type = 'ol'
                list_buffer.append(f'<li style="margin: 4px 0;">{number_match.group(3)}</li>')
            else:
                # Skip blank lines when inside a list to prevent double-spacing
                if in_list and line.strip() == '':
                    continue
                if in_list:
                    list_buffer.append('</ul>' if list_type == 'ul' else '</ol>')
                    flush_list()
                result.append(line)

        if in_list:
            list_buffer.append('</ul>' if list_type == 'ul' else '</ol>')
            flush_list()

        return '\n'.join(result)

    def _render_pulse_command(self, text: str) -> str:
        """Render [[PULSE:Xm]] commands."""
        pattern = r'\[\[PULSE:(3m|10m|30m|1h|6h)\]\]'
        return re.sub(
            pattern,
            rf'<span style="color: {self.theme.pulse};">&#x23F1; \g<0></span>',
            text
        )


# =============================================================================
# MESSAGE DATA
# =============================================================================

@dataclass
class MessageData:
    """Data for a single chat message."""
    id: str
    role: str  # 'user', 'assistant', 'system'
    content: str
    timestamp: str
    bookmarked: bool = False
    collapsed: bool = False


# =============================================================================
# SEARCH BAR
# =============================================================================

class SearchBar(QFrame):
    """Search bar for finding messages in conversation."""

    search_requested = pyqtSignal(str)  # Emitted when user searches
    search_closed = pyqtSignal()        # Emitted when search is closed
    next_result = pyqtSignal()          # Navigate to next result
    prev_result = pyqtSignal()          # Navigate to previous result

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._setup_ui()
        self.hide()  # Hidden by default

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(5)

        # Search icon label
        self.icon_label = QLabel("🔍")
        layout.addWidget(self.icon_label)

        # Search input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search messages...")
        self.search_input.returnPressed.connect(self._on_search)
        self.search_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.search_input, stretch=1)

        # Result count
        self.result_label = QLabel("")
        self.result_label.setStyleSheet(f"color: {self.theme.text_dim};")
        layout.addWidget(self.result_label)

        # Navigation buttons
        self.prev_btn = QPushButton("▲")
        self.prev_btn.setMaximumWidth(30)
        self.prev_btn.clicked.connect(self.prev_result.emit)
        layout.addWidget(self.prev_btn)

        self.next_btn = QPushButton("▼")
        self.next_btn.setMaximumWidth(30)
        self.next_btn.clicked.connect(self.next_result.emit)
        layout.addWidget(self.next_btn)

        # Close button
        self.close_btn = QPushButton("✕")
        self.close_btn.setMaximumWidth(30)
        self.close_btn.clicked.connect(self._close)
        layout.addWidget(self.close_btn)

    def _on_search(self):
        text = self.search_input.text().strip()
        if text:
            self.search_requested.emit(text)

    def _on_text_changed(self, text: str):
        if text:
            self.search_requested.emit(text)

    def _close(self):
        self.hide()
        self.search_input.clear()
        self.result_label.setText("")
        self.search_closed.emit()

    def show_results(self, current: int, total: int):
        """Update result count display."""
        if total > 0:
            self.result_label.setText(f"{current}/{total}")
        else:
            self.result_label.setText("No results")

    def activate(self):
        """Show and focus the search bar."""
        self.show()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def update_theme(self, theme: Theme):
        """Update colors for new theme."""
        self.theme = theme
        self.result_label.setStyleSheet(f"color: {theme.text_dim};")


# =============================================================================
# COMMAND PALETTE
# =============================================================================

@dataclass
class Command:
    """A command for the command palette."""
    id: str
    name: str
    shortcut: str
    callback: Callable
    description: str = ""


class CommandPalette(QFrame):
    """Quick command access palette (like VS Code Ctrl+Shift+P)."""

    command_selected = pyqtSignal(str)  # Emitted with command id
    closed = pyqtSignal()

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.commands: List[Command] = []
        self._filtered_commands: List[Command] = []
        self._setup_ui()
        self.hide()

    def _setup_ui(self):
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setMinimumWidth(400)
        self.setMaximumWidth(600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Search input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type a command...")
        self.search_input.textChanged.connect(self._filter_commands)
        layout.addWidget(self.search_input)

        # Command list
        self.command_list = QListWidget()
        self.command_list.setMaximumHeight(300)
        self.command_list.itemClicked.connect(self._on_item_clicked)
        self.command_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.command_list)

        # Handle keyboard navigation
        self.search_input.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Handle keyboard events for navigation."""
        from PyQt5.QtCore import QEvent

        if obj == self.search_input and event.type() == QEvent.KeyPress:
            key = event.key()

            if key == Qt.Key_Down:
                self._move_selection(1)
                return True
            elif key == Qt.Key_Up:
                self._move_selection(-1)
                return True
            elif key == Qt.Key_Return:
                self._execute_selected()
                return True
            elif key == Qt.Key_Escape:
                self.hide()
                self.closed.emit()
                return True

        return super().eventFilter(obj, event)

    def _move_selection(self, delta: int):
        """Move selection up or down."""
        current = self.command_list.currentRow()
        new_row = max(0, min(current + delta, self.command_list.count() - 1))
        self.command_list.setCurrentRow(new_row)

    def _execute_selected(self):
        """Execute the currently selected command."""
        current = self.command_list.currentRow()
        if 0 <= current < len(self._filtered_commands):
            cmd = self._filtered_commands[current]
            self.hide()
            self.command_selected.emit(cmd.id)
            cmd.callback()

    def _on_item_clicked(self, item):
        """Handle single click - just select."""
        pass

    def _on_item_double_clicked(self, item):
        """Handle double click - execute."""
        self._execute_selected()

    def set_commands(self, commands: List[Command]):
        """Set available commands."""
        self.commands = commands
        self._filter_commands("")

    def _filter_commands(self, query: str):
        """Filter commands based on search query."""
        query = query.lower()

        if not query:
            self._filtered_commands = self.commands.copy()
        else:
            self._filtered_commands = [
                cmd for cmd in self.commands
                if query in cmd.name.lower() or query in cmd.description.lower()
            ]

        self._update_list()

    def _update_list(self):
        """Update the command list display."""
        self.command_list.clear()

        for cmd in self._filtered_commands:
            text = f"{cmd.name}"
            if cmd.shortcut:
                text += f"  ({cmd.shortcut})"

            item = QListWidgetItem(text)
            if cmd.description:
                item.setToolTip(cmd.description)
            self.command_list.addItem(item)

        if self.command_list.count() > 0:
            self.command_list.setCurrentRow(0)

    def activate(self):
        """Show and focus the command palette."""
        self.search_input.clear()
        self._filter_commands("")

        # Position near top center of parent
        if self.parent():
            parent_rect = self.parent().rect()
            x = (parent_rect.width() - self.width()) // 2
            y = 50
            self.move(self.parent().mapToGlobal(self.parent().rect().topLeft()) +
                     self.parent().rect().topLeft())
            self.move(x, y)

        self.show()
        self.search_input.setFocus()

    def update_theme(self, theme: Theme):
        """Update colors for new theme."""
        self.theme = theme


# =============================================================================
# NOTIFICATION SYSTEM
# =============================================================================

class NotificationToast(QFrame):
    """A single toast notification."""

    closed = pyqtSignal()

    def __init__(self, message: str, level: str, theme: Theme, duration: int = 3000, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.duration = duration

        self._setup_ui(message, level)
        self._setup_animation()

    def _setup_ui(self, message: str, level: str):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumWidth(300)
        self.setMaximumWidth(400)

        # Choose color based on level
        if level == "success":
            color = self.theme.success
            icon = "✓"
        elif level == "warning":
            color = self.theme.warning
            icon = "⚠"
        elif level == "error":
            color = self.theme.error
            icon = "✕"
        else:
            color = self.theme.text
            icon = "ℹ"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)

        # Icon
        icon_label = QLabel(icon)
        icon_label.setStyleSheet(f"color: {color}; font-size: 16px;")
        layout.addWidget(icon_label)

        # Message
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"color: {self.theme.text};")
        layout.addWidget(msg_label, stretch=1)

        # Style the frame
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {self.theme.surface};
                border: 1px solid {color};
                border-radius: 8px;
            }}
        """)

    def _setup_animation(self):
        """Setup fade in/out animations."""
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)

        # Fade in
        self.fade_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_in.setDuration(200)
        self.fade_in.setStartValue(0)
        self.fade_in.setEndValue(1)

        # Fade out
        self.fade_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out.setDuration(200)
        self.fade_out.setStartValue(1)
        self.fade_out.setEndValue(0)
        self.fade_out.finished.connect(self._on_fade_out_done)

        # Auto-close timer
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self._start_fade_out)

    def show_notification(self):
        """Show the notification with animation."""
        self.show()
        self.fade_in.start()
        self.close_timer.start(self.duration)

    def _start_fade_out(self):
        self.fade_out.start()

    def _on_fade_out_done(self):
        self.closed.emit()
        self.deleteLater()


class NotificationManager(QObject):
    """Manages toast notifications."""

    def __init__(self, parent_widget: QWidget):
        super().__init__()
        self.parent_widget = parent_widget
        self.theme = get_theme_manager().current
        self.active_toasts: List[NotificationToast] = []
        self.toast_spacing = 10
        self.margin_right = 20
        self.margin_top = 60

        # Connect to theme changes
        get_theme_manager().theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, theme: Theme):
        self.theme = theme

    def show(self, message: str, level: str = "info", duration: int = 3000):
        """Show a toast notification."""
        toast = NotificationToast(message, level, self.theme, duration, self.parent_widget)
        toast.closed.connect(lambda: self._on_toast_closed(toast))

        self.active_toasts.append(toast)
        self._position_toasts()
        toast.show_notification()

    def _on_toast_closed(self, toast: NotificationToast):
        """Handle toast closed."""
        if toast in self.active_toasts:
            self.active_toasts.remove(toast)
            self._position_toasts()

    def _position_toasts(self):
        """Position all active toasts."""
        if not self.parent_widget:
            return

        parent_rect = self.parent_widget.rect()
        y = self.margin_top

        for toast in self.active_toasts:
            toast.adjustSize()
            x = parent_rect.width() - toast.width() - self.margin_right

            # Convert to global position
            global_pos = self.parent_widget.mapToGlobal(self.parent_widget.rect().topLeft())
            toast.move(global_pos.x() + x, global_pos.y() + y)

            y += toast.height() + self.toast_spacing

    def success(self, message: str, duration: int = 3000):
        """Show a success notification."""
        self.show(message, "success", duration)

    def warning(self, message: str, duration: int = 3000):
        """Show a warning notification."""
        self.show(message, "warning", duration)

    def error(self, message: str, duration: int = 3000):
        """Show an error notification."""
        self.show(message, "error", duration)

    def info(self, message: str, duration: int = 3000):
        """Show an info notification."""
        self.show(message, "info", duration)


# =============================================================================
# DRAFT MANAGER
# =============================================================================

class DraftManager:
    """Manages auto-saving and restoring of message drafts."""

    def __init__(self, draft_path: Optional[Path] = None):
        if draft_path is None:
            from pathlib import Path
            import config
            draft_path = config.DATA_DIR / "draft.json"
        self.draft_path = draft_path
        self._auto_save_timer: Optional[QTimer] = None
        self._last_saved_text = ""

    def save_draft(self, text: str):
        """Save draft to disk."""
        if text == self._last_saved_text:
            return  # No change

        try:
            data = {
                "text": text,
                "timestamp": datetime.now().isoformat()
            }
            self.draft_path.parent.mkdir(parents=True, exist_ok=True)
            self.draft_path.write_text(json.dumps(data))
            self._last_saved_text = text
        except Exception:
            pass  # Silent fail for drafts

    def load_draft(self) -> str:
        """Load draft from disk."""
        try:
            if self.draft_path.exists():
                data = json.loads(self.draft_path.read_text())
                return data.get("text", "")
        except Exception:
            pass
        return ""

    def clear_draft(self):
        """Clear saved draft."""
        try:
            if self.draft_path.exists():
                self.draft_path.unlink()
            self._last_saved_text = ""
        except Exception:
            pass

    def setup_auto_save(self, text_widget: QTextEdit, interval_ms: int = 2000):
        """Setup auto-save timer for a text widget."""
        self._auto_save_timer = QTimer()
        self._auto_save_timer.timeout.connect(
            lambda: self.save_draft(text_widget.toPlainText())
        )
        self._auto_save_timer.start(interval_ms)

    def stop_auto_save(self):
        """Stop auto-save timer."""
        if self._auto_save_timer:
            self._auto_save_timer.stop()


# =============================================================================
# KEYBOARD SHORTCUT MANAGER
# =============================================================================

class KeyboardShortcutManager:
    """Manages keyboard shortcuts for the application."""

    def __init__(self, parent: QWidget):
        self.parent = parent
        self.shortcuts: Dict[str, QShortcut] = {}

    def register(self, key_sequence: str, callback: Callable, description: str = ""):
        """Register a keyboard shortcut."""
        shortcut = QShortcut(QKeySequence(key_sequence), self.parent)
        shortcut.activated.connect(callback)
        self.shortcuts[key_sequence] = shortcut
        return shortcut

    def unregister(self, key_sequence: str):
        """Unregister a keyboard shortcut."""
        if key_sequence in self.shortcuts:
            self.shortcuts[key_sequence].deleteLater()
            del self.shortcuts[key_sequence]

    def get_all(self) -> Dict[str, QShortcut]:
        """Get all registered shortcuts."""
        return self.shortcuts.copy()


# =============================================================================
# STATUS MANAGER
# =============================================================================

class StatusManager(QObject):
    """Manages granular status updates."""

    status_changed = pyqtSignal(str, str)  # status text, status type

    # Status types for styling
    STATUS_READY = "ready"
    STATUS_THINKING = "thinking"
    STATUS_TOOLS = "tools"
    STATUS_SEARCHING = "searching"
    STATUS_ERROR = "error"

    def __init__(self):
        super().__init__()
        self._current_status = "Ready"
        self._current_type = self.STATUS_READY

    def set_ready(self):
        """Set status to ready."""
        self._update("Ready", self.STATUS_READY)

    def set_thinking(self):
        """Set status to thinking."""
        self._update("Thinking...", self.STATUS_THINKING)

    def set_executing_tools(self, tool_name: str = ""):
        """Set status to executing tools."""
        if tool_name:
            self._update(f"Executing: {tool_name}...", self.STATUS_TOOLS)
        else:
            self._update("Executing tools...", self.STATUS_TOOLS)

    def set_searching_memories(self):
        """Set status to searching memories."""
        self._update("Searching memories...", self.STATUS_SEARCHING)

    def set_processing_pass(self, pass_num: int):
        """Set status to processing pass N."""
        self._update(f"Processing (pass {pass_num})...", self.STATUS_THINKING)

    def set_error(self, message: str):
        """Set error status."""
        self._update(f"Error: {message}", self.STATUS_ERROR)

    def set_custom(self, text: str, status_type: str = "ready"):
        """Set a custom status."""
        self._update(text, status_type)

    def _update(self, text: str, status_type: str):
        self._current_status = text
        self._current_type = status_type
        self.status_changed.emit(text, status_type)

    @property
    def current_status(self) -> str:
        return self._current_status

    @property
    def current_type(self) -> str:
        return self._current_type


# =============================================================================
# QUICK ACTIONS BAR
# =============================================================================

class QuickActionsBar(QFrame):
    """Bar with quick action buttons above the input field."""

    action_triggered = pyqtSignal(str)  # action id

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._actions: List[Dict[str, Any]] = []
        self._buttons: Dict[str, QPushButton] = {}
        self._setup_ui()

    def _setup_ui(self):
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(5, 3, 5, 3)
        self.layout.setSpacing(5)
        self.layout.addStretch()

    def add_action(self, action_id: str, label: str, tooltip: str = "", icon: str = ""):
        """Add a quick action button."""
        btn = QPushButton(f"{icon} {label}" if icon else label)
        btn.setToolTip(tooltip)
        btn.setMaximumHeight(24)
        btn.setFont(QFont("Segoe UI", 9))
        btn.clicked.connect(lambda: self.action_triggered.emit(action_id))

        # Insert before stretch
        self.layout.insertWidget(self.layout.count() - 1, btn)
        self._buttons[action_id] = btn
        self._actions.append({"id": action_id, "label": label, "tooltip": tooltip})

    def remove_action(self, action_id: str):
        """Remove a quick action button."""
        if action_id in self._buttons:
            self._buttons[action_id].deleteLater()
            del self._buttons[action_id]
            self._actions = [a for a in self._actions if a["id"] != action_id]

    def set_action_enabled(self, action_id: str, enabled: bool):
        """Enable or disable an action."""
        if action_id in self._buttons:
            self._buttons[action_id].setEnabled(enabled)

    def update_theme(self, theme: Theme):
        """Update colors for new theme."""
        self.theme = theme


# =============================================================================
# CANCEL BUTTON WIDGET
# =============================================================================

class CancelButton(QPushButton):
    """Cancel button that appears during processing."""

    def __init__(self, theme: Theme, parent=None):
        super().__init__("Cancel", parent)
        self.theme = theme
        self._setup_style()
        self.hide()  # Hidden by default

    def _setup_style(self):
        self.setFont(QFont("Segoe UI", 10))
        self.setMinimumWidth(70)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.error};
                color: white;
                border: none;
                border-radius: 12px;
                padding: 5px 12px;
            }}
            QPushButton:hover {{
                background-color: {self.theme.error};
                opacity: 0.8;
            }}
        """)

    def update_theme(self, theme: Theme):
        """Update colors for new theme."""
        self.theme = theme
        self._setup_style()
