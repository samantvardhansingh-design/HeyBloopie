"""Unit tests for the HeyBloopie Wake Word Detection Module."""

import os
import sqlite3
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

# Ensure python directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from python.wake_word import WakeWordListener, get_preferred_wake_word


class TestWakeWordDetection:
    """Tests for WakeWordListener with pvporcupine mocked."""

    def test_get_preferred_wake_word_default(self):
        """Verifies that the default wake word is 'hey bloopie' when preference is unset."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_db = tmp.name

        try:
            phrase = get_preferred_wake_word(tmp_db)
            assert phrase == "hey bloopie"
        finally:
            if os.path.exists(tmp_db):
                os.remove(tmp_db)

    def test_get_preferred_wake_word_custom(self):
        """Verifies reading a custom wake word from the SQLite preferences table."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_db = tmp.name

        try:
            conn = sqlite3.connect(tmp_db)
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE preferences (key TEXT PRIMARY KEY, value TEXT)")
            cursor.execute("INSERT INTO preferences VALUES ('wake_word', 'bloopie assistant')")
            conn.commit()
            conn.close()

            phrase = get_preferred_wake_word(tmp_db)
            assert phrase == "bloopie assistant"
        finally:
            if os.path.exists(tmp_db):
                os.remove(tmp_db)

    def test_listener_starts_correctly_with_mock_porcupine(self):
        """Verifies that the listener starts its background thread when pvporcupine is initialized."""
        mock_porcupine_instance = MagicMock()
        mock_porcupine_instance.frame_length = 512
        mock_porcupine_instance.process.return_value = -1

        mock_pvporcupine = MagicMock()
        mock_pvporcupine.create.return_value = mock_porcupine_instance

        callback_mock = MagicMock()

        with patch.dict(sys.modules, {"pvporcupine": mock_pvporcupine, "pvrecorder": MagicMock()}):
            listener = WakeWordListener(
                on_wake_detected=callback_mock,
                access_key="test_access_key"
            )
            success = listener.start()
            assert success is True
            assert listener.is_listening() is True

            listener.stop()
            assert listener.is_listening() is False

    def test_callback_triggered_on_wake_word_detection(self):
        """Verifies that the callback function is triggered when a mock wake word detection event occurs."""
        mock_porcupine_instance = MagicMock()
        mock_porcupine_instance.frame_length = 512

        # Return 0 (keyword detected) on first call, then -1
        mock_porcupine_instance.process.side_effect = [0, -1, -1, -1]

        mock_pvporcupine = MagicMock()
        mock_pvporcupine.create.return_value = mock_porcupine_instance

        mock_recorder_instance = MagicMock()
        mock_recorder_instance.read.return_value = [0] * 512

        mock_pvrecorder = MagicMock()
        mock_pvrecorder.PvRecorder.return_value = mock_recorder_instance

        callback_called_event = MagicMock()

        with patch.dict(sys.modules, {"pvporcupine": mock_pvporcupine, "pvrecorder": mock_pvrecorder}):
            listener = WakeWordListener(
                on_wake_detected=callback_called_event,
                access_key="test_access_key"
            )
            started = listener.start()
            assert started is True

            # Allow the audio loop to process the mock frame
            time.sleep(0.1)

            listener.stop()

            # Ensure the callback was triggered
            assert callback_called_event.called is True
            assert callback_called_event.call_count >= 1

    def test_listener_graceful_fallback_when_microphone_fails(self):
        """Verifies that listener gracefully logs and returns False on hardware failure without crashing."""
        mock_pvporcupine = MagicMock()
        mock_pvporcupine.create.side_effect = RuntimeError("Microphone or Audio device not found")

        callback_mock = MagicMock()

        with patch.dict(sys.modules, {"pvporcupine": mock_pvporcupine}):
            listener = WakeWordListener(
                on_wake_detected=callback_mock,
                access_key="test_access_key"
            )
            started = listener.start()

            # Must return False and not crash
            assert started is False
            assert listener.is_listening() is False
            assert callback_mock.called is False
