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


class DevWindowSignals(QObject):
    """Signals for updating the dev window from other threads."""
    prompt_assembly = pyqtSignal(object)  # PromptAssemblyData
    command_executed = pyqtSignal(object)  # CommandExecutionData
    response_pass = pyqtSignal(object)  # ResponsePassData
    memory_recall = pyqtSignal(object)  # MemoryRecallData
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
        """Create the Commands tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Info label
        info = QLabel("Shows tool/command execution details")
        info.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(info)

        # Content area
        self.commands_display = QTextBrowser()
        self.commands_display.setFont(QFont("Consolas", 10))
        self.commands_display.setOpenExternalLinks(False)
        layout.addWidget(self.commands_display)

        self.tabs.addTab(tab, "Commands")

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
        info = QLabel("Shows memory recall queries and scores")
        info.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(info)

        # Content area
        self.memory_display = QTextBrowser()
        self.memory_display.setFont(QFont("Consolas", 10))
        self.memory_display.setOpenExternalLinks(False)
        layout.addWidget(self.memory_display)

        self.tabs.addTab(tab, "Memory Recall")

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
        self._update_status(f"Command executed: [[{data.command_name}]]")

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

    def _clear_all(self):
        """Clear all displays."""
        self.prompt_display.clear()
        self.commands_display.clear()
        self.response_display.clear()
        self.memory_display.clear()
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
        """Format command execution data as HTML."""
        status_color = COLORS["success"] if not data.error else COLORS["error"]
        status_text = "Success" if not data.error else f"Error: {data.error}"

        lines = [
            f'<div style="margin-bottom: 15px; padding: 10px; background-color: {COLORS["surface_alt"]}; border-radius: 5px;">',
            f'<div style="color: {COLORS["warning"]}; font-weight: bold; margin-bottom: 8px;">'
            f'[[{data.command_name}: {data.query}]]</div>',
            f'<div style="color: {COLORS["text_dim"]}; margin-bottom: 5px;">{data.timestamp}</div>',
            f'<div style="color: {status_color}; margin-bottom: 5px;">{status_text}</div>',
        ]

        if data.needs_continuation:
            lines.append(
                f'<div style="color: {COLORS["info"]};">Triggered continuation (Pass 2)</div>'
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
                f'Commands detected: {cmd_list}</div>'
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
        """Format memory recall data as HTML."""
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

        for i, result in enumerate(data.results, 1):
            score = result.get("score", 0)
            semantic = result.get("semantic_score", 0)
            importance = result.get("importance_score", 0)
            freshness = result.get("freshness_score", 0)
            content = result.get("content", "")[:150]
            content = content.replace("<", "&lt;").replace(">", "&gt;")

            # Color code by score
            score_color = COLORS["success"] if score > 0.7 else (
                COLORS["warning"] if score > 0.4 else COLORS["text_dim"]
            )

            lines.append(
                f'<div style="margin: 8px 0; padding: 8px; border-left: 3px solid {score_color};">'
                f'<div style="color: {score_color}; font-weight: bold;">#{i} Score: {score:.3f}</div>'
                f'<div style="color: {COLORS["text_dim"]}; font-size: 11px;">'
                f'semantic: {semantic:.2f} | importance: {importance:.2f} | freshness: {freshness:.2f}</div>'
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


# Global instance
_dev_window: Optional[DevWindow] = None


def get_dev_window() -> Optional[DevWindow]:
    """Get the global dev window instance (None if not created)."""
    return _dev_window


def init_dev_window(parent=None) -> DevWindow:
    """Initialize and return the dev window."""
    global _dev_window
    _dev_window = DevWindow(parent)
    return _dev_window


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
