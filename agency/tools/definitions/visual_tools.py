"""Visual capture and image memory tool definitions."""

from typing import Any, Dict

CAPTURE_SCREENSHOT_TOOL: Dict[str, Any] = {
    "name": "capture_screenshot",
    "description": """Capture the current screen to see what the user is looking at.

Use when:
- The user asks about what's on their screen
- You need to see what application they're using
- Troubleshooting a visual issue
- The user references something they can see

The screenshot is captured and provided to you for analysis.
Describe what you see and continue your response naturally.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

CAPTURE_WEBCAM_TOOL: Dict[str, Any] = {
    "name": "capture_webcam",
    "description": """Capture a webcam image to see the user.

Use respectfully when visual context would genuinely help:
- The user asks you to see them
- Checking on the user's presence or wellbeing
- The user references their appearance or environment

Be respectful of privacy - describe what you see generally without excessive detail.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

SAVE_IMAGE_TOOL: Dict[str, Any] = {
    "name": "save_image",
    "description": """Save the current image to your long-term visual memory.

When you see an image this turn (screenshot, webcam, telegram photo, or pasted image),
you can choose to save it if it seems worth remembering. Your description will be
embedded and searchable — it's how you'll find this image later, so be descriptive.

The image is saved to permanent storage and linked as a memory. When that memory is
later recalled (via search_memories or automatic relevance), the original image will
be loaded and shown to you again so you can reprocess it with fresh context.

Use when:
- An image contains information you may want to revisit later
- The user shares something visually significant (workspace, project, photo)
- A screenshot captures a state you want to compare against in the future
- You notice something visually interesting or important

Your description should capture what you see AND why it matters — future recall
depends on how well your description matches future queries.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Which image to save from this turn",
                "enum": ["screenshot", "webcam", "telegram", "clipboard"]
            },
            "description": {
                "type": "string",
                "description": "Your description of the image and why you're saving it. Be specific — this is how you'll find it later."
            }
        },
        "required": ["source", "description"]
    }
}
