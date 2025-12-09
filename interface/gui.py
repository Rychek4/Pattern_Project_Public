"""
Pattern Project - PyQt5 Chat GUI
Version: 0.1.0

A visual chat interface with timestamps, session tracking,
and system pulse countdown.
"""

import sys
import re
import html
import queue
import threading
import traceback
from datetime import datetime, timedelta
from typing import Optional, Callable

import config
from core.logger import log_info, log_error, log_warning

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTextBrowser, QTextEdit, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton, QLineEdit, QLabel, QDialog, QSlider, QCheckBox,
    QSpinBox, QMessageBox, QFrame, QSizePolicy, QComboBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette


# Color scheme (dark theme matching the prototype)
COLORS = {
    "background": "#1a1a2e",
    "surface": "#16213e",
    "primary": "#0f3460",
    "accent": "#e94560",
    "text": "#eaeaea",
    "text_dim": "#888888",
    "user": "#4ade80",      # Green for user messages
    "assistant": "#60a5fa", # Blue for AI messages
    "system": "#f59e0b",    # Amber for system messages
    "timestamp": "#6b7280", # Gray for timestamps
    "pulse": "#a855f7",     # Purple for pulse countdown
    "action": "#c4a7e7",    # Soft purple for AI action text (*action*)
}


class MessageSignals(QObject):
    """Signals for thread-safe message passing to GUI."""
    new_message = pyqtSignal(str, str, str)  # role, content, timestamp
    update_status = pyqtSignal(str)
    update_timer = pyqtSignal(str, str)  # session_time, total_time
    response_complete = pyqtSignal()
    pulse_interval_change = pyqtSignal(int)  # new interval in seconds


class ChatInputWidget(QTextEdit):
    """Multi-line chat input with Enter to send, Shift+Enter for newline.

    Features:
    - Auto-expands up to 5x single line height
    - Enter key sends message (emits send_requested signal)
    - Shift+Enter inserts a newline
    - Plain text only (no rich text)
    """

    send_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setAcceptRichText(False)
        self.setPlaceholderText("Type a message...")

        # Calculate single line height for auto-expand limits
        font_metrics = self.fontMetrics()
        self._single_line_height = font_metrics.lineSpacing() + 16  # Add padding
        self._max_height = self._single_line_height * 5

        # Set initial size
        self.setMinimumHeight(self._single_line_height)
        self.setMaximumHeight(self._single_line_height)

        # Connect text changes to auto-resize
        self.textChanged.connect(self._auto_resize)

    def setFont(self, font: QFont):
        """Override to recalculate line height when font changes."""
        super().setFont(font)
        font_metrics = self.fontMetrics()
        self._single_line_height = font_metrics.lineSpacing() + 16
        self._max_height = self._single_line_height * 5
        self.setMinimumHeight(self._single_line_height)
        self._auto_resize()

    def _auto_resize(self):
        """Auto-resize based on content, up to max height."""
        doc = self.document()
        doc_height = doc.size().height() + 16  # Add padding

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

    def clear(self):
        """Clear and reset to single line height."""
        super().clear()
        self.setMaximumHeight(self._single_line_height)


