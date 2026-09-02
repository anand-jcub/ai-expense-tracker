"""In-app assistant: Gemini tool-calling + confirm-before-write (zone I)."""

from .loop import confirm_action, run_chat

__all__ = ["run_chat", "confirm_action"]
