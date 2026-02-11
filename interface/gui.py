"""
Pattern Project - PyQt5 Chat GUI
Version: 0.2.0

A visual chat interface with timestamps, session tracking,
system pulse countdown, and enhanced UX features.

Features:
- Light/dark theme support
- Full markdown rendering
- Draft persistence
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
    NotificationManager, DraftManager,
    KeyboardShortcutManager, StatusManager,
    CancelButton
)
from interface.process_panel import (
    ProcessPanel, ProcessEventType, get_process_event_bus
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

# UI font family - proportional sans-serif for chat, matching Claude.ai style
UI_FONT_FAMILY = "Segoe UI"


class MessageSignals(QObject):
    """Signals for thread-safe message passing to GUI."""
    new_message = pyqtSignal(str, str, str)  # role, content, timestamp
    update_status = pyqtSignal(str, str)  # status text, status type
    update_timer = pyqtSignal(str, str)  # session_time, total_time
    response_complete = pyqtSignal()
    pulse_interval_change = pyqtSignal(int)  # new interval in seconds
    show_notification = pyqtSignal(str, str)  # message, level (info/success/warning/error)
    tool_executing = pyqtSignal(str)  # tool name being executed
    # Streaming signals
    stream_start = pyqtSignal(str)  # timestamp - start of streaming response
    stream_chunk = pyqtSignal(str)  # text chunk to append
    stream_complete = pyqtSignal(str)  # full_text - streaming finished
    # Clarification signal
    show_clarification = pyqtSignal(dict, str)  # clarification_data, timestamp


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
        self.setPlaceholderText("Reply...")

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

        # Streaming state
        self._streaming_msg_id: Optional[str] = None  # ID of current streaming message
        self._streaming_text: str = ""  # Accumulated text during streaming
        self._streaming_content_position: Optional[int] = None  # Cursor position where content starts

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

        # Deferred retry manager for API failures
        from llm.retry_manager import get_retry_manager
        self._retry_manager = get_retry_manager()

        # Prompt export recorder
        from core.round_recorder import RoundRecorder
        self._round_recorder = RoundRecorder()

        # User settings
        from core.user_settings import get_user_settings
        self._user_settings = get_user_settings()

        self._setup_ui()
        self._setup_signals()
        self._setup_timers()
        self._setup_keyboard_shortcuts()
        self._setup_draft_manager()
        self._apply_style()
        self._init_model_dropdown()

    def _setup_signals(self):
        """Connect signals to slots."""
        self.signals.new_message.connect(self._append_message)
        self.signals.update_status.connect(self._update_status_with_type)
        self.signals.update_timer.connect(self._update_timer_display)
        self.signals.response_complete.connect(self._on_response_complete)
        self.signals.pulse_interval_change.connect(self.set_pulse_interval_by_seconds)
        self.signals.show_notification.connect(self._show_notification)
        # Streaming signal connections
        self.signals.stream_start.connect(self._on_stream_start)
        self.signals.stream_chunk.connect(self._on_stream_chunk)
        self.signals.stream_complete.connect(self._on_stream_complete)
        self.signals.tool_executing.connect(self._on_tool_executing)
        # Clarification signal
        self.signals.show_clarification.connect(self._show_clarification_message)

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
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(6)

        # Header frame
        header = self._create_header()
        layout.addWidget(header)


        # Main content area: process panel + chat display side by side
        content_area = QWidget()
        content_area.setStyleSheet("background: transparent; border: none;")
        content_layout = QHBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Process panel (left side)
        self._process_panel = ProcessPanel()
        content_layout.addWidget(self._process_panel)

        # Chat display (right side, takes remaining space)
        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(False)  # Handle links ourselves for clarification
        self.chat_display.anchorClicked.connect(self._on_link_clicked)
        self.chat_display.setFont(QFont(UI_FONT_FAMILY, self._user_settings.font_size))
        self.chat_display.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_display.customContextMenuRequested.connect(self._show_chat_context_menu)
        content_layout.addWidget(self.chat_display, stretch=1)

        layout.addWidget(content_area, stretch=1)


        # Input area - add horizontal padding since central widget has 0 margins
        input_frame = self._create_input_area()
        input_container = QWidget()
        input_container_layout = QHBoxLayout(input_container)
        input_container_layout.setContentsMargins(12, 0, 12, 0)
        input_container_layout.addWidget(input_frame)
        layout.addWidget(input_container)

        # Status bar with progress indicator
        status_frame = QFrame()
        status_frame.setFrameStyle(QFrame.NoFrame)
        status_frame.setStyleSheet("QFrame { border: none; background: transparent; }")
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(16, 2, 16, 0)

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

    def _create_header(self) -> QFrame:
        """Create the header with timer, pulse countdown, and controls."""
        header = QFrame()
        header.setFrameStyle(QFrame.NoFrame)
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {self._theme.background};
                border: none;
                border-bottom: 1px solid {self._theme.border};
                border-radius: 0px;
                padding: 0px;
            }}
        """)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 6, 12, 6)

        # Session timer
        self.timer_label = QLabel("Session: --:--")
        self.timer_label.setFont(QFont(UI_FONT_FAMILY, 11))
        self.timer_label.setStyleSheet(f"color: {COLORS['text_dim']};")
        layout.addWidget(self.timer_label)

        # Add spacing between session timer and pulse timer
        layout.addSpacing(20)

        # Pulse countdown (only if enabled)
        self.pulse_label = QLabel("Pulse: --:--")
        self.pulse_label.setFont(QFont(UI_FONT_FAMILY, 11))
        self.pulse_label.setStyleSheet(f"color: {COLORS['pulse']};")
        self.pulse_label.setToolTip("Time until next system pulse")
        if not config.SYSTEM_PULSE_ENABLED:
            self.pulse_label.hide()
        layout.addWidget(self.pulse_label)

        # Pulse interval dropdown
        self.pulse_dropdown = QComboBox()
        self.pulse_dropdown.setFont(QFont(UI_FONT_FAMILY, 10))
        self.pulse_dropdown.addItems(["3 min", "10 min", "30 min", "1 hour", "2 hours", "3 hours", "6 hours", "12 hours"])
        self.pulse_dropdown.setCurrentIndex(1)  # Default: 10 min
        self.pulse_dropdown.setToolTip("Set pulse timer interval")
        self.pulse_dropdown.currentIndexChanged.connect(self._on_pulse_interval_changed)
        if not config.SYSTEM_PULSE_ENABLED:
            self.pulse_dropdown.hide()
        layout.addWidget(self.pulse_dropdown)

        # Pulse Now button
        self.pulse_now_btn = QPushButton("Pulse")
        self.pulse_now_btn.setFont(QFont(UI_FONT_FAMILY, 9))
        self.pulse_now_btn.setToolTip("Fire a system pulse now")
        self.pulse_now_btn.clicked.connect(self._on_pulse_now_clicked)
        if not config.SYSTEM_PULSE_ENABLED:
            self.pulse_now_btn.hide()
        layout.addWidget(self.pulse_now_btn)

        # Model switcher dropdown
        self.model_dropdown = QComboBox()
        self.model_dropdown.setFont(QFont(UI_FONT_FAMILY, 10))
        self.model_dropdown.addItems(["Opus 4.6", "Sonnet 4.5"])
        self.model_dropdown.setToolTip("Conversation model (affects new messages)")
        self.model_dropdown.currentIndexChanged.connect(self._on_model_changed)
        layout.addWidget(self.model_dropdown)

        # Font size controls
        self.font_decrease_btn = QPushButton("A-")
        self.font_decrease_btn.setFont(QFont(UI_FONT_FAMILY, 9))
        self.font_decrease_btn.setMaximumWidth(36)
        self.font_decrease_btn.clicked.connect(self._decrease_font_size)
        layout.addWidget(self.font_decrease_btn)

        self.font_increase_btn = QPushButton("A+")
        self.font_increase_btn.setFont(QFont(UI_FONT_FAMILY, 9))
        self.font_increase_btn.setMaximumWidth(36)
        self.font_increase_btn.clicked.connect(self._increase_font_size)
        layout.addWidget(self.font_increase_btn)

        self._update_font_tooltips()

        layout.addStretch()

        # Prompt export button
        self.export_prompt_btn = QPushButton("Export")
        self.export_prompt_btn.setFont(QFont(UI_FONT_FAMILY, 9))
        self.export_prompt_btn.setToolTip("Export the last AI round (full API payload) to a log file")
        self.export_prompt_btn.clicked.connect(self._export_prompt)
        layout.addWidget(self.export_prompt_btn)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setFont(QFont(UI_FONT_FAMILY, 9))
        self.settings_btn.clicked.connect(self._show_settings)
        layout.addWidget(self.settings_btn)

        return header

    def _create_input_area(self) -> QFrame:
        """Create the input area with text field and send button."""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {self._theme.surface};
                border: 1px solid {self._theme.border};
                border-radius: 22px;
                padding: 4px;
            }}
        """)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(6)

        # Multi-line input with Enter to send, Shift+Enter for newline
        self.input_field = ChatInputWidget()
        self.input_field.setFont(QFont(UI_FONT_FAMILY, self._user_settings.font_size))
        self.input_field.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                border: none;
                padding: 6px 8px;
                color: {self._theme.text};
            }}
        """)
        self.input_field.send_requested.connect(self._send_message)
        layout.addWidget(self.input_field, stretch=1)

        self.send_btn = QPushButton("\u2191")  # Up arrow character
        self.send_btn.setFont(QFont(UI_FONT_FAMILY, 14))
        self.send_btn.clicked.connect(self._send_message)
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._theme.accent};
                color: {self._theme.background};
                border: none;
                border-radius: 18px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                opacity: 0.85;
            }}
            QPushButton:disabled {{
                background-color: {self._theme.text_dim};
                color: {self._theme.surface};
            }}
        """)
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

        # Copy last message
        self._shortcut_manager.register("Ctrl+Shift+C", self._copy_last_message, "Copy last message")

        # Focus input
        self._shortcut_manager.register("Escape", self._focus_input, "Focus input")

        # Scroll to bottom
        self._shortcut_manager.register("Ctrl+End", self._scroll_to_bottom, "Scroll to bottom")

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

    def _export_prompt(self):
        """Export the last AI round's full API payloads to a human-readable file."""
        if not self._round_recorder.has_data:
            self._notification_manager.warning("No prompt data to export yet")
            return

        export_path = str(config.PROMPT_EXPORT_PATH)
        success = self._round_recorder.export_to_file(export_path)
        if success:
            self._notification_manager.info(f"Prompt exported to {export_path}")
        else:
            self._notification_manager.warning("Prompt export failed — check logs")

    def _on_theme_changed(self, theme: Theme):
        """Handle theme change."""
        global COLORS
        self._theme = theme
        COLORS = get_colors_from_theme(theme)

        # Update markdown renderer
        self._markdown_renderer.update_theme(theme)

        # Re-apply stylesheet
        self._apply_style()

        # Update inline-styled elements that don't pick up global stylesheet changes
        self.timer_label.setStyleSheet(f"color: {theme.text_dim};")
        self.pulse_label.setStyleSheet(f"color: {theme.pulse};")
        self.status_label.setStyleSheet(f"color: {theme.text_dim}; font-size: 10px;")

        # Update header frame style
        header_frame = self.timer_label.parent()
        if header_frame:
            header_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {theme.background};
                    border: none;
                    border-bottom: 1px solid {theme.border};
                    border-radius: 0px;
                    padding: 0px;
                }}
            """)

        # Update input area styles
        self.input_field.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                border: none;
                padding: 6px 8px;
                color: {theme.text};
            }}
        """)
        input_frame = self.input_field.parent()
        if input_frame:
            input_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {theme.surface};
                    border: 1px solid {theme.border};
                    border-radius: 22px;
                    padding: 4px;
                }}
            """)
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.accent};
                color: {theme.background};
                border: none;
                border-radius: 18px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                opacity: 0.85;
            }}
            QPushButton:disabled {{
                background-color: {theme.text_dim};
                color: {theme.surface};
            }}
        """)

        # Update component themes
        self.cancel_btn.update_theme(theme)

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
            4: 7200,   # 2 hours
            5: 10800,  # 3 hours
            6: 21600,  # 6 hours
            7: 43200,  # 12 hours
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
            7200: 4,   # 2 hours
            10800: 5,  # 3 hours
            21600: 6,  # 6 hours
            43200: 7,  # 12 hours
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

    def _init_model_dropdown(self):
        """Initialize model dropdown based on saved user preference."""
        saved_model = self._user_settings.conversation_model

        # Map model ID to dropdown index
        model_to_index = {
            "claude-opus-4-6": 0,
            "claude-sonnet-4-5-20250929": 1
        }

        index = model_to_index.get(saved_model, 1)  # Default to Sonnet (index 1)

        # Block signals to avoid triggering _on_model_changed during initialization
        self.model_dropdown.blockSignals(True)
        self.model_dropdown.setCurrentIndex(index)
        self.model_dropdown.blockSignals(False)

    def _on_model_changed(self, index: int):
        """Handle model dropdown change."""
        # Map dropdown index to model ID
        model_map = {
            0: ("Opus 4.6", "claude-opus-4-6"),
            1: ("Sonnet 4.5", "claude-sonnet-4-5-20250929")
        }

        name, model_id = model_map.get(index, ("Sonnet 4.5", "claude-sonnet-4-5-20250929"))

        # Save to user settings
        if self._user_settings:
            self._user_settings.conversation_model = model_id
            self._notification_manager.info(f"Switched to {name}")
            log_info(f"Conversation model changed to {name}", prefix="🤖")

    def _decrease_font_size(self):
        """Decrease font size by 1pt (minimum 10pt)."""
        current = self._user_settings.font_size
        if current > 10:
            self._apply_font_size(current - 1)

    def _increase_font_size(self):
        """Increase font size by 1pt (maximum 24pt)."""
        current = self._user_settings.font_size
        if current < 24:
            self._apply_font_size(current + 1)

    def _apply_font_size(self, size: int):
        """Apply font size to chat display and input field."""
        self._user_settings.font_size = size
        self.chat_display.setFont(QFont(UI_FONT_FAMILY, size))
        self.input_field.setFont(QFont(UI_FONT_FAMILY, size))
        self._update_font_tooltips()

    def _update_font_tooltips(self):
        """Update tooltips on font buttons to show current size."""
        size = self._user_settings.font_size
        self.font_decrease_btn.setToolTip(f"Decrease font size ({size}pt)")
        self.font_increase_btn.setToolTip(f"Increase font size ({size}pt)")

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
        code_bg = self._theme.code_bg
        code_style = (
            f"background-color:{code_bg}; "
            "padding: 2px 6px; "
            "border-radius: 4px; "
            "font-family: 'Consolas', 'Monaco', 'Courier New', monospace; "
            "font-size: 13px;"
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

        # Pattern: [[PULSE:3m]], [[PULSE:10m]], [[PULSE:30m]], [[PULSE:1h]], [[PULSE:2h]], [[PULSE:3h]], [[PULSE:6h]], [[PULSE:12h]]
        pattern = r'\[\[PULSE:(3m|10m|30m|1h|2h|3h|6h|12h)\]\]'
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
        pattern = r'\[\[PULSE:(3m|10m|30m|1h|2h|3h|6h|12h)\]\]'

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

        # Format content with markdown renderer (for assistant messages)
        # or simple HTML escape (for user/system)
        if role == "assistant":
            formatted_content = self._markdown_renderer.render(content, role)
        else:
            formatted_content = self._format_message_text(content, role)

        # Build HTML based on role - table layout for Qt compatibility
        # Qt's QTextBrowser ignores background-color CSS on divs; use bgcolor on td instead.
        # String concatenation avoids f-string indentation whitespace in Qt rendering.
        if role == "user":
            # User messages: right-aligned bubble via left spacer, bgcolor for background
            msg_html = (
                '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                '<td width="80"></td>'
                '<td bgcolor="' + self._theme.user_bubble + '" style="padding: 14px 18px;">'
                '<span style="color: ' + self._theme.text + '; line-height: 1.6;">' + formatted_content + '</span>'
                '<br/><span style="color: ' + self._theme.timestamp + '; font-size: 10px;">' + timestamp + '</span>'
                '</td>'
                '</tr></table>'
            )
        elif role == "assistant":
            # Assistant messages: full-width with right spacer, no background
            msg_html = (
                '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                '<td style="padding: 4px 0;">'
                '<span style="color: ' + self._theme.text + '; line-height: 1.6;">' + formatted_content + '</span>'
                '</td>'
                '<td width="40"></td>'
                '</tr></table>'
            )
        else:
            # System messages: spacers on both sides, narrow colored cell as border-left accent
            msg_html = (
                '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                '<td width="40"></td>'
                '<td width="3" bgcolor="' + self._theme.system + '"></td>'
                '<td style="padding: 10px 16px;">'
                '<span style="color: ' + self._theme.system + '; font-size: 12px;">' + formatted_content + '</span>'
                '</td>'
                '<td width="40"></td>'
                '</tr></table>'
            )

        self.chat_display.append(msg_html)
        self.chat_display.moveCursor(QTextCursor.End)

        # Trigger TTS for assistant messages if enabled
        if role == "assistant":
            self._trigger_tts(content)

    def _show_clarification_message(self, clarification_data: dict, timestamp: str):
        """Display a clarification request with clickable option buttons."""
        import html as html_module

        question = clarification_data.get("question", "")
        options = clarification_data.get("options", [])
        context = clarification_data.get("context", "")

        # Store as a special message
        msg_id = str(uuid.uuid4())
        msg_data = MessageData(
            id=msg_id,
            role="clarification",
            content=question,
            timestamp=timestamp
        )
        self._messages.append(msg_data)

        # Build HTML for clarification panel
        # Yellow/amber styling to stand out
        clarification_color = "#f0c040"
        bg_color = "#3d3520"

        content_parts = []

        if context:
            content_parts.append(
                f"<div style='color: #888888; font-style: italic; margin-bottom: 8px;'>"
                f"{html_module.escape(context)}</div>"
            )

        content_parts.append(
            f"<div style='font-weight: bold; margin-bottom: 10px;'>"
            f"{html_module.escape(question)}</div>"
        )

        # Add clickable options as styled buttons
        if options:
            content_parts.append("<div style='margin-top: 10px;'>")
            for i, opt in enumerate(options, 1):
                escaped_opt = html_module.escape(opt)
                # Use a special link format that we can intercept
                content_parts.append(
                    f"<div style='margin: 5px 0;'>"
                    f"<a href='clarification://{i}' style='color: #4da6ff; text-decoration: none;'>"
                    f"  {i}. {escaped_opt}</a>"
                    f"</div>"
                )
            content_parts.append("</div>")

        # Store options for click handling
        self._pending_clarification_options = options

        msg_html = f"""
        <div style='margin-bottom: 10px; padding: 12px; background-color: {bg_color};
                    border: 2px solid {clarification_color}; border-radius: 8px;'
             data-msg-id='{msg_id}'>
            <div style='margin-bottom: 8px;'>
                <span style='color:{self._theme.timestamp};'>[{timestamp}]</span>
                <span style='color: {clarification_color}; font-weight: bold;'>
                    ⚠️ Clarification Needed
                </span>
            </div>
            <div style='color: {self._theme.text}; margin-left: 10px;'>
                {"".join(content_parts)}
            </div>
            <div style='color: #888888; font-size: 0.9em; margin-top: 10px; font-style: italic;'>
                Click an option above or type your response below.
            </div>
        </div>
        """

        self.chat_display.append(msg_html)
        self.chat_display.moveCursor(QTextCursor.End)

    def _on_link_clicked(self, url):
        """Handle clicks on links in chat display."""
        import webbrowser
        url_str = url.toString()

        # Check for clarification links
        if url_str.startswith("clarification://"):
            self._on_clarification_link_clicked(url)
        else:
            # Open external links in browser
            webbrowser.open(url_str)

    def _on_clarification_link_clicked(self, url):
        """Handle clicks on clarification option links."""
        url_str = url.toString()
        if url_str.startswith("clarification://"):
            try:
                option_num = int(url_str.replace("clarification://", ""))
                if hasattr(self, '_pending_clarification_options'):
                    options = self._pending_clarification_options
                    if 1 <= option_num <= len(options):
                        selected_option = options[option_num - 1]
                        # Set the input field and send
                        self.input_field.setPlainText(selected_option)
                        self._send_message()
            except (ValueError, IndexError):
                pass

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

            # Play TTS (runs in background thread internally)
            try:
                from tts.player import play_tts
                voice_id = get_tts_voice_id()
                play_tts(text, voice_id)
            except Exception as e:
                log_warning(f"TTS playback error: {e}")

        except Exception as e:
            log_warning(f"TTS trigger error: {e}")

    def _on_stream_start(self, timestamp: str):
        """Handle start of streaming response - create message container and track position."""
        # Generate unique ID for this streaming message
        self._streaming_msg_id = str(uuid.uuid4())
        self._streaming_text = ""

        # Append a minimal separator; streaming content will be inserted after this position
        self.chat_display.append('')

        # Record cursor position where streaming content will be inserted
        # This position-based approach avoids fragile regex matching on normalized HTML
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._streaming_content_position = cursor.position()

        self.chat_display.moveCursor(QTextCursor.End)

    def _on_stream_chunk(self, chunk: str):
        """Handle incoming text chunk - update streaming content using cursor position."""
        import html as html_module

        if not self._streaming_msg_id or self._streaming_content_position is None:
            return

        self._streaming_text += chunk

        # Format accumulated text for display (simple HTML escaping during streaming)
        escaped_text = html_module.escape(self._streaming_text)
        display_text = escaped_text.replace('\n', '<br/>')

        # Use cursor-based update: select from content start to end, replace
        # This avoids fragile regex matching on Qt-normalized HTML
        cursor = self.chat_display.textCursor()
        cursor.setPosition(self._streaming_content_position)
        cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()

        # Insert the updated content wrapped in assistant-style table layout
        stream_html = (
            '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            '<td style="padding: 4px 0;">'
            '<span style="color:' + self._theme.text + '; line-height: 1.6;">' + display_text + '</span>'
            '</td>'
            '<td width="40"></td>'
            '</tr></table>'
        )
        cursor.insertHtml(stream_html)
        self.chat_display.moveCursor(QTextCursor.End)

    def _on_stream_complete(self, full_text: str):
        """Handle streaming complete - finalize with markdown rendering."""
        if not self._streaming_msg_id:
            return

        # Fallback: if full_text is empty but we have accumulated streaming text, use that
        # This provides defense-in-depth for edge cases where tool processing might lose text
        if not full_text.strip() and self._streaming_text.strip():
            from core.logger import log_warning
            log_warning(
                "Empty full_text received but streaming_text exists - using streaming text as fallback",
                prefix="⚠️"
            )
            full_text = self._streaming_text

        # Store message for search
        timestamp = self._get_timestamp()
        msg_data = MessageData(
            id=self._streaming_msg_id,
            role="assistant",
            content=full_text,
            timestamp=timestamp
        )
        self._messages.append(msg_data)

        # Apply full markdown rendering to the final message
        formatted_content = self._markdown_renderer.render(full_text, "assistant")

        # Use cursor-based update for final content (same approach as chunks)
        if self._streaming_content_position is not None:
            cursor = self.chat_display.textCursor()
            cursor.setPosition(self._streaming_content_position)
            cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()

            # Insert the final markdown-rendered content wrapped in assistant-style table layout
            final_html = (
                '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                '<td style="padding: 4px 0;">'
                '<span style="color:' + self._theme.text + '; line-height: 1.6;">' + formatted_content + '</span>'
                '</td>'
                '<td width="40"></td>'
                '</tr></table>'
            )
            cursor.insertHtml(final_html)
            self.chat_display.moveCursor(QTextCursor.End)

        # Clear streaming state
        self._streaming_msg_id = None
        self._streaming_text = ""
        self._streaming_content_position = None

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
        self.pulse_now_btn.setEnabled(False)
        self._status_manager.set_thinking()
        self._show_cancel_button()

        # Cancel any pending deferred retry (user has moved on)
        if self._retry_manager.has_pending():
            self._retry_manager.cancel()
            log_info("Deferred retry cancelled - user sent new message", prefix="🔄")

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

        # Emit to process panel
        get_process_event_bus().emit_event(ProcessEventType.MESSAGE_RECEIVED, origin="user")

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
        """Process a message in background thread with streaming response."""
        import time
        from core.sentence_splitter import SentenceBuffer
        from tts.player import queue_tts_sentence
        from core.user_settings import is_tts_enabled, get_tts_voice_id

        # DIAGNOSTIC: Log entry point
        log_info("=== _process_message START ===", prefix="📨")
        log_info(f"Input length: {len(user_input)} chars", prefix="📨")
        log_info(f"Has pasted image: {pasted_image is not None and not pasted_image.isNull()}", prefix="📨")

        try:
            # Check for cancellation early
            if self._cancel_requested:
                self.signals.show_notification.emit("Request cancelled", "warning")
                log_info("Cancelled early", prefix="📨")
                return

            # Build prompt (no base prompt - emergent personality from context)
            log_info("Building prompt...", prefix="📨")
            assembled = self._prompt_builder.build(
                user_input=user_input,
                system_prompt="",
                additional_context={"is_session_start": self._is_first_message_of_session}
            )
            self._is_first_message_of_session = False
            log_info(f"Prompt built: {len(assembled.full_system_prompt)} chars system prompt", prefix="📨")

            # Emit to process panel
            get_process_event_bus().emit_event(ProcessEventType.PROMPT_ASSEMBLED)

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
                total_tokens = len(assembled.full_system_prompt) // 4
                emit_prompt_assembly(blocks_data, total_tokens)

            # Get conversation history BEFORE storing the new turn
            log_info("Getting conversation history...", prefix="📨")
            history = self._conversation_mgr.get_api_messages()
            log_info(f"Got {len(history)} messages in history", prefix="📨")

            # Store user message for persistence (NOTE: this may trigger memory extraction!)
            log_info("Storing user turn (may trigger extraction)...", prefix="📨")
            if self._conversation_mgr:
                self._conversation_mgr.add_turn(
                    role="user",
                    content=user_input,
                    input_type="text"
                )
            log_info("User turn stored", prefix="📨")

            # Build user message (with visuals if applicable)
            log_info("Building user message...", prefix="📨")
            if pasted_image and not pasted_image.isNull():
                user_message = self._build_message_with_pasted_image(user_input, pasted_image)
                log_info("Built message with pasted image", prefix="📨")
            else:
                user_message = self._capture_visuals_for_message(user_input)
                # Log what type of message was built
                content = user_message.get("content", "")
                if isinstance(content, list):
                    log_info(f"Built multimodal message with {len(content)} content blocks", prefix="📨")
                else:
                    log_info(f"Built text-only message ({len(content)} chars)", prefix="📨")

            # Inject relevant memories
            relevant_memories = assembled.session_context.get("relevant_memories")
            if relevant_memories:
                content = user_message.get("content")
                if isinstance(content, str):
                    user_message["content"] = f"{relevant_memories}\n\n{content}"
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            block["text"] = f"{relevant_memories}\n\n{block.get('text', '')}"
                            break

            # Emit memories injected to process panel
            get_process_event_bus().emit_event(ProcessEventType.MEMORIES_INJECTED)

            history.append(user_message)
            log_info(f"History now has {len(history)} messages (after appending user message)", prefix="📨")

            # Get tools
            from llm.router import TaskType
            from agency.tools import get_tool_definitions, get_tool_processor

            tools = get_tool_definitions()
            log_info(f"Got {len(tools)} tool definitions", prefix="📨")

            # Start streaming
            log_info("Emitting stream_start signal...", prefix="📨")
            timestamp = self._get_timestamp()
            self.signals.stream_start.emit(timestamp)
            log_info("Starting streaming API call...", prefix="📨")

            # Emit stream start to process panel
            get_process_event_bus().emit_event(
                ProcessEventType.STREAM_START, is_active=True
            )

            # Initialize sentence buffer for TTS
            sentence_buffer = SentenceBuffer()
            tts_enabled = is_tts_enabled()
            voice_id = get_tts_voice_id() if tts_enabled else None

            # Start recording this round for prompt export
            self._round_recorder.start_round()
            self._round_recorder.record_request(
                system_prompt=assembled.full_system_prompt,
                messages=history,
                tools=tools,
                model=self._user_settings.conversation_model,
                temperature=0.7,
                thinking_enabled=True,
                is_streaming=True,
            )

            # Stream the response (thinking always enabled)
            final_state = None
            for chunk, state in self._llm_router.chat_stream(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools,
                thinking_enabled=True
            ):
                # Check for cancellation
                if self._cancel_requested:
                    self.signals.show_notification.emit("Request cancelled", "warning")
                    break

                final_state = state

                # Emit chunk to GUI
                if chunk:
                    self.signals.stream_chunk.emit(chunk)

                    # Process for TTS - detect sentences
                    if tts_enabled:
                        sentences = sentence_buffer.add_chunk(chunk)
                        for sentence_text, is_speakable in sentences:
                            if is_speakable and sentence_text.strip():
                                queue_tts_sentence(sentence_text, voice_id)

            # Check if streaming completed successfully
            log_info("Streaming loop exited, checking result...", prefix="📨")
            if final_state is None:
                log_error("final_state is None - streaming yielded nothing!", prefix="📨")
                self.signals.update_status.emit("Streaming error", StatusManager.STATUS_ERROR)
                self.signals.stream_complete.emit("")
                return
            elif final_state.stop_reason == "error":
                error_msg = getattr(final_state, '_error_message', 'unknown error')
                error_type = getattr(final_state, '_error_type', None)
                log_error(f"Streaming ended with error ({error_type}): {error_msg}", prefix="📨")

                # Both models unavailable — schedule deferred retry
                if error_type == "both_models_unavailable":
                    self._schedule_deferred_retry(user_input, source="gui")
                    self.signals.stream_complete.emit(
                        "\u26a0 Both models are currently unavailable. Will retry automatically in 20 minutes."
                    )
                else:
                    self.signals.update_status.emit("Streaming error", StatusManager.STATUS_ERROR)
                    self.signals.stream_complete.emit("")
                return

            log_info(f"Streaming completed successfully: {len(final_state.text)} chars, stop_reason={final_state.stop_reason}", prefix="📨")

            # Emit stream complete to process panel
            token_detail = ""
            if final_state.output_tokens:
                token_detail = f"{final_state.output_tokens} tokens"
            get_process_event_bus().emit_event(
                ProcessEventType.STREAM_COMPLETE,
                detail=token_detail,
                round_number=1
            )

            # Emit server-side tool calls (web_search, web_fetch) to process panel
            # These are not in tool_calls so they won't be emitted by process_with_tools()
            if final_state.server_tool_details:
                from agency.tools.response_helper import _build_tool_detail
                for st in final_state.server_tool_details:
                    tool_detail = _build_tool_detail(st.get("name", ""), st.get("input", {}))
                    get_process_event_bus().emit_event(
                        ProcessEventType.TOOL_INVOKED,
                        detail=tool_detail,
                        round_number=1
                    )

            # Record the streaming response for prompt export
            self._round_recorder.record_response(
                response_text=final_state.text,
                thinking_text=final_state.thinking_text,
                tool_calls=final_state.tool_calls,
                raw_content=final_state.raw_content,
                stop_reason=final_state.stop_reason or "",
                tokens_in=final_state.input_tokens,
                tokens_out=final_state.output_tokens,
            )

            # Log thinking in dev mode
            if final_state.thinking_text and config.DEV_MODE_ENABLED:
                log_info(f"Thinking ({len(final_state.thinking_text)} chars): {final_state.thinking_text[:500]}...", prefix="🧠")

            # Flush any remaining TTS content
            if tts_enabled:
                remaining = sentence_buffer.flush()
                for sentence_text, is_speakable in remaining:
                    if is_speakable and sentence_text.strip():
                        queue_tts_sentence(sentence_text, voice_id)

            # Get the full streamed text
            streamed_text = final_state.text
            final_text = streamed_text

            # Check for tool calls and process them
            if final_state.has_tool_calls():
                # Process tool calls using non-streaming continuation
                # Convert streaming state to response format for tool processing
                from llm.router import LLMResponse, LLMProvider

                # Build a response object from streaming state
                response = LLMResponse(
                    text=final_state.text,
                    success=True,
                    provider=LLMProvider.ANTHROPIC,
                    tokens_in=final_state.input_tokens,
                    tokens_out=final_state.output_tokens,
                    stop_reason=final_state.stop_reason,
                    tool_calls=final_state.tool_calls,
                    raw_content=final_state.raw_content,
                    web_searches_used=final_state.web_searches_used,
                    citations=final_state.citations,
                    server_tool_details=final_state.server_tool_details,
                    thinking_text=final_state.thinking_text
                )

                max_passes = getattr(config, 'COMMAND_MAX_PASSES', 15)

                # Set up dev callbacks
                dev_callbacks = None
                if config.DEV_MODE_ENABLED:
                    from interface.dev_window import emit_response_pass, emit_command_executed
                    dev_callbacks = {
                        "emit_response_pass": emit_response_pass,
                        "emit_command_executed": emit_command_executed
                    }

                # Process tools (uses non-streaming for continuations)
                from agency.tools import process_with_tools
                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=max_passes,
                    pulse_callback=lambda interval: self._emit_pulse_interval_change(interval),
                    tools=tools,
                    dev_mode_callbacks=dev_callbacks,
                    thinking_enabled=True,
                    round_recorder=self._round_recorder
                )

                final_text = result.final_text

                # If tool processing added more text, queue it for TTS
                if tts_enabled and final_text != streamed_text:
                    additional_text = final_text[len(streamed_text):]
                    if additional_text.strip():
                        # Process additional text through sentence buffer
                        add_buffer = SentenceBuffer()
                        sentences = add_buffer.add_chunk(additional_text)
                        sentences.extend(add_buffer.flush())
                        for sentence_text, is_speakable in sentences:
                            if is_speakable and sentence_text.strip():
                                queue_tts_sentence(sentence_text, voice_id)

                # Check for clarification request
                if result.clarification_requested and result.clarification_data:
                    timestamp = self._get_timestamp()
                    self.signals.show_clarification.emit(result.clarification_data, timestamp)

            # Strip any temporal markers the LLM echoed from prompt context
            from core.temporal import strip_temporal_echoes
            final_text = strip_temporal_echoes(final_text)

            # Store response
            log_info(f"Storing assistant response ({len(final_text)} chars)", prefix="📨")
            self._conversation_mgr.add_turn(
                role="assistant",
                content=final_text,
                input_type="text"
            )

            # Finalize streaming display
            log_info("Emitting stream_complete with final text", prefix="📨")
            self.signals.stream_complete.emit(final_text)
            log_info("=== _process_message COMPLETE ===", prefix="📨")

            # Emit processing complete to process panel
            get_process_event_bus().emit_event(ProcessEventType.PROCESSING_COMPLETE)

        except Exception as e:
            error_msg = f"Message processing error: {str(e)}"
            tb = traceback.format_exc()
            log_error(f"=== _process_message EXCEPTION ===", prefix="📨")
            log_error(f"Exception in _process_message: {error_msg}", prefix="📨")
            log_error(f"Exception type: {type(e).__name__}", prefix="📨")
            log_error(f"Traceback:\n{tb}", prefix="📨")
            self.signals.update_status.emit(f"Error: {str(e)}", StatusManager.STATUS_ERROR)
            self.signals.stream_complete.emit("")

            # Emit error to process panel
            get_process_event_bus().emit_event(
                ProcessEventType.PROCESSING_ERROR, detail=str(e)
            )

        finally:
            log_info("_process_message finally block - emitting response_complete", prefix="📨")
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
                tools=tools,
                thinking_enabled=True
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
                temperature=0.7,
                thinking_enabled=True
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
        self.pulse_now_btn.setEnabled(True)
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

        # Cancel any pending deferred retry (user has moved on)
        if self._retry_manager.has_pending():
            self._retry_manager.cancel()
            log_info("Deferred retry cancelled - Telegram message received", prefix="🔄")

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

        # Emit to process panel
        get_process_event_bus().emit_event(ProcessEventType.TELEGRAM_RECEIVED, origin="user")

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

            # Get conversation history (uses saved context count from shutdown)
            history = self._conversation_mgr.get_api_messages()

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

            # Inject relevant memories as prefix to user message (API-only, not stored in DB)
            relevant_memories = assembled.session_context.get("relevant_memories")
            if relevant_memories:
                content = user_message.get("content")
                if isinstance(content, str):
                    user_message["content"] = f"{relevant_memories}\n\n{content}"
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            block["text"] = f"{relevant_memories}\n\n{block.get('text', '')}"
                            break

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
                tools=tools,  # Enable native tools for Telegram responses
                thinking_enabled=True
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
                    dev_mode_callbacks=dev_callbacks,
                    thinking_enabled=True
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
                # Check for clarification request
                if result.clarification_requested and result.clarification_data:
                    self.signals.show_clarification.emit(result.clarification_data, timestamp)
                    if final_text.strip():
                        self.signals.new_message.emit("assistant", f"📱 {final_text}", timestamp)
                else:
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
                # Check if both models are down — schedule deferred retry
                if getattr(response, 'error_type', None) == "both_models_unavailable":
                    self._schedule_deferred_retry(message.text, source="telegram")
                    # Notify user via GUI
                    timestamp = self._get_timestamp()
                    self.signals.new_message.emit(
                        "system",
                        "\u26a0 Both models are currently unavailable. Will retry automatically in 20 minutes.",
                        timestamp
                    )
                    # Notify via Telegram too
                    try:
                        if config.TELEGRAM_ENABLED:
                            from communication.telegram_gateway import get_telegram_gateway
                            gateway = get_telegram_gateway()
                            if gateway.is_available():
                                gateway.send("\u26a0 Both models are currently unavailable. Will retry in 20 minutes.")
                    except Exception:
                        pass
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
            get_process_event_bus().emit_event(ProcessEventType.PROCESSING_COMPLETE)
            self.signals.response_complete.emit()

    def _schedule_deferred_retry(self, original_input: str, source: str = "gui"):
        """
        Schedule a deferred retry when both models are unavailable.

        The retry will re-process the original message through the normal flow
        after a delay. It is automatically cancelled if the user sends a new
        message before the timer fires.

        Args:
            original_input: The original user input text to retry
            source: "gui" or "telegram" — determines how the retry is processed
        """
        def retry_callback():
            self._process_deferred_retry(original_input, source)

        self._retry_manager.schedule(callback=retry_callback, source=source)

    def _process_deferred_retry(self, original_input: str, source: str):
        """
        Process a deferred retry attempt.

        Re-runs the original message through the normal message flow.
        If it fails again, gives up silently (single retry only).
        """
        log_info(f"Processing deferred retry for source={source}", prefix="🔄")

        # Don't retry if already processing something
        if self._is_processing:
            log_warning("Deferred retry skipped - already processing a message")
            return

        if source == "telegram":
            self._process_deferred_telegram_retry(original_input)
        else:
            self._process_deferred_gui_retry(original_input)

    def _process_deferred_gui_retry(self, original_input: str):
        """Process a deferred GUI message retry in a background thread."""
        from llm.router import TaskType
        from agency.tools import get_tool_definitions, process_with_tools

        self._is_processing = True

        try:
            # Pause timers
            if self._system_pulse_timer:
                self._system_pulse_timer.pause()
            if self._telegram_listener:
                self._telegram_listener.pause()

            self.signals.update_status.emit("Retrying message...", StatusManager.STATUS_THINKING)

            # Show retry notification in chat
            timestamp = self._get_timestamp()
            self.signals.new_message.emit("system", "[Retrying previously failed message]", timestamp)

            # Rebuild prompt and history fresh
            assembled = self._prompt_builder.build(
                user_input=original_input,
                system_prompt=""
            )

            history = self._conversation_mgr.get_api_messages()
            user_message = self._capture_visuals_for_message(original_input)

            # Inject relevant memories
            relevant_memories = assembled.session_context.get("relevant_memories")
            if relevant_memories:
                content = user_message.get("content")
                if isinstance(content, str):
                    user_message["content"] = f"{relevant_memories}\n\n{content}"

            history.append(user_message)
            tools = get_tool_definitions()

            # Use non-streaming for retry (simpler, and user isn't actively watching)
            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools,
                thinking_enabled=True
            )

            if response.success:
                # Process tool calls if any
                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=5,
                    pulse_callback=lambda interval: self._emit_pulse_interval_change(interval),
                    tools=tools,
                    thinking_enabled=True
                )

                final_text = result.final_text

                # Prepend deferred notice
                notice = "\u26a0 Delayed response to your earlier message:\n\n"
                final_text = notice + final_text

                # Store and display
                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=final_text,
                    input_type="text"
                )
                timestamp = self._get_timestamp()
                self.signals.new_message.emit("assistant", final_text, timestamp)
                log_info("Deferred GUI retry succeeded", prefix="🔄")
            else:
                log_warning(f"Deferred GUI retry also failed: {response.error}")
                timestamp = self._get_timestamp()
                self.signals.new_message.emit(
                    "system",
                    "[Retry failed — models still unavailable]",
                    timestamp
                )

        except Exception as e:
            log_error(f"Deferred GUI retry exception: {e}")
            timestamp = self._get_timestamp()
            self.signals.new_message.emit(
                "system",
                "[Retry failed — unexpected error]",
                timestamp
            )

        finally:
            self.signals.response_complete.emit()

    def _process_deferred_telegram_retry(self, original_input: str):
        """Process a deferred Telegram message retry."""
        from llm.router import TaskType
        from agency.tools import get_tool_definitions, process_with_tools

        self._is_processing = True

        try:
            # Pause timers
            if self._system_pulse_timer:
                self._system_pulse_timer.pause()
            if self._telegram_listener:
                self._telegram_listener.pause()

            self.signals.update_status.emit("Retrying Telegram message...", StatusManager.STATUS_THINKING)

            # Rebuild prompt and history fresh
            assembled = self._prompt_builder.build(
                user_input=original_input,
                system_prompt=""
            )

            history = self._conversation_mgr.get_api_messages()
            user_message = {"role": "user", "content": original_input}

            # Inject relevant memories
            relevant_memories = assembled.session_context.get("relevant_memories")
            if relevant_memories:
                user_message["content"] = f"{relevant_memories}\n\n{original_input}"

            history.append(user_message)
            tools = get_tool_definitions()

            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools,
                thinking_enabled=True
            )

            if response.success:
                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=5,
                    pulse_callback=lambda interval: self._emit_pulse_interval_change(interval),
                    tools=tools,
                    thinking_enabled=True
                )

                final_text = result.final_text
                notice = "\u26a0 Delayed response to your earlier message:\n\n"
                final_text = notice + final_text

                # Store response
                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=final_text,
                    input_type="text"
                )

                # Display in GUI
                timestamp = self._get_timestamp()
                self.signals.new_message.emit("assistant", f"📱 {final_text}", timestamp)

                # Send to Telegram
                if not result.telegram_sent:
                    try:
                        if config.TELEGRAM_ENABLED:
                            from communication.telegram_gateway import get_telegram_gateway
                            gateway = get_telegram_gateway()
                            if gateway.is_available():
                                gateway.send(final_text)
                    except Exception as e:
                        log_warning(f"Failed to send deferred retry response to Telegram: {e}")

                log_info("Deferred Telegram retry succeeded", prefix="🔄")
            else:
                log_warning(f"Deferred Telegram retry also failed: {response.error}")
                # Notify via Telegram
                try:
                    if config.TELEGRAM_ENABLED:
                        from communication.telegram_gateway import get_telegram_gateway
                        gateway = get_telegram_gateway()
                        if gateway.is_available():
                            gateway.send("[Retry failed — models still unavailable]")
                except Exception:
                    pass

        except Exception as e:
            log_error(f"Deferred Telegram retry exception: {e}")

        finally:
            self.signals.response_complete.emit()

    def _on_pulse_now_clicked(self):
        """Handle Pulse Now button click — fire a pulse immediately."""
        if self._is_processing:
            return
        # Reset the countdown so it restarts from the full interval after this pulse
        if self._system_pulse_timer:
            self._system_pulse_timer.reset()
        self._on_pulse_fired()

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

        # Emit to process panel with interval detail
        get_process_event_bus().emit_event(
            ProcessEventType.PULSE_FIRED,
            detail="Choosing what to do",
            origin="isaac"
        )

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
            get_process_event_bus().emit_event(ProcessEventType.PROMPT_ASSEMBLED)

            # Get conversation history (uses saved context count from shutdown)
            history = self._conversation_mgr.get_api_messages()

            # Add the pulse prompt as the message to respond to
            # (role="user" is an API constraint, but content clarifies it's automated)
            # No screenshots during pulse — the AI's autonomous moment should focus
            # on introspection, curiosity, and intentions, not whatever is on screen.
            # The AI can still request screenshots on-demand via [[SCREENSHOT]] if needed.
            history.append({"role": "user", "content": pulse_prompt})

            # Get tool definitions for native tool use (pulse-only tools included)
            tools = get_tool_definitions(is_pulse=True)

            # Get LLM response WITH tools enabled
            from llm.router import TaskType

            get_process_event_bus().emit_event(
                ProcessEventType.STREAM_START, is_active=True
            )
            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools,  # Enable native tools for pulse responses
                thinking_enabled=True
            )

            log_info(f"PULSE: Router returned, success={response.success}", prefix="⏱️")

            # Emit initial response to process panel
            if response.success:
                token_detail = ""
                if hasattr(response, 'tokens_out') and response.tokens_out:
                    token_detail = f"{response.tokens_out} tokens"
                get_process_event_bus().emit_event(
                    ProcessEventType.STREAM_COMPLETE,
                    detail=token_detail,
                    round_number=1
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
                # The helper handles multi-pass tool execution and pulse interval changes
                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=5,
                    pulse_callback=lambda interval: self._emit_pulse_interval_change(interval),
                    tools=tools,
                    dev_mode_callbacks=dev_callbacks,
                    thinking_enabled=True
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
                # Check for clarification request
                if result.clarification_requested and result.clarification_data:
                    self.signals.show_clarification.emit(result.clarification_data, timestamp)
                    if final_text.strip():
                        self.signals.new_message.emit("assistant", final_text, timestamp)
                else:
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
            get_process_event_bus().emit_event(ProcessEventType.PROCESSING_COMPLETE)
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

        # Emit to process panel with reminder details
        reminder_detail = ""
        if triggered_intentions:
            previews = []
            for intention in triggered_intentions:
                content = getattr(intention, 'content', '')
                if content:
                    previews.append(content[:50])
            reminder_detail = "; ".join(previews) if previews else ""
        get_process_event_bus().emit_event(
            ProcessEventType.REMINDER_FIRED,
            detail=reminder_detail,
            origin="isaac"
        )

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

            # Get conversation history (uses saved context count from shutdown)
            history = self._conversation_mgr.get_api_messages()

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
                tools=tools,  # Enable native tools for reminder responses
                thinking_enabled=True
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
                    dev_mode_callbacks=dev_callbacks,
                    thinking_enabled=True
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
                # Check for clarification request
                if result.clarification_requested and result.clarification_data:
                    self.signals.show_clarification.emit(result.clarification_data, timestamp)
                    if final_text.strip():
                        self.signals.new_message.emit("assistant", final_text, timestamp)
                else:
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
            get_process_event_bus().emit_event(ProcessEventType.PROCESSING_COMPLETE)
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
        self.font_spin.setRange(10, 24)
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
            self.parent().chat_display.setFont(QFont(UI_FONT_FAMILY, font_size))
            self.parent().input_field.setFont(QFont(UI_FONT_FAMILY, font_size))
            self.parent()._update_font_tooltips()

        # TTS settings
        self._user_settings.tts_enabled = self.tts_enabled_check.isChecked()
        self._user_settings.tts_voice_id = self.voice_id_input.text().strip()

        log_info(f"Settings applied - TTS: {self._user_settings.tts_enabled}, Voice: {self._user_settings.tts_voice_id}", prefix="⚙️")


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

    # Shutdown TTS system (stops playback and terminates worker process)
    try:
        from tts.player import shutdown_tts
        shutdown_tts()
    except Exception:
        pass  # Ignore errors during shutdown

    return exit_code


if __name__ == "__main__":
    sys.exit(run_gui())
