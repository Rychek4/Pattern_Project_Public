"""
Pattern Project - PyQt5 Chat GUI
Version: 0.2.0

A visual chat interface with timestamps, session tracking,
system pulse countdown, and enhanced UX features.

Features:
- Light/dark theme support
- Full markdown rendering
- Draft persistence
- Command palette
- Keyboard shortcuts
- Toast notifications
- Image paste from clipboard
"""

import sys
import re
import html
import queue
import threading
import traceback
import uuid
from datetime import datetime, timedelta
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass

import config
from core.logger import log_info, log_error, log_warning

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTextBrowser, QTextEdit, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton, QLineEdit, QLabel, QDialog, QSlider, QCheckBox,
    QSpinBox, QMessageBox, QFrame, QSizePolicy, QComboBox, QScrollArea,
    QShortcut, QMenu, QAction
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QMimeData, QEvent
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette, QKeySequence, QClipboard, QImage

# Import new GUI components
from interface.gui_components import (
    Theme, DARK_THEME, LIGHT_THEME,
    ThemeManager, get_theme_manager,
    MarkdownRenderer, MessageData,
    CommandPalette, Command,
    NotificationManager, DraftManager,
    KeyboardShortcutManager, StatusManager,
    CancelButton
)

# Legacy color dict for backwards compatibility (maps from theme)
def get_colors_from_theme(theme: Theme) -> dict:
    """Convert theme to legacy COLORS dict."""
    return {
        "background": theme.background,
        "surface": theme.surface,
        "primary": theme.primary,
        "accent": theme.accent,
        "text": theme.text,
        "text_dim": theme.text_dim,
        "user": theme.user,
        "assistant": theme.assistant,
        "system": theme.system,
        "timestamp": theme.timestamp,
        "pulse": theme.pulse,
        "action": theme.action,
    }

# Initialize with dark theme
COLORS = get_colors_from_theme(DARK_THEME)


class MessageSignals(QObject):
    """Signals for thread-safe message passing to GUI."""
    new_message = pyqtSignal(str, str, str)  # role, content, timestamp
    update_status = pyqtSignal(str, str)  # status text, status type
    update_timer = pyqtSignal(str, str)  # session_time, total_time
    response_complete = pyqtSignal()
    pulse_interval_change = pyqtSignal(int)  # new interval in seconds
    show_notification = pyqtSignal(str, str)  # message, level (info/success/warning/error)
    tool_executing = pyqtSignal(str)  # tool name being executed


class ChatInputWidget(QTextEdit):
    """Multi-line chat input with Enter to send, Shift+Enter for newline.

    Features:
    - Auto-expands up to 5x single line height
    - Enter key sends message (emits send_requested signal)
    - Shift+Enter inserts a newline
    - Plain text only (no rich text)
    - Image paste from clipboard
    """

    send_requested = pyqtSignal()
    image_pasted = pyqtSignal(QImage)  # Emitted when image is pasted

    def __init__(self):
        super().__init__()
        self.setAcceptRichText(False)
        self.setPlaceholderText("Type a message... (Ctrl+V to paste images)")

        # Hide scroll bar for single-line mode, show only when needed for multi-line
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Calculate single line height for auto-expand limits
        # Account for: CSS padding (8px*2), border (1px*2), document margins (~8px)
        font_metrics = self.fontMetrics()
        self._single_line_height = font_metrics.lineSpacing() + 28  # Increased padding
        self._max_height = self._single_line_height * 5

        # Set initial size
        self.setMinimumHeight(self._single_line_height)
        self.setMaximumHeight(self._single_line_height)

        # Track pasted image
        self._pending_image: Optional[QImage] = None

        # Connect text changes to auto-resize
        self.textChanged.connect(self._auto_resize)

    def setFont(self, font: QFont):
        """Override to recalculate line height when font changes."""
        super().setFont(font)
        font_metrics = self.fontMetrics()
        self._single_line_height = font_metrics.lineSpacing() + 28  # Match __init__ padding
        self._max_height = self._single_line_height * 5
        self.setMinimumHeight(self._single_line_height)
        self._auto_resize()

    def _auto_resize(self):
        """Auto-resize based on content, up to max height."""
        doc = self.document()
        doc_height = doc.size().height() + 28  # Match padding from __init__

        # Clamp between single line and max
        new_height = max(self._single_line_height, min(int(doc_height), self._max_height))
        self.setMaximumHeight(new_height)

    def keyPressEvent(self, event):
        """Handle Enter vs Shift+Enter."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                # Shift+Enter: insert newline
                super().keyPressEvent(event)
            else:
                # Enter alone: send message
                self.send_requested.emit()
        else:
            super().keyPressEvent(event)

    def insertFromMimeData(self, source: QMimeData):
        """Handle paste - check for images."""
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage) and not image.isNull():
                self._pending_image = image
                self.image_pasted.emit(image)
                # Add indicator text
                cursor = self.textCursor()
                cursor.insertText("[Image attached] ")
                return
        # Fall back to text paste
        super().insertFromMimeData(source)

    def get_pending_image(self) -> Optional[QImage]:
        """Get and clear the pending pasted image."""
        img = self._pending_image
        self._pending_image = None
        return img

    def has_pending_image(self) -> bool:
        """Check if there's a pending pasted image."""
        return self._pending_image is not None

    def clear(self):
        """Clear and reset to single line height."""
        super().clear()
        self._pending_image = None
        self.setMaximumHeight(self._single_line_height)


