"""
Pattern Project - PyQt5 Chat GUI
Version: 0.1.0

A visual chat interface with timestamps, relationship indicators,
and session tracking.
"""

import sys
import queue
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTextBrowser, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton, QLineEdit, QLabel, QDialog, QSlider, QCheckBox,
    QSpinBox, QMessageBox, QFrame, QSizePolicy
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
    "affinity": "#ef4444",  # Red heart
    "trust": "#22c55e",     # Green shield
    "timestamp": "#6b7280", # Gray for timestamps
}


class MessageSignals(QObject):
    """Signals for thread-safe message passing to GUI."""
    new_message = pyqtSignal(str, str, str, float, float)  # role, content, timestamp, affinity, trust
    update_status = pyqtSignal(str)
    update_timer = pyqtSignal(str, str)  # session_time, total_time
    response_complete = pyqtSignal()


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
        self._current_affinity = 0.0
        self._current_trust = 0.5
        self._message_queue = queue.Queue()

        # Backend references (set during initialization)
        self._conversation_mgr = None
        self._llm_router = None
        self._prompt_builder = None
        self._temporal_tracker = None
        self._relationship_source = None

        self._setup_ui()
        self._setup_timers()
        self._apply_style()

    def _setup_signals(self):
        """Connect signals to slots."""
        self.signals.new_message.connect(self._append_message)
        self.signals.update_status.connect(self._update_status)
        self.signals.update_timer.connect(self._update_timer_display)
        self.signals.response_complete.connect(self._on_response_complete)

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
        """Create the header with timer and controls."""
        header = QFrame()
        header.setFrameStyle(QFrame.StyledPanel)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(10, 5, 10, 5)

        # Session timer
        self.timer_label = QLabel("Session: --:-- | Total: --:--")
        self.timer_label.setFont(QFont("Consolas", 13, QFont.Bold))
        self.timer_label.setStyleSheet(f"color: {COLORS['text']};")
        layout.addWidget(self.timer_label)

        layout.addStretch()

        # Relationship indicators
        self.affinity_label = QLabel("--")
        self.affinity_label.setFont(QFont("Consolas", 12, QFont.Bold))
        self.affinity_label.setToolTip("Affinity (-1.0 to +1.0)")
        layout.addWidget(self.affinity_label)

        self.trust_label = QLabel("--")
        self.trust_label.setFont(QFont("Consolas", 12, QFont.Bold))
        self.trust_label.setToolTip("Trust (0.0 to 1.0)")
        layout.addWidget(self.trust_label)

        layout.addSpacing(20)

        # Control buttons
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setCheckable(True)
        self.pause_btn.clicked.connect(self._toggle_pause)
        layout.addWidget(self.pause_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear_display)
        layout.addWidget(self.clear_btn)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self._show_settings)
        layout.addWidget(self.settings_btn)

        return header

    def _create_input_area(self) -> QFrame:
        """Create the input area with text field and send button."""
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Type a message...")
        self.input_field.setFont(QFont("Consolas", 12))
        self.input_field.returnPressed.connect(self._send_message)
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

        # Relationship state update (every 5 seconds)
        self.relationship_update = QTimer(self)
        self.relationship_update.timeout.connect(self._update_relationship)
        self.relationship_update.start(5000)

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
        """)

        # Update relationship labels with colors
        self._update_relationship_display()

    def set_backend(
        self,
        conversation_mgr,
        llm_router,
        prompt_builder,
        temporal_tracker,
        relationship_source
    ):
        """Set backend references for communication."""
        self._conversation_mgr = conversation_mgr
        self._llm_router = llm_router
        self._prompt_builder = prompt_builder
        self._temporal_tracker = temporal_tracker
        self._relationship_source = relationship_source

        # Start session if not active
        if not temporal_tracker.is_session_active:
            temporal_tracker.start_session()

        self._session_start = datetime.now()
        self._first_session_start = datetime.now()

        # Initial relationship update
        self._update_relationship()

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
        """Update the session timer display."""
        if self._session_start is None:
            return

        session_duration = datetime.now() - self._session_start
        total_duration = datetime.now() - self._first_session_start if self._first_session_start else session_duration

        session_str = self._format_duration(session_duration)
        total_str = self._format_duration(total_duration)

        self.timer_label.setText(f"Session: {session_str} | Total: {total_str}")

    def _update_relationship(self):
        """Update relationship indicators from backend."""
        if self._relationship_source is None:
            return

        try:
            state = self._relationship_source.get_state()
            if state:
                self._current_affinity = state.affinity
                self._current_trust = state.trust
                self._update_relationship_display()
        except Exception:
            pass

    def _update_relationship_display(self):
        """Update the visual relationship indicators."""
        # Affinity: red heart with value
        affinity_val = int(self._current_affinity * 100)
        self.affinity_label.setText(f"<span style='color:{COLORS['affinity']};'>&#10084;</span> {affinity_val}")
        self.affinity_label.setStyleSheet(f"color: {COLORS['text']};")

        # Trust: green shield with value
        trust_val = int(self._current_trust * 100)
        self.trust_label.setText(f"<span style='color:{COLORS['trust']};'>&#128994;</span> {trust_val}")
        self.trust_label.setStyleSheet(f"color: {COLORS['text']};")

    def _get_timestamp(self) -> str:
        """Get current timestamp string."""
        return datetime.now().strftime("%H:%M:%S")

    def _append_message(self, role: str, content: str, timestamp: str, affinity: float, trust: float):
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

        # Build HTML
        affinity_int = int(affinity * 100)
        trust_int = int(trust * 100)

        scores_html = ""
        if role == "assistant":
            scores_html = (
                f"<span style='color:{COLORS['affinity']};'>&#10084;</span>{affinity_int} "
                f"<span style='color:{COLORS['trust']};'>&#128994;</span>{trust_int}"
            )

        html = f"""
        <div style='margin-bottom: 10px;'>
            <span style='color:{COLORS['timestamp']};'>[{timestamp}]</span>
            <span style='color:{color}; font-weight:bold;'>{prefix}:</span>
            {scores_html}
            <br/>
            <span style='color:{COLORS['text']}; margin-left: 20px;'>{content}</span>
        </div>
        """

        self.chat_display.append(html)
        self.chat_display.moveCursor(QTextCursor.End)

    def _send_message(self):
        """Handle sending a message."""
        text = self.input_field.text().strip()
        if not text or self._is_processing:
            return

        self.input_field.clear()
        self._is_processing = True
        self.send_btn.setEnabled(False)
        self.status_label.setText("Thinking...")

        # Add user message to display immediately
        timestamp = self._get_timestamp()
        self.signals.new_message.emit(
            "user", text, timestamp, self._current_affinity, self._current_trust
        )

        # Process in background thread
        thread = threading.Thread(
            target=self._process_message,
            args=(text,),
            daemon=True
        )
        thread.start()

    def _process_message(self, user_input: str):
        """Process a message in background thread."""
        try:
            # Store user message
            if self._conversation_mgr:
                self._conversation_mgr.add_turn(
                    role="user",
                    content=user_input,
                    input_type="text"
                )

            # Build prompt
            system_prompt = """You are a thoughtful AI companion engaged in natural conversation.
