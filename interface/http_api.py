"""
Pattern Project - HTTP API
Flask-based REST API for external integrations
"""

import threading
from typing import Optional
from flask import Flask, request, jsonify

from core.logger import log_info, log_error
from core.database import get_database
from core.temporal import get_temporal_tracker
from memory.conversation import get_conversation_manager
from memory.vector_store import get_vector_store
from memory.extractor import get_memory_extractor
from llm.router import get_llm_router, TaskType


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        """Health check endpoint."""
        return jsonify({"status": "healthy", "service": "pattern-project"})

    @app.route("/chat", methods=["POST"])
    def chat():
        """
        Send a chat message and get a response.

        Request body:
        {
            "message": "The user message",
            "system_prompt": "Optional system prompt",
            "temperature": 0.7
        }
        """
        try:
            data = request.get_json()

            if not data or "message" not in data:
                return jsonify({"error": "Missing 'message' field"}), 400

            message = data["message"]
            system_prompt = data.get("system_prompt")
            temperature = data.get("temperature", 0.7)

            # Store user message
            conversation_mgr = get_conversation_manager()
            conversation_mgr.add_turn(
                role="user",
                content=message,
                input_type="text"
            )

            # Get history with semantic timestamps
            history = conversation_mgr.get_api_messages(limit=20)

            # Get response
            router = get_llm_router()
            from core.user_settings import get_user_settings
            response = router.chat(
                messages=history,
                system_prompt=system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=temperature,
                thinking_enabled=True
            )

            if response.success:
                # Strip any temporal markers the LLM echoed from prompt context
                from core.temporal import strip_temporal_echoes
                clean_text = strip_temporal_echoes(response.text)

                # Store response
                conversation_mgr.add_turn(
                    role="assistant",
                    content=clean_text,
                    input_type="text"
                )

                return jsonify({
                    "response": clean_text,
                    "provider": response.provider.value,
                    "tokens_in": response.tokens_in,
                    "tokens_out": response.tokens_out
                })
            else:
                return jsonify({"error": response.error}), 500

        except Exception as e:
            log_error(f"Chat API error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/memories/search", methods=["POST"])
    def search_memories():
        """
        Search memories.

        Request body:
        {
            "query": "Search query",
            "limit": 10,
            "memory_type": "fact|preference|event|observation|reflection"
        }
        """
        try:
            data = request.get_json()

            if not data or "query" not in data:
                return jsonify({"error": "Missing 'query' field"}), 400

            query = data["query"]
            limit = data.get("limit", 10)
            memory_type = data.get("memory_type")

            vector_store = get_vector_store()
            results = vector_store.search(
                query=query,
                limit=limit,
                memory_type=memory_type
            )

            return jsonify({
                "results": [
                    {
                        "id": r.memory.id,
                        "content": r.memory.content,
                        "type": r.memory.memory_type,
                        "importance": r.memory.importance,
                        "semantic_score": r.semantic_score,
                        "importance_score": r.importance_score,
                        "freshness_score": r.freshness_score,
                        "combined_score": r.combined_score
                    }
                    for r in results
                ]
            })

        except Exception as e:
            log_error(f"Memory search API error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/memories", methods=["POST"])
    def add_memory():
        """
        Add a memory directly.

        Request body:
        {
            "content": "Memory content",
            "memory_type": "fact|preference|event|observation|reflection",
            "importance": 0.5,
            "decay_category": "permanent|standard|ephemeral"
        }

        decay_category controls how quickly the memory fades from relevance:
          - permanent: Never decays (core identity, lasting preferences)
          - standard: 30-day half-life (events, discussions, insights)
          - ephemeral: 7-day half-life (situational observations)
        """
        try:
            data = request.get_json()

            if not data or "content" not in data:
                return jsonify({"error": "Missing 'content' field"}), 400

            vector_store = get_vector_store()
            memory_id = vector_store.add_memory(
                content=data["content"],
                source_conversation_ids=[],
                importance=data.get("importance", 0.5),
                memory_type=data.get("memory_type"),
                decay_category=data.get("decay_category", "standard")
            )

            if memory_id:
                return jsonify({"memory_id": memory_id})
            else:
                return jsonify({"error": "Failed to create memory"}), 500

        except Exception as e:
            log_error(f"Add memory API error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/stats", methods=["GET"])
    def stats():
        """Get system statistics."""
        try:
            db = get_database()
            db_stats = db.get_stats()

            tracker = get_temporal_tracker()
            context = tracker.get_context()

            extractor = get_memory_extractor()
            ext_stats = extractor.get_stats()

            return jsonify({
                "database": db_stats,
                "session": {
                    "active": tracker.is_session_active,
                    "session_id": tracker.current_session_id,
                    "turns_this_session": context.turns_this_session,
                    "duration_seconds": context.session_duration.total_seconds() if context.session_duration else 0
                },
                "extractor": ext_stats
            })

        except Exception as e:
            log_error(f"Stats API error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/session/new", methods=["POST"])
    def new_session():
        """Start a new session."""
        try:
            tracker = get_temporal_tracker()

            # End current session if active
            if tracker.is_session_active:
                tracker.end_session()

            session_id = tracker.start_session()
            return jsonify({"session_id": session_id})

        except Exception as e:
            log_error(f"New session API error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/session/end", methods=["POST"])
    def end_session():
        """End the current session."""
        try:
            tracker = get_temporal_tracker()

            if not tracker.is_session_active:
                return jsonify({"error": "No active session"}), 400

            # Extract memories before ending
            extractor = get_memory_extractor()
            extractor.extract_memories(force=True)

            summary = tracker.end_session()
            return jsonify({"summary": summary})

        except Exception as e:
            log_error(f"End session API error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/extract", methods=["POST"])
    def extract():
        """Force memory extraction."""
        try:
            extractor = get_memory_extractor()
            count = extractor.extract_memories(force=True)
            return jsonify({"memories_extracted": count})

        except Exception as e:
            log_error(f"Extract API error: {e}")
            return jsonify({"error": str(e)}), 500

    return app


class HTTPServer:
    """
    HTTP server manager.

    Runs Flask in a background thread.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 5000):
        self.host = host
        self.port = port
        self._app: Optional[Flask] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the HTTP server in a background thread."""
        self._app = create_app()

        self._thread = threading.Thread(
            target=self._run_server,
            daemon=True,
            name="HTTPServer"
        )
        self._thread.start()

        log_info(f"HTTP API started on http://{self.host}:{self.port}", prefix="🌐")

    def _run_server(self) -> None:
        """Run the Flask server."""
        # Suppress Flask's default logging
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)

        self._app.run(
            host=self.host,
            port=self.port,
            debug=False,
            use_reloader=False,
            threaded=True
        )

    def stop(self) -> None:
        """Stop the HTTP server."""
        # Flask doesn't have a clean shutdown mechanism in dev mode
        # The thread is a daemon, so it will stop when the main process exits
        pass


# Global HTTP server instance
_http_server: Optional[HTTPServer] = None


def get_http_server() -> HTTPServer:
    """Get the global HTTP server instance."""
    global _http_server
    if _http_server is None:
        from config import HTTP_HOST, HTTP_PORT
        _http_server = HTTPServer(host=HTTP_HOST, port=HTTP_PORT)
    return _http_server


def init_http_server(host: str = "127.0.0.1", port: int = 5000) -> HTTPServer:
    """Initialize the global HTTP server."""
    global _http_server
    _http_server = HTTPServer(host=host, port=port)
    return _http_server