class ChatWindow(QMainWindow):
    """
    Main chat window with:
    - Header: Session timer, controls
    - Chat display: Rich HTML with timestamps and scores
    - Input: Text entry with send button
    """

    def __init__(self):
        super().__init__()
        self.signals = MessageSignals()
        self._setup_signals()

        # State
        self._session_start: Optional[datetime] = None
        self._first_session_start: Optional[datetime] = None
        self._is_processing = False
        self._message_queue = queue.Queue()

        # Backend references (set during initialization)
        self._conversation_mgr = None
        self._llm_router = None
        self._prompt_builder = None
        self._temporal_tracker = None
        self._system_pulse_timer = None

        self._setup_ui()
        self._setup_timers()
        self._apply_style()

    def _setup_signals(self):
        """Connect signals to slots."""
        self.signals.new_message.connect(self._append_message)
        self.signals.update_status.connect(self._update_status)
        self.signals.update_timer.connect(self._update_timer_display)
        self.signals.response_complete.connect(self._on_response_complete)
        self.signals.pulse_interval_change.connect(self.set_pulse_interval_by_seconds)

    def _setup_ui(self):
        """Create the UI layout."""
        self.setWindowTitle("Pattern Project")
        self.setMinimumSize(700, 500)

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
        self.chat_display.setOpenExternalLinks(False)
        self.chat_display.setFont(QFont("Consolas", 12))
        layout.addWidget(self.chat_display, stretch=1)

        # Input area
        input_frame = self._create_input_area()
        layout.addWidget(input_frame)

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px;")
        layout.addWidget(self.status_label)

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
        """Apply dark theme styling."""
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {COLORS['background']};
            }}
            QFrame {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['primary']};
                border-radius: 5px;
            }}
            QTextBrowser {{
                background-color: {COLORS['surface']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['primary']};
                border-radius: 5px;
                padding: 10px;
            }}
            QLineEdit {{
                background-color: {COLORS['surface']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['primary']};
                border-radius: 5px;
                padding: 8px;
            }}
            QLineEdit:focus {{
                border: 1px solid {COLORS['accent']};
            }}
            QTextEdit {{
                background-color: {COLORS['surface']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['primary']};
                border-radius: 5px;
                padding: 8px;
            }}
            QTextEdit:focus {{
                border: 1px solid {COLORS['accent']};
            }}
            QPushButton {{
                background-color: {COLORS['primary']};
                color: {COLORS['text']};
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent']};
            }}
            QPushButton:checked {{
                background-color: {COLORS['accent']};
            }}
            QLabel {{
                color: {COLORS['text']};
            }}
            QComboBox {{
                background-color: {COLORS['surface']};
                color: {COLORS['pulse']};
                border: 1px solid {COLORS['primary']};
                border-radius: 5px;
                padding: 4px 8px;
                min-width: 80px;
            }}
            QComboBox:hover {{
                border: 1px solid {COLORS['pulse']};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['surface']};
                color: {COLORS['text']};
                selection-background-color: {COLORS['primary']};
            }}
        """)

    def set_backend(
        self,
        conversation_mgr,
        llm_router,
        prompt_builder,
        temporal_tracker,
        system_pulse_timer=None
    ):
        """Set backend references for communication."""
        self._conversation_mgr = conversation_mgr
        self._llm_router = llm_router
        self._prompt_builder = prompt_builder
        self._temporal_tracker = temporal_tracker
        self._system_pulse_timer = system_pulse_timer

        # Set up pulse callback if timer is provided
        if self._system_pulse_timer:
            self._system_pulse_timer.set_callback(self._on_pulse_fired)

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

    def set_pulse_interval_by_seconds(self, seconds: int):
        """Set the pulse interval and update dropdown to match.

        Used when AI changes the interval via [[PULSE:Xm]] command.
        """
        # Map seconds to dropdown index
        seconds_to_index = {
            180: 0,    # 3 min
            600: 1,    # 10 min
            1800: 2,   # 30 min
            3600: 3,   # 1 hour
            21600: 4,  # 6 hours
        }

        index = seconds_to_index.get(seconds)
        if index is not None:
            # Block signals to avoid triggering _on_pulse_interval_changed twice
            self.pulse_dropdown.blockSignals(True)
            self.pulse_dropdown.setCurrentIndex(index)
            self.pulse_dropdown.blockSignals(False)

            # Update the timer
            if self._system_pulse_timer:
                old_interval = self._system_pulse_timer.pulse_interval
                self._system_pulse_timer.pulse_interval = seconds
                self._system_pulse_timer.reset()

                # Log the change
                from prompt_builder.sources.system_pulse import get_interval_label
                old_label = get_interval_label(old_interval)
                new_label = get_interval_label(seconds)
                log_info(f"AI adjusted pulse timer: {old_label} -> {new_label}", prefix="⏱️")

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
        # Color based on role
        if role == "user":
            color = COLORS['user']
            prefix = "You"
        elif role == "assistant":
            color = COLORS['assistant']
            prefix = "AI"
        else:
            color = COLORS['system']
            prefix = "System"

        # Format content with all text formatting (bold, italic, code, etc.)
        formatted_content = self._format_message_text(content, role)

        # Build HTML (using msg_html to avoid shadowing html module)
        msg_html = f"""
        <div style='margin-bottom: 10px;'>
            <span style='color:{COLORS['timestamp']};'>[{timestamp}]</span>
            <span style='color:{color}; font-weight:bold;'>{prefix}:</span>
            <br/>
            <span style='color:{COLORS['text']}; margin-left: 20px;'>{formatted_content}</span>
        </div>
        """

        self.chat_display.append(msg_html)
        self.chat_display.moveCursor(QTextCursor.End)

    def _send_message(self):
        """Handle sending a message."""
        text = self.input_field.toPlainText().strip()
        if not text or self._is_processing:
            return

        self.input_field.clear()
        self._is_processing = True
        self.send_btn.setEnabled(False)
        self.status_label.setText("Thinking...")

        # Reset and pause the pulse timer (user is active)
        if self._system_pulse_timer:
            self._system_pulse_timer.reset()
            self._system_pulse_timer.pause()

        # Add user message to display immediately
        timestamp = self._get_timestamp()
        self.signals.new_message.emit("user", text, timestamp)

        # Process in background thread
        thread = threading.Thread(
            target=self._process_message,
            args=(text,),
            daemon=True
        )
        thread.start()

    def _process_message(self, user_input: str):
        """Process a message in background thread."""
        import time

        try:
            # Store user message
            if self._conversation_mgr:
                self._conversation_mgr.add_turn(
                    role="user",
                    content=user_input,
                    input_type="text"
                )

            # Build prompt (no base prompt - emergent personality from context)
            assembled = self._prompt_builder.build(
                user_input=user_input,
                system_prompt=""
            )

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

            # Get conversation history
            history = self._conversation_mgr.get_recent_history(limit=30)

            # Get LLM response
            from llm.router import TaskType
            start_time = time.time()
            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7
            )
            pass1_duration = (time.time() - start_time) * 1000

            if response.success:
                from agency.commands import get_command_processor

                processor = get_command_processor()
                max_passes = getattr(config, 'COMMAND_MAX_PASSES', 3)

                # Check initial response for pulse timer command
                pulse_interval = self._parse_pulse_command(response.text)
                if pulse_interval is not None:
                    self.signals.pulse_interval_change.emit(pulse_interval)

                # Multi-pass command processing loop
                current_text = response.text
                current_history = history.copy()
                pass_num = 1
                current_duration = pass1_duration

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
                        final_text = processed.display_text
                        break

                    # Show status for command execution
                    if pass_num == 1:
                        self.signals.update_status.emit("Executing command...")
                    else:
                        self.signals.update_status.emit(f"Executing command (pass {pass_num})...")

                    # Build continuation history
                    current_history.append({"role": "assistant", "content": current_text})
                    current_history.append({"role": "user", "content": processed.continuation_prompt})

                    # Get next response
                    cont_start = time.time()
                    continuation = self._llm_router.chat(
                        messages=current_history,
                        system_prompt=assembled.full_system_prompt,
                        task_type=TaskType.CONVERSATION,
                        temperature=0.7
                    )
                    current_duration = (time.time() - cont_start) * 1000

                    if not continuation.success:
                        # On failure, use last successful response
                        final_text = processed.display_text
                        break

                    # Check continuation for pulse commands
                    pulse_interval = self._parse_pulse_command(continuation.text)
                    if pulse_interval is not None:
                        self.signals.pulse_interval_change.emit(pulse_interval)

                    # Prepare for next iteration
                    current_text = continuation.text
                    pass_num += 1
                else:
                    # Hit max passes - use final response as-is
                    processed = processor.process(current_text)
                    final_text = processed.display_text

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
                self.signals.update_status.emit(f"Error: {response.error}")

        except Exception as e:
            error_msg = f"Message processing error: {str(e)}"
            tb = traceback.format_exc()
            log_error(f"Exception in _process_message: {error_msg}")
            log_error(f"Traceback:\n{tb}")
            self.signals.update_status.emit(f"Error: {str(e)}")

        finally:
            self.signals.response_complete.emit()

    def _on_response_complete(self):
        """Called when response processing is complete."""
        self._is_processing = False
        self.send_btn.setEnabled(True)
        self.status_label.setText("Ready")

        # Resume the pulse timer
        if self._system_pulse_timer:
            self._system_pulse_timer.resume()

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
        """Process a system pulse in background thread."""
        from agency.system_pulse import get_pulse_prompt, PULSE_STORED_MESSAGE
        from prompt_builder.sources.system_pulse import get_interval_label

        # Get dynamic pulse prompt with current interval
        current_interval = self._system_pulse_timer.pulse_interval if self._system_pulse_timer else 600
        interval_label = get_interval_label(current_interval)
        pulse_prompt = get_pulse_prompt(interval_label)

        log_info("=== PULSE DEBUG: Starting _process_pulse() ===", prefix="🔍")

        try:
            self._is_processing = True
            log_info("PULSE DEBUG: Set _is_processing = True", prefix="🔍")

            # Pause timer during processing
            if self._system_pulse_timer:
                self._system_pulse_timer.pause()
                log_info("PULSE DEBUG: Timer paused", prefix="🔍")

            # Update UI status
            self.signals.update_status.emit("System pulse...")

            # Show system message in chat
            timestamp = self._get_timestamp()
            self.signals.new_message.emit("system", PULSE_STORED_MESSAGE, timestamp)
            log_info("PULSE DEBUG: Emitted [System Pulse] to chat", prefix="🔍")

            # Store abbreviated pulse message in conversation history
            if self._conversation_mgr:
                self._conversation_mgr.add_turn(
                    role="system",
                    content=PULSE_STORED_MESSAGE,
                    input_type="system"
                )
                log_info("PULSE DEBUG: Added pulse turn to conversation", prefix="🔍")
            else:
                log_error("PULSE DEBUG: _conversation_mgr is None!")

            # Build prompt with full pulse message
            log_info("PULSE DEBUG: Building prompt...", prefix="🔍")
            assembled = self._prompt_builder.build(
                user_input=pulse_prompt,
                system_prompt=""
            )
            log_info(f"PULSE DEBUG: Prompt built, system_prompt length: {len(assembled.full_system_prompt)}", prefix="🔍")

            # Get conversation history
            log_info("PULSE DEBUG: Getting conversation history...", prefix="🔍")
            history = self._conversation_mgr.get_recent_history(limit=30)
            log_info(f"PULSE DEBUG: Got {len(history)} messages in history", prefix="🔍")

            # Log history details for debugging
            if history:
                for i, msg in enumerate(history[-3:]):  # Last 3 messages
                    role = msg.get('role', 'unknown')
                    content_preview = msg.get('content', '')[:50]
                    log_info(f"PULSE DEBUG: History[-{len(history)-i}]: {role}: {content_preview}...", prefix="🔍")

            # Add the pulse prompt as the message to respond to
            # (role="user" is an API constraint, but content clarifies it's automated)
            history.append({"role": "user", "content": pulse_prompt})
            log_info(f"PULSE DEBUG: Added pulse_prompt to history, now {len(history)} messages", prefix="🔍")

            # Get LLM response
            log_info("PULSE DEBUG: About to call _llm_router.chat()...", prefix="🔍")
            from llm.router import TaskType

            log_info(f"PULSE DEBUG: Router type: {type(self._llm_router)}", prefix="🔍")
            log_info(f"PULSE DEBUG: TaskType: {TaskType.CONVERSATION}", prefix="🔍")

            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7
            )

            log_info(f"PULSE DEBUG: Router returned! success={response.success}, provider={response.provider}", prefix="🔍")

            if response.success:
                from agency.commands import get_command_processor

                log_info(f"PULSE DEBUG: Response successful, text length: {len(response.text)}", prefix="🔍")

                # Check for pulse timer command in response
                pulse_interval = self._parse_pulse_command(response.text)
                if pulse_interval is not None:
                    self.signals.pulse_interval_change.emit(pulse_interval)

                # Process response for AI commands
                processor = get_command_processor()
                processed = processor.process(response.text)

                # Handle continuation if commands need results
                final_text = processed.display_text

                if processed.needs_continuation:
                    self.signals.update_status.emit("Executing command...")

                    # Build continuation
                    continuation_history = history.copy()
                    continuation_history.append({"role": "assistant", "content": response.text})
                    continuation_history.append({"role": "user", "content": processed.continuation_prompt})

                    continuation = self._llm_router.chat(
                        messages=continuation_history,
                        system_prompt=assembled.full_system_prompt,
                        task_type=TaskType.CONVERSATION,
                        temperature=0.7
                    )

                    if continuation.success:
                        # Check continuation for pulse commands too
                        pulse_interval = self._parse_pulse_command(continuation.text)
                        if pulse_interval is not None:
                            self.signals.pulse_interval_change.emit(pulse_interval)
                        final_text = continuation.text

                # Store response
                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=final_text,
                    input_type="text"
                )

                # Emit to GUI
                timestamp = self._get_timestamp()
                self.signals.new_message.emit("assistant", final_text, timestamp)
                log_info("PULSE DEBUG: Emitted assistant response to chat", prefix="🔍")
            else:
                error_msg = f"Pulse API error: {response.error}"
                log_error(f"PULSE DEBUG: API call failed - {error_msg}")

                # Show error in CHAT (not just status bar) so it's visible
                timestamp = self._get_timestamp()
                self.signals.new_message.emit("system", f"[Pulse Error: {response.error}]", timestamp)
                self.signals.update_status.emit(error_msg)

        except Exception as e:
            error_msg = f"Pulse exception: {str(e)}"
            tb = traceback.format_exc()
            log_error(f"PULSE DEBUG: Exception caught!")
            log_error(f"PULSE DEBUG: {error_msg}")
            log_error(f"PULSE DEBUG: Traceback:\n{tb}")

            # Show error in CHAT (not just status bar) so it's visible
            timestamp = self._get_timestamp()
            self.signals.new_message.emit("system", f"[Pulse Exception: {str(e)}]", timestamp)
            self.signals.update_status.emit(error_msg)

        finally:
            log_info("=== PULSE DEBUG: _process_pulse() completing ===", prefix="🔍")
            self.signals.response_complete.emit()

    def _update_status(self, status: str):
        """Update status bar."""
        self.status_label.setText(status)

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
    """Settings dialog for font size, etc."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)

        # Font size
        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("Font Size:"))
        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 24)
        self.font_spin.setValue(12)
        font_layout.addWidget(self.font_spin)
        layout.addLayout(font_layout)

        # Apply button
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_settings)
        layout.addWidget(apply_btn)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _apply_settings(self):
        """Apply settings."""
        if self.parent():
            font_size = self.font_spin.value()
            self.parent().chat_display.setFont(QFont("Consolas", font_size))


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

    # Initialize remaining components
    print("Initializing components...")
    init_lock_manager()
    init_temporal_tracker()
    init_conversation_manager()
    init_vector_store()
    init_llm_router(
        primary_provider=config.LLM_PRIMARY_PROVIDER,
        fallback_enabled=config.LLM_FALLBACK_ENABLED
    )
    init_memory_extractor()
    init_prompt_builder()
    init_system_pulse_timer()

    # Start system pulse timer if enabled
    pulse_timer = None
    if config.SYSTEM_PULSE_ENABLED:
        pulse_timer = get_system_pulse_timer()
        pulse_timer.start()

    # Create and configure window
    window = init_gui()
    window.set_backend(
        conversation_mgr=get_conversation_manager(),
        llm_router=get_llm_router(),
        prompt_builder=get_prompt_builder(),
        temporal_tracker=get_temporal_tracker(),
        system_pulse_timer=pulse_timer
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

    return exit_code


if __name__ == "__main__":
    sys.exit(run_gui())
