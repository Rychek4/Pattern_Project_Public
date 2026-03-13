"""
Pattern Project - Image Memory Handler
Allows the AI to save images to long-term visual memory.

When the AI decides an image is worth remembering, it calls save_image
with a description. The handler:
1. Finds the temp image file for the specified source
2. Moves it to permanent storage (data/images/)
3. Creates an image_files record
4. Creates a memory record with the description + image_id reference

The image description is embedded and searchable like any other memory.
When recalled (automatically or via search_memories), the image is loaded
from disk and injected as multimodal content.
"""

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import config
from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType
from core.logger import log_info, log_error

if TYPE_CHECKING:
    from agency.visual_capture import ImageContent


def load_image_for_memory(image_file_id: int) -> Optional["ImageContent"]:
    """Load an image from disk by its image_files table ID.

    Looks up the file path in the image_files table, reads the JPEG bytes,
    and returns an ImageContent ready for multimodal injection.

    Args:
        image_file_id: Primary key in the image_files table

    Returns:
        ImageContent or None if the file doesn't exist or can't be read
    """
    from core.database import get_database
    from agency.visual_capture import format_image_for_claude

    try:
        db = get_database()
        rows = db.execute(
            "SELECT file_path, source_type FROM image_files WHERE id = ?",
            (image_file_id,),
            fetch=True
        )
        if not rows:
            log_error(f"Image file record #{image_file_id} not found")
            return None

        file_path = config.IMAGE_STORAGE_DIR / rows[0]["file_path"]
        source_type = rows[0]["source_type"]

        if not file_path.exists():
            log_error(f"Image file not found on disk: {file_path}")
            return None

        image_bytes = file_path.read_bytes()
        return format_image_for_claude(image_bytes, source_type)

    except Exception as e:
        log_error(f"Failed to load image #{image_file_id}: {e}")
        return None


class SaveImageHandler(CommandHandler):
    """Save the current turn's image to long-term visual memory."""

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Save an image to permanent storage and create a memory record.

        Args:
            query: Pipe-separated "source_type | description"
            context: Session context dict
        """
        from agency.visual_capture import get_temp_images
        from memory.vector_store import get_vector_store
        from core.database import get_database
        from concurrency.locks import get_lock_manager
        from concurrency.db_retry import db_retry

        if not config.IMAGE_MEMORY_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Image memory is disabled.",
                    expected_format=None,
                    example=None
                )
            )

        # Parse input: "source_type | description"
        parts = query.split("|", 1)
        if len(parts) < 2:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=ToolError(
                    error_type=ToolErrorType.INVALID_INPUT,
                    message="Expected format: source | description",
                    expected_format="save_image(source='screenshot', description='...')",
                    example="save_image(source='screenshot', description='User workspace with dual monitors')"
                )
            )

        source_type = parts[0].strip().lower()
        description = parts[1].strip()

        if not description:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=ToolError(
                    error_type=ToolErrorType.INVALID_INPUT,
                    message="Description is required when saving an image.",
                    expected_format="save_image(source='screenshot', description='...')",
                    example=None
                )
            )

        # Find temp image for this source type
        temp_images = get_temp_images()
        temp_path = temp_images.get(source_type)

        if not temp_path or not Path(temp_path).exists():
            available = list(temp_images.keys()) if temp_images else []
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=ToolError(
                    error_type=ToolErrorType.INVALID_INPUT,
                    message=f"No image available for source '{source_type}'. Available sources: {available}",
                    expected_format=None,
                    example=None
                )
            )

        try:
            # Generate permanent filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Use first 30 chars of description, sanitized
            safe_desc = "".join(c if c.isalnum() or c in "_- " else "" for c in description[:30]).strip().replace(" ", "_")
            permanent_filename = f"{timestamp}_{safe_desc}.jpg"
            permanent_path = config.IMAGE_STORAGE_DIR / permanent_filename

            # Move from temp to permanent storage
            config.IMAGE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(temp_path, str(permanent_path))
            log_info(f"Image moved to permanent storage: {permanent_filename}", prefix="💾")

            # Create image_files record
            lock_manager = get_lock_manager()
            with lock_manager.acquire("memory"):
                db = get_database()
                db.execute(
                    """
                    INSERT INTO image_files (file_path, source_type, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (permanent_filename, source_type, datetime.now().isoformat())
                )
                result = db.execute(
                    "SELECT id FROM image_files ORDER BY id DESC LIMIT 1",
                    fetch=True
                )
                image_file_id = result[0]["id"] if result else None

            if image_file_id is None:
                log_error("Failed to create image_files record")
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Failed to create image file record in database.",
                        expected_format=None,
                        example=None
                    )
                )

            # Create memory record with image_id reference
            vector_store = get_vector_store()
            memory_id = vector_store.add_memory(
                content=f"[Visual memory] {description}",
                source_conversation_ids=[],
                importance=0.7,
                memory_type="observation",
                decay_category="standard",
                memory_category="episodic",
                image_id=image_file_id
            )

            if memory_id is None:
                log_error("Failed to create memory record for saved image")
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Image file saved but memory record creation failed (embedding error).",
                        expected_format=None,
                        example=None
                    )
                )

            log_info(f"Image memory created: memory #{memory_id}, image_file #{image_file_id}", prefix="🖼️")

            return CommandResult(
                command_name=self.command_name,
                query=query,
                data={
                    "memory_id": memory_id,
                    "image_file_id": image_file_id,
                    "filename": permanent_filename,
                    "description": description,
                    "source_type": source_type
                },
                needs_continuation=True,
                display_text=f"Saved image to visual memory: {description}"
            )

        except Exception as e:
            log_error(f"Failed to save image: {e}")
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Failed to save image: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"
        data = result.data or {}
        return f"  Image saved to visual memory (memory #{data.get('memory_id', '?')}): {data.get('description', '')}"