Your personality emerges from the context provided - memories, relationship history, and ongoing dialogue.
Be genuine, curious, and responsive to the emotional tone of the conversation."""

            assembled = self._prompt_builder.build(
                user_input=user_input,
                system_prompt=system_prompt
            )

            # Get conversation history
            history = self._conversation_mgr.get_recent_history(limit=30)

            # Get LLM response
            from llm.router import TaskType
            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7
            )

            if response.success:
                # Store response
                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=response.text,
                    input_type="text"
                )

                # Emit to GUI
                timestamp = self._get_timestamp()
                self.signals.new_message.emit(
                    "assistant",
                    response.text,
                    timestamp,
                    self._current_affinity,
                    self._current_trust
                )
            else:
                self.signals.update_status.emit(f"Error: {response.error}")

        except Exception as e:
            self.signals.update_status.emit(f"Error: {str(e)}")

        finally:
            self.signals.response_complete.emit()

    def _on_response_complete(self):
        """Called when response processing is complete."""
        self._is_processing = False
        self.send_btn.setEnabled(True)
        self.status_label.setText("Ready")

    def _update_status(self, status: str):
        """Update status bar."""
        self.status_label.setText(status)

    def _update_timer_display(self, session_time: str, total_time: str):
        """Update timer display."""
        self.timer_label.setText(f"Session: {session_time} | Total: {total_time}")

    def _toggle_pause(self):
        """Toggle pause state."""
        is_paused = self.pause_btn.isChecked()
        self.pause_btn.setText("Resume" if is_paused else "Pause")

        # TODO: Actually pause background processes
        status = "Paused" if is_paused else "Ready"
        self.status_label.setText(status)

    def _clear_display(self):
        """Clear the chat display."""
        reply = QMessageBox.question(
            self,
            "Clear Chat",
            "Clear the chat display? (History is preserved in database)",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.chat_display.clear()

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
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Import and initialize backend
    import config
    from core.database import init_database
    from core.embeddings import load_embedding_model
    from core.temporal import init_temporal_tracker, get_temporal_tracker
    from concurrency.locks import init_lock_manager
    from memory.conversation import init_conversation_manager, get_conversation_manager
    from memory.vector_store import init_vector_store
    from memory.extractor import init_memory_extractor, get_memory_extractor
    from llm.router import init_llm_router, get_llm_router
    from prompt_builder import init_prompt_builder, get_prompt_builder
    from prompt_builder.sources.relationship import get_relationship_source
    from agency.relationship_analyzer import init_relationship_analyzer, get_relationship_analyzer

    # Setup directories
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize components
    print("Initializing database...")
    init_database(db_path=config.DATABASE_PATH, busy_timeout_ms=config.DB_BUSY_TIMEOUT_MS)

    print("Loading embedding model...")
    embedding_loaded = load_embedding_model(config.EMBEDDING_MODEL)
    if not embedding_loaded:
        print("=" * 60)
        print("WARNING: Running in degraded mode - semantic memory disabled")
        print("Conversations will be stored, but memory recall won't work.")
        print("=" * 60)

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
    init_relationship_analyzer()

    # Start background services
    get_memory_extractor().start()
    get_relationship_analyzer().start()

    # Create and configure window
    window = init_gui()
    window.set_backend(
        conversation_mgr=get_conversation_manager(),
        llm_router=get_llm_router(),
        prompt_builder=get_prompt_builder(),
        temporal_tracker=get_temporal_tracker(),
        relationship_source=get_relationship_source()
    )

    window.show()
    print("GUI ready!")

    # Run event loop
    exit_code = app.exec_()

    # Cleanup
    print("Shutting down...")
    get_memory_extractor().stop()
    get_relationship_analyzer().stop()

    return exit_code


if __name__ == "__main__":
    sys.exit(run_gui())
