"""TTS provider package."""

from .mock_tts_provider import MockTtsProvider
from .piper_provider import PiperTtsProvider

__all__ = ["MockTtsProvider", "PiperTtsProvider"]
