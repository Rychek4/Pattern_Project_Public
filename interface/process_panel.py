"""
Pattern Project - Process Panel
A real-time sidebar showing the AI's internal processing pipeline.

Displays step-by-step events as the harness processes messages:
message receipt, prompt assembly, streaming, tool calls, continuation
rounds, memory extraction, and system pulse activity.

Events accumulate across messages with visual separators. The panel
auto-scrolls to follow activity but allows the user to scroll back
through history.
"""

from datetime import datetime
from enum import Enum, auto
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QLabel, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor


# =============================================================================
# PROCESS EVENT TYPES
# =============================================================================

class ProcessEventType(Enum):
    """Types of events that can appear in the process panel."""
    MESSAGE_RECEIVED = auto()
    PROMPT_ASSEMBLED = auto()
    MEMORIES_INJECTED = auto()
    STREAM_START = auto()
    STREAMING = auto()
    STREAM_COMPLETE = auto()
    TOOL_INVOKED = auto()
    CONTINUATION_START = auto()
    ROUND_COMPLETE = auto()
    PROCESSING_COMPLETE = auto()
    PROCESSING_ERROR = auto()
    MEMORY_EXTRACTION = auto()
    PULSE_FIRED = auto()
    REMINDER_FIRED = auto()
    TELEGRAM_RECEIVED = auto()
    DELEGATION_START = auto()
    DELEGATION_TOOL = auto()
    DELEGATION_COMPLETE = auto()
    CURIOSITY_SELECTED = auto()


# =============================================================================
# PROCESS EVENT DATA
# =============================================================================

@dataclass
class ProcessEvent:
    """A single event in the processing pipeline."""
    event_type: ProcessEventType
    timestamp: datetime = field(default_factory=datetime.now)
    detail: str = ""
    round_number: int = 0
    is_active: bool = False
    origin: str = "user"  # "user", "isaac", or "system"

    @property
    def label(self) -> str:
        """Human-readable label for this event type."""
        labels = {
            ProcessEventType.MESSAGE_RECEIVED: "You said something",
            ProcessEventType.PROMPT_ASSEMBLED: "Gathering thoughts",
            ProcessEventType.MEMORIES_INJECTED: "Recalling past conversations",
            ProcessEventType.STREAM_START: "Thinking...",
            ProcessEventType.STREAMING: "Thinking...",
            ProcessEventType.STREAM_COMPLETE: "Responded",
            ProcessEventType.TOOL_INVOKED: "Tool",
            ProcessEventType.CONTINUATION_START: "Thinking further...",
            ProcessEventType.ROUND_COMPLETE: "Round complete",
            ProcessEventType.PROCESSING_COMPLETE: "Settled",
            ProcessEventType.PROCESSING_ERROR: "Something went wrong",
            ProcessEventType.MEMORY_EXTRACTION: "Reflecting on what to remember",
            ProcessEventType.PULSE_FIRED: "Checking in",
            ProcessEventType.REMINDER_FIRED: "Remembered something he promised",
            ProcessEventType.TELEGRAM_RECEIVED: "You sent a Telegram",
            ProcessEventType.DELEGATION_START: "Asking for help with a task",
            ProcessEventType.DELEGATION_TOOL: "Delegate",
            ProcessEventType.DELEGATION_COMPLETE: "Got the help he needed",
            ProcessEventType.CURIOSITY_SELECTED: "Got curious about something",
        }
        return labels.get(self.event_type, "Unknown")


# =============================================================================
# PROCESS EVENT BUS
# =============================================================================

class ProcessEventBus(QObject):
    """
    Central event bus for process panel updates.

    Components throughout the pipeline emit events here. The process
    panel subscribes and renders them. This keeps the panel completely
    decoupled from the pipeline -- emitters don't know about the panel.
    """

    event_emitted = pyqtSignal(object)  # ProcessEvent

    def emit_event(self, event_type: ProcessEventType, detail: str = "",
                   round_number: int = 0, is_active: bool = False,
                   origin: str = "user"):
        """Emit a process event to all subscribers."""
        event = ProcessEvent(
            event_type=event_type,
            detail=detail,
            round_number=round_number,
            is_active=is_active,
            origin=origin
        )
        self.event_emitted.emit(event)


