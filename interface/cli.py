"""
Pattern Project - CLI Interface
Rich terminal interface for conversation
"""

import queue
from typing import Optional, Callable, Dict, Any

from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table

import config
from core.logger import log_error, get_timestamp
from core.temporal import get_temporal_tracker
from memory.vector_store import get_vector_store
from memory.extractor import get_memory_extractor
from llm.router import TaskType
from concurrency.locks import get_lock_manager
from prompt_builder.sources.core_memory import get_core_memory_source


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
        self._reminder_queue: queue.Queue = queue.Queue()
        self._telegram_queue: queue.Queue = queue.Queue()
        self._system_pulse_timer = None
        self._reminder_scheduler = None
        self._telegram_listener = None
        self._engine = None  # ChatEngine (set via set_engine)
        self._is_first_message_of_session = True  # Track for next_session reminder triggers
        self._setup_commands()

    def set_engine(self, engine):
        """Set the ChatEngine instance for message processing."""
        self._engine = engine

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
            "/pulse": self._cmd_pulse,
        }

    def start(self) -> None:
        """Start the CLI chat loop."""
        self._running = True
        tracker = get_temporal_tracker()

        # Set up pulse manager if enabled
        if config.SYSTEM_PULSE_ENABLED:
            from agency.system_pulse import get_pulse_manager
            self._system_pulse_timer = get_pulse_manager()
            self._system_pulse_timer.set_reflective_callback(self._on_pulse_fired)
            self._system_pulse_timer.set_action_callback(self._on_pulse_fired)

        # Set up reminder scheduler
        from agency.intentions import get_reminder_scheduler
        self._reminder_scheduler = get_reminder_scheduler()
        self._reminder_scheduler.set_callback(self._on_reminder_fired)

        # Set up Telegram listener if enabled
        if config.TELEGRAM_ENABLED:
            from communication.telegram_listener import get_telegram_listener
            self._telegram_listener = get_telegram_listener()
            self._telegram_listener.set_callback(self._on_telegram_message)

        # Register engine event listener for CLI display
        if self._engine:
            self._engine.add_listener(self._on_engine_event)

        # Start a session if not already active
        if not tracker.is_session_active:
            tracker.start_session()

        self.console.print()
        self.console.print(
            "[bold cyan]💬 Entering chat mode. Type '/help' for commands.[/bold cyan]"
        )
        if config.SYSTEM_PULSE_ENABLED:
            self.console.print(
                f"[dim]System pulse active: action every {config.ACTION_PULSE_INTERVAL // 3600}h, reflection every {config.REFLECTIVE_PULSE_INTERVAL // 3600}h[/dim]"
            )
        if config.TELEGRAM_ENABLED:
            self.console.print(
                "[dim]Telegram bidirectional messaging active[/dim]"
            )
        if config.DEV_MODE_ENABLED:
            self.console.print(
                "[bold magenta]🔧 Dev mode active: Showing internal operations[/bold magenta]"
            )
        self.console.print()

        # State for collecting engine results
        self._last_result = {}

        while self._running:
            try:
                # Check for pending pulse/reminder/telegram before getting input
                self._check_pulse_queue()
                self._check_reminder_queue()
                self._check_telegram_queue()

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
                    self._system_pulse_timer.reset_all()
                    self._system_pulse_timer.pause()

                # Process via engine (synchronous — blocks until complete)
                self._last_result = {}
                with self.console.status("[bold blue]Thinking...[/bold blue]", spinner="dots"):
                    self._engine.process_message(user_input)

                # Display the result collected by the event listener
                if self._last_result.get("error"):
                    self.console.print(
                        f"[bold red]Error:[/bold red] {self._last_result['error']}"
                    )
                elif self._last_result.get("text"):
                    final_text = self._last_result["text"]
                    provider = self._last_result.get("provider", "anthropic")
                    clarification = self._last_result.get("clarification")
                    self._display_response(final_text, provider, clarification)

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

    def _display_response(
        self,
        text: str,
        provider: str,
        clarification: Optional[Dict[str, Any]] = None
    ) -> None:
        """Display the AI response, with special styling for clarification requests."""
        timestamp = get_timestamp()

        if clarification:
            # Special styling for clarification requests
            question = clarification.get("question", "")
            options = clarification.get("options", [])
            context_note = clarification.get("context", "")

            # Build clarification panel content
            content_parts = []
            if context_note:
                content_parts.append(f"[dim italic]{context_note}[/dim italic]")
                content_parts.append("")

            content_parts.append(f"[bold]{question}[/bold]")

            if options:
                content_parts.append("")
                for i, opt in enumerate(options, 1):
                    content_parts.append(f"  [cyan]{i}.[/cyan] {opt}")

            clarification_panel = Panel(
                "\n".join(content_parts),
                title="[bold yellow]Clarification Needed[/bold yellow]",
                title_align="left",
                border_style="yellow",
                padding=(1, 2)
            )
            self.console.print(clarification_panel)

            # Also show any additional response text (Claude's natural language)
            if text.strip():
                self.console.print()
                self.console.print(Markdown(text))
        else:
            # Normal response display
            panel = Panel(
                Markdown(text),
                title=f"[bold blue]AI[/bold blue] [dim]({provider})[/dim]",
                title_align="left",
                border_style="blue",
                padding=(0, 1)
            )
            self.console.print(panel)

        self.console.print()

    def _display_clarification_panel(self, clarification: Dict[str, Any]) -> None:
        """Display a clarification request panel."""
        question = clarification.get("question", "")
        options = clarification.get("options", [])
        context_note = clarification.get("context", "")

        # Build clarification panel content
        content_parts = []
        if context_note:
            content_parts.append(f"[dim italic]{context_note}[/dim italic]")
            content_parts.append("")

        content_parts.append(f"[bold]{question}[/bold]")

        if options:
            content_parts.append("")
            for i, opt in enumerate(options, 1):
                content_parts.append(f"  [cyan]{i}.[/cyan] {opt}")

        panel = Panel(
            "\n".join(content_parts),
            title="[bold yellow]Clarification Needed[/bold yellow]",
            title_align="left",
            border_style="yellow",
            padding=(1, 2)
        )
        self.console.print(panel)

    def _on_engine_event(self, event):
        """Handle engine events for CLI display.

        For user messages (synchronous), we collect results in _last_result
        and display after the engine call returns.

        For async sources (pulse, reminder, telegram), we display directly
        since they run in background threads via the queue system.
        """
        from engine.events import EngineEventType

        etype = event.event_type
        data = event.data

        if etype == EngineEventType.RESPONSE_COMPLETE:
            source = data.get("source", "user")
            text = data.get("text", "")
            provider = data.get("provider", "anthropic")

            if source == "user":
                # Collect for synchronous display after engine returns
                self._last_result["text"] = text
                self._last_result["provider"] = provider
            elif source == "pulse":
                pulse_type = data.get("pulse_type", "action")
                panel = Panel(
                    Markdown(text),
                    title=f"[bold magenta]AI ({pulse_type} pulse)[/bold magenta] [dim]({provider})[/dim]",
                    title_align="left",
                    border_style="magenta",
                    padding=(0, 1)
                )
                self.console.print(panel)
                self.console.print()
            elif source == "reminder":
                panel = Panel(
                    Markdown(text),
                    title=f"[bold yellow]AI (reminder)[/bold yellow] [dim]({provider})[/dim]",
                    title_align="left",
                    border_style="yellow",
                    padding=(0, 1)
                )
                self.console.print(panel)
                self.console.print()
            elif source == "telegram":
                panel = Panel(
                    Markdown(text),
                    title=f"[bold cyan]AI (telegram)[/bold cyan] [dim]({provider})[/dim]",
                    title_align="left",
                    border_style="cyan",
                    padding=(0, 1)
                )
                self.console.print(panel)
                self.console.print()
            elif source == "retry":
                original_source = data.get("original_source", "user")
                style = "cyan" if original_source == "telegram" else "blue"
                panel = Panel(
                    Markdown(text),
                    title=f"[bold {style}]AI (retry)[/bold {style}] [dim]({provider})[/dim]",
                    title_align="left",
                    border_style=style,
                    padding=(0, 1)
                )
                self.console.print(panel)
                self.console.print()

        elif etype == EngineEventType.PROCESSING_ERROR:
            error = data.get("error", "Unknown error")
            source = data.get("source", "")
            # For user messages, collect for synchronous display
            if not hasattr(self, '_last_result') or self._last_result is None:
                self._last_result = {}
            self._last_result["error"] = error

        elif etype == EngineEventType.CLARIFICATION_REQUESTED:
            # Collect for synchronous display
            if hasattr(self, '_last_result'):
                self._last_result["clarification"] = data.get("data")

        elif etype == EngineEventType.TELEGRAM_RECEIVED:
            from_info = f" from {data.get('from_user', '')}" if data.get('from_user') else ""
            text = data.get("text", "")
            self.console.print()
            self.console.print(f"[bold cyan]📱 Telegram Message{from_info}[/bold cyan]")
            self.console.print(f"[dim]{text}[/dim]")

        elif etype == EngineEventType.PULSE_FIRED:
            pulse_type = data.get("pulse_type", "action")
            self.console.print()
            self.console.print(f"[bold magenta]⏱️ {pulse_type.capitalize()} Pulse[/bold magenta]")

        elif etype == EngineEventType.REMINDER_FIRED:
            intentions = data.get("intentions", [])
            self.console.print()
            self.console.print(f"[bold yellow]⏰ Reminder Triggered ({len(intentions)} intention(s))[/bold yellow]")

        elif etype == EngineEventType.RETRY_FAILED:
            source = data.get("source", "user")
            self.console.print(f"[bold red]Retry failed ({source}):[/bold red] {data.get('error', 'unknown')}")

    def _display_dev_prompt_assembly(self, assembled) -> None:
        """Display prompt assembly info in dev mode."""
        if not config.DEV_MODE_ENABLED:
            return

        self.console.print()
        self.console.print("[bold magenta]═══ DEV: Prompt Assembly ═══[/bold magenta]")

        total_tokens = len(assembled.full_system_prompt) // 4  # Rough estimate
        self.console.print(f"[dim]Estimated tokens: ~{total_tokens}[/dim]")

        for block in sorted(assembled.context_blocks, key=lambda b: b.priority):
            block_tokens = len(block.content) // 4
            self.console.print(
                f"  [cyan]{block.source_name}[/cyan] "
                f"[dim](priority {block.priority}, ~{block_tokens} tokens)[/dim]"
            )

        self.console.print()

    def _display_dev_response_pass(self, pass_num: int, provider: str,
                                    response_text: str, commands: list,
                                    duration_ms: float = 0) -> None:
        """Display response pass info in dev mode."""
        if not config.DEV_MODE_ENABLED:
            return

        self.console.print(
            f"[bold magenta]═══ DEV: Pass {pass_num} ({provider}) ═══[/bold magenta]"
        )
        if duration_ms > 0:
            self.console.print(f"[dim]Duration: {duration_ms:.0f}ms[/dim]")

        if commands:
            cmd_list = ", ".join([f"[[{c}]]" for c in commands])
            self.console.print(f"[yellow]Commands detected: {cmd_list}[/yellow]")

        # Show truncated response preview
        preview = response_text[:200]
        if len(response_text) > 200:
            preview += "..."
        self.console.print(f"[dim]Response: {preview}[/dim]")
        self.console.print()

    def _display_dev_command_execution(self, cmd_name: str, query: str,
                                        result_data, error: str = None) -> None:
        """Display command execution info in dev mode."""
        if not config.DEV_MODE_ENABLED:
            return

        status = "[green]Success[/green]" if not error else f"[red]Error: {error}[/red]"
        self.console.print(
            f"  [yellow][[{cmd_name}: {query[:50]}{'...' if len(query) > 50 else ''}]][/yellow] → {status}"
        )

    def _process_native_tools_response_cli(
        self,
        response,
        history: list,
        system_prompt: str,
        tools: list,
        max_passes: int,
        pass1_duration: float,
        router
    ) -> tuple:
        """
        Process response using native tool use (CLI version).

        DEPRECATED (December 2025): This method is no longer called.
        Use `process_with_tools` from agency.tools instead.
        The shared helper provides consistent processing across all entry points.
        Kept for reference during migration period.

        Returns:
            Tuple of (final_text, final_provider)
        """
        import time
        from llm.router import TaskType
        from agency.tools import get_tool_processor

        processor = get_tool_processor()
        current_response = response
        current_history = history.copy()
        current_duration = pass1_duration
        current_provider = response.provider.value

        for pass_num in range(1, max_passes + 1):
            # Process response for tool calls
            processed = processor.process(current_response, context={})

            # Get tool names for dev display
            tool_names = [tc.name for tc in current_response.tool_calls] if current_response.has_tool_calls() else []

            # Display dev mode info
            self._display_dev_response_pass(
                pass_num, current_provider, current_response.text,
                tool_names, current_duration
            )

            # Display dev mode tool execution info
            for result in processed.tool_results:
                self._display_dev_command_execution(
                    result.tool_name,
                    str(result.content)[:100] if result.content else "",
                    result.content,
                    str(result.content) if result.is_error else None
                )

            # If no continuation needed
            if not processed.needs_continuation:
                return processed.display_text, current_provider

            # Show status
            if pass_num == 1:
                self.console.print("[dim]  ↳ Executing tools...[/dim]")
            else:
                self.console.print(f"[dim]  ↳ Executing tools (pass {pass_num})...[/dim]")

            # Build continuation with raw content blocks
            current_history.append({
                "role": "assistant",
                "content": current_response.raw_content
            })

            # Ensure every tool_use block has a matching tool_result
            # (server-side tools need synthetic results)
            from agency.tools.response_helper import ensure_tool_results
            tool_result_msg = ensure_tool_results(
                current_response.raw_content,
                processed.tool_result_message
            )
            current_history.append(tool_result_msg)

            # Get next response
            cont_start = time.time()
            with self.console.status("[bold blue]Continuing...[/bold blue]", spinner="dots"):
                from core.user_settings import get_user_settings
                continuation = router.chat(
                    messages=current_history,
                    system_prompt=system_prompt,
                    task_type=TaskType.CONVERSATION,
                    temperature=0.7,
                    tools=tools,
                    thinking_enabled=True
                )
            current_duration = (time.time() - cont_start) * 1000

            if not continuation.success:
                return processed.display_text, current_provider

            current_response = continuation
            current_provider = continuation.provider.value

        # Hit max passes
        return current_response.text, current_provider

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
        """Process a system pulse via engine (defaults to action pulse in CLI)."""
        if self._engine:
            with self.console.status("[bold magenta]Pulse thinking...[/bold magenta]", spinner="dots"):
                self._engine.process_pulse("action")
        else:
            log_error("Engine not available for pulse processing")

    def _on_reminder_fired(self, triggered_intentions) -> None:
        """Called when the reminder scheduler detects due intentions (from background thread)."""
        # Queue the reminder for processing in the main loop
        self._reminder_queue.put(triggered_intentions)

    def _check_reminder_queue(self) -> None:
        """Check if there's a pending reminder to process."""
        try:
            # Non-blocking check
            triggered_intentions = self._reminder_queue.get_nowait()
            # Reminder is pending, process it
            self._process_reminder(triggered_intentions)
        except queue.Empty:
            pass

    def _process_reminder(self, triggered_intentions) -> None:
        """Process a reminder pulse via engine."""
        if self._engine:
            with self.console.status("[bold yellow]Reminder thinking...[/bold yellow]", spinner="dots"):
                self._engine.process_reminder(triggered_intentions)
        else:
            log_error("Engine not available for reminder processing")

    def _on_telegram_message(self, message) -> None:
        """Called when a Telegram message is received (from background thread)."""
        # Queue the message for processing in the main loop
        self._telegram_queue.put(message)

    def _check_telegram_queue(self) -> None:
        """Check if there's a pending Telegram message to process."""
        try:
            # Non-blocking check
            message = self._telegram_queue.get_nowait()
            # Message is pending, process it
            self._process_telegram_message(message)
        except queue.Empty:
            pass

    def _process_telegram_message(self, message) -> None:
        """Process an inbound Telegram message via engine."""
        if self._engine:
            with self.console.status("[bold cyan]Responding to Telegram...[/bold cyan]", spinner="dots"):
                self._engine.process_telegram(message)
        else:
            log_error("Engine not available for telegram processing")

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
        self._is_first_message_of_session = True  # Reset flag for next_session reminder triggers
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
        table.add_column("Import", style="magenta")
        table.add_column("Fresh", style="yellow")
        table.add_column("Total", style="bold green")

        for result in results:
            mem = result.memory
            table.add_row(
                mem.memory_type or "?",
                mem.content[:50] + "..." if len(mem.content) > 50 else mem.content,
                f"{result.semantic_score:.2f}",
                f"{result.importance_score:.2f}",
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

    def _cmd_pulse(self, args: str) -> None:
        """Show system pulse timer status."""
        if not config.SYSTEM_PULSE_ENABLED:
            self.console.print("[dim]System pulse timer is disabled[/dim]")
            return

        if self._system_pulse_timer is None:
            self.console.print("[dim]System pulse timer not initialized[/dim]")
            return

        stats = self._system_pulse_timer.get_stats()
        from prompt_builder.sources.system_pulse import get_interval_label

        table = Table(title="Pulse Manager", show_header=False)
        table.add_column("Property", style="cyan")
        table.add_column("Value")

        table.add_row("Enabled", "Yes" if stats["enabled"] else "No")
        table.add_row("Running", "Yes" if stats["is_running"] else "No")
        table.add_row("Paused", "Yes" if stats["paused"] else "No")
        table.add_row("Processing", "Yes" if stats["is_processing"] else "No")

        r = stats["reflective"]
        r_label = get_interval_label(r["interval"])
        r_remaining = r["seconds_remaining"]
        r_min, r_sec = divmod(r_remaining, 60)
        table.add_row("Reflective Interval", f"{r_label} (Opus)")
        table.add_row("Reflective Next In", f"{r_min}:{r_sec:02d}")

        a = stats["action"]
        a_label = get_interval_label(a["interval"])
        a_remaining = a["seconds_remaining"]
        a_min, a_sec = divmod(a_remaining, 60)
        table.add_row("Action Interval", f"{a_label} (Sonnet)")
        table.add_row("Action Next In", f"{a_min}:{a_sec:02d}")

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
