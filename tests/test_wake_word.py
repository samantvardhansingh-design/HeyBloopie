"""Unit tests for the HeyBloopie Wake Word Detection Module (WakeWordDetector).

Tests cover:
- Mock pvporcupine.create to return a fake detector.
- Verify the callback is called when a mock detection event fires.
- Verify stop() releases resources cleanly.
- Verify the fallback is triggered when the microphone is unavailable.
- Verify preferences configuration (wake_word, wake_word_path) and credential lookup.
"""

import os
import sqlite3
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

# Ensure python directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from python.wake_word import (
    WakeWordDetector,
    get_access_key,
    get_keyword_path,
    get_preferred_wake_word,
)


class TestWakeWordDetector:
    """Tests for WakeWordDetector with pvporcupine and pvrecorder mocked."""

    def test_get_preferred_wake_word_and_keyword_path(self):
        """Verifies loading wake_word and wake_word_path from preferences."""
        fd, tmp_db = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        try:
            # Default values
            assert get_preferred_wake_word(tmp_db) == "hey bloopie"
            assert get_keyword_path(tmp_db) == "python/models/hey_bloopie.ppn"

            # Custom values in SQLite
            conn = sqlite3.connect(tmp_db)
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)")
            cursor.execute("INSERT OR REPLACE INTO preferences VALUES ('wake_word', 'bloopie computer')")
            cursor.execute("INSERT OR REPLACE INTO preferences VALUES ('wake_word_path', 'custom/path.ppn')")
            conn.commit()
            conn.close()

            assert get_preferred_wake_word(tmp_db) == "bloopie computer"
            assert get_keyword_path(tmp_db) == "custom/path.ppn"
        finally:
            try:
                if os.path.exists(tmp_db):
                    os.remove(tmp_db)
            except Exception:
                pass


    def test_credential_store_access_key_retrieval(self, monkeypatch):
        """Verifies access key retrieval from Windows Credential Manager under 'heybloopie'/'porcupine'."""
        mock_get_password = MagicMock(return_value="vault_porcupine_key_123")
        monkeypatch.setattr("keyring.get_password", mock_get_password)

        key = get_access_key()
        assert key == "vault_porcupine_key_123"
        mock_get_password.assert_called_once_with("heybloopie", "porcupine")

    def test_mock_pvporcupine_create_and_start(self):
        """TEST 1 & 2: Mock pvporcupine.create and verify detector starts and stops cleanly."""
        mock_porcupine = MagicMock()
        mock_porcupine.frame_length = 512
        mock_porcupine.process.return_value = -1

        mock_pvporcupine = MagicMock()
        mock_pvporcupine.create.return_value = mock_porcupine

        mock_recorder = MagicMock()
        mock_recorder.read.return_value = [0] * 512
        mock_pvrecorder = MagicMock()
        mock_pvrecorder.PvRecorder.return_value = mock_recorder

        callback_mock = MagicMock()

        with patch.dict(sys.modules, {"pvporcupine": mock_pvporcupine, "pvrecorder": mock_pvrecorder}):
            detector = WakeWordDetector(
                access_key="test_key",
                keyword_path="python/models/hey_bloopie.ppn",
                callback=callback_mock,
            )
            started = detector.start()
            assert started is True
            assert detector.is_running() is True

            # Verify stop() releases resources cleanly
            detector.stop()
            assert detector.is_running() is False
            assert mock_recorder.stop.called is True
            assert mock_recorder.delete.called is True
            assert mock_porcupine.delete.called is True

    def test_callback_called_when_wake_word_detected(self):
        """TEST: Verify the callback is called when a mock detection event fires."""
        mock_porcupine = MagicMock()
        mock_porcupine.frame_length = 512
        # Return 0 (keyword detected index) on first process call, then -1
        mock_porcupine.process.side_effect = [0, -1, -1, -1]

        mock_pvporcupine = MagicMock()
        mock_pvporcupine.create.return_value = mock_porcupine

        mock_recorder = MagicMock()
        mock_recorder.read.return_value = [0] * 512
        mock_pvrecorder = MagicMock()
        mock_pvrecorder.PvRecorder.return_value = mock_recorder

        callback_mock = MagicMock()

        with patch.dict(sys.modules, {"pvporcupine": mock_pvporcupine, "pvrecorder": mock_pvrecorder}):
            detector = WakeWordDetector(
                access_key="test_key",
                keyword_path="python/models/hey_bloopie.ppn",
                callback=callback_mock,
            )
            started = detector.start()
            assert started is True

            # Give background thread time to process mock frame
            time.sleep(0.1)

            detector.stop()

            assert callback_mock.called is True
            assert callback_mock.call_count >= 1

    def test_fallback_triggered_when_microphone_unavailable(self):
        """TEST: Verify the fallback is triggered when the microphone is unavailable."""
        mock_porcupine = MagicMock()
        mock_porcupine.frame_length = 512

        mock_pvporcupine = MagicMock()
        mock_pvporcupine.create.return_value = mock_porcupine

        # Simulate microphone hardware failure
        mock_pvrecorder = MagicMock()
        mock_pvrecorder.PvRecorder.side_effect = RuntimeError("Microphone audio device unavailable")

        callback_mock = MagicMock()
        fallback_mock = MagicMock()

        with patch.dict(sys.modules, {"pvporcupine": mock_pvporcupine, "pvrecorder": mock_pvrecorder}):
            detector = WakeWordDetector(
                access_key="test_key",
                keyword_path="python/models/hey_bloopie.ppn",
                callback=callback_mock,
                fallback_callback=fallback_mock,
            )
            started = detector.start()

            # Must fail gracefully
            assert started is False
            assert detector.is_running() is False
            assert callback_mock.called is False
            # Fallback callback must be invoked
            assert fallback_mock.called is True

    def test_fallback_triggered_when_porcupine_initialization_fails(self):
        """TEST: Verify fallback is triggered if Porcupine fails to initialize."""
        mock_pvporcupine = MagicMock()
        mock_pvporcupine.create.side_effect = ValueError("Invalid Picovoice AccessKey")

        callback_mock = MagicMock()
        fallback_mock = MagicMock()

        with patch.dict(sys.modules, {"pvporcupine": mock_pvporcupine}):
            detector = WakeWordDetector(
                access_key="invalid_key",
                keyword_path="python/models/hey_bloopie.ppn",
                callback=callback_mock,
                fallback_callback=fallback_mock,
            )
            started = detector.start()

            assert started is False
            assert detector.is_running() is False
            assert fallback_mock.called is True