# Global instance
_event_bus: Optional[ProcessEventBus] = None


def get_process_event_bus() -> ProcessEventBus:
    """Get the global process event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = ProcessEventBus()
    return _event_bus


# =============================================================================
# COLORS (matching dark theme from gui_components.py DARK_THEME)
# =============================================================================

# Panel colors
PANEL_BG = "#252525"
PANEL_BORDER = "#3a3a3a"

# Event node colors
COLOR_ACTIVE = "#d4a574"       # Warm amber - something is happening now
COLOR_COMPLETE = "#7a7770"     # Muted - finished
COLOR_TOOL = "#c4a7e7"         # Purple - tool invocation
COLOR_ERROR = "#e07a6b"        # Red - error
COLOR_SYSTEM = "#5bb98c"       # Green - system events (pulse, extraction)
COLOR_CONNECTOR = "#3a3a3a"    # Very dim connector lines
COLOR_DELEGATION = "#6bb5e0"   # Blue - delegation events
COLOR_TEXT = "#e8e6e3"         # Primary text
COLOR_TEXT_DIM = "#7a7770"     # Dimmed text
COLOR_TEXT_DETAIL = "#9a9892"  # Detail/metadata text
COLOR_ROUND_BG = "#2e2e2e"    # Round group background
COLOR_ROUND_BORDER = "#424240" # Round group border
COLOR_SEPARATOR = "#3a3a3a"    # Message separator

# Origin-based left border colors (per message group)
COLOR_BORDER_AI = "#c4a7e7"      # Purple - AI-initiated
COLOR_BORDER_USER = "#6bb5e0"    # Blue - User-initiated
COLOR_BORDER_SYSTEM = "#5bb98c"  # Green - System-initiated


# =============================================================================
# NODE WIDGET
# =============================================================================

class ProcessNodeWidget(QFrame):
    """
    A single step in the process pipeline.

    Displays: [status dot] [label] [detail]
    With a vertical connector line below (except for terminal nodes).
    """

    def __init__(self, event: ProcessEvent, show_connector: bool = True, parent=None):
        super().__init__(parent)
        self._event = event
        self._show_connector = show_connector
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameStyle(QFrame.NoFrame)
        self.setStyleSheet("background: transparent; border: none;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main row: dot + label + detail
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 4, 2)
        row_layout.setSpacing(1)

        # Label line with dot
        label_text = self._build_label_html()
        label = QLabel(label_text)
        label.setFont(QFont("Segoe UI", 9))
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        label.setStyleSheet("background: transparent; border: none;")
        row_layout.addWidget(label)

        # Detail line (if present)
        if self._event.detail:
            detail = QLabel(self._build_detail_html())
            detail.setFont(QFont("Segoe UI", 8))
            detail.setTextFormat(Qt.RichText)
            detail.setWordWrap(True)
            detail.setStyleSheet("background: transparent; border: none;")
            row_layout.addWidget(detail)

        layout.addWidget(row)

    def _get_dot_color(self) -> str:
        """Get the color for the status dot based on event state."""
        if self._event.is_active:
            return COLOR_ACTIVE

        type_colors = {
            ProcessEventType.TOOL_INVOKED: COLOR_TOOL,
            ProcessEventType.PROCESSING_ERROR: COLOR_ERROR,
            ProcessEventType.MEMORY_EXTRACTION: COLOR_SYSTEM,
            ProcessEventType.PULSE_FIRED: COLOR_SYSTEM,
            ProcessEventType.REMINDER_FIRED: COLOR_SYSTEM,
            ProcessEventType.PROCESSING_COMPLETE: COLOR_SYSTEM,
            ProcessEventType.CURIOSITY_SELECTED: COLOR_SYSTEM,
            ProcessEventType.DELEGATION_START: COLOR_DELEGATION,
            ProcessEventType.DELEGATION_TOOL: COLOR_DELEGATION,
            ProcessEventType.DELEGATION_COMPLETE: COLOR_DELEGATION,
        }
        return type_colors.get(self._event.event_type, COLOR_COMPLETE)

    def _build_label_html(self) -> str:
        """Build the HTML for the label with colored dot."""
        dot_color = self._get_dot_color()
        label = self._event.label

        # For tool invocations, show tool name
        if self._event.event_type == ProcessEventType.TOOL_INVOKED:
            tool_name = self._event.detail.split(":")[0] if ":" in self._event.detail else self._event.detail
            if tool_name:
                label = f"Tool: {tool_name}"

        # For delegation sub-tool calls, show tool name
        if self._event.event_type == ProcessEventType.DELEGATION_TOOL:
            tool_name = self._event.detail.split(":")[0] if ":" in self._event.detail else self._event.detail
            if tool_name:
                label = f"Delegate: {tool_name}"

        # Build timestamp
        time_str = self._event.timestamp.strftime("%H:%M:%S")

        # Unicode circle character for dot
        dot_char = "\u25cf"

        return (
            f'<span style="color: {dot_color};">{dot_char}</span>'
            f' <span style="color: {COLOR_TEXT};">{label}</span>'
            f'  <span style="color: {COLOR_TEXT_DIM}; font-size: 8px;">{time_str}</span>'
        )

    def _build_detail_html(self) -> str:
        """Build the HTML for the detail line."""
        detail = self._event.detail

        # For tool invocations and delegation sub-tools, only show the part after ":"
        tool_detail_types = (ProcessEventType.TOOL_INVOKED, ProcessEventType.DELEGATION_TOOL)
        if self._event.event_type in tool_detail_types and ":" in detail:
            detail = detail.split(":", 1)[1].strip()
        elif self._event.event_type in tool_detail_types:
            # No extra detail beyond tool name
            return ""

        if not detail:
            return ""

        return (
            f'<span style="color: {COLOR_TEXT_DIM}; margin-left: 14px;">'
            f'  {detail}</span>'
        )

    def mark_complete(self):
        """Mark this node as complete (no longer active)."""
        self._event.is_active = False
        # Rebuild the label to update the dot color
        label = self.findChild(QLabel)
        if label:
            label.setText(self._build_label_html())


# =============================================================================
# ROUND GROUP WIDGET
# =============================================================================

class RoundGroupWidget(QFrame):
    """
    Visual grouping for a single round of processing.

    Contains the nodes that belong to a round (streaming/thinking + tool calls).
    Has a subtle background and border to visually group related steps.
    """

    def __init__(self, round_number: int, parent=None):
        super().__init__(parent)
        self.round_number = round_number
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameStyle(QFrame.NoFrame)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLOR_ROUND_BG};
                border: 1px solid {COLOR_ROUND_BORDER};
                border-radius: 4px;
                margin: 2px 0px;
                padding: 0px;
            }}
        """)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 4, 4, 4)
        self._layout.setSpacing(0)

        # Round header
        header = QLabel(
            f'<span style="color: {COLOR_TEXT_DIM}; font-size: 8px;">'
            f'Round {self.round_number}</span>'
        )
        header.setFont(QFont("Segoe UI", 8))
        header.setTextFormat(Qt.RichText)
        header.setStyleSheet("background: transparent; border: none;")
        self._layout.addWidget(header)

    def add_node(self, node: ProcessNodeWidget):
        """Add a process node to this round group."""
        self._layout.addWidget(node)


