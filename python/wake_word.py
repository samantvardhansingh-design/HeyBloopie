"""HeyBloopie Wake Word Detection Service.

This module provides on-device wake word detection using Picovoice Porcupine (pvporcupine).
All audio is processed locally on the user's machine and never leaves the device.

When the wake word (default: "hey bloopie") is detected, a callback function is invoked
to display the overlay and initiate speech recognition.
"""

import logging
import os
import sqlite3
import threading
import time
from typing import Callable, Optional

import keyring

logger = logging.getLogger("heybloopie.wake_word")

DEFAULT_MODEL_PATH = "python/models/hey_bloopie.ppn"
DEFAULT_DB_PATH = "heybloopie.db"


def get_preference(key: str, default: str, db_path: str = DEFAULT_DB_PATH) -> str:
    """Reads a setting from the SQLite preferences table with a default fallback."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)"
        )
        cursor.execute("SELECT value FROM preferences WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception as e:
        logger.warning(f"Could not load preference '{key}': {e}")
    return default


def get_preferred_wake_word(db_path: str = DEFAULT_DB_PATH) -> str:
    """Retrieves the configured wake word phrase from preferences (default: 'hey bloopie')."""
    return get_preference("wake_word", "hey bloopie", db_path)


def get_keyword_path(db_path: str = DEFAULT_DB_PATH) -> str:
    """Retrieves the wake word model file path from preferences (default: 'python/models/hey_bloopie.ppn')."""
    return get_preference("wake_word_path", DEFAULT_MODEL_PATH, db_path)


def get_access_key() -> Optional[str]:
    """Retrieves the Porcupine access key from Windows Credential Manager."""
    try:
        return keyring.get_password("heybloopie", "porcupine")
    except Exception as e:
        logger.warning(f"Could not retrieve Porcupine access key from keyring: {e}")
        return None


class WakeWordDetector:
    """On-device wake word detector running Picovoice Porcupine in a background thread."""

    def __init__(
        self,
        access_key: Optional[str] = None,
        keyword_path: Optional[str] = None,
        callback: Optional[Callable[[], None]] = None,
        fallback_callback: Optional[Callable[[], None]] = None,
        db_path: str = DEFAULT_DB_PATH,
        on_wake_detected: Optional[Callable[[], None]] = None,
    ):
        """Initializes the WakeWordDetector.

        Args:
            access_key: Porcupine access key. If None, loaded from Windows Credential Manager.
            keyword_path: Path to custom .ppn keyword model. If None, loaded from preferences.
            callback: Function called when wake word is detected.
            fallback_callback: Optional function called when microphone/audio fails.
            db_path: SQLite preferences database path.
            on_wake_detected: Backward-compatible alias for callback.
        """
        self.db_path = db_path
        self.callback = callback or on_wake_detected
        self.fallback_callback = fallback_callback

        self.wake_word = get_preferred_wake_word(self.db_path)
        self.keyword_path = keyword_path or get_keyword_path(self.db_path)

        # Retrieve access key from Windows Credential Manager if not passed explicitly
        if not access_key:
            access_key = get_access_key()
        self.access_key = access_key or ""

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._porcupine = None
        self._recorder = None

    def start(self) -> bool:
        """Starts the background listening thread.

        Returns:
            True if started successfully, False if microphone/Porcupine failed.
        """
        if self.is_running():
            return True

        # Check keyword file existence
        if not self.keyword_path or not os.path.exists(self.keyword_path):
            logger.error(
                "Wake word model not found. Please download it from the Picovoice console or use the hotkey."
            )

        try:
            import pvporcupine
        except ImportError:
            logger.error("pvporcupine library is not installed. Falling back to hotkey.")
            if self.fallback_callback:
                self.fallback_callback()
            return False

        # Initialize Porcupine instance
        try:
            if self.keyword_path and os.path.exists(self.keyword_path):
                self._porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keyword_paths=[self.keyword_path],
                )
            else:
                # Built-in keyword fallback for testing/placeholder
                self._porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keywords=["porcupine"],
                )
        except Exception as err:
            logger.error(f"Porcupine initialization failed: {err}. Falling back to hotkey.")
            if self.fallback_callback:
                self.fallback_callback()
            return False

        # Open default microphone using pvrecorder
        try:
            import pvrecorder
            self._recorder = pvrecorder.PvRecorder(frame_length=self._porcupine.frame_length)
            self._recorder.start()
        except Exception as err:
            logger.error(
                f"Microphone is unavailable: {err}. Falling back to hotkey (Ctrl+Shift+Space)."
            )
            self._cleanup()
            if self.fallback_callback:
                self.fallback_callback()
            return False

        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name="WakeWordDetectorThread",
        )
        self._thread.start()
        logger.info(f"Wake word detector started successfully (Phrase: '{self.wake_word}').")
        return True

    def _listen_loop(self) -> None:
        """Continuously reads audio frames and feeds them to Porcupine."""
        try:
            while self._running:
                if self._recorder is not None:
                    pcm = self._recorder.read()
                    if self._porcupine is not None:
                        result = self._porcupine.process(pcm)
                        if result >= 0:
                            logger.info("Wake word detected! Triggering callback.")
                            if self.callback:
                                self.callback()
                else:
                    time.sleep(0.02)
        except Exception as err:
            logger.error(f"Error in wake word audio loop: {err}. Falling back to hotkey.")
            if self.fallback_callback:
                self.fallback_callback()
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        """Releases microphone and Porcupine resources cleanly."""
        if self._recorder is not None:
            try:
                self._recorder.stop()
                self._recorder.delete()
            except Exception:
                pass
            self._recorder = None

        if self._porcupine is not None:
            try:
                self._porcupine.delete()
            except Exception:
                pass
            self._porcupine = None

    def stop(self) -> None:
        """Stops the listening thread and releases all audio resources."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._cleanup()
        logger.info("Wake word detector stopped.")

    def is_running(self) -> bool:
        """Returns True if the background listening thread is active."""
        return self._running and (self._thread is not None and self._thread.is_alive())

    def is_listening(self) -> bool:
        """Alias for is_running()."""
        return self.is_running()


# Backward-compatible alias
WakeWordListener = WakeWordDetector
