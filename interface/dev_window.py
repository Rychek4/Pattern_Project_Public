"""
Pattern Project - Dev Mode Debug Window
Floating window showing internal operations for debugging
"""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTextBrowser, QLabel, QFrame, QSplitter, QScrollArea,
    QPushButton, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor

import config


# Color scheme matching main GUI
COLORS = {
    "background": "#1a1a2e",
    "surface": "#16213e",
    "surface_alt": "#1f2940",
    "primary": "#0f3460",
    "accent": "#e94560",
    "text": "#eaeaea",
    "text_dim": "#888888",
    "success": "#4ade80",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "info": "#60a5fa",
    "purple": "#a855f7",
}


@dataclass
class PromptAssemblyData:
    """Data about prompt assembly."""
    context_blocks: List[Dict[str, Any]] = field(default_factory=list)
    total_tokens_estimate: int = 0
    timestamp: str = ""


@dataclass
class CommandExecutionData:
    """Data about command execution."""
    command_name: str = ""
    query: str = ""
    result_data: Any = None
    error: Optional[str] = None
    needs_continuation: bool = False
    timestamp: str = ""


@dataclass
class WebSearchCitationData:
    """Citation from a web search result."""
    title: str = ""
    url: str = ""
    cited_text: str = ""


@dataclass
class ResponsePassData:
    """Data about a single response pass."""
    pass_number: int = 0
    provider: str = ""
    response_text: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: float = 0
    commands_detected: List[str] = field(default_factory=list)
    timestamp: str = ""
    # Web search fields
    web_searches_used: int = 0
    citations: List[WebSearchCitationData] = field(default_factory=list)


@dataclass
class MemoryRecallData:
    """Data about memory recall."""
    query: str = ""
    results: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class ActiveThoughtsData:
    """Data about active thoughts update."""
    thoughts: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class CuriosityData:
    """Data about curiosity engine state."""
    current_goal: Optional[Dict[str, Any]] = None  # id, content, category, context, activated_at
    history: List[Dict[str, Any]] = field(default_factory=list)  # Recent resolved goals
    cooldowns: List[Dict[str, Any]] = field(default_factory=list)  # Memories in cooldown
    timestamp: str = ""
    event: str = ""  # "initial", "resolved", "activated"


@dataclass
class IntentionData:
    """Data about intentions (reminders/goals)."""
    intentions: List[Dict[str, Any]] = field(default_factory=list)  # All active intentions
    timestamp: str = ""
    event: str = ""  # "created", "triggered", "completed", "dismissed", "initial"


class DevWindowSignals(QObject):
    """Signals for updating the dev window from other threads."""
    prompt_assembly = pyqtSignal(object)  # PromptAssemblyData
    command_executed = pyqtSignal(object)  # CommandExecutionData
    response_pass = pyqtSignal(object)  # ResponsePassData
    memory_recall = pyqtSignal(object)  # MemoryRecallData
    active_thoughts_updated = pyqtSignal(object)  # ActiveThoughtsData
    curiosity_updated = pyqtSignal(object)  # CuriosityData
    intentions_updated = pyqtSignal(object)  # IntentionData
    clear_all = pyqtSignal()