# =============================================================================
# MESSAGE SEPARATOR WIDGET
# =============================================================================

class MessageSeparatorWidget(QFrame):
    """Thin separator between message processing pipelines."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.NoFrame)
        self.setFixedHeight(16)
        self.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {COLOR_SEPARATOR};
                margin: 4px 8px;
            }}
        """)


# =============================================================================
# MESSAGE GROUP WIDGET
# =============================================================================

class MessageGroupWidget(QFrame):
    """
    Container for all nodes within a single message processing group.

    Each group has a 3px left border colored by origin:
    - Purple: AI-initiated (pulses, reminders, curiosity)
    - Blue: User-initiated (messages, telegrams)
    - Green: System-initiated
    """

    def __init__(self, origin: str = "user", parent=None):
        super().__init__(parent)
        self._origin = origin
        self._setup_ui()

    def _setup_ui(self):
        border_color = {
            "isaac": COLOR_BORDER_AI,
            "user": COLOR_BORDER_USER,
            "system": COLOR_BORDER_SYSTEM,
        }.get(self._origin, COLOR_BORDER_USER)

        self.setFrameStyle(QFrame.NoFrame)
        self.setStyleSheet(f"""
            MessageGroupWidget {{
                background: transparent;
                border: none;
                border-left: 3px solid {border_color};
                margin: 0px;
                padding: 0px 0px 0px 6px;
            }}
        """)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._layout.setSpacing(2)
        self._layout.setAlignment(Qt.AlignTop)

    def add_node(self, node):
        """Add a process node or round group to this message group."""
        self._layout.addWidget(node)


