"""
Pattern Project - Visual Capture Command Handlers
Handlers for [[SCREENSHOT]] and [[WEBCAM]] commands (on-demand mode)

These handlers allow the AI to request visual captures when in on_demand mode.
In auto mode, visual captures are automatically attached to every prompt and
these handlers are not registered.
"""

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType
from core.logger import log_info, log_warning, log_error


class ScreenshotHandler(CommandHandler):
    """
    Handles [[SCREENSHOT]] commands for AI-initiated screen capture.

    This handler captures the current screen and returns it as image data
    for the continuation prompt. The AI will see the captured image.

    Usage:
        AI includes [[SCREENSHOT]] in response
        -> Handler captures screen
        -> Image attached to continuation message
        -> AI sees screenshot and continues response
    """

    @property
    def command_name(self) -> str:
        return "SCREENSHOT"

    @property
    def pattern(self) -> str:
        # Parameterless command: [[SCREENSHOT]]
        return r'\[\[SCREENSHOT\]\]'

    @property
    def needs_continuation(self) -> bool:
        # AI needs to see the captured image
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Execute screenshot capture.

        Args:
            query: Unused (parameterless command)
            context: Session context dict

        Returns:
            CommandResult with captured image in image_data
        """
        try:
            from agency.visual_capture import (
                capture_screenshot_for_claude,
                is_visual_capture_available
            )

            # Check availability
            screenshot_available, _ = is_visual_capture_available()
            if not screenshot_available:
                log_warning("Screenshot capture not available (PIL not installed)")
                return CommandResult(
                    command_name=self.command_name,
                    query="",
                    data=None,
                    needs_continuation=True,
                    display_text="Screenshot unavailable",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Screenshot capture is not available. PIL library may not be installed.",
                        expected_format=None,
                        example=None
                    )
                )

            # Capture screenshot
            image_content = capture_screenshot_for_claude()

            if image_content is None:
                log_warning("Screenshot capture returned None")
                return CommandResult(
                    command_name=self.command_name,
                    query="",
                    data=None,
                    needs_continuation=True,
                    display_text="Screenshot capture failed",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Failed to capture screenshot. The screen may not be accessible.",
                        expected_format=None,
                        example=None
                    )
                )

            log_info("Screenshot captured via [[SCREENSHOT]] command", prefix="📸")

            return CommandResult(
                command_name=self.command_name,
                query="",
                data={"source": "screenshot", "captured": True},
                needs_continuation=True,
                display_text="Screenshot captured",
                image_data=[image_content]
            )

        except Exception as e:
            log_error(f"Screenshot command exception: {e}")
            return CommandResult(
                command_name=self.command_name,
                query="",
                data=None,
                needs_continuation=True,
                display_text="Screenshot error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Screenshot capture error: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def get_instructions(self) -> str:
        """Return prompt instructions for the AI."""
        return """You can capture the current screen by including this command in your response:
  [[SCREENSHOT]]

Use this when:
- The user asks about what's on their screen
- You need to see what application they're using
- Troubleshooting a visual issue
- The user references something they can see

The screenshot is captured and provided to you for analysis. Describe what you see
and continue your response naturally."""

    def format_result(self, result: CommandResult) -> str:
        """Format result for continuation prompt text."""
        if result.error:
            return f"  {result.get_error_message()}"
        if result.has_images():
            return "  [Screenshot captured - see attached image]"
        return "  Screenshot capture completed."


class WebcamHandler(CommandHandler):
    """
    Handles [[WEBCAM]] commands for AI-initiated webcam capture.

    This handler captures a frame from the default webcam and returns it
    as image data for the continuation prompt. The AI will see the captured image.

    Usage:
        AI includes [[WEBCAM]] in response
        -> Handler captures webcam frame
        -> Image attached to continuation message
        -> AI sees webcam image and continues response
    """

    @property
    def command_name(self) -> str:
        return "WEBCAM"

    @property
    def pattern(self) -> str:
        # Parameterless command: [[WEBCAM]]
        return r'\[\[WEBCAM\]\]'

    @property
    def needs_continuation(self) -> bool:
        # AI needs to see the captured image
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Execute webcam capture.

        Args:
            query: Unused (parameterless command)
            context: Session context dict

        Returns:
            CommandResult with captured image in image_data
        """
        try:
            from agency.visual_capture import (
                capture_webcam_for_claude,
                is_visual_capture_available
            )

            # Check availability
            _, webcam_available = is_visual_capture_available()
            if not webcam_available:
                log_warning("Webcam capture not available (OpenCV not installed)")
                return CommandResult(
                    command_name=self.command_name,
                    query="",
                    data=None,
                    needs_continuation=True,
                    display_text="Webcam unavailable",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Webcam capture is not available. OpenCV library may not be installed.",
                        expected_format=None,
                        example=None
                    )
                )

            # Capture webcam
            image_content = capture_webcam_for_claude()

            if image_content is None:
                log_warning("Webcam capture returned None")
                return CommandResult(
                    command_name=self.command_name,
                    query="",
                    data=None,
                    needs_continuation=True,
                    display_text="Webcam capture failed",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Failed to capture webcam. The camera may not be accessible or in use by another application.",
                        expected_format=None,
                        example=None
                    )
                )

            log_info("Webcam captured via [[WEBCAM]] command", prefix="📷")

            return CommandResult(
                command_name=self.command_name,
                query="",
                data={"source": "webcam", "captured": True},
                needs_continuation=True,
                display_text="Webcam captured",
                image_data=[image_content]
            )

        except Exception as e:
            log_error(f"Webcam command exception: {e}")
            return CommandResult(
                command_name=self.command_name,
                query="",
                data=None,
                needs_continuation=True,
                display_text="Webcam error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Webcam capture error: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def get_instructions(self) -> str:
        """Return prompt instructions for the AI."""
        return """You can capture a webcam image by including this command in your response:
  [[WEBCAM]]

Use this when:
- The user asks you to see them
- Checking on the user's presence or wellbeing
- The user references their appearance or environment
- You want to provide a more personal, aware response

The webcam image is captured and provided to you. Be respectful of privacy -
describe what you see generally without identifying details."""

    def format_result(self, result: CommandResult) -> str:
        """Format result for continuation prompt text."""
        if result.error:
            return f"  {result.get_error_message()}"
        if result.has_images():
            return "  [Webcam image captured - see attached image]"
        return "  Webcam capture completed."
