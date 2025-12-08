"""
Pattern Project - CLI Interface
Rich terminal interface for conversation
"""

import threading
import queue
from typing import Optional, Callable, Dict, Any

from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

import config
from core.logger import log_info, log_warning, log_error, log_success, get_timestamp
from core.temporal import get_temporal_tracker, temporal_context_to_semantic
from memory.conversation import get_conversation_manager
from memory.vector_store import get_vector_store
from memory.extractor import get_memory_extractor
from llm.router import get_llm_router, TaskType
from concurrency.locks import get_lock_manager
from prompt_builder import get_prompt_builder
from prompt_builder.sources.core_memory import get_core_memory_source
from prompt_builder.sources.relationship import get_relationship_source


class ChatCLI:
    """
    Rich CLI interface for conversation.

    Provides:
    - Formatted input/output
    - Slash commands
    - Status displays
    - System pulse timer integration
    """

    def __init__(self):
        self.console = Console()
        self._running = False
        self._lock_manager = get_lock_manager()
        self._commands: Dict[str, Callable] = {}
        self._pulse_queue: queue.Queue = queue.Queue()
        self._system_pulse_timer = None
        self._setup_commands()

    def _setup_commands(self) -> None:
        """Register slash commands."""
        self._commands = {
            "/help": self._cmd_help,
            "/quit": self._cmd_quit,
            "/exit": self._cmd_quit,
            "/end": self._cmd_end_session,
            "/new": self._cmd_new_session,
            "/stats": self._cmd_stats,
            "/memories": self._cmd_memories,
            "/search": self._cmd_search,
            "/extract": self._cmd_extract,
            "/pause": self._cmd_pause,
            "/resume": self._cmd_resume,
            "/core": self._cmd_core_memories,
            "/addcore": self._cmd_add_core,
            "/relationship": self._cmd_relationship,
            "/pulse": self._cmd_pulse,
        }

    def start(self) -> None:
        """Start the CLI chat loop."""
        self._running = True
        tracker = get_temporal_tracker()
        conversation_mgr = get_conversation_manager()
        router = get_llm_router()
        prompt_builder = get_prompt_builder()

        # Set up system pulse timer if enabled
        if config.SYSTEM_PULSE_ENABLED:
            from agency.system_pulse import get_system_pulse_timer
            self._system_pulse_timer = get_system_pulse_timer()
            self._system_pulse_timer.set_callback(self._on_pulse_fired)

        # Start a session if not already active
        if not tracker.is_session_active:
            tracker.start_session()

        self.console.print()
        self.console.print(
            "[bold cyan]💬 Entering chat mode. Type '/help' for commands.[/bold cyan]"
        )
        if config.SYSTEM_PULSE_ENABLED:
            self.console.print(
                f"[dim]System pulse active: AI will speak every {config.SYSTEM_PULSE_INTERVAL // 60} minutes if idle[/dim]"
            )
        self.console.print()

        while self._running:
            try:
                # Check for pending pulse before getting input
                self._check_pulse_queue()

                # Get user input
                user_input = Prompt.ask("[bold green]You[/bold green]")

                if not user_input.strip():
                    continue

                # Check for commands
                if user_input.startswith("/"):
                    self._handle_command(user_input)
                    continue

                # Reset pulse timer on user input
                if self._system_pulse_timer:
                    self._system_pulse_timer.reset()
                    self._system_pulse_timer.pause()

                # Store user message
                conversation_mgr.add_turn(
                    role="user",
                    content=user_input,
                    input_type="text"
                )

                # Build rich prompt with all context sources (no base prompt - emergent personality)
                assembled = prompt_builder.build(
                    user_input=user_input,
                    system_prompt=""
                )

                # Get conversation history for LLM
                history = conversation_mgr.get_recent_history(limit=30)

                # Show thinking indicator
                with self.console.status("[bold blue]Thinking...[/bold blue]", spinner="dots"):
                    # Get response from LLM with full context
                    response = router.chat(
                        messages=history,
                        system_prompt=assembled.full_system_prompt,
                        task_type=TaskType.CONVERSATION,
                        temperature=0.7
                    )

                if response.success:
                    # Store assistant response
                    conversation_mgr.add_turn(
                        role="assistant",
                        content=response.text,
                        input_type="text"
                    )

                    # Display response
                    self._display_response(response.text, response.provider.value)
                else:
                    self.console.print(
                        f"[bold red]Error:[/bold red] {response.error}"
                    )

                # Resume pulse timer after response
                if self._system_pulse_timer:
                    self._system_pulse_timer.resume()

            except KeyboardInterrupt:
                self.console.print("\n[dim]Use /quit to exit[/dim]")
            except EOFError:
                self._cmd_quit("")
            except Exception as e:
                log_error(f"CLI error: {e}")
                self.console.print(f"[bold red]Error:[/bold red] {e}")

    def stop(self) -> None:
        """Stop the CLI loop."""
        self._running = False

    def _display_response(self, text: str, provider: str) -> None:
        """Display the AI response."""
        timestamp = get_timestamp()

        # Create a panel for the response
        panel = Panel(
            Markdown(text),
            title=f"[bold blue]AI[/bold blue] [dim]({provider})[/dim]",
            title_align="left",
            border_style="blue",
            padding=(0, 1)
        )
        self.console.print(panel)
        self.console.print()

    def _on_pulse_fired(self) -> None:
        """Called when the system pulse timer fires (from background thread)."""
        # Queue the pulse for processing in the main loop
        self._pulse_queue.put(True)

    def _check_pulse_queue(self) -> None:
        """Check if there's a pending pulse to process."""
        try:
            # Non-blocking check
            self._pulse_queue.get_nowait()
            # Pulse is pending, process it
            self._process_pulse()
        except queue.Empty:
            pass

    def _process_pulse(self) -> None:
        """Process a system pulse."""
        from agency.system_pulse import PULSE_PROMPT, PULSE_STORED_MESSAGE

        conversation_mgr = get_conversation_manager()
        router = get_llm_router()
        prompt_builder = get_prompt_builder()

        try:
            # Pause timer during processing
            if self._system_pulse_timer:
                self._system_pulse_timer.pause()

            # Show pulse indicator
            self.console.print()
            self.console.print("[bold magenta]⏱️ System Pulse[/bold magenta]")

            # Store abbreviated pulse message
            conversation_mgr.add_turn(
                role="user",
                content=PULSE_STORED_MESSAGE,
                input_type="system_pulse"
            )

            # Build prompt with full pulse message
            assembled = prompt_builder.build(
                user_input=PULSE_PROMPT,
                system_prompt=""
            )

            # Get conversation history
            history = conversation_mgr.get_recent_history(limit=30)

            # Add the pulse prompt as the message to respond to
            # (role="user" is an API constraint, but content clarifies it's automated)
            history.append({"role": "user", "content": PULSE_PROMPT})

            # Show thinking indicator
            with self.console.status("[bold magenta]Pulse thinking...[/bold magenta]", spinner="dots"):
                response = router.chat(
                    messages=history,
                    system_prompt=assembled.full_system_prompt,
                    task_type=TaskType.CONVERSATION,
                    temperature=0.7
                )

            if response.success:
                # Store response
                conversation_mgr.add_turn(
                    role="assistant",
                    content=response.text,
                    input_type="text"
                )

                # Display with special styling
                panel = Panel(
                    Markdown(response.text),
                    title=f"[bold magenta]AI (pulse)[/bold magenta] [dim]({response.provider.value})[/dim]",
                    title_align="left",
                    border_style="magenta",
                    padding=(0, 1)
                )
                self.console.print(panel)
                self.console.print()
            else:
                self.console.print(f"[bold red]Pulse error:[/bold red] {response.error}")

        except Exception as e:
            log_error(f"Pulse processing error: {e}")
            self.console.print(f"[bold red]Pulse error:[/bold red] {e}")

        finally:
            # Resume timer
            if self._system_pulse_timer:
                self._system_pulse_timer.resume()

    def _handle_command(self, input_str: str) -> None:
        """Handle a slash command."""
        parts = input_str.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in self._commands:
            self._commands[cmd](args)
        else:
            self.console.print(f"[yellow]Unknown command: {cmd}[/yellow]")
            self.console.print("[dim]Type /help for available commands[/dim]")

    def _cmd_help(self, args: str) -> None:
        """Show help."""
        table = Table(title="Available Commands", show_header=True)
        table.add_column("Command", style="cyan")
        table.add_column("Description")

        table.add_row("/help", "Show this help message")
        table.add_row("/quit, /exit", "Exit the program")
        table.add_row("/new", "Start a new session")
        table.add_row("/end", "End the current session")
        table.add_row("/stats", "Show system statistics")
        table.add_row("/memories", "Show recent memories")
        table.add_row("/search <query>", "Search memories")
        table.add_row("/extract", "Force memory extraction")
        table.add_row("/core", "Show core memories")
        table.add_row("/addcore <category> <content>", "Add core memory (identity/relationship/preference/fact)")
        table.add_row("/relationship", "Show relationship status")
        table.add_row("/pulse", "Show system pulse timer status")
        table.add_row("/pause", "Pause background processes")
        table.add_row("/resume", "Resume background processes")

        self.console.print(table)

    def _cmd_quit(self, args: str) -> None:
        """Quit the program."""
        tracker = get_temporal_tracker()

        if tracker.is_session_active:
            self.console.print("[dim]Ending session...[/dim]")
            summary = tracker.end_session()
            if summary:
                self.console.print(
                    f"[dim]Session {summary['session_id']}: "
                    f"{summary['turn_count']} turns, "
                    f"{summary['duration_seconds']:.0f}s[/dim]"
                )

        self.console.print("[bold]Goodbye![/bold]")
        self._running = False

    def _cmd_end_session(self, args: str) -> None:
        """End the current session."""
        tracker = get_temporal_tracker()

        if not tracker.is_session_active:
            self.console.print("[yellow]No active session[/yellow]")
            return

        # Trigger memory extraction before ending
        extractor = get_memory_extractor()
        extractor.extract_memories(force=True)

        summary = tracker.end_session()
        if summary:
            self.console.print(
                f"[green]Session {summary['session_id']} ended: "
                f"{summary['turn_count']} turns, "
                f"{summary['duration_seconds']:.0f}s[/green]"
            )

    def _cmd_new_session(self, args: str) -> None:
        """Start a new session."""
        tracker = get_temporal_tracker()

        if tracker.is_session_active:
            self._cmd_end_session("")

        session_id = tracker.start_session()
        self.console.print(f"[green]Started new session {session_id}[/green]")

    def _cmd_stats(self, args: str) -> None:
        """Show statistics."""
        from core.database import get_database

        db = get_database()
        stats = db.get_stats()
        tracker = get_temporal_tracker()
        context = tracker.get_context()
        extractor = get_memory_extractor()
        ext_stats = extractor.get_stats()

        table = Table(title="System Statistics", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")

        table.add_row("Total Sessions", str(stats["total_sessions"]))
        table.add_row("Active Sessions", str(stats["active_sessions"]))
        table.add_row("Total Conversations", str(stats["total_conversations"]))
        table.add_row("Total Memories", str(stats["total_memories"]))
        table.add_row("Unprocessed Turns", str(stats["unprocessed_conversations"]))
        table.add_row("Memories Extracted", str(ext_stats["total_extractions"]))

        if context.session_duration:
            table.add_row(
                "Current Session Duration",
                f"{context.session_duration.total_seconds():.0f}s"
            )
        table.add_row("Turns This Session", str(context.turns_this_session))

        self.console.print(table)

    def _cmd_memories(self, args: str) -> None:
        """Show recent memories."""
        vector_store = get_vector_store()
        count = vector_store.get_memory_count()

        if count == 0:
            self.console.print("[dim]No memories stored yet[/dim]")
            return

        # Get recent memories by searching with empty-ish query
        results = vector_store.search("recent events and information", limit=5)

        if not results:
            self.console.print("[dim]No memories found[/dim]")
            return

        table = Table(title=f"Recent Memories ({count} total)", show_header=True)
        table.add_column("ID", style="dim")
        table.add_column("Type", style="cyan")
        table.add_column("Content")
        table.add_column("Score", style="green")

        for result in results:
            mem = result.memory
            table.add_row(
                str(mem.id),
                mem.memory_type or "?",
                mem.content[:60] + "..." if len(mem.content) > 60 else mem.content,
                f"{result.combined_score:.2f}"
            )

        self.console.print(table)

    def _cmd_search(self, args: str) -> None:
        """Search memories."""
        if not args:
            self.console.print("[yellow]Usage: /search <query>[/yellow]")
            return

        vector_store = get_vector_store()

        with self.console.status("[bold blue]Searching...[/bold blue]"):
            results = vector_store.search(args, limit=5)

        if not results:
            self.console.print("[dim]No matching memories found[/dim]")
            return

        table = Table(title=f"Search Results for: {args}", show_header=True)
        table.add_column("Type", style="cyan")
        table.add_column("Content")
        table.add_column("Semantic", style="green")
        table.add_column("Fresh", style="yellow")
        table.add_column("Total", style="bold green")

        for result in results:
            mem = result.memory
            table.add_row(
                mem.memory_type or "?",
                mem.content[:50] + "..." if len(mem.content) > 50 else mem.content,
                f"{result.semantic_score:.2f}",
                f"{result.freshness_score:.2f}",
                f"{result.combined_score:.2f}"
            )

        self.console.print(table)

    def _cmd_extract(self, args: str) -> None:
        """Force memory extraction."""
        extractor = get_memory_extractor()

        with self.console.status("[bold blue]Extracting memories...[/bold blue]"):
            count = extractor.extract_memories(force=True)

        if count > 0:
            self.console.print(f"[green]Extracted {count} memories[/green]")
        else:
            self.console.print("[dim]No new memories extracted[/dim]")

    def _cmd_pause(self, args: str) -> None:
        """Pause background processes."""
        extractor = get_memory_extractor()
        extractor.stop()
        self.console.print("[yellow]Background processes paused[/yellow]")

    def _cmd_resume(self, args: str) -> None:
        """Resume background processes."""
        extractor = get_memory_extractor()
        extractor.start()
        self.console.print("[green]Background processes resumed[/green]")

    def _cmd_core_memories(self, args: str) -> None:
        """Show core memories."""
        core_source = get_core_memory_source()
        memories = core_source.get_all()

        if not memories:
            self.console.print("[dim]No core memories set[/dim]")
            self.console.print("[dim]Use /addcore <category> <content> to add one[/dim]")
            return

        table = Table(title="Core Memories", show_header=True)
        table.add_column("ID", style="dim")
        table.add_column("Category", style="cyan")
        table.add_column("Content")

        for mem in memories:
            table.add_row(
                str(mem.id),
                mem.category,
                mem.content[:60] + "..." if len(mem.content) > 60 else mem.content
            )

        self.console.print(table)

    def _cmd_add_core(self, args: str) -> None:
        """Add a core memory."""
        if not args:
            self.console.print("[yellow]Usage: /addcore <category> <content>[/yellow]")
            self.console.print("[dim]Categories: identity, relationship, preference, fact[/dim]")
            return

        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            self.console.print("[yellow]Usage: /addcore <category> <content>[/yellow]")
            return

        category = parts[0].lower()
        content = parts[1]

        valid_categories = ["identity", "relationship", "preference", "fact"]
        if category not in valid_categories:
            self.console.print(f"[yellow]Invalid category. Use: {', '.join(valid_categories)}[/yellow]")
            return

        core_source = get_core_memory_source()
        memory_id = core_source.add(content=content, category=category)

        if memory_id:
            self.console.print(f"[green]Added core memory [{category}]: {content}[/green]")
        else:
            self.console.print("[red]Failed to add core memory[/red]")

    def _cmd_relationship(self, args: str) -> None:
        """Show relationship status."""
        relationship_source = get_relationship_source()
        state = relationship_source.get_state()

        if state is None:
            self.console.print("[dim]No relationship data yet[/dim]")
            return

        # Create visual representation (0-100 scale)
        affinity_bar = self._create_bar(state.affinity, 0, 100, 20)
        trust_bar = self._create_bar(state.trust, 0, 100, 20)

        table = Table(title="Relationship Status", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        table.add_column("Visual")

        table.add_row(
            "Affinity",
            f"{state.affinity}/100",
            affinity_bar
        )
        table.add_row(
            "Trust",
            f"{state.trust}/100",
            trust_bar
        )
        table.add_row(
            "Interactions",
            str(state.interaction_count),
            ""
        )

        if state.first_interaction:
            days = (state.updated_at - state.first_interaction).days
            table.add_row("Known for", f"{days} days", "")

        self.console.print(table)

    def _cmd_pulse(self, args: str) -> None:
        """Show system pulse timer status."""
        if not config.SYSTEM_PULSE_ENABLED:
            self.console.print("[dim]System pulse timer is disabled[/dim]")
            return

        if self._system_pulse_timer is None:
            self.console.print("[dim]System pulse timer not initialized[/dim]")
            return

        stats = self._system_pulse_timer.get_stats()

        table = Table(title="System Pulse Timer", show_header=False)
        table.add_column("Property", style="cyan")
        table.add_column("Value")

        table.add_row("Enabled", "Yes" if stats["enabled"] else "No")
        table.add_row("Running", "Yes" if stats["is_running"] else "No")
        table.add_row("Paused", "Yes" if stats["paused"] else "No")
        table.add_row("Interval", f"{stats['pulse_interval']}s ({stats['pulse_interval'] // 60}m)")

        remaining = stats["seconds_remaining"]
        minutes = remaining // 60
        seconds = remaining % 60
        table.add_row("Next Pulse In", f"{minutes}:{seconds:02d}")

        self.console.print(table)

    def _create_bar(self, value: float, min_val: float, max_val: float, width: int) -> str:
        """Create a visual bar representation."""
        normalized = (value - min_val) / (max_val - min_val)
        filled = int(normalized * width)
        empty = width - filled

        if min_val < 0:  # Affinity-style bar (negative to positive)
            mid = width // 2
            if value >= 0:
                left = "─" * mid
                right_filled = int((value / max_val) * mid)
                right = "█" * right_filled + "─" * (mid - right_filled)
            else:
                left_empty = int((abs(value) / abs(min_val)) * mid)
                left = "─" * (mid - left_empty) + "▓" * left_empty
                right = "─" * mid
            return f"[dim]{left}[/dim]│[green]{right}[/green]"
        else:  # Trust-style bar (0 to 1)
            return f"[green]{'█' * filled}[/green][dim]{'─' * empty}[/dim]"


# Global CLI instance
_cli: Optional[ChatCLI] = None


def get_cli() -> ChatCLI:
    """Get the global CLI instance."""
    global _cli
    if _cli is None:
        _cli = ChatCLI()
    return _cli


def init_cli() -> ChatCLI:
    """Initialize the global CLI instance."""
    global _cli
    _cli = ChatCLI()
    return _cli