class ChatWindow(QMainWindow):
    """
    Main chat window with:
    - Header: Session timer, controls, theme toggle
    - Chat display: Rich HTML with timestamps and markdown
    - Input: Text entry with send button and image paste
    - Command palette: All commands accessible via Ctrl+Shift+P
    - Keyboard shortcuts: Full navigation
    - Notifications: Toast alerts
    """

    def __init__(self):
        super().__init__()
        self.signals = MessageSignals()

        # Theme management
        self._theme_manager = get_theme_manager()
        self._theme = self._theme_manager.current
        self._markdown_renderer = MarkdownRenderer(self._theme)

        # Status management
        self._status_manager = StatusManager()

        # State
        self._session_start: Optional[datetime] = None
        self._first_session_start: Optional[datetime] = None
        self._is_processing = False
        self._cancel_requested = False  # Flag to cancel current request
        self._processing_thread: Optional[threading.Thread] = None
        self._message_queue = queue.Queue()
        self._is_first_message_of_session = True  # Track for next_session reminder triggers

        # Message storage for navigation
        self._messages: List[MessageData] = []

        # Backend references (set during initialization)
        self._conversation_mgr = None
        self._llm_router = None
        self._prompt_builder = None
        self._temporal_tracker = None
        self._system_pulse_timer = None
        self._reminder_scheduler = None
        self._telegram_listener = None

        self._setup_ui()
        self._setup_signals()
        self._setup_timers()
        self._setup_keyboard_shortcuts()
        self._setup_command_palette()
        self._setup_draft_manager()
        self._apply_style()

    def _setup_signals(self):
        """Connect signals to slots."""
        self.signals.new_message.connect(self._append_message)
        self.signals.update_status.connect(self._update_status_with_type)
        self.signals.update_timer.connect(self._update_timer_display)
        self.signals.response_complete.connect(self._on_response_complete)
        self.signals.pulse_interval_change.connect(self.set_pulse_interval_by_seconds)
        self.signals.show_notification.connect(self._show_notification)
        self.signals.tool_executing.connect(self._on_tool_executing)

        # Theme change signal
        self._theme_manager.theme_changed.connect(self._on_theme_changed)

        # Status manager signals
        self._status_manager.status_changed.connect(self._on_status_changed)

    def _setup_ui(self):
        """Create the UI layout."""
        self.setWindowTitle("Pattern Project")
        self.setMinimumSize(700, 500)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header frame
        header = self._create_header()
        layout.addWidget(header)


        # Chat display
        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(True)  # Enable clicking links
        self.chat_display.setFont(QFont("Consolas", 12))
        self.chat_display.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_display.customContextMenuRequested.connect(self._show_chat_context_menu)
        layout.addWidget(self.chat_display, stretch=1)


        # Input area with cancel button
        input_frame = self._create_input_area()
        layout.addWidget(input_frame)

        # Status bar with progress indicator
        status_frame = QFrame()
        status_frame.setFrameStyle(QFrame.NoFrame)
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(0, 0, 0, 0)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px;")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        # Cancel button (hidden by default)
        self.cancel_btn = CancelButton(self._theme, self)
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        status_layout.addWidget(self.cancel_btn)

        layout.addWidget(status_frame)

        # Notification manager
        self._notification_manager = NotificationManager(self)

        # Command palette (hidden by default)
        self._command_palette = CommandPalette(self._theme, self)

    def _create_header(self) -> QFrame:
        """Create the header with timer, pulse countdown, and controls."""
        header = QFrame()
        header.setFrameStyle(QFrame.StyledPanel)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(10, 5, 10, 5)

        # Session timer
        self.timer_label = QLabel("Session: --:--")
        self.timer_label.setFont(QFont("Consolas", 13, QFont.Bold))
        self.timer_label.setStyleSheet(f"color: {COLORS['text']};")
        layout.addWidget(self.timer_label)

        # Add spacing between session timer and pulse timer
        layout.addSpacing(30)

        # Pulse countdown (only if enabled)
        self.pulse_label = QLabel("Pulse: --:--")
        self.pulse_label.setFont(QFont("Consolas", 13, QFont.Bold))
        self.pulse_label.setStyleSheet(f"color: {COLORS['pulse']};")
        self.pulse_label.setToolTip("Time until next system pulse")
        if not config.SYSTEM_PULSE_ENABLED:
            self.pulse_label.hide()
        layout.addWidget(self.pulse_label)

        # Pulse interval dropdown
        self.pulse_dropdown = QComboBox()
        self.pulse_dropdown.setFont(QFont("Consolas", 11))
        self.pulse_dropdown.addItems(["3 min", "10 min", "30 min", "1 hour", "6 hours"])
        self.pulse_dropdown.setCurrentIndex(1)  # Default: 10 min
        self.pulse_dropdown.setToolTip("Set pulse timer interval")
        self.pulse_dropdown.currentIndexChanged.connect(self._on_pulse_interval_changed)
        if not config.SYSTEM_PULSE_ENABLED:
            self.pulse_dropdown.hide()
        layout.addWidget(self.pulse_dropdown)

        layout.addStretch()

        # Theme toggle button
        self.theme_btn = QPushButton("🌙")
        self.theme_btn.setToolTip("Toggle light/dark theme (Ctrl+T)")
        self.theme_btn.setMaximumWidth(40)
        self.theme_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self.theme_btn)

        # Command palette button
        self.palette_btn = QPushButton("⌘")
        self.palette_btn.setToolTip("Command palette (Ctrl+Shift+P)")
        self.palette_btn.setMaximumWidth(40)
        self.palette_btn.clicked.connect(self._show_command_palette)
        layout.addWidget(self.palette_btn)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self._show_settings)
        layout.addWidget(self.settings_btn)

        return header

    def _create_input_area(self) -> QFrame:
        """Create the input area with text field and send button."""
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)

        # Multi-line input with Enter to send, Shift+Enter for newline
        self.input_field = ChatInputWidget()
        self.input_field.setFont(QFont("Consolas", 12))
        self.input_field.send_requested.connect(self._send_message)
        layout.addWidget(self.input_field, stretch=1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setFont(QFont("Consolas", 11))
        self.send_btn.clicked.connect(self._send_message)
        self.send_btn.setMinimumWidth(80)
        layout.addWidget(self.send_btn)

        return frame

    def _setup_timers(self):
        """Setup update timers."""
        # Timer display update (every second)
        self.timer_update = QTimer(self)
        self.timer_update.timeout.connect(self._update_timer)
        self.timer_update.start(1000)

    def _apply_style(self):
        """Apply theme styling using theme manager."""
        self.setStyleSheet(self._theme_manager.get_stylesheet())

    def _setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts."""
        self._shortcut_manager = KeyboardShortcutManager(self)

        # Command palette
        self._shortcut_manager.register("Ctrl+Shift+P", self._show_command_palette, "Command palette")

        # Theme toggle
        self._shortcut_manager.register("Ctrl+T", self._toggle_theme, "Toggle theme")

        # Copy last message
        self._shortcut_manager.register("Ctrl+Shift+C", self._copy_last_message, "Copy last message")

        # Focus input
        self._shortcut_manager.register("Escape", self._focus_input, "Focus input")

        # Scroll to bottom
        self._shortcut_manager.register("Ctrl+End", self._scroll_to_bottom, "Scroll to bottom")

    def _setup_command_palette(self):
        """Setup command palette with available commands."""
        commands = [
            Command("toggle_theme", "Toggle Theme", "Ctrl+T", self._toggle_theme,
                   "Switch between light and dark themes"),
            Command("copy_last", "Copy Last Response", "Ctrl+Shift+C", self._copy_last_message,
                   "Copy the last AI response to clipboard"),
            Command("extract_memories", "Extract Memories", "", self._trigger_extraction,
                   "Force memory extraction now"),
            Command("scroll_bottom", "Scroll to Bottom", "Ctrl+End", self._scroll_to_bottom,
                   "Jump to latest messages"),
            Command("focus_input", "Focus Input", "Escape", self._focus_input,
                   "Move focus to message input"),
        ]
        self._command_palette.set_commands(commands)

    def _setup_draft_manager(self):
        """Setup draft persistence."""
        self._draft_manager = DraftManager()

        # Load any existing draft
        saved_draft = self._draft_manager.load_draft()
        if saved_draft:
            self.input_field.setPlainText(saved_draft)

        # Setup auto-save
        self._draft_manager.setup_auto_save(self.input_field)

    # =========================================================================
    # THEME HANDLING
    # =========================================================================

    def _toggle_theme(self):
        """Toggle between light and dark themes."""
        self._theme_manager.toggle()

    def _on_theme_changed(self, theme: Theme):
        """Handle theme change."""
        global COLORS
        self._theme = theme
        COLORS = get_colors_from_theme(theme)

        # Update theme button icon
        if theme.name == "dark":
            self.theme_btn.setText("🌙")
        else:
            self.theme_btn.setText("☀️")

        # Update markdown renderer
        self._markdown_renderer.update_theme(theme)

        # Re-apply stylesheet
        self._apply_style()

        # Update component themes
        self.cancel_btn.update_theme(theme)
        self._command_palette.update_theme(theme)

        # Notify user
        self._notification_manager.info(f"Switched to {theme.name} theme")

    def _trigger_extraction(self):
        """Trigger memory extraction."""
        try:
            from memory.extractor import get_memory_extractor
            extractor = get_memory_extractor()
            extractor.process_turns()
            self._notification_manager.success("Memory extraction completed")
        except Exception as e:
            self._notification_manager.error(f"Extraction failed: {e}")

    # =========================================================================
    # COMMAND PALETTE
    # =========================================================================

    def _show_command_palette(self):
        """Show the command palette."""
        # Position it centered near top
        palette_x = (self.width() - self._command_palette.width()) // 2
        palette_y = 80

        global_pos = self.mapToGlobal(self.rect().topLeft())
        self._command_palette.move(global_pos.x() + palette_x, global_pos.y() + palette_y)
        self._command_palette.show()
        self._command_palette.search_input.setFocus()

    # =========================================================================
    # CHAT CONTEXT MENU
    # =========================================================================

    def _show_chat_context_menu(self, position):
        """Show context menu for chat display."""
        menu = QMenu(self)

        # Copy selected text
        copy_action = QAction("Copy Selected", self)
        copy_action.triggered.connect(self._copy_selected_text)
        menu.addAction(copy_action)

        # Copy last message
        copy_last_action = QAction("Copy Last Response", self)
        copy_last_action.triggered.connect(self._copy_last_message)
        menu.addAction(copy_last_action)

        menu.exec_(self.chat_display.viewport().mapToGlobal(position))

    def _copy_selected_text(self):
        """Copy selected text to clipboard."""
        cursor = self.chat_display.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            QApplication.clipboard().setText(text)
            self._notification_manager.success("Copied to clipboard")

    def _copy_last_message(self):
        """Copy the last AI response to clipboard."""
        for msg in reversed(self._messages):
            if msg.role == "assistant":
                QApplication.clipboard().setText(msg.content)
                self._notification_manager.success("Last response copied")
                return
        self._notification_manager.warning("No AI response to copy")

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def _focus_input(self):
        """Focus the input field."""
        self.input_field.setFocus()

    def _scroll_to_bottom(self):
        """Scroll chat to bottom."""
        self.chat_display.moveCursor(QTextCursor.End)

    # =========================================================================
    # STATUS AND NOTIFICATION HANDLERS
    # =========================================================================

    def _update_status_with_type(self, text: str, status_type: str):
        """Update status bar with type-based styling."""
        if status_type == StatusManager.STATUS_ERROR:
            color = self._theme.error
        elif status_type == StatusManager.STATUS_THINKING:
            color = self._theme.pulse
        elif status_type == StatusManager.STATUS_TOOLS:
            color = self._theme.action
        else:
            color = self._theme.text_dim

        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 10px;")

    def _on_status_changed(self, text: str, status_type: str):
        """Handle status manager changes."""
        self.signals.update_status.emit(text, status_type)

    def _show_notification(self, message: str, level: str):
        """Show a toast notification."""
        if level == "success":
            self._notification_manager.success(message)
        elif level == "warning":
            self._notification_manager.warning(message)
        elif level == "error":
            self._notification_manager.error(message)
        else:
            self._notification_manager.info(message)

    def _on_tool_executing(self, tool_name: str):
        """Handle tool execution status."""
        self._status_manager.set_executing_tools(tool_name)

    # =========================================================================
    # CANCEL HANDLING
    # =========================================================================

    def _on_cancel_clicked(self):
        """Handle cancel button click."""
        self._cancel_requested = True
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Cancelling...")
        self._notification_manager.warning("Cancelling request...")

    def _show_cancel_button(self):
        """Show the cancel button."""
        self._cancel_requested = False
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel")
        self.cancel_btn.show()

    def _hide_cancel_button(self):
        """Hide the cancel button."""
        self.cancel_btn.hide()

    def set_backend(
        self,
        conversation_mgr,
        llm_router,
        prompt_builder,
        temporal_tracker,
        system_pulse_timer=None,
        reminder_scheduler=None,
        telegram_listener=None
    ):
        """Set backend references for communication."""
        self._conversation_mgr = conversation_mgr
        self._llm_router = llm_router
        self._prompt_builder = prompt_builder
        self._temporal_tracker = temporal_tracker
        self._system_pulse_timer = system_pulse_timer
        self._reminder_scheduler = reminder_scheduler
        self._telegram_listener = telegram_listener

        # Set up pulse callback if timer is provided
        if self._system_pulse_timer:
            self._system_pulse_timer.set_callback(self._on_pulse_fired)

        # Set up Telegram listener callback if provided
        if self._telegram_listener:
            self._telegram_listener.set_callback(self._on_telegram_message)

        # Set up reminder scheduler callback if provided
        if self._reminder_scheduler:
            self._reminder_scheduler.set_callback(self._on_reminder_fired)

        # Start session if not active
        if not temporal_tracker.is_session_active:
            temporal_tracker.start_session()

        self._session_start = datetime.now()
        self._first_session_start = datetime.now()

    def _format_duration(self, td: timedelta) -> str:
        """Format a timedelta as human-readable string."""
        total_seconds = int(td.total_seconds())

        if total_seconds < 3600:  # Less than 1 hour
            minutes = total_seconds // 60
            return f"{minutes}m"
        elif total_seconds < 86400:  # Less than 1 day
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"
        else:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            return f"{days}d {hours}h"

    def _update_timer(self):
        """Update the session timer and pulse countdown display."""
        if self._session_start is None:
            return

        session_duration = datetime.now() - self._session_start
        session_str = self._format_duration(session_duration)
        self.timer_label.setText(f"Session: {session_str}")

        # Update pulse countdown
        if self._system_pulse_timer and config.SYSTEM_PULSE_ENABLED:
            remaining = self._system_pulse_timer.get_seconds_remaining()
            minutes = remaining // 60
            seconds = remaining % 60
            pulse_str = f"{minutes}:{seconds:02d}"

            # Change color when paused or close to firing
            if self._system_pulse_timer.is_paused():
                self.pulse_label.setStyleSheet(f"color: {COLORS['text_dim']};")
                pulse_str = f"{pulse_str} (paused)"
            elif remaining <= 30:
                self.pulse_label.setStyleSheet(f"color: {COLORS['accent']};")
            else:
                self.pulse_label.setStyleSheet(f"color: {COLORS['pulse']};")

            self.pulse_label.setText(f"Pulse: {pulse_str}")

    def _on_pulse_interval_changed(self, index: int):
        """Handle pulse interval dropdown change."""
        # Map dropdown index to seconds
        interval_map = {
            0: 180,    # 3 min
            1: 600,    # 10 min
            2: 1800,   # 30 min
            3: 3600,   # 1 hour
            4: 21600,  # 6 hours
        }

        new_interval = interval_map.get(index, 600)

        if self._system_pulse_timer:
            old_interval = self._system_pulse_timer.pulse_interval
            self._system_pulse_timer.pulse_interval = new_interval
            self._system_pulse_timer.reset()

            # Log the change
            from prompt_builder.sources.system_pulse import get_interval_label
            old_label = get_interval_label(old_interval)
            new_label = get_interval_label(new_interval)
            log_info(f"Pulse timer changed: {old_label} -> {new_label}", prefix="⏱️")

    def _emit_pulse_interval_change(self, interval: int):
        """Emit pulse interval change signal with debug logging."""
        log_info(f"PULSE DEBUG: Emitting pulse_interval_change signal with {interval}s", prefix="🔍")
        self.signals.pulse_interval_change.emit(interval)
        log_info("PULSE DEBUG: Signal emitted", prefix="🔍")

    def set_pulse_interval_by_seconds(self, seconds: int):
        """Set the pulse interval and update dropdown to match.

        Used when AI changes the interval via [[PULSE:Xm]] command.
        """
        log_info(f"PULSE DEBUG: set_pulse_interval_by_seconds({seconds}) ENTRY", prefix="🔍")

        # Map seconds to dropdown index
        seconds_to_index = {
            180: 0,    # 3 min
            600: 1,    # 10 min
            1800: 2,   # 30 min
            3600: 3,   # 1 hour
            21600: 4,  # 6 hours
        }

        index = seconds_to_index.get(seconds)
        log_info(f"PULSE DEBUG: seconds={seconds} mapped to index={index}", prefix="🔍")

        if index is not None:
            # Block signals to avoid triggering _on_pulse_interval_changed twice
            log_info(f"PULSE DEBUG: Updating dropdown to index {index}", prefix="🔍")
            self.pulse_dropdown.blockSignals(True)
            self.pulse_dropdown.setCurrentIndex(index)
            self.pulse_dropdown.blockSignals(False)
            log_info(f"PULSE DEBUG: Dropdown updated, current index now: {self.pulse_dropdown.currentIndex()}", prefix="🔍")

            # Update the timer
            if self._system_pulse_timer:
                old_interval = self._system_pulse_timer.pulse_interval
                log_info(f"PULSE DEBUG: Updating timer: {old_interval}s -> {seconds}s", prefix="🔍")
                self._system_pulse_timer.pulse_interval = seconds
                self._system_pulse_timer.reset()
                log_info(f"PULSE DEBUG: Timer updated, pulse_interval now: {self._system_pulse_timer.pulse_interval}s", prefix="🔍")

                # Log the change
                from prompt_builder.sources.system_pulse import get_interval_label
                old_label = get_interval_label(old_interval)
                new_label = get_interval_label(seconds)
                log_info(f"AI adjusted pulse timer: {old_label} -> {new_label}", prefix="⏱️")
            else:
                log_warning("PULSE DEBUG: _system_pulse_timer is None!")
        else:
            log_warning(f"PULSE DEBUG: Invalid seconds value {seconds} - not in mapping!")

    def _get_timestamp(self) -> str:
        """Get current timestamp string."""
        return datetime.now().strftime("%H:%M:%S")

    def _format_bold(self, content: str) -> str:
        """Format **bold** text.

        Args:
            content: HTML-escaped content

        Returns:
            Content with **text** converted to <b>text</b>
        """
        pattern = r'\*\*([^*]+)\*\*'
        return re.sub(pattern, r'<b>\1</b>', content)

    def _format_italic(self, content: str) -> str:
        """Format _italic_ text using underscores.

        Args:
            content: HTML-escaped content

        Returns:
            Content with _text_ converted to <i>text</i>
        """
        # Match _text_ with word boundary awareness to avoid matching mid-word underscores
        pattern = r'(?<!\w)_([^_]+)_(?!\w)'
        return re.sub(pattern, r'<i>\1</i>', content)

    def _format_strikethrough(self, content: str) -> str:
        """Format ~~strikethrough~~ text.

        Args:
            content: HTML-escaped content

        Returns:
            Content with ~~text~~ converted to <s>text</s>
        """
        pattern = r'~~([^~]+)~~'
        return re.sub(pattern, r'<s>\1</s>', content)

    def _format_code_inline(self, content: str) -> str:
        """Format `code` text with monospace font and subtle background.

        Args:
            content: HTML-escaped content

        Returns:
            Content with `code` converted to styled spans
        """
        pattern = r'`([^`]+)`'
        code_bg = "#2d2d44"  # Subtle dark background
        code_style = (
            f"background-color:{code_bg}; "
            "padding: 2px 4px; "
            "border-radius: 3px; "
            "font-family: monospace;"
        )
        return re.sub(pattern, rf'<span style="{code_style}">\1</span>', content)

    def _format_action_text(self, content: str) -> str:
        """Format asterisk-wrapped action text with a different color.

        Converts *action text* to colored spans for AI messages.
        Ignores **bold** syntax (double asterisks).

        Args:
            content: HTML-escaped content (bold already processed)

        Returns:
            Content with *action* converted to colored spans
        """
        # Match *text* but not **text** (negative lookbehind/lookahead for asterisks)
        # Pattern: single * not preceded/followed by *, then non-* content, then closing *
        pattern = r'(?<!\*)\*(?!\*)([^*]+)\*(?!\*)'

        action_color = COLORS["action"]

        def replace_action(match):
            action_text = match.group(1)
            return f"<span style='color:{action_color};'>{action_text}</span>"

        return re.sub(pattern, replace_action, content)

    def _format_message_text(self, content: str, role: str) -> str:
        """Apply all text formatting to message content.

        Formatting is only applied to assistant messages.
        Order matters to prevent conflicts between patterns.

        Args:
            content: Raw message content
            role: Message role (user, assistant, system)

        Returns:
            HTML-formatted string ready for display
        """
        # HTML escape first to prevent injection
        text = html.escape(content)

        if role == "assistant":
            # Order matters:
            # 1. Code inline first - protects content in backticks from other formatting
            # 2. Bold before action text - ** matched before single *
            # 3. Italic (underscores) - no conflict with asterisks
            # 4. Strikethrough - unique ~~ delimiter
            # 5. Action text last - single * catches remaining
            # 6. Pulse commands - special [[PULSE:Xm]] syntax
            text = self._format_code_inline(text)
            text = self._format_bold(text)
            text = self._format_italic(text)
            text = self._format_strikethrough(text)
            text = self._format_action_text(text)
            text = self._format_pulse_command(text)

        # Convert newlines to HTML breaks for multi-line display
        text = text.replace('\n', '<br/>')

        return text

    def _parse_pulse_command(self, text: str) -> Optional[int]:
        """Parse [[PULSE:Xm]] command from response text.

        DEPRECATED (December 2025): This method is no longer used.
        Pulse interval changes are now handled via the native `set_pulse_interval`
        tool in the shared response helper. Kept for backwards compatibility
        with any code that might still reference it.

        Args:
            text: The AI response text

        Returns:
            Interval in seconds if command found, None otherwise
        """
        from prompt_builder.sources.system_pulse import PULSE_COMMAND_TO_SECONDS

        # Pattern: [[PULSE:3m]], [[PULSE:10m]], [[PULSE:30m]], [[PULSE:1h]], [[PULSE:6h]]
        pattern = r'\[\[PULSE:(3m|10m|30m|1h|6h)\]\]'
        match = re.search(pattern, text)

        if match:
            command = match.group(1)
            return PULSE_COMMAND_TO_SECONDS.get(command)

        return None

    def _format_pulse_command(self, content: str) -> str:
        """Format [[PULSE:Xm]] commands with purple color and emoji.

        NOTE: This is kept for display formatting of any legacy [[PULSE:Xm]]
        text that might appear in conversation history. The native tool
        doesn't produce this syntax.

        Args:
            content: HTML content (already escaped)

        Returns:
            HTML with pulse commands styled
        """
        # Pattern matches the escaped version of [[PULSE:Xm]]
        # In HTML-escaped text, brackets are still brackets
        pattern = r'\[\[PULSE:(3m|10m|30m|1h|6h)\]\]'

        pulse_color = COLORS["pulse"]

        def replace_pulse(match):
            full_match = match.group(0)
            return f"<span style='color:{pulse_color};'>⏱️ {full_match}</span>"

        return re.sub(pattern, replace_pulse, content)

    def _append_message(self, role: str, content: str, timestamp: str):
        """Append a message to the chat display."""
        # Store message for search
        msg_id = str(uuid.uuid4())
        msg_data = MessageData(
            id=msg_id,
            role=role,
            content=content,
            timestamp=timestamp
        )
        self._messages.append(msg_data)

        # Color based on role
        if role == "user":
            color = self._theme.user
            prefix = "You"
        elif role == "assistant":
            color = self._theme.assistant
            prefix = "AI"
        else:
            color = self._theme.system
            prefix = "System"

        # Format content with new markdown renderer (for assistant messages)
        # or simple HTML escape (for user/system)
        if role == "assistant":
            formatted_content = self._markdown_renderer.render(content, role)
        else:
            formatted_content = self._format_message_text(content, role)

        # Build HTML (using msg_html to avoid shadowing html module)
        msg_html = f"""
        <div style='margin-bottom: 10px;' data-msg-id='{msg_id}'>
            <span style='color:{self._theme.timestamp};'>[{timestamp}]</span>
            <span style='color:{color}; font-weight:bold;'>{prefix}:</span>
            <br/>
            <span style='color:{self._theme.text}; margin-left: 20px;'>{formatted_content}</span>
        </div>
        """

        self.chat_display.append(msg_html)
        self.chat_display.moveCursor(QTextCursor.End)

        # Trigger TTS for assistant messages if enabled
        if role == "assistant":
            self._trigger_tts(content)

    def _trigger_tts(self, text: str):
        """Trigger text-to-speech for the given text if TTS is enabled."""
        try:
            from core.user_settings import is_tts_enabled, get_tts_voice_id

            if not is_tts_enabled():
                log_info("TTS skipped - not enabled", prefix="🔊")
                return

            # Truncate text for logging
            preview = text[:50] + "..." if len(text) > 50 else text
            log_info(f"TTS triggered for: {preview}", prefix="🔊")

            # Run TTS in background thread to not block UI
            def play_tts_async():
                try:
                    from subprocess_mgmt.audio_player import play_tts
                    voice_id = get_tts_voice_id()
                    log_info(f"TTS sending to audio player (voice: {voice_id})", prefix="🔊")
                    result = play_tts(text, voice_id)
                    if result:
                        log_info("TTS request accepted by audio player", prefix="🔊")
                    else:
                        log_warning("TTS request rejected by audio player")
                except Exception as e:
                    log_warning(f"TTS playback error: {e}")

            tts_thread = threading.Thread(target=play_tts_async, daemon=True)
            tts_thread.start()

        except Exception as e:
            log_warning(f"TTS trigger error: {e}")

    def _send_message(self):
        """Handle sending a message."""
        text = self.input_field.toPlainText().strip()
        if not text or self._is_processing:
            return

        # Check for pasted image
        pasted_image = self.input_field.get_pending_image()

        self.input_field.clear()
        self._draft_manager.clear_draft()  # Clear saved draft
        self._is_processing = True
        self.send_btn.setEnabled(False)
        self._status_manager.set_thinking()
        self._show_cancel_button()

        # Reset and pause the pulse timer (user is active)
        if self._system_pulse_timer:
            self._system_pulse_timer.reset()
            self._system_pulse_timer.pause()

        # Pause Telegram listener during processing to prevent message loss
        if self._telegram_listener:
            self._telegram_listener.pause()

        # Add user message to display immediately
        timestamp = self._get_timestamp()
        display_text = text
        if pasted_image:
            display_text = f"[Image] {text}" if text else "[Image attached]"
        self.signals.new_message.emit("user", display_text, timestamp)

        # Process in background thread
        self._processing_thread = threading.Thread(
            target=self._process_message,
            args=(text, pasted_image),
            daemon=True
        )
        self._processing_thread.start()

    def _capture_visuals_for_message(self, text_content: str) -> dict:
        """
        Capture visual content and build a multimodal message if enabled.

        Captures sources configured for "auto" mode and returns a message dict
        with multimodal content array. Sources in "on_demand" mode are NOT
        captured here - they are captured via tool calls instead.

        Args:
            text_content: The text content for the message

        Returns:
            Message dict suitable for LLM API (text-only or multimodal)
        """
        # Check if visual capture is enabled
        if not config.VISUAL_ENABLED:
            return {"role": "user", "content": text_content}

        # Check if any visual source is in auto mode
        has_auto_visuals = (
            config.VISUAL_SCREENSHOT_MODE == "auto" or
            config.VISUAL_WEBCAM_MODE == "auto"
        )
        if not has_auto_visuals:
            return {"role": "user", "content": text_content}

        try:
            from agency.visual_capture import capture_all_visuals, build_multimodal_content

            # Capture all enabled visual sources
            images = capture_all_visuals()

            if not images:
                # No images captured (failed or disabled), use text-only
                return {"role": "user", "content": text_content}

            # Build multimodal content array
            content_array = build_multimodal_content(text_content, images)

            log_info(
                f"Built multimodal message with {len(images)} image(s)",
                prefix="👁️"
            )

            return {"role": "user", "content": content_array}

        except Exception as e:
            log_error(f"Visual capture error, falling back to text-only: {e}")
            return {"role": "user", "content": text_content}

    def _build_continuation_message(self, prompt_text: str, images=None) -> dict:
        """
        Build a continuation message, optionally with images from commands.

        Args:
            prompt_text: The continuation prompt text
            images: Optional list of ImageContent from command results

        Returns:
            Message dict (text-only or multimodal)
        """
        if not images:
            return {"role": "user", "content": prompt_text}

        try:
            from agency.visual_capture import build_multimodal_content

            content_array = build_multimodal_content(prompt_text, images)

            log_info(
                f"Built multimodal continuation with {len(images)} image(s)",
                prefix="🖼️"
            )

            return {"role": "user", "content": content_array}

        except Exception as e:
            log_error(f"Failed to build multimodal continuation: {e}")
            return {"role": "user", "content": prompt_text}

    def _build_telegram_image_message(self, text: str, image) -> dict:
        """
        Build a multimodal message from a Telegram photo attachment.

        This is used when processing Telegram messages that include user-sent
        images. Unlike _capture_visuals_for_message() which captures local
        screen/webcam, this uses an image the user explicitly sent via Telegram.

        Args:
            text: The message text (or caption)
            image: ImageContent object from Telegram photo processing

        Returns:
            Message dict with multimodal content array
        """
        try:
            from agency.visual_capture import build_multimodal_content

            content_array = build_multimodal_content(text, [image])

            log_info(
                f"Built Telegram image message (source: {image.source_type})",
                prefix="📷"
            )

            return {"role": "user", "content": content_array}

        except Exception as e:
            log_error(f"Failed to build Telegram image message: {e}")
            # Fallback to text-only
            return {"role": "user", "content": text}

    def _build_message_with_pasted_image(self, text: str, image: QImage) -> dict:
        """
        Build a multimodal message from a pasted QImage.

        Converts the QImage to base64 and includes it in the message.

        Args:
            text: The message text
            image: QImage pasted from clipboard

        Returns:
            Message dict with multimodal content array
        """
        try:
            import base64
            from io import BytesIO
            from PIL import Image as PILImage
            from agency.visual_capture import ImageContent, build_multimodal_content

            # Convert QImage to PIL Image
            buffer = image.bits()
            buffer.setsize(image.byteCount())

            # Get image dimensions and format
            width = image.width()
            height = image.height()

            # Create PIL image from QImage data
            if image.format() == QImage.Format_RGB32 or image.format() == QImage.Format_ARGB32:
                pil_image = PILImage.frombytes("RGBA", (width, height), bytes(buffer), "raw", "BGRA")
            else:
                # Convert to a standard format first
                converted = image.convertToFormat(QImage.Format_ARGB32)
                buffer = converted.bits()
                buffer.setsize(converted.byteCount())
                pil_image = PILImage.frombytes("RGBA", (width, height), bytes(buffer), "raw", "BGRA")

            # Convert to RGB (remove alpha)
            pil_image = pil_image.convert("RGB")

            # Resize if too large
            max_dim = 1024
            if pil_image.width > max_dim or pil_image.height > max_dim:
                pil_image.thumbnail((max_dim, max_dim), PILImage.Resampling.LANCZOS)

            # Convert to base64
            buffer_io = BytesIO()
            pil_image.save(buffer_io, format="JPEG", quality=85)
            image_bytes = buffer_io.getvalue()
            base64_data = base64.standard_b64encode(image_bytes).decode("utf-8")

            # Create ImageContent
            img_content = ImageContent(
                data=base64_data,
                media_type="image/jpeg",
                source_type="clipboard"
            )

            content_array = build_multimodal_content(text, [img_content])

            log_info("Built multimodal message from pasted image", prefix="📋")

            return {"role": "user", "content": content_array}

        except Exception as e:
            log_error(f"Failed to build pasted image message: {e}")
            # Fallback to text-only
            return {"role": "user", "content": text}

    def _process_message(self, user_input: str, pasted_image: Optional[QImage] = None):
        """Process a message in background thread."""
        import time

        try:
            # Check for cancellation early
            if self._cancel_requested:
                self.signals.show_notification.emit("Request cancelled", "warning")
                return

            # Build prompt (no base prompt - emergent personality from context)
            # Pass is_session_start flag to trigger next_session reminders on first message
            assembled = self._prompt_builder.build(
                user_input=user_input,
                system_prompt="",
                additional_context={"is_session_start": self._is_first_message_of_session}
            )
            self._is_first_message_of_session = False  # Only first message triggers session start

            # Emit prompt assembly to dev window
            if config.DEV_MODE_ENABLED:
                from interface.dev_window import emit_prompt_assembly
                blocks_data = [
                    {
                        "source_name": block.source_name,
                        "priority": block.priority,
                        "content": block.content,
                        "metadata": block.metadata
                    }
                    for block in assembled.context_blocks
                ]
                total_tokens = len(assembled.full_system_prompt) // 4  # Rough estimate
                emit_prompt_assembly(blocks_data, total_tokens)

            # Get conversation history BEFORE storing the new turn
            # This prevents duplication when we append the user message below
            history = self._conversation_mgr.get_recent_history(limit=30)

            # Store user message for persistence (after getting history)
            if self._conversation_mgr:
                self._conversation_mgr.add_turn(
                    role="user",
                    content=user_input,
                    input_type="text"
                )

            # Capture visuals and build multimodal message if in auto mode
            # This adds the current user input with any captured images
            # If a pasted image was provided, include it
            if pasted_image and not pasted_image.isNull():
                user_message = self._build_message_with_pasted_image(user_input, pasted_image)
            else:
                user_message = self._capture_visuals_for_message(user_input)
            history.append(user_message)

            # Get LLM response with native tool use
            from llm.router import TaskType
            from agency.tools import get_tool_definitions, process_with_tools

            tools = get_tool_definitions()

            start_time = time.time()
            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools
            )
            pass1_duration = (time.time() - start_time) * 1000

            if response.success:
                max_passes = getattr(config, 'COMMAND_MAX_PASSES', 3)

                # Set up dev window callbacks for tool/response tracking
                dev_callbacks = None
                if config.DEV_MODE_ENABLED:
                    from interface.dev_window import emit_response_pass, emit_command_executed
                    dev_callbacks = {
                        "emit_response_pass": emit_response_pass,
                        "emit_command_executed": emit_command_executed
                    }

                # Use shared helper to process response with native tools
                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=max_passes,
                    pulse_callback=lambda interval: self._emit_pulse_interval_change(interval),
                    tools=tools,
                    dev_mode_callbacks=dev_callbacks
                )

                final_text = result.final_text

                # Store response
                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=final_text,
                    input_type="text"
                )

                # Emit to GUI
                timestamp = self._get_timestamp()
                self.signals.new_message.emit("assistant", final_text, timestamp)
            else:
                self.signals.update_status.emit(f"Error: {response.error}", StatusManager.STATUS_ERROR)

        except Exception as e:
            error_msg = f"Message processing error: {str(e)}"
            tb = traceback.format_exc()
            log_error(f"Exception in _process_message: {error_msg}")
            log_error(f"Traceback:\n{tb}")
            self.signals.update_status.emit(f"Error: {str(e)}", StatusManager.STATUS_ERROR)

        finally:
            self.signals.response_complete.emit()

    def _process_native_tools_response(
        self,
        response,
        history: list,
        system_prompt: str,
        tools: list,
        max_passes: int,
        pass1_duration: float
    ) -> str:
        """
        Process response using native tool use.

        DEPRECATED (December 2025): This method is no longer called.
        Use `process_with_tools` from agency.tools instead.
        The shared helper provides consistent processing across all entry points.
        Kept for reference during migration period.

        Args:
            response: Initial LLMResponse
            history: Conversation history
            system_prompt: System prompt for continuations
            tools: Tool definitions list
            max_passes: Maximum tool execution passes
            pass1_duration: Duration of first API call

        Returns:
            Final response text
        """
        import time
        from llm.router import TaskType
        from agency.tools import get_tool_processor

        processor = get_tool_processor()
        current_response = response
        current_history = history.copy()
        current_duration = pass1_duration

        for pass_num in range(1, max_passes + 1):
            # Process response for tool calls
            processed = processor.process(current_response, context={})

            # Emit to dev window
            if config.DEV_MODE_ENABLED:
                from interface.dev_window import emit_response_pass, emit_command_executed
                tool_names = [tc.name for tc in current_response.tool_calls] if current_response.has_tool_calls() else []
                emit_response_pass(
                    pass_number=pass_num,
                    provider=response.provider.value if pass_num == 1 else "continuation",
                    response_text=current_response.text,
                    tokens_in=getattr(current_response, 'tokens_in', 0) if pass_num == 1 else 0,
                    tokens_out=getattr(current_response, 'tokens_out', 0) if pass_num == 1 else 0,
                    duration_ms=current_duration,
                    commands_detected=tool_names,
                    web_searches_used=getattr(current_response, 'web_searches_used', 0) if pass_num == 1 else 0,
                    citations=getattr(current_response, 'citations', []) if pass_num == 1 else []
                )

                # Emit each tool execution
                for result in processed.tool_results:
                    emit_command_executed(
                        command_name=result.tool_name,
                        query=str(result.content)[:100] if result.content else "",
                        result_data=result.content,
                        error=str(result.content) if result.is_error else None,
                        needs_continuation=True
                    )

            # If no continuation needed (no tool calls or stop_reason != "tool_use")
            if not processed.needs_continuation:
                return processed.display_text

            # Show status
            if pass_num == 1:
                self.signals.update_status.emit("Executing tools...", StatusManager.STATUS_TOOLS)
            else:
                self.signals.update_status.emit(f"Executing tools (pass {pass_num})...", StatusManager.STATUS_TOOLS)

            # Build continuation: add assistant message with raw content blocks
            current_history.append({
                "role": "assistant",
                "content": current_response.raw_content
            })

            # Add tool results message
            current_history.append(processed.tool_result_message)

            # Get next response
            cont_start = time.time()
            continuation = self._llm_router.chat(
                messages=current_history,
                system_prompt=system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools
            )
            current_duration = (time.time() - cont_start) * 1000

            if not continuation.success:
                # On failure, return last text
                return processed.display_text

            # Check for pulse commands in continuation
            pulse_interval = self._parse_pulse_command(continuation.text)
            if pulse_interval is not None:
                self.signals.pulse_interval_change.emit(pulse_interval)

            current_response = continuation

        # Hit max passes - return final text
        return current_response.text

    def _process_legacy_commands_response(
        self,
        response,
        history: list,
        system_prompt: str,
        max_passes: int,
        pass1_duration: float
    ) -> str:
        """
        Process response using legacy [[COMMAND]] pattern.

        DEPRECATED (December 2025): This method is no longer called.
        The legacy [[COMMAND]] syntax has been replaced by native tool use.
        Use `process_with_tools` from agency.tools instead.
        Kept for reference during migration period.

        Args:
            response: Initial LLMResponse
            history: Conversation history
            system_prompt: System prompt for continuations
            max_passes: Maximum command execution passes
            pass1_duration: Duration of first API call

        Returns:
            Final response text
        """
        import time
        from llm.router import TaskType
        from agency.commands import get_command_processor

        processor = get_command_processor()
        current_text = response.text
        current_history = history.copy()
        current_duration = pass1_duration
        pass_num = 1

        while pass_num <= max_passes:
            # Process current response for commands
            processed = processor.process(current_text)

            # Extract detected command names for dev window
            commands_detected = [cmd.command_name for cmd in processed.commands_executed]

            # Emit response pass to dev window
            if config.DEV_MODE_ENABLED:
                from interface.dev_window import emit_response_pass, emit_command_executed
                emit_response_pass(
                    pass_number=pass_num,
                    provider=response.provider.value if pass_num == 1 else "continuation",
                    response_text=current_text,
                    tokens_in=getattr(response, 'tokens_in', 0) if pass_num == 1 else 0,
                    tokens_out=getattr(response, 'tokens_out', 0) if pass_num == 1 else 0,
                    duration_ms=current_duration,
                    commands_detected=commands_detected,
                    web_searches_used=getattr(response, 'web_searches_used', 0) if pass_num == 1 else 0,
                    citations=getattr(response, 'citations', []) if pass_num == 1 else []
                )

                # Emit each command execution
                for cmd_result in processed.commands_executed:
                    emit_command_executed(
                        command_name=cmd_result.command_name,
                        query=cmd_result.query,
                        result_data=cmd_result.data,
                        error=str(cmd_result.error) if cmd_result.error else None,
                        needs_continuation=cmd_result.needs_continuation
                    )

            # If no continuation needed, we're done
            if not processed.needs_continuation:
                return processed.display_text

            # Show status for command execution
            if pass_num == 1:
                self.signals.update_status.emit("Executing command...", StatusManager.STATUS_TOOLS)
            else:
                self.signals.update_status.emit(f"Executing command (pass {pass_num})...", StatusManager.STATUS_TOOLS)

            # Build continuation history with potential images from commands
            current_history.append({"role": "assistant", "content": current_text})

            # Build continuation message (may include images from visual commands)
            continuation_msg = self._build_continuation_message(
                processed.continuation_prompt,
                processed.continuation_images
            )
            current_history.append(continuation_msg)

            # Get next response
            cont_start = time.time()
            continuation = self._llm_router.chat(
                messages=current_history,
                system_prompt=system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7
            )
            current_duration = (time.time() - cont_start) * 1000

            if not continuation.success:
                # On failure, use last successful response
                return processed.display_text

            # Check continuation for pulse commands
            pulse_interval = self._parse_pulse_command(continuation.text)
            if pulse_interval is not None:
                self.signals.pulse_interval_change.emit(pulse_interval)

            # Prepare for next iteration
            current_text = continuation.text
            pass_num += 1

        # Hit max passes - use final response as-is
        processed = processor.process(current_text)

        # Emit final pass to dev window
        if config.DEV_MODE_ENABLED:
            from interface.dev_window import emit_response_pass
            emit_response_pass(
                pass_number=pass_num,
                provider="max_passes_reached",
                response_text=current_text,
                duration_ms=current_duration,
                commands_detected=[cmd.command_name for cmd in processed.commands_executed],
                web_searches_used=0,
                citations=[]
            )

        return processed.display_text

    def _on_response_complete(self):
        """Called when response processing is complete."""
        self._is_processing = False
        self._cancel_requested = False
        self._processing_thread = None
        self.send_btn.setEnabled(True)
        self._status_manager.set_ready()
        self._hide_cancel_button()

        # Resume the pulse timer
        if self._system_pulse_timer:
            self._system_pulse_timer.resume()

        # Resume the Telegram listener
        if self._telegram_listener:
            self._telegram_listener.resume()

    def _on_telegram_message(self, message):
        """Called when a Telegram message is received (from background thread)."""
        log_info(f"Telegram message received: {message.text[:50]}...", prefix="📱")

        # Don't process if already handling something
        if self._is_processing:
            log_warning("Skipping Telegram message - already processing")
            return

        # Process in background thread
        thread = threading.Thread(
            target=self._process_telegram_message,
            args=(message,),
            daemon=True
        )
        thread.start()

    def _process_telegram_message(self, message):
        """
        Process an inbound Telegram message and generate AI response using native tools.

        IMPORTANT: Visual capture (screenshot/webcam) is intentionally NOT used
        for Telegram messages. The user is interacting remotely, so capturing
        the local screen or webcam would not be relevant to their context.

        Instead, we only process images that the user explicitly sends via
        Telegram as attachments. These are handled by the InboundMessage.image
        field populated by the telegram_listener.
        """
        from llm.router import TaskType
        from agency.tools import get_tool_definitions, process_with_tools
        import config

        self._is_processing = True
        self.signals.update_status.emit("Processing Telegram message...", StatusManager.STATUS_THINKING)

        try:
            # Pause timers during processing
            if self._system_pulse_timer:
                self._system_pulse_timer.pause()
            if self._telegram_listener:
                self._telegram_listener.pause()

            # Store the message as user input
            from_info = f" from {message.from_user}" if message.from_user else ""
            self._conversation_mgr.add_turn(
                role="user",
                content=message.text,
                input_type="telegram"
            )

            # Display in GUI (indicate if image was attached)
            timestamp = self._get_timestamp()
            image_indicator = " 🖼️" if message.image else ""
            display_text = f"📱 Telegram{from_info}{image_indicator}: {message.text}"
            self.signals.new_message.emit("user", display_text, timestamp)

            # Build prompt
            assembled = self._prompt_builder.build(
                user_input=message.text,
                system_prompt=""
            )

            # Get conversation history
            history = self._conversation_mgr.get_recent_history(limit=30)

            # Build user message - include Telegram image if present
            # NOTE: We do NOT capture local screen/webcam for Telegram (see docstring)
            if message.image:
                # Build multimodal message with Telegram-sent image
                user_message = self._build_telegram_image_message(
                    message.text,
                    message.image
                )
                log_info("Telegram message includes user-sent image", prefix="📷")
            else:
                # Text-only message
                user_message = {"role": "user", "content": message.text}

            history.append(user_message)

            # Get tool definitions for native tool use
            tools = get_tool_definitions()

            # Get response from LLM WITH tools enabled
            self.signals.update_status.emit("Responding to Telegram...", StatusManager.STATUS_THINKING)
            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools  # Enable native tools for Telegram responses
            )

            if response.success:
                # Set up dev window callbacks for tool/response tracking
                dev_callbacks = None
                if config.DEV_MODE_ENABLED:
                    from interface.dev_window import emit_response_pass, emit_command_executed
                    dev_callbacks = {
                        "emit_response_pass": emit_response_pass,
                        "emit_command_executed": emit_command_executed
                    }

                # Use shared helper to process response with native tools
                # The helper tracks telegram_sent to avoid duplicate sends
                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=5,
                    pulse_callback=lambda interval: self._emit_pulse_interval_change(interval),
                    tools=tools,
                    dev_mode_callbacks=dev_callbacks
                )

                final_text = result.final_text
                telegram_sent = result.telegram_sent

                # Store response
                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=final_text,
                    input_type="text"
                )

                # Emit to GUI
                timestamp = self._get_timestamp()
                self.signals.new_message.emit("assistant", f"📱 {final_text}", timestamp)

                # Send response back to Telegram (only if not already sent via tool)
                if config.TELEGRAM_ENABLED and not telegram_sent:
                    try:
                        from communication.telegram_gateway import get_telegram_gateway
                        gateway = get_telegram_gateway()
                        if gateway.is_available():
                            gateway.send(final_text)
                            log_info("Telegram response sent successfully", prefix="📱")
                        else:
                            log_warning("Telegram gateway not available for response")
                    except Exception as e:
                        log_warning(f"Failed to send response to Telegram: {e}")
            else:
                self.signals.update_status.emit(f"Error: {response.error}", StatusManager.STATUS_ERROR)
                log_error(f"Telegram response error: {response.error}")

        except Exception as e:
            error_msg = f"Telegram message processing error: {str(e)}"
            tb = traceback.format_exc()
            log_error(f"Exception in _process_telegram_message: {error_msg}")
            log_error(f"Traceback:\n{tb}")
            self.signals.update_status.emit(f"Error: {str(e)}", StatusManager.STATUS_ERROR)

        finally:
            self.signals.response_complete.emit()

    def _on_pulse_fired(self):
        """Called when the system pulse timer fires."""
        log_info("PULSE DEBUG: _on_pulse_fired() callback triggered", prefix="🔍")

        # Don't fire if already processing a message
        if self._is_processing:
            log_warning("PULSE DEBUG: Skipping pulse - already processing (_is_processing=True)")
            return

        log_info("PULSE DEBUG: Starting pulse processing thread...", prefix="🔍")

        # Process the pulse in a background thread
        thread = threading.Thread(
            target=self._process_pulse,
            daemon=True
        )
        thread.start()
        log_info(f"PULSE DEBUG: Pulse thread started (thread={thread.name})", prefix="🔍")

    def _process_pulse(self):
        """Process a system pulse in background thread using native tools."""
        from agency.system_pulse import get_pulse_prompt, PULSE_STORED_MESSAGE
        from agency.tools import get_tool_definitions, process_with_tools
        from prompt_builder.sources.system_pulse import get_interval_label

        # Get dynamic pulse prompt with current interval
        current_interval = self._system_pulse_timer.pulse_interval if self._system_pulse_timer else 600
        interval_label = get_interval_label(current_interval)
        pulse_prompt = get_pulse_prompt(interval_label)

        log_info("=== PULSE: Starting _process_pulse() ===", prefix="⏱️")

        try:
            self._is_processing = True

            # Pause timer during processing
            if self._system_pulse_timer:
                self._system_pulse_timer.pause()

            # Pause Telegram listener during processing to prevent message loss
            if self._telegram_listener:
                self._telegram_listener.pause()

            # Update UI status
            self.signals.update_status.emit("System pulse...", StatusManager.STATUS_THINKING)

            # Show system message in chat
            timestamp = self._get_timestamp()
            self.signals.new_message.emit("system", PULSE_STORED_MESSAGE, timestamp)

            # Store abbreviated pulse message in conversation history
            if self._conversation_mgr:
                self._conversation_mgr.add_turn(
                    role="system",
                    content=PULSE_STORED_MESSAGE,
                    input_type="system"
                )
            else:
                log_error("PULSE: _conversation_mgr is None!")

            # Build prompt with full pulse message
            # Mark as pulse so CuriositySource can provide directive context
            assembled = self._prompt_builder.build(
                user_input=pulse_prompt,
                system_prompt="",
                additional_context={"is_pulse": True}
            )

            # Get conversation history
            history = self._conversation_mgr.get_recent_history(limit=30)

            # Add the pulse prompt as the message to respond to
            # (role="user" is an API constraint, but content clarifies it's automated)
            # Capture visuals for the pulse message (same as user messages in auto mode)
            pulse_message = self._capture_visuals_for_message(pulse_prompt)
            history.append(pulse_message)

            # Get tool definitions for native tool use
            tools = get_tool_definitions()

            # Get LLM response WITH tools enabled
            from llm.router import TaskType

            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools  # Enable native tools for pulse responses
            )

            log_info(f"PULSE: Router returned, success={response.success}", prefix="⏱️")

            if response.success:
                # Set up dev window callbacks for tool/response tracking
                dev_callbacks = None
                if config.DEV_MODE_ENABLED:
                    from interface.dev_window import emit_response_pass, emit_command_executed
                    dev_callbacks = {
                        "emit_response_pass": emit_response_pass,
                        "emit_command_executed": emit_command_executed
                    }

                # Use shared helper to process response with native tools
                # The helper handles multi-pass tool execution and pulse interval changes
                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=5,
                    pulse_callback=lambda interval: self._emit_pulse_interval_change(interval),
                    tools=tools,
                    dev_mode_callbacks=dev_callbacks
                )

                final_text = result.final_text
                log_info(f"PULSE: Processed in {result.passes_executed} pass(es)", prefix="⏱️")

                # Store response
                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=final_text,
                    input_type="text"
                )

                # Emit to GUI
                timestamp = self._get_timestamp()
                self.signals.new_message.emit("assistant", final_text, timestamp)
            else:
                error_msg = f"Pulse API error: {response.error}"
                log_error(f"PULSE: API call failed - {error_msg}")

                # Show error in CHAT (not just status bar) so it's visible
                timestamp = self._get_timestamp()
                self.signals.new_message.emit("system", f"[Pulse Error: {response.error}]", timestamp)
                self.signals.update_status.emit(error_msg, StatusManager.STATUS_ERROR)

        except Exception as e:
            error_msg = f"Pulse exception: {str(e)}"
            tb = traceback.format_exc()
            log_error(f"PULSE: Exception - {error_msg}")
            log_error(f"PULSE: Traceback:\n{tb}")

            # Show error in CHAT (not just status bar) so it's visible
            timestamp = self._get_timestamp()
            self.signals.new_message.emit("system", f"[Pulse Exception: {str(e)}]", timestamp)
            self.signals.update_status.emit(error_msg, StatusManager.STATUS_ERROR)

        finally:
            log_info("=== PULSE: _process_pulse() completing ===", prefix="⏱️")
            self.signals.response_complete.emit()

    def _on_reminder_fired(self, triggered_intentions):
        """Called when the reminder scheduler detects due intentions."""
        from agency.intentions import Intention
        log_info(f"REMINDER DEBUG: _on_reminder_fired() callback triggered with {len(triggered_intentions)} intention(s)", prefix="⏰")

        # Don't fire if already processing a message
        if self._is_processing:
            log_warning("REMINDER DEBUG: Skipping reminder pulse - already processing")
            return

        log_info("REMINDER DEBUG: Starting reminder processing thread...", prefix="⏰")

        # Process the reminder pulse in a background thread
        thread = threading.Thread(
            target=self._process_reminder_pulse,
            args=(triggered_intentions,),
            daemon=True
        )
        thread.start()

    def _process_reminder_pulse(self, triggered_intentions):
        """Process a reminder pulse in background thread using native tools."""
        from agency.intentions import get_reminder_pulse_prompt
        from agency.tools import get_tool_definitions, process_with_tools

        # Generate reminder-specific pulse prompt
        reminder_prompt = get_reminder_pulse_prompt(triggered_intentions)

        # Format stored message to indicate it's a reminder pulse
        stored_message = "[Reminder Pulse]"

        log_info("=== REMINDER: Starting _process_reminder_pulse() ===", prefix="⏰")

        try:
            self._is_processing = True

            # Pause idle timer during processing (so we don't double-fire)
            if self._system_pulse_timer:
                self._system_pulse_timer.pause()

            # Pause Telegram listener during processing to prevent message loss
            if self._telegram_listener:
                self._telegram_listener.pause()

            # Update UI status
            self.signals.update_status.emit("Reminder triggered...", StatusManager.STATUS_THINKING)

            # Show system message in chat
            timestamp = self._get_timestamp()
            self.signals.new_message.emit("system", stored_message, timestamp)

            # Store abbreviated message in conversation history
            if self._conversation_mgr:
                self._conversation_mgr.add_turn(
                    role="system",
                    content=stored_message,
                    input_type="system"
                )

            # Build prompt with reminder message
            assembled = self._prompt_builder.build(
                user_input=reminder_prompt,
                system_prompt=""
            )

            # Get conversation history
            history = self._conversation_mgr.get_recent_history(limit=30)

            # Add the reminder prompt as the message to respond to
            history.append({"role": "user", "content": reminder_prompt})

            # Get tool definitions for native tool use
            tools = get_tool_definitions()

            # Get LLM response WITH tools enabled
            from llm.router import TaskType

            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools  # Enable native tools for reminder responses
            )

            if response.success:
                # Set up dev window callbacks for tool/response tracking
                dev_callbacks = None
                if config.DEV_MODE_ENABLED:
                    from interface.dev_window import emit_response_pass, emit_command_executed
                    dev_callbacks = {
                        "emit_response_pass": emit_response_pass,
                        "emit_command_executed": emit_command_executed
                    }

                # Use shared helper to process response with native tools
                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=5,
                    pulse_callback=lambda interval: self._emit_pulse_interval_change(interval),
                    tools=tools,
                    dev_mode_callbacks=dev_callbacks
                )

                final_text = result.final_text
                log_info(f"REMINDER: Processed in {result.passes_executed} pass(es)", prefix="⏰")

                # Store response
                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=final_text,
                    input_type="text"
                )

                # Emit to GUI
                timestamp = self._get_timestamp()
                self.signals.new_message.emit("assistant", final_text, timestamp)
            else:
                error_msg = f"Reminder pulse API error: {response.error}"
                log_error(f"REMINDER: API call failed - {error_msg}")
                timestamp = self._get_timestamp()
                self.signals.new_message.emit("system", f"[Reminder Pulse Error: {response.error}]", timestamp)
                self.signals.update_status.emit(error_msg, StatusManager.STATUS_ERROR)

        except Exception as e:
            error_msg = f"Reminder pulse exception: {str(e)}"
            tb = traceback.format_exc()
            log_error(f"REMINDER: Exception - {error_msg}")
            log_error(f"REMINDER: Traceback:\n{tb}")
            timestamp = self._get_timestamp()
            self.signals.new_message.emit("system", f"[Reminder Pulse Exception: {str(e)}]", timestamp)
            self.signals.update_status.emit(error_msg, StatusManager.STATUS_ERROR)

        finally:
            log_info("=== REMINDER: _process_reminder_pulse() completing ===", prefix="⏰")
            self.signals.response_complete.emit()

    def _update_status(self, status: str):
        """Update status bar (legacy - uses default type)."""
        self._update_status_with_type(status, StatusManager.STATUS_READY)

    def _update_timer_display(self, session_time: str, total_time: str):
        """Update timer display."""
        self.timer_label.setText(f"Session: {session_time} | Total: {total_time}")

    def _show_settings(self):
        """Show settings dialog."""
        dialog = SettingsDialog(self)
        dialog.exec_()

    def closeEvent(self, event):
        """Handle window close."""
        # End session if active
        if self._temporal_tracker and self._temporal_tracker.is_session_active:
            self._temporal_tracker.end_session()
        event.accept()


class SettingsDialog(QDialog):
    """Settings dialog for font size, TTS, etc."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)

        # Import user settings
        from core.user_settings import get_user_settings
        self._user_settings = get_user_settings()

        layout = QVBoxLayout(self)

        # ===== Display Settings =====
        display_label = QLabel("Display")
        display_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 10px;")
        layout.addWidget(display_label)

        # Font size
        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("Font Size:"))
        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 24)
        self.font_spin.setValue(self._user_settings.font_size)
        font_layout.addWidget(self.font_spin)
        layout.addLayout(font_layout)

        # ===== TTS Settings =====
        tts_label = QLabel("Text-to-Speech (ElevenLabs)")
        tts_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 20px;")
        layout.addWidget(tts_label)

        # TTS enabled toggle
        self.tts_enabled_check = QCheckBox("Enable TTS for assistant responses")
        self.tts_enabled_check.setChecked(self._user_settings.tts_enabled)
        layout.addWidget(self.tts_enabled_check)

        # Voice ID input
        voice_layout = QHBoxLayout()
        voice_layout.addWidget(QLabel("Voice ID:"))
        self.voice_id_input = QLineEdit()
        self.voice_id_input.setPlaceholderText("Leave blank for default voice")
        # Show current voice ID if custom, otherwise leave blank
        current_voice = self._user_settings._settings.tts.voice_id
        if current_voice:
            self.voice_id_input.setText(current_voice)
        voice_layout.addWidget(self.voice_id_input)
        layout.addLayout(voice_layout)

        # Voice ID help text
        help_label = QLabel("Find voice IDs at elevenlabs.io/voice-library")
        help_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(help_label)

        # Spacer
        layout.addSpacing(20)

        # Buttons
        button_layout = QHBoxLayout()

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_settings)
        button_layout.addWidget(apply_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _apply_settings(self):
        """Apply settings."""
        # Font size
        font_size = self.font_spin.value()
        self._user_settings.font_size = font_size
        if self.parent():
            self.parent().chat_display.setFont(QFont("Consolas", font_size))

        # TTS settings
        tts_was_enabled = self._user_settings.tts_enabled
        tts_now_enabled = self.tts_enabled_check.isChecked()

        self._user_settings.tts_enabled = tts_now_enabled
        self._user_settings.tts_voice_id = self.voice_id_input.text().strip()

        # Start/stop audio player subprocess based on TTS toggle
        if tts_now_enabled and not tts_was_enabled:
            self._start_audio_player()
        elif not tts_now_enabled and tts_was_enabled:
            self._stop_audio_player()

        log_info(f"Settings applied - TTS: {tts_now_enabled}, Voice: {self._user_settings.tts_voice_id}", prefix="⚙️")

    def _start_audio_player(self):
        """Start the audio player subprocess."""
        try:
            from subprocess_mgmt.audio_player import register_audio_player, start_audio_player
            register_audio_player(enabled=True)
            start_audio_player()
            log_info("Audio player started", prefix="🔊")
        except Exception as e:
            log_error(f"Failed to start audio player: {e}")

    def _stop_audio_player(self):
        """Stop the audio player subprocess."""
        try:
            from subprocess_mgmt.audio_player import stop_audio_player
            stop_audio_player()
            log_info("Audio player stopped", prefix="🔊")
        except Exception as e:
            log_error(f"Failed to stop audio player: {e}")


# Global GUI instance
_gui: Optional[ChatWindow] = None


def get_gui() -> ChatWindow:
    """Get the global GUI instance."""
    global _gui
    if _gui is None:
        raise RuntimeError("GUI not initialized. Call init_gui() first.")
    return _gui


def init_gui() -> ChatWindow:
    """Initialize the global GUI instance."""
    global _gui
    _gui = ChatWindow()
    return _gui


def run_gui():
    """Run the GUI application (blocking)."""
    # =========================================================
    # CRITICAL: Load PyTorch/native libraries BEFORE Qt5
    # MS Store Python has DLL loading issues if Qt5 initializes first.
    # PyTorch's c10.dll fails to load in the sandbox environment
    # when Qt5 DLLs are already loaded.
    # =========================================================

    # Import backend modules needed for pre-Qt initialization
    import config
    from core.database import init_database
    from core.embeddings import load_embedding_model

    # Setup directories
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize database
    print("Initializing database...")
    init_database(db_path=config.DATABASE_PATH, busy_timeout_ms=config.DB_BUSY_TIMEOUT_MS)

    # Load embedding model BEFORE Qt - this loads PyTorch DLLs
    # Note: When called from main.py, model is already loaded (returns True immediately)
    embedding_loaded = load_embedding_model(config.EMBEDDING_MODEL)
    if not embedding_loaded:
        print("=" * 60)
        print("WARNING: Running in degraded mode - semantic memory disabled")
        print("Conversations will be stored, but memory recall won't work.")
        print("=" * 60)

    # =========================================================
    # NOW safe to create Qt application (PyTorch DLLs are loaded)
    # =========================================================
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Import remaining backend modules
    from core.temporal import init_temporal_tracker, get_temporal_tracker
    from concurrency.locks import init_lock_manager
    from memory.conversation import init_conversation_manager, get_conversation_manager
    from memory.vector_store import init_vector_store
    from memory.extractor import init_memory_extractor, get_memory_extractor
    from llm.router import init_llm_router, get_llm_router
    from prompt_builder import init_prompt_builder, get_prompt_builder
    from agency.system_pulse import init_system_pulse_timer, get_system_pulse_timer
    from agency.intentions import init_reminder_scheduler, get_reminder_scheduler

    # Import Telegram modules if enabled
    telegram_listener = None
    if config.TELEGRAM_ENABLED:
        from communication.telegram_gateway import init_telegram_gateway, get_telegram_gateway
        from communication.telegram_listener import init_telegram_listener, get_telegram_listener

    # Initialize remaining components
    print("Initializing components...")
    init_lock_manager()
    init_temporal_tracker()
    init_conversation_manager()

    # Clean up any empty assistant messages from previous sessions
    # These can cause API errors: "messages must have non-empty content"
    get_conversation_manager().cleanup_empty_messages()

    init_vector_store()
    init_llm_router(
        primary_provider=config.LLM_PRIMARY_PROVIDER,
        fallback_enabled=config.LLM_FALLBACK_ENABLED
    )
    init_memory_extractor()
    init_prompt_builder()
    init_system_pulse_timer()

    # Initialize Telegram gateway and listener if enabled
    if config.TELEGRAM_ENABLED:
        gateway = init_telegram_gateway()
        telegram_listener = init_telegram_listener()

        # Connect listener to gateway so auto-detected chat_id propagates
        def on_chat_id_detected(chat_id: str):
            gateway.set_chat_id(chat_id)
            log_info(f"Telegram chat_id detected and set: {chat_id}", prefix="📱")
        telegram_listener.set_chat_id_callback(on_chat_id_detected)

        # Start the listener
        telegram_listener.start()
        log_info("Telegram listener started", prefix="📱")

    # Start system pulse timer if enabled
    pulse_timer = None
    if config.SYSTEM_PULSE_ENABLED:
        pulse_timer = get_system_pulse_timer()
        pulse_timer.start()

    # Initialize and start reminder scheduler
    init_reminder_scheduler(enabled=True)
    reminder_scheduler = get_reminder_scheduler()
    reminder_scheduler.start()

    # Create and configure window
    window = init_gui()
    window.set_backend(
        conversation_mgr=get_conversation_manager(),
        llm_router=get_llm_router(),
        prompt_builder=get_prompt_builder(),
        temporal_tracker=get_temporal_tracker(),
        system_pulse_timer=pulse_timer,
        reminder_scheduler=reminder_scheduler,
        telegram_listener=telegram_listener
    )

    window.show()

    # Create dev window if dev mode is enabled
    dev_window = None
    if config.DEV_MODE_ENABLED:
        from interface.dev_window import init_dev_window
        dev_window = init_dev_window()
        dev_window.show()
        # Position dev window to the right of main window
        main_geo = window.geometry()
        dev_window.move(main_geo.x() + main_geo.width() + 20, main_geo.y())
        print("Dev mode: Debug window opened")

    print("GUI ready!")

    # Initialize TTS audio player if enabled in user settings
    try:
        from core.user_settings import is_tts_enabled
        if is_tts_enabled():
            from subprocess_mgmt.audio_player import register_audio_player, start_audio_player
            register_audio_player(enabled=True)
            start_audio_player()
            log_info("TTS audio player started (from saved settings)", prefix="🔊")
    except Exception as e:
        log_warning(f"Failed to initialize TTS: {e}")

    # Run event loop
    exit_code = app.exec_()

    # Cleanup
    print("Shutting down...")
    if config.SYSTEM_PULSE_ENABLED:
        get_system_pulse_timer().stop()

    # Stop reminder scheduler
    get_reminder_scheduler().stop()

    # Stop Telegram listener if enabled
    if config.TELEGRAM_ENABLED and telegram_listener:
        telegram_listener.stop()
        log_info("Telegram listener stopped", prefix="📱")

    # Release webcam device if it was opened
    from agency.visual_capture import release_webcam
    release_webcam()

    # Stop TTS audio player if running
    try:
        from subprocess_mgmt.audio_player import stop_audio_player
        stop_audio_player()
    except Exception:
        pass  # Ignore errors during shutdown

    return exit_code


if __name__ == "__main__":
    sys.exit(run_gui())