# =============================================================================
# PROCESS PANEL WIDGET
# =============================================================================

class ProcessPanel(QFrame):
    """
    Main process panel widget.

    Always-visible vertical panel showing the AI's processing pipeline
    in real time. Sits to the left of the chat area.

    Features:
    - Real-time event display as processing happens
    - Round grouping for multi-pass tool execution
    - Message separators between distinct processing pipelines
    - Auto-scroll during active processing
    - User can scroll back through history
    - 240px fixed width
    """

    PANEL_WIDTH = 240

    def __init__(self, parent=None):
        super().__init__(parent)
        self._events: List[ProcessEvent] = []
        self._current_round: int = 0
        self._current_round_widget: Optional[RoundGroupWidget] = None
        self._current_message_group: Optional[MessageGroupWidget] = None
        self._has_content: bool = False
        self._user_scrolled_up: bool = False
        self._streaming_node: Optional[ProcessNodeWidget] = None
        self._active_nodes: List[ProcessNodeWidget] = []

        self._setup_ui()
        self._connect_event_bus()

    def _setup_ui(self):
        self.setFixedWidth(self.PANEL_WIDTH)
        self.setFrameStyle(QFrame.NoFrame)
        self.setStyleSheet(f"""
            ProcessPanel {{
                background-color: {PANEL_BG};
                border: none;
                border-right: 1px solid {PANEL_BORDER};
            }}
        """)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Header
        header = QLabel("AI")
        header.setFont(QFont("Segoe UI", 9, QFont.Bold))
        header.setAlignment(Qt.AlignLeft)
        header.setStyleSheet(f"""
            color: {COLOR_TEXT_DIM};
            background-color: {PANEL_BG};
            padding: 8px 10px 6px 10px;
            border: none;
            border-bottom: 1px solid {PANEL_BORDER};
        """)
        outer_layout.addWidget(header)

        # Scrollable content area
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {PANEL_BG};
                border: none;
            }}
            QWidget#process_content {{
                background-color: {PANEL_BG};
            }}
            QScrollBar:vertical {{
                background-color: transparent;
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {PANEL_BORDER};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {COLOR_TEXT_DIM};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)

        # Content widget inside scroll area
        self._content = QWidget()
        self._content.setObjectName("process_content")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 6, 4, 6)
        self._content_layout.setSpacing(2)
        self._content_layout.setAlignment(Qt.AlignTop)

        self._scroll_area.setWidget(self._content)
        outer_layout.addWidget(self._scroll_area)

        # Track scroll position for auto-scroll behavior
        scrollbar = self._scroll_area.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_scroll_changed)
        scrollbar.rangeChanged.connect(self._on_scroll_range_changed)

    def _connect_event_bus(self):
        """Subscribe to the global process event bus."""
        bus = get_process_event_bus()
        bus.event_emitted.connect(self._on_event)

    def _on_scroll_changed(self, value: int):
        """Track whether user has scrolled away from bottom."""
        scrollbar = self._scroll_area.verticalScrollBar()
        at_bottom = value >= scrollbar.maximum() - 20
        self._user_scrolled_up = not at_bottom

    def _on_scroll_range_changed(self, _min: int, _max: int):
        """Auto-scroll to bottom when new content is added (unless user scrolled up)."""
        if not self._user_scrolled_up:
            self._scroll_area.verticalScrollBar().setValue(_max)

    # =========================================================================
    # EVENT HANDLING
    # =========================================================================

    def _on_event(self, event: ProcessEvent):
        """Handle an incoming process event."""
        self._events.append(event)

        # Handle special event types
        if event.event_type == ProcessEventType.MESSAGE_RECEIVED:
            self._start_new_message_group(event)
        elif event.event_type == ProcessEventType.PULSE_FIRED:
            self._start_new_message_group(event)
        elif event.event_type == ProcessEventType.REMINDER_FIRED:
            self._start_new_message_group(event)
        elif event.event_type == ProcessEventType.TELEGRAM_RECEIVED:
            self._start_new_message_group(event)
        elif event.event_type == ProcessEventType.STREAM_START:
            self._handle_stream_start(event)
        elif event.event_type == ProcessEventType.STREAMING:
            self._handle_streaming_update(event)
        elif event.event_type == ProcessEventType.STREAM_COMPLETE:
            self._handle_stream_complete(event)
        elif event.event_type == ProcessEventType.TOOL_INVOKED:
            self._handle_tool_invoked(event)
        elif event.event_type == ProcessEventType.CONTINUATION_START:
            self._handle_continuation_start(event)
        elif event.event_type == ProcessEventType.PROCESSING_COMPLETE:
            self._handle_processing_complete(event)
        elif event.event_type == ProcessEventType.PROCESSING_ERROR:
            self._add_node(event)
            self._mark_all_active_complete()
        elif event.event_type in (
            ProcessEventType.DELEGATION_START,
            ProcessEventType.DELEGATION_TOOL,
            ProcessEventType.DELEGATION_COMPLETE,
        ):
            # Delegation events belong inside the current round
            event.round_number = self._current_round
            self._add_node_to_round(event)
        else:
            self._add_node(event)

    def _start_new_message_group(self, event: ProcessEvent):
        """Start a new processing pipeline section with separator."""
        # Add separator if there's existing content
        if self._has_content:
            sep = MessageSeparatorWidget()
            self._content_layout.addWidget(sep)

        # Reset round tracking
        self._current_round = 0
        self._current_round_widget = None
        self._streaming_node = None
        self._mark_all_active_complete()
        self._has_content = True

        # Create a new message group container with origin-based border
        self._current_message_group = MessageGroupWidget(origin=event.origin)
        self._content_layout.addWidget(self._current_message_group)

        # Add the entry node inside the group
        self._add_node(event)

    def _handle_stream_start(self, event: ProcessEvent):
        """Handle the start of streaming - create an active streaming node."""
        # If no round has started yet, this is round 1
        if self._current_round == 0:
            self._current_round = 1
            event.round_number = 1
        else:
            event.round_number = self._current_round

        # Start a round group for round 1
        if self._current_round == 1:
            self._start_round_group(1)

        event.is_active = True
        node = self._add_node_to_round(event)
        self._streaming_node = node
        self._active_nodes.append(node)

    def _handle_streaming_update(self, event: ProcessEvent):
        """Update the streaming node with new token count."""
        if self._streaming_node:
            # Update the detail on the existing streaming node
            self._streaming_node._event.detail = event.detail
            # Find and update the detail label
            labels = self._streaming_node.findChildren(QLabel)
            if len(labels) >= 2:
                labels[1].setText(self._streaming_node._build_detail_html())
            elif event.detail and len(labels) == 1:
                # Need to add a detail label
                detail = QLabel(self._streaming_node._build_detail_html())
                detail.setFont(QFont("Segoe UI", 8))
                detail.setTextFormat(Qt.RichText)
                detail.setWordWrap(True)
                detail.setStyleSheet("background: transparent; border: none;")
                row = self._streaming_node.findChild(QWidget)
                if row:
                    row_layout = row.layout()
                    if row_layout:
                        row_layout.addWidget(detail)

    def _handle_stream_complete(self, event: ProcessEvent):
        """Handle streaming completion."""
        if self._streaming_node:
            self._streaming_node._event.is_active = False
            self._streaming_node._event.event_type = ProcessEventType.STREAM_COMPLETE
            self._streaming_node._event.detail = event.detail
            self._streaming_node._event.round_number = event.round_number or self._current_round

            # Rebuild the label and detail
            labels = self._streaming_node.findChildren(QLabel)
            if labels:
                labels[0].setText(self._streaming_node._build_label_html())
            if len(labels) >= 2 and event.detail:
                labels[1].setText(self._streaming_node._build_detail_html())

            if self._streaming_node in self._active_nodes:
                self._active_nodes.remove(self._streaming_node)
            self._streaming_node = None

    def _handle_tool_invoked(self, event: ProcessEvent):
        """Handle a tool invocation within the current round."""
        event.round_number = self._current_round
        self._add_node_to_round(event)

    def _handle_continuation_start(self, event: ProcessEvent):
        """Handle the start of a continuation round."""
        self._current_round += 1
        event.round_number = self._current_round
        event.is_active = True

        # Start a new round group
        self._start_round_group(self._current_round)

        node = self._add_node_to_round(event)
        self._streaming_node = node  # Treat as streaming node for updates
        self._active_nodes.append(node)

    def _handle_processing_complete(self, event: ProcessEvent):
        """Handle the end of all processing."""
        # Close current round group
        self._current_round_widget = None

        # Build completion detail
        detail_parts = []
        if self._current_round > 1:
            detail_parts.append(f"{self._current_round} rounds")
        if event.detail:
            detail_parts.append(event.detail)
        event.detail = ", ".join(detail_parts) if detail_parts else ""

        self._mark_all_active_complete()
        self._add_node(event)

    def _mark_all_active_complete(self):
        """Mark all active nodes as complete."""
        for node in self._active_nodes:
            node.mark_complete()
        self._active_nodes.clear()

    # =========================================================================
    # NODE / ROUND CREATION
    # =========================================================================

    def _add_node(self, event: ProcessEvent) -> ProcessNodeWidget:
        """Add a standalone node to the current message group (or content area)."""
        node = ProcessNodeWidget(event)
        if self._current_message_group:
            self._current_message_group.add_node(node)
        else:
            self._content_layout.addWidget(node)
        return node

    def _add_node_to_round(self, event: ProcessEvent) -> ProcessNodeWidget:
        """Add a node inside the current round group."""
        node = ProcessNodeWidget(event)
        if self._current_round_widget:
            self._current_round_widget.add_node(node)
        elif self._current_message_group:
            self._current_message_group.add_node(node)
        else:
            self._content_layout.addWidget(node)
        return node

    def _start_round_group(self, round_number: int):
        """Start a new visual round group inside the current message group."""
        self._current_round_widget = RoundGroupWidget(round_number)
        if self._current_message_group:
            self._current_message_group.add_node(self._current_round_widget)
        else:
            self._content_layout.addWidget(self._current_round_widget)