class DevWindow(QMainWindow):
    """
    Debug window showing internal operations.

    Displays:
    - Prompt assembly with context blocks
    - Command/tool execution details
    - Multi-pass response processing
    - Memory recall with scores
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = DevWindowSignals()
        self._setup_signals()
        self._setup_ui()
        self._apply_style()

    def _setup_signals(self):
        """Connect signals to update methods."""
        self.signals.prompt_assembly.connect(self._on_prompt_assembly)
        self.signals.command_executed.connect(self._on_command_executed)
        self.signals.response_pass.connect(self._on_response_pass)
        self.signals.memory_recall.connect(self._on_memory_recall)
        self.signals.active_thoughts_updated.connect(self._on_active_thoughts_updated)
        self.signals.curiosity_updated.connect(self._on_curiosity_updated)
        self.signals.intentions_updated.connect(self._on_intentions_updated)
        self.signals.clear_all.connect(self._clear_all)

    def _setup_ui(self):
        """Create the UI layout."""
        self.setWindowTitle("Dev Mode - Debug Window")
        self.setMinimumSize(600, 500)
        self.resize(800, 700)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header
        header = self._create_header()
        layout.addWidget(header)

        # Tab widget for different views
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Create tabs
        self._create_prompt_tab()
        self._create_commands_tab()
        self._create_response_tab()
        self._create_memory_tab()
        self._create_active_thoughts_tab()
        self._create_curiosity_tab()
        self._create_intentions_tab()

        # Status bar
        self.status_label = QLabel("Dev mode active")
        self.status_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px;")
        layout.addWidget(self.status_label)

    def _create_header(self) -> QFrame:
        """Create the header with controls."""
        header = QFrame()
        header.setFrameStyle(QFrame.StyledPanel)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(10, 5, 10, 5)

        # Title
        title = QLabel("Debug Window")
        title.setFont(QFont("Consolas", 14, QFont.Bold))
        title.setStyleSheet(f"color: {COLORS['purple']};")
        layout.addWidget(title)

        layout.addStretch()

        # Auto-scroll checkbox
        self.auto_scroll_check = QCheckBox("Auto-scroll")
        self.auto_scroll_check.setChecked(True)
        self.auto_scroll_check.setStyleSheet(f"color: {COLORS['text']};")
        layout.addWidget(self.auto_scroll_check)

        # Clear button
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self._clear_all)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['surface_alt']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['primary']};
                padding: 5px 15px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['primary']};
            }}
        """)
        layout.addWidget(clear_btn)

        return header

    def _create_prompt_tab(self):
        """Create the Prompt Assembly tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Info label
        info = QLabel("Shows context blocks assembled for each prompt")
        info.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(info)

        # Content area
        self.prompt_display = QTextBrowser()
        self.prompt_display.setFont(QFont("Consolas", 10))
        self.prompt_display.setOpenExternalLinks(False)
        layout.addWidget(self.prompt_display)

        self.tabs.addTab(tab, "Prompt Assembly")

    def _create_commands_tab(self):
        """Create the Tools tab (native tool use)."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Info label
        info = QLabel("Shows native tool execution details")
        info.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(info)

        # Content area
        self.commands_display = QTextBrowser()
        self.commands_display.setFont(QFont("Consolas", 10))
        self.commands_display.setOpenExternalLinks(False)
        layout.addWidget(self.commands_display)

        self.tabs.addTab(tab, "Tools")

    def _create_response_tab(self):
        """Create the Response Pipeline tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Info label
        info = QLabel("Shows multi-pass response processing")
        info.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(info)

        # Content area
        self.response_display = QTextBrowser()
        self.response_display.setFont(QFont("Consolas", 10))
        self.response_display.setOpenExternalLinks(False)
        layout.addWidget(self.response_display)

        self.tabs.addTab(tab, "Response Pipeline")

    def _create_memory_tab(self):
        """Create the Memory Recall tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Info label
        info = QLabel("Shows memory recall queries, scores, and warmth cache status")
        info.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(info)

        # Content area
        self.memory_display = QTextBrowser()
        self.memory_display.setFont(QFont("Consolas", 10))
        self.memory_display.setOpenExternalLinks(False)
        layout.addWidget(self.memory_display)

        self.tabs.addTab(tab, "Memory Recall")

    def _create_active_thoughts_tab(self):
        """Create the Active Thoughts tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Info label
        info = QLabel("Shows the AI's active working memory")
        info.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(info)

        # Content area
        self.active_thoughts_display = QTextBrowser()
        self.active_thoughts_display.setFont(QFont("Consolas", 10))
        self.active_thoughts_display.setOpenExternalLinks(False)
        layout.addWidget(self.active_thoughts_display)

        self.tabs.addTab(tab, "Active Thoughts")

    def _create_curiosity_tab(self):
        """Create the Curiosity tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Info label
        info = QLabel("Shows the AI's current curiosity goal and history")
        info.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(info)

        # Content area
        self.curiosity_display = QTextBrowser()
        self.curiosity_display.setFont(QFont("Consolas", 10))
        self.curiosity_display.setOpenExternalLinks(False)
        layout.addWidget(self.curiosity_display)

        self.tabs.addTab(tab, "Curiosity")

    def _create_intentions_tab(self):
        """Create the Intentions tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Info label
        info = QLabel("Shows the AI's intentions (reminders, goals)")
        info.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(info)

        # Content area
        self.intentions_display = QTextBrowser()
        self.intentions_display.setFont(QFont("Consolas", 10))
        self.intentions_display.setOpenExternalLinks(False)
        layout.addWidget(self.intentions_display)

        self.tabs.addTab(tab, "Intentions")

    def _apply_style(self):
        """Apply dark theme styling."""
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {COLORS['background']};
            }}
            QWidget {{
                background-color: {COLORS['background']};
                color: {COLORS['text']};
            }}
            QFrame {{
                background-color: {COLORS['surface']};
                border-radius: 5px;
            }}
            QTabWidget::pane {{
                border: 1px solid {COLORS['primary']};
                border-radius: 5px;
                background-color: {COLORS['surface']};
            }}
            QTabBar::tab {{
                background-color: {COLORS['surface_alt']};
                color: {COLORS['text_dim']};
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS['primary']};
                color: {COLORS['text']};
            }}
            QTabBar::tab:hover {{
                background-color: {COLORS['primary']};
            }}
            QTextBrowser {{
                background-color: {COLORS['surface']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['primary']};
                border-radius: 4px;
                padding: 8px;
            }}
            QLabel {{
                background-color: transparent;
            }}
            QCheckBox {{
                background-color: transparent;
            }}
        """)

    def _on_prompt_assembly(self, data: PromptAssemblyData):
        """Handle prompt assembly data."""
        html = self._format_prompt_assembly(data)
        self.prompt_display.append(html)
        if self.auto_scroll_check.isChecked():
            self.prompt_display.verticalScrollBar().setValue(
                self.prompt_display.verticalScrollBar().maximum()
            )
        self._update_status(f"Prompt assembled: {len(data.context_blocks)} blocks")

    def _on_command_executed(self, data: CommandExecutionData):
        """Handle command execution data."""
        html = self._format_command_execution(data)
        self.commands_display.append(html)
        if self.auto_scroll_check.isChecked():
            self.commands_display.verticalScrollBar().setValue(
                self.commands_display.verticalScrollBar().maximum()
            )
        self._update_status(f"Tool executed: {data.command_name}")

    def _on_response_pass(self, data: ResponsePassData):
        """Handle response pass data."""
        html = self._format_response_pass(data)
        self.response_display.append(html)
        if self.auto_scroll_check.isChecked():
            self.response_display.verticalScrollBar().setValue(
                self.response_display.verticalScrollBar().maximum()
            )
        self._update_status(f"Pass {data.pass_number} complete ({data.provider})")

    def _on_memory_recall(self, data: MemoryRecallData):
        """Handle memory recall data."""
        html = self._format_memory_recall(data)
        self.memory_display.append(html)
        if self.auto_scroll_check.isChecked():
            self.memory_display.verticalScrollBar().setValue(
                self.memory_display.verticalScrollBar().maximum()
            )
        self._update_status(f"Memory recall: {len(data.results)} results")

    def _on_active_thoughts_updated(self, data: ActiveThoughtsData):
        """Handle active thoughts update."""
        html = self._format_active_thoughts(data)
        self.active_thoughts_display.append(html)
        if self.auto_scroll_check.isChecked():
            self.active_thoughts_display.verticalScrollBar().setValue(
                self.active_thoughts_display.verticalScrollBar().maximum()
            )
        self._update_status(f"Active thoughts updated: {len(data.thoughts)} items")

    def _on_curiosity_updated(self, data: CuriosityData):
        """Handle curiosity update."""
        html = self._format_curiosity(data)
        self.curiosity_display.append(html)
        if self.auto_scroll_check.isChecked():
            self.curiosity_display.verticalScrollBar().setValue(
                self.curiosity_display.verticalScrollBar().maximum()
            )
        goal_desc = data.current_goal.get("content", "none")[:40] if data.current_goal else "none"
        self._update_status(f"Curiosity {data.event}: {goal_desc}")

    def _on_intentions_updated(self, data: IntentionData):
        """Handle intentions update."""
        html = self._format_intentions(data)
        self.intentions_display.append(html)
        if self.auto_scroll_check.isChecked():
            self.intentions_display.verticalScrollBar().setValue(
                self.intentions_display.verticalScrollBar().maximum()
            )
        self._update_status(f"Intentions {data.event}: {len(data.intentions)} total")

    def _clear_all(self):
        """Clear all displays."""
        self.prompt_display.clear()
        self.commands_display.clear()
        self.response_display.clear()
        self.memory_display.clear()
        self.active_thoughts_display.clear()
        self.curiosity_display.clear()
        self.intentions_display.clear()
        self._update_status("Cleared all")

    def _update_status(self, message: str):
        """Update status bar."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_label.setText(f"[{timestamp}] {message}")

    def _format_prompt_assembly(self, data: PromptAssemblyData) -> str:
        """Format prompt assembly data as HTML."""
        lines = [
            f'<div style="margin-bottom: 15px; padding: 10px; background-color: {COLORS["surface_alt"]}; border-radius: 5px;">',
            f'<div style="color: {COLORS["purple"]}; font-weight: bold; margin-bottom: 8px;">'
            f'Prompt Assembly - {data.timestamp}</div>',
            f'<div style="color: {COLORS["text_dim"]}; margin-bottom: 10px;">'
            f'Estimated tokens: ~{data.total_tokens_estimate}</div>',
        ]

        for block in data.context_blocks:
            source = block.get("source_name", "unknown")
            priority = block.get("priority", 0)
            content_len = len(block.get("content", ""))
            token_estimate = content_len // 4  # Rough estimate

            # Color code by source type
            source_color = COLORS["info"]
            if source in ["core_memory", "dev_mode"]:
                source_color = COLORS["purple"]
            elif source in ["semantic_memory", "conversation"]:
                source_color = COLORS["success"]
            elif source in ["ai_commands", "system_pulse"]:
                source_color = COLORS["warning"]

            lines.append(
                f'<div style="margin: 5px 0; padding: 5px; border-left: 3px solid {source_color};">'
                f'<span style="color: {source_color}; font-weight: bold;">{source}</span> '
                f'<span style="color: {COLORS["text_dim"]};">(priority {priority}, ~{token_estimate} tokens)</span>'
                f'</div>'
            )

            # Show truncated content preview
            content = block.get("content", "")
            if content:
                preview = content[:200].replace("<", "&lt;").replace(">", "&gt;")
                if len(content) > 200:
                    preview += "..."
                lines.append(
                    f'<div style="margin-left: 15px; color: {COLORS["text_dim"]}; '
                    f'font-size: 11px; white-space: pre-wrap;">{preview}</div>'
                )

        lines.append('</div>')
        return ''.join(lines)

    def _format_command_execution(self, data: CommandExecutionData) -> str:
        """Format tool execution data as HTML."""
        status_color = COLORS["success"] if not data.error else COLORS["error"]
        status_text = "Success" if not data.error else f"Error: {data.error}"

        # Format query preview
        query_preview = data.query[:80] if data.query else "(no input)"
        if len(data.query) > 80:
            query_preview += "..."

        lines = [
            f'<div style="margin-bottom: 15px; padding: 10px; background-color: {COLORS["surface_alt"]}; border-radius: 5px;">',
            f'<div style="color: {COLORS["warning"]}; font-weight: bold; margin-bottom: 8px;">'
            f'🔧 {data.command_name}</div>',
            f'<div style="color: {COLORS["text_dim"]}; margin-bottom: 5px;">{data.timestamp}</div>',
            f'<div style="color: {status_color}; margin-bottom: 5px;">{status_text}</div>',
        ]

        if data.needs_continuation:
            lines.append(
                f'<div style="color: {COLORS["info"]};">Triggered continuation</div>'
            )

        if data.result_data:
            result_str = json.dumps(data.result_data, indent=2, default=str)
            if len(result_str) > 500:
                result_str = result_str[:500] + "\n..."
            result_str = result_str.replace("<", "&lt;").replace(">", "&gt;")
            lines.append(
                f'<div style="margin-top: 8px; color: {COLORS["text_dim"]}; font-size: 11px;">'
                f'<div style="font-weight: bold;">Result:</div>'
                f'<pre style="white-space: pre-wrap; margin: 5px 0;">{result_str}</pre>'
                f'</div>'
            )

        lines.append('</div>')
        return ''.join(lines)

    def _format_response_pass(self, data: ResponsePassData) -> str:
        """Format response pass data as HTML."""
        pass_color = COLORS["info"] if data.pass_number == 1 else COLORS["purple"]

        lines = [
            f'<div style="margin-bottom: 15px; padding: 10px; background-color: {COLORS["surface_alt"]}; border-radius: 5px;">',
            f'<div style="color: {pass_color}; font-weight: bold; margin-bottom: 8px;">'
            f'Pass {data.pass_number} - {data.provider}</div>',
            f'<div style="color: {COLORS["text_dim"]}; margin-bottom: 5px;">{data.timestamp}</div>',
            f'<div style="color: {COLORS["text_dim"]}; margin-bottom: 5px;">'
            f'Tokens: {data.tokens_in} in / {data.tokens_out} out | '
            f'Duration: {data.duration_ms:.0f}ms</div>',
        ]

        if data.commands_detected:
            cmd_list = ", ".join(data.commands_detected)
            lines.append(
                f'<div style="color: {COLORS["warning"]}; margin-bottom: 5px;">'
                f'🔧 Tools used: {cmd_list}</div>'
            )

        # Show web search info if any
        if data.web_searches_used > 0:
            lines.append(
                f'<div style="color: {COLORS["info"]}; margin-bottom: 5px;">'
                f'🔍 Web searches used: {data.web_searches_used}</div>'
            )

        # Show truncated response
        response_preview = data.response_text[:300].replace("<", "&lt;").replace(">", "&gt;")
        if len(data.response_text) > 300:
            response_preview += "..."
        lines.append(
            f'<div style="margin-top: 8px; border-left: 2px solid {COLORS["primary"]}; '
            f'padding-left: 10px; color: {COLORS["text"]}; white-space: pre-wrap;">'
            f'{response_preview}</div>'
        )

        # Show citations if any
        if data.citations:
            lines.append(
                f'<div style="margin-top: 10px; padding: 8px; background-color: {COLORS["surface"]}; '
                f'border-radius: 4px; border-left: 3px solid {COLORS["info"]};">'
                f'<div style="color: {COLORS["info"]}; font-weight: bold; margin-bottom: 5px;">'
                f'📚 Citations ({len(data.citations)})</div>'
            )
            for i, citation in enumerate(data.citations[:5], 1):  # Limit to 5
                title_escaped = citation.title.replace("<", "&lt;").replace(">", "&gt;")
                cited_text_escaped = citation.cited_text[:100].replace("<", "&lt;").replace(">", "&gt;")
                if len(citation.cited_text) > 100:
                    cited_text_escaped += "..."
                lines.append(
                    f'<div style="margin: 5px 0; padding: 5px; font-size: 11px;">'
                    f'<div style="color: {COLORS["text"]}; font-weight: bold;">{i}. {title_escaped}</div>'
                    f'<div style="color: {COLORS["text_dim"]};">{citation.url}</div>'
                    f'<div style="color: {COLORS["text_dim"]}; font-style: italic; margin-top: 3px;">'
                    f'"{cited_text_escaped}"</div>'
                    f'</div>'
                )
            if len(data.citations) > 5:
                lines.append(
                    f'<div style="color: {COLORS["text_dim"]}; font-size: 11px;">'
                    f'...and {len(data.citations) - 5} more</div>'
                )
            lines.append('</div>')

        lines.append('</div>')
        return ''.join(lines)

    def _format_memory_recall(self, data: MemoryRecallData) -> str:
        """Format memory recall data as HTML with warmth cache information."""
        lines = [
            f'<div style="margin-bottom: 15px; padding: 10px; background-color: {COLORS["surface_alt"]}; border-radius: 5px;">',
            f'<div style="color: {COLORS["success"]}; font-weight: bold; margin-bottom: 8px;">'
            f'Memory Recall</div>',
            f'<div style="color: {COLORS["text_dim"]}; margin-bottom: 5px;">{data.timestamp}</div>',
            f'<div style="color: {COLORS["text"]}; margin-bottom: 10px;">'
            f'Query: "{data.query[:100]}{"..." if len(data.query) > 100 else ""}"</div>',
            f'<div style="color: {COLORS["text_dim"]}; margin-bottom: 5px;">'
            f'{len(data.results)} result(s)</div>',
        ]

        # Show warmth cache stats if available (attached to first result)
        if data.results and data.results[0].get("_warmth_stats"):
            stats = data.results[0]["_warmth_stats"]
            topic_warmed = data.results[0].get("_topic_warmed_count", 0)
            lines.append(
                f'<div style="margin: 8px 0; padding: 8px; background-color: {COLORS["surface"]}; '
                f'border-radius: 4px; border-left: 3px solid {COLORS["purple"]};">'
                f'<div style="color: {COLORS["purple"]}; font-weight: bold; margin-bottom: 5px;">'
                f'🔥 Warmth Cache</div>'
                f'<div style="color: {COLORS["text_dim"]}; font-size: 11px;">'
                f'Cache entries: {stats.get("total_entries", 0)} | '
                f'Retrieval warm: {stats.get("retrieval_warm", 0)} | '
                f'Topic warm: {stats.get("topic_warm", 0)} | '
                f'Avg warmth: {stats.get("avg_combined", 0):.3f}</div>'
                f'<div style="color: {COLORS["text_dim"]}; font-size: 11px;">'
                f'Topic-warmed this turn: {topic_warmed}</div>'
                f'</div>'
            )

        for i, result in enumerate(data.results, 1):
            score = result.get("score", 0)
            semantic = result.get("semantic_score", 0)
            importance = result.get("importance_score", 0)
            freshness = result.get("freshness_score", 0)
            content = result.get("content", "")[:150]
            content = content.replace("<", "&lt;").replace(">", "&gt;")

            # Warmth information
            warmth_boost = result.get("warmth_boost", 0)
            retrieval_warmth = result.get("retrieval_warmth", 0)
            topic_warmth = result.get("topic_warmth", 0)
            adjusted_score = result.get("adjusted_score", score)

            # Color code by adjusted score (includes warmth)
            score_color = COLORS["success"] if adjusted_score > 0.7 else (
                COLORS["warning"] if adjusted_score > 0.4 else COLORS["text_dim"]
            )

            # Build score line with warmth indicator
            score_display = f'#{i} Score: {score:.3f}'
            if warmth_boost > 0.001:
                score_display += f' <span style="color: {COLORS["purple"]};">(+{warmth_boost:.3f} warmth = {adjusted_score:.3f})</span>'

            lines.append(
                f'<div style="margin: 8px 0; padding: 8px; border-left: 3px solid {score_color};">'
                f'<div style="color: {score_color}; font-weight: bold;">{score_display}</div>'
                f'<div style="color: {COLORS["text_dim"]}; font-size: 11px;">'
                f'semantic: {semantic:.2f} | importance: {importance:.2f} | freshness: {freshness:.2f}</div>'
            )

            # Show warmth breakdown if there's any warmth
            if warmth_boost > 0.001:
                warmth_details = []
                if retrieval_warmth > 0.001:
                    warmth_details.append(f'retrieval: {retrieval_warmth:.3f}')
                if topic_warmth > 0.001:
                    warmth_details.append(f'topic: {topic_warmth:.3f}')
                if warmth_details:
                    lines.append(
                        f'<div style="color: {COLORS["purple"]}; font-size: 11px;">'
                        f'🔥 warmth: {" | ".join(warmth_details)}</div>'
                    )

            lines.append(
                f'<div style="color: {COLORS["text"]}; margin-top: 5px; white-space: pre-wrap;">'
                f'{content}{"..." if len(result.get("content", "")) > 150 else ""}</div>'
                f'</div>'
            )

        if not data.results:
            lines.append(
                f'<div style="color: {COLORS["text_dim"]}; font-style: italic;">No memories matched</div>'
            )

        lines.append('</div>')
        return ''.join(lines)

    def _format_active_thoughts(self, data: ActiveThoughtsData) -> str:
        """Format active thoughts data as HTML."""
        lines = [
            f'<div style="margin-bottom: 15px; padding: 10px; background-color: {COLORS["surface_alt"]}; border-radius: 5px;">',
            f'<div style="color: {COLORS["purple"]}; font-weight: bold; margin-bottom: 8px;">'
            f'Active Thoughts Updated - {data.timestamp}</div>',
            f'<div style="color: {COLORS["text_dim"]}; margin-bottom: 10px;">'
            f'{len(data.thoughts)} item{"s" if len(data.thoughts) != 1 else ""}</div>',
        ]

        if not data.thoughts:
            lines.append(
                f'<div style="color: {COLORS["text_dim"]}; font-style: italic;">List cleared</div>'
            )
        else:
            for thought in sorted(data.thoughts, key=lambda t: t.get("rank", 99)):
                rank = thought.get("rank", "?")
                slug = thought.get("slug", "unknown")
                topic = thought.get("topic", "")[:60]
                topic = topic.replace("<", "&lt;").replace(">", "&gt;")
                elaboration = thought.get("elaboration", "")[:120]
                elaboration = elaboration.replace("<", "&lt;").replace(">", "&gt;")

                # Color gradient based on rank (higher rank = more dimmed)
                rank_color = COLORS["purple"] if rank <= 3 else (
                    COLORS["info"] if rank <= 6 else COLORS["text_dim"]
                )

                lines.append(
                    f'<div style="margin: 8px 0; padding: 8px; border-left: 3px solid {rank_color};">'
                    f'<div style="color: {rank_color}; font-weight: bold;">#{rank} [{slug}]</div>'
                    f'<div style="color: {COLORS["text"]}; margin-top: 3px;">{topic}</div>'
                    f'<div style="color: {COLORS["text_dim"]}; font-size: 11px; font-style: italic; margin-top: 3px;">'
                    f'"{elaboration}{"..." if len(thought.get("elaboration", "")) > 120 else ""}"</div>'
                    f'</div>'
                )

        lines.append('</div>')
        return ''.join(lines)

    def _format_curiosity(self, data: CuriosityData) -> str:
        """Format curiosity data as HTML."""
        # Determine event color
        event_colors = {
            "initial": COLORS["info"],
            "activated": COLORS["success"],
            "resolved": COLORS["warning"],
            "ai_specified": COLORS["success"],   # AI chose next topic (green)
            "context_inject": COLORS["purple"],  # Normal conversation context
            "pulse_inject": COLORS["accent"],    # Pulse/idle trigger
            "interaction": COLORS["info"],       # Progress recorded
        }
        event_color = event_colors.get(data.event, COLORS["text_dim"])

        lines = [
            f'<div style="margin-bottom: 15px; padding: 10px; background-color: {COLORS["surface_alt"]}; border-radius: 5px;">',
            f'<div style="color: {event_color}; font-weight: bold; margin-bottom: 8px;">'
            f'Curiosity {data.event.title()} - {data.timestamp}</div>',
        ]

        # Current goal section
        if data.current_goal:
            goal = data.current_goal
            content = goal.get("content", "").replace("<", "&lt;").replace(">", "&gt;")
            category = goal.get("category", "unknown")
            context = goal.get("context", "")[:200].replace("<", "&lt;").replace(">", "&gt;")
            activated = goal.get("activated_at", "")
            goal_id = goal.get("id", "?")

            lines.append(
                f'<div style="margin: 10px 0; padding: 10px; border-left: 3px solid {COLORS["success"]}; '
                f'background-color: {COLORS["surface"]};">'
                f'<div style="color: {COLORS["success"]}; font-weight: bold; margin-bottom: 5px;">'
                f'Current Goal (ID: {goal_id})</div>'
                f'<div style="color: {COLORS["text"]}; margin-bottom: 5px;">{content}</div>'
                f'<div style="color: {COLORS["text_dim"]}; font-size: 11px;">Category: {category}</div>'
            )
            if context:
                lines.append(
                    f'<div style="color: {COLORS["text_dim"]}; font-size: 11px; font-style: italic; margin-top: 5px;">'
                    f'Context: {context}{"..." if len(goal.get("context", "")) > 200 else ""}</div>'
                )
            if activated:
                lines.append(
                    f'<div style="color: {COLORS["text_dim"]}; font-size: 10px; margin-top: 5px;">'
                    f'Activated: {activated}</div>'
                )
            lines.append('</div>')
        else:
            lines.append(
                f'<div style="color: {COLORS["error"]}; font-style: italic;">No active goal (this should not happen)</div>'
            )

        # History section (last 5)
        if data.history:
            lines.append(
                f'<div style="margin-top: 10px; color: {COLORS["text_dim"]}; font-weight: bold;">Recent History:</div>'
            )
            for h in data.history[:5]:
                status = h.get("status", "unknown")
                status_colors = {
                    "explored": COLORS["success"],
                    "deferred": COLORS["warning"],
                    "declined": COLORS["error"],
                }
                status_color = status_colors.get(status, COLORS["text_dim"])
                h_content = h.get("content", "")[:60].replace("<", "&lt;").replace(">", "&gt;")
                resolved_at = h.get("resolved_at", "")

                lines.append(
                    f'<div style="margin: 5px 0; padding: 5px; border-left: 2px solid {status_color};">'
                    f'<span style="color: {status_color}; font-weight: bold;">[{status}]</span> '
                    f'<span style="color: {COLORS["text"]};">{h_content}{"..." if len(h.get("content", "")) > 60 else ""}</span>'
                    f'<div style="color: {COLORS["text_dim"]}; font-size: 10px;">{resolved_at}</div>'
                    f'</div>'
                )

        # Cooldowns section
        if data.cooldowns:
            lines.append(
                f'<div style="margin-top: 10px; color: {COLORS["text_dim"]}; font-weight: bold;">'
                f'Memories in Cooldown ({len(data.cooldowns)}):</div>'
            )
            for c in data.cooldowns[:5]:
                memory_id = c.get("memory_id", "?")
                expires = c.get("expires_at", "")
                lines.append(
                    f'<div style="color: {COLORS["text_dim"]}; font-size: 11px; margin-left: 10px;">'
                    f'Memory #{memory_id} - expires: {expires}</div>'
                )
            if len(data.cooldowns) > 5:
                lines.append(
                    f'<div style="color: {COLORS["text_dim"]}; font-size: 11px; margin-left: 10px;">'
                    f'...and {len(data.cooldowns) - 5} more</div>'
                )

        lines.append('</div>')
        return ''.join(lines)

    def _format_intentions(self, data: IntentionData) -> str:
        """Format intentions data as HTML."""
        # Event colors
        event_colors = {
            "created": COLORS["success"],
            "triggered": COLORS["warning"],
            "completed": COLORS["info"],
            "dismissed": COLORS["text_dim"],
            "initial": COLORS["purple"],
        }
        event_color = event_colors.get(data.event, COLORS["text"])

        lines = [
            f'<div style="margin-bottom: 15px; padding: 10px; background-color: {COLORS["surface_alt"]}; border-radius: 5px;">',
            f'<div style="color: {event_color}; font-weight: bold; margin-bottom: 8px;">'
            f'Intentions {data.event.title()} - {data.timestamp}</div>',
        ]

        if not data.intentions:
            lines.append(
                f'<div style="color: {COLORS["text_dim"]}; font-style: italic;">No active intentions</div>'
            )
        else:
            # Group by status
            triggered = [i for i in data.intentions if i.get("status") == "triggered"]
            pending = [i for i in data.intentions if i.get("status") == "pending"]
            completed = [i for i in data.intentions if i.get("status") == "completed"]
            dismissed = [i for i in data.intentions if i.get("status") == "dismissed"]

            lines.append(
                f'<div style="color: {COLORS["text_dim"]}; margin-bottom: 10px;">'
                f'Total: {len(data.intentions)} | Triggered: {len(triggered)} | '
                f'Pending: {len(pending)} | Completed: {len(completed)} | Dismissed: {len(dismissed)}</div>'
            )

            # Show triggered intentions first (most important)
            if triggered:
                lines.append(
                    f'<div style="color: {COLORS["warning"]}; font-weight: bold; margin-top: 10px;">⏰ TRIGGERED:</div>'
                )
                for intention in triggered:
                    lines.append(self._format_intention_item(intention, COLORS["warning"]))

            # Then pending
            if pending:
                lines.append(
                    f'<div style="color: {COLORS["info"]}; font-weight: bold; margin-top: 10px;">⏳ PENDING:</div>'
                )
                for intention in pending:
                    lines.append(self._format_intention_item(intention, COLORS["info"]))

            # Recently completed/dismissed (show max 5)
            if completed:
                lines.append(
                    f'<div style="color: {COLORS["success"]}; font-weight: bold; margin-top: 10px;">✓ RECENTLY COMPLETED:</div>'
                )
                for intention in completed[:5]:
                    lines.append(self._format_intention_item(intention, COLORS["success"]))

            if dismissed:
                lines.append(
                    f'<div style="color: {COLORS["text_dim"]}; font-weight: bold; margin-top: 10px;">✗ RECENTLY DISMISSED:</div>'
                )
                for intention in dismissed[:5]:
                    lines.append(self._format_intention_item(intention, COLORS["text_dim"]))

        lines.append('</div>')
        return ''.join(lines)

    def _format_intention_item(self, intention: Dict[str, Any], border_color: str) -> str:
        """Format a single intention item as HTML."""
        int_id = intention.get("id", "?")
        int_type = intention.get("type", "unknown")
        content = intention.get("content", "")[:100].replace("<", "&lt;").replace(">", "&gt;")
        if len(intention.get("content", "")) > 100:
            content += "..."

        context = intention.get("context", "")
        trigger_type = intention.get("trigger_type", "")
        trigger_at = intention.get("trigger_at", "")
        created_at = intention.get("created_at", "")
        priority = intention.get("priority", 5)
        status = intention.get("status", "unknown")

        # Build the item display
        lines = [
            f'<div style="margin: 5px 0; padding: 8px; border-left: 3px solid {border_color};">',
            f'<div style="color: {border_color}; font-weight: bold;">'
            f'[I-{int_id}] {int_type.upper()} (priority: {priority})</div>',
            f'<div style="color: {COLORS["text"]}; margin-top: 3px;">{content}</div>',
        ]

        # Show trigger info
        trigger_info = []
        if trigger_type == "time" and trigger_at:
            trigger_info.append(f"triggers at: {trigger_at}")
        elif trigger_type == "next_session":
            trigger_info.append("triggers: next session")

        if created_at:
            trigger_info.append(f"created: {created_at}")

        if trigger_info:
            lines.append(
                f'<div style="color: {COLORS["text_dim"]}; font-size: 11px; margin-top: 3px;">'
                f'{" | ".join(trigger_info)}</div>'
            )

        # Show context if available
        if context:
            context_escaped = context[:80].replace("<", "&lt;").replace(">", "&gt;")
            if len(context) > 80:
                context_escaped += "..."
            lines.append(
                f'<div style="color: {COLORS["text_dim"]}; font-size: 11px; font-style: italic; margin-top: 3px;">'
                f'Context: {context_escaped}</div>'
            )

        # Show outcome for completed/dismissed
        if status in ["completed", "dismissed"]:
            outcome = intention.get("outcome", "")
            completed_at = intention.get("completed_at", "")
            if outcome:
                outcome_escaped = outcome[:80].replace("<", "&lt;").replace(">", "&gt;")
                if len(outcome) > 80:
                    outcome_escaped += "..."
                lines.append(
                    f'<div style="color: {COLORS["text_dim"]}; font-size: 11px; margin-top: 3px;">'
                    f'Outcome: {outcome_escaped}</div>'
                )
            if completed_at:
                lines.append(
                    f'<div style="color: {COLORS["text_dim"]}; font-size: 10px; margin-top: 2px;">'
                    f'Completed: {completed_at}</div>'
                )

        lines.append('</div>')
        return ''.join(lines)


# Global instance
_dev_window: Optional[DevWindow] = None


def get_dev_window() -> Optional[DevWindow]:
    """Get the global dev window instance (None if not created)."""
    return _dev_window


def init_dev_window(parent=None) -> DevWindow:
    """Initialize and return the dev window."""
    global _dev_window
    _dev_window = DevWindow(parent)
    # Load initial state for tabs that need it
    load_initial_active_thoughts()
    load_initial_curiosity()
    load_initial_intentions()
    return _dev_window


def load_initial_active_thoughts():
    """Load current active thoughts into the dev window on startup."""
    if not _dev_window or not config.DEV_MODE_ENABLED:
        return

    try:
        from agency.active_thoughts import get_active_thoughts_manager
        manager = get_active_thoughts_manager()
        thoughts = manager.get_all()

        if thoughts:
            # Convert ActiveThought dataclass objects to dicts
            thought_dicts = []
            for t in thoughts:
                thought_dicts.append({
                    "rank": t.rank,
                    "slug": t.slug,
                    "topic": t.topic,
                    "elaboration": t.elaboration
                })

            # Emit to the dev window with special timestamp
            data = ActiveThoughtsData(
                thoughts=thought_dicts,
                timestamp="(initial load)"
            )
            _dev_window.signals.active_thoughts_updated.emit(data)
    except Exception:
        # Don't fail dev window initialization if this fails
        pass


def load_initial_curiosity():
    """Load current curiosity state into the dev window on startup."""
    from core.logger import log_info, log_error

    if not _dev_window:
        log_info("Curiosity initial load skipped: dev window not initialized", prefix="🔍")
        return

    if not config.DEV_MODE_ENABLED:
        log_info("Curiosity initial load skipped: DEV_MODE not enabled", prefix="🔍")
        return

    try:
        from agency.curiosity import is_curiosity_enabled, get_curiosity_engine

        if not is_curiosity_enabled():
            log_info("Curiosity initial load skipped: curiosity system disabled", prefix="🔍")
            return

        log_info("Loading initial curiosity state for DEV window...", prefix="🔍")

        engine = get_curiosity_engine()
        goal = engine.get_current_goal()
        history = engine.get_goal_history(limit=5)

        # Convert goal to dict
        goal_dict = {
            "id": goal.id,
            "content": goal.content,
            "category": goal.category,
            "context": goal.context,
            "activated_at": goal.activated_at.isoformat() if goal.activated_at else ""
        }

        log_info(f"Initial curiosity goal [{goal.id}]: {goal.content[:50]}...", prefix="🔍")

        # Convert history to list of dicts
        history_dicts = []
        for h in history:
            if h.status.value != "active":  # Skip active goal
                history_dicts.append({
                    "id": h.id,
                    "content": h.content,
                    "status": h.status.value,
                    "resolved_at": h.resolved_at.isoformat() if h.resolved_at else ""
                })

        data = CuriosityData(
            current_goal=goal_dict,
            history=history_dicts,
            cooldowns=[],  # Don't need cooldowns on initial load
            timestamp="(initial load)",
            event="initial"
        )
        _dev_window.signals.curiosity_updated.emit(data)
        log_info("Curiosity initial load emitted to DEV window", prefix="🔍")
    except Exception as e:
        # Log the error instead of silently swallowing it
        log_error(f"Failed to load initial curiosity state: {e}", prefix="🔍")


def load_initial_intentions():
    """Load current intentions into the dev window on startup."""
    if not _dev_window or not config.DEV_MODE_ENABLED:
        return

    try:
        from agency.intentions import get_intention_manager

        manager = get_intention_manager()

        # Get all intentions (active and recently completed/dismissed)
        all_intentions = []

        # Get active intentions (pending + triggered)
        active = manager.get_all_active_intentions()
        for intention in active:
            all_intentions.append({
                "id": intention.id,
                "type": intention.type,
                "content": intention.content,
                "context": intention.context,
                "trigger_type": intention.trigger_type,
                "trigger_at": intention.trigger_at.isoformat() if intention.trigger_at else None,
                "status": intention.status,
                "priority": intention.priority,
                "created_at": intention.created_at.isoformat() if intention.created_at else None,
                "triggered_at": intention.triggered_at.isoformat() if intention.triggered_at else None,
                "completed_at": intention.completed_at.isoformat() if intention.completed_at else None,
                "outcome": intention.outcome,
            })

        # Emit to dev window
        data = IntentionData(
            intentions=all_intentions,
            timestamp="(initial load)",
            event="initial"
        )
        _dev_window.signals.intentions_updated.emit(data)
    except Exception:
        # Don't fail dev window initialization if this fails
        pass


def emit_prompt_assembly(context_blocks: List[Dict[str, Any]], total_tokens: int = 0):
    """Emit prompt assembly data to dev window if active."""
    if _dev_window and config.DEV_MODE_ENABLED:
        data = PromptAssemblyData(
            context_blocks=context_blocks,
            total_tokens_estimate=total_tokens,
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3]
        )
        _dev_window.signals.prompt_assembly.emit(data)


def emit_command_executed(
    command_name: str,
    query: str,
    result_data: Any = None,
    error: Optional[str] = None,
    needs_continuation: bool = False
):
    """Emit command execution data to dev window if active."""
    if _dev_window and config.DEV_MODE_ENABLED:
        data = CommandExecutionData(
            command_name=command_name,
            query=query,
            result_data=result_data,
            error=error,
            needs_continuation=needs_continuation,
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3]
        )
        _dev_window.signals.command_executed.emit(data)


def emit_response_pass(
    pass_number: int,
    provider: str,
    response_text: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    duration_ms: float = 0,
    commands_detected: Optional[List[str]] = None,
    web_searches_used: int = 0,
    citations: Optional[List[Any]] = None
):
    """Emit response pass data to dev window if active."""
    if _dev_window and config.DEV_MODE_ENABLED:
        # Convert citations to WebSearchCitationData
        citation_data = []
        if citations:
            for c in citations:
                citation_data.append(WebSearchCitationData(
                    title=getattr(c, "title", "") if hasattr(c, "title") else c.get("title", ""),
                    url=getattr(c, "url", "") if hasattr(c, "url") else c.get("url", ""),
                    cited_text=getattr(c, "cited_text", "") if hasattr(c, "cited_text") else c.get("cited_text", "")
                ))

        data = ResponsePassData(
            pass_number=pass_number,
            provider=provider,
            response_text=response_text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=duration_ms,
            commands_detected=commands_detected or [],
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
            web_searches_used=web_searches_used,
            citations=citation_data
        )
        _dev_window.signals.response_pass.emit(data)


def emit_memory_recall(query: str, results: List[Dict[str, Any]]):
    """Emit memory recall data to dev window if active."""
    if _dev_window and config.DEV_MODE_ENABLED:
        data = MemoryRecallData(
            query=query,
            results=results,
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3]
        )
        _dev_window.signals.memory_recall.emit(data)


def emit_active_thoughts_update(thoughts: List[Dict[str, Any]]):
    """Emit active thoughts update to dev window if active."""
    if _dev_window and config.DEV_MODE_ENABLED:
        data = ActiveThoughtsData(
            thoughts=thoughts,
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3]
        )
        _dev_window.signals.active_thoughts_updated.emit(data)


def emit_curiosity_update(
    current_goal: Optional[Dict[str, Any]],
    history: Optional[List[Dict[str, Any]]] = None,
    cooldowns: Optional[List[Dict[str, Any]]] = None,
    event: str = "updated"
):
    """Emit curiosity update to dev window if active."""
    from core.logger import log_info

    if not config.DEV_MODE_ENABLED:
        return

    if not _dev_window:
        log_info(f"emit_curiosity_update called but dev window not initialized (event={event})", prefix="🔍")
        return

    data = CuriosityData(
        current_goal=current_goal,
        history=history or [],
        cooldowns=cooldowns or [],
        timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
        event=event
    )
    _dev_window.signals.curiosity_updated.emit(data)


def emit_intentions_update(intentions: List[Dict[str, Any]], event: str = "updated"):
    """Emit intentions update to dev window if active."""
    if _dev_window and config.DEV_MODE_ENABLED:
        data = IntentionData(
            intentions=intentions,
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
            event=event
        )
        _dev_window.signals.intentions_updated.emit(data)
