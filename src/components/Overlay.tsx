import React, { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useSpeechRecognition } from "../hooks/useSpeechRecognition";
import { useSpeechSynthesis } from "../hooks/useSpeechSynthesis";
import {
  Mic,
  Square,
  Volume2,
  VolumeX,
  Settings as SettingsIcon,
  X,
  Sparkles,
  FileText,
  AlertTriangle,
} from "lucide-react";
import { safeInvoke } from "../utils/tauriBridge";

export interface ExecutionReport {
  success: boolean;
  summary: string;
  details: Array<{
    step: string;
    params: Record<string, any>;
    data?: any;
    message?: string;
    verified?: boolean;
    warning?: string;
  }>;
  exceptions: Array<{
    step: string;
    params: Record<string, any>;
    reason: string;
  }>;
  total_steps: number;
  steps_succeeded: number;
  steps_failed: number;
}

interface OverlayProps {
  onClose?: () => void;
  onOpenSettings?: () => void;
  onRun?: (request: string) => Promise<ExecutionReport>;
}

/**
 * HeyBloopie Voice HUD & Interaction Overlay.
 *
 * Implements:
 * 1. Wake word event listener ("Hey Bloopie") & Global Hotkey (Ctrl+Shift+Space).
 * 2. Automated Speech-to-Text (STT) upon activation with pulsing microphone indicator.
 * 3. Execution via Tauri invoke("run_core") -> core.run().
 * 4. Text-to-Speech (TTS) playback of ExecutionReport.summary.
 * 5. Full Interruption Handling:
 *    - User speaking interrupts ongoing TTS immediately without apology.
 *    - Escape key or "Stop" button halts all speech and hides the overlay.
 * 6. Mute toggle button & Close button with SVG icons & smooth micro-interactions.
 */
export const Overlay: React.FC<OverlayProps> = ({ onClose, onOpenSettings, onRun }) => {
  const [isVisible, setIsVisible] = useState<boolean>(true);
  const [inputText, setInputText] = useState<string>("");
  const [isWorking, setIsWorking] = useState<boolean>(false);
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const [report, setReport] = useState<ExecutionReport | null>(null);

  const { transcript, isListening, startListening, stopListening } =
    useSpeechRecognition();
  const { speak, stop: stopSpeaking, isSpeaking } = useSpeechSynthesis();

  const prevListeningRef = useRef<boolean>(false);
  const isSpeakingRef = useRef<boolean>(false);
  isSpeakingRef.current = isSpeaking;

  // Sync transcript directly into input field as user speaks
  useEffect(() => {
    if (transcript) {
      setInputText(transcript);
    }
  }, [transcript]);

  // Clean stop of all audio and recognition
  const stopAllAudio = useCallback(() => {
    stopSpeaking();
    stopListening();
    setIsWorking(false);
  }, [stopSpeaking, stopListening]);

  // Stop everything and close/hide overlay
  const handleStopAndClose = useCallback(() => {
    stopAllAudio();
    setIsVisible(false);
    if (onClose) {
      onClose();
    }
  }, [stopAllAudio, onClose]);

  // Invokes Core execution loop with finalized prompt
  const executeRequest = useCallback(
    async (requestText: string) => {
      const cleanPrompt = requestText.trim();
      if (!cleanPrompt) return;

      stopListening();
      setIsWorking(true);
      setReport(null);

      try {
        let result: ExecutionReport;

        if (onRun) {
          result = await onRun(cleanPrompt);
        } else {
          result = await safeInvoke("run_core", { request: cleanPrompt });
        }

        if (!result) {
          throw new Error("No response received from HeyBloopie Core.");
        }

        setReport(result);
        setIsWorking(false);

        // Speak summary only (never speak full file lists)
        if (!isMuted && result.summary) {
          speak(result.summary);
        }
      } catch (err: any) {
        const errorReport: ExecutionReport = {
          success: false,
          summary: `An error occurred: ${err.message || err}`,
          details: [],
          exceptions: [{ step: "execution", params: {}, reason: String(err) }],
          total_steps: 1,
          steps_succeeded: 0,
          steps_failed: 1,
        };
        setReport(errorReport);
        setIsWorking(false);

        if (!isMuted) {
          speak(errorReport.summary);
        }
      }
    },
    [onRun, isMuted, speak, stopListening]
  );

  // Automatically execute when user finishes speaking (isListening goes from true -> false)
  useEffect(() => {
    if (prevListeningRef.current && !isListening && transcript.trim()) {
      executeRequest(transcript);
    }
    prevListeningRef.current = isListening;
  }, [isListening, transcript, executeRequest]);

  // Wake word & voice trigger handler
  const handleWakeWordTriggered = useCallback(() => {
    // Interruption handling: If talking, immediately stop speaking without apologizing
    if (isSpeakingRef.current) {
      stopSpeaking();
    }

    setIsVisible(true);
    setInputText("");
    setReport(null);
    startListening();
  }, [stopSpeaking, startListening]);

  // Handle manual mic click (also interrupts speaking if active)
  const handleMicClick = useCallback(() => {
    if (isListening) {
      stopListening();
    } else {
      if (isSpeaking) {
        stopSpeaking();
      }
      setInputText("");
      setReport(null);
      startListening();
    }
  }, [isListening, isSpeaking, stopListening, stopSpeaking, startListening]);

  // Listen for wake word events & Global Hotkey
  useEffect(() => {
    let unlistenTauriEvent: (() => void) | undefined;

    const setupWakeWord = async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        unlistenTauriEvent = await listen("wake_word_detected", () => {
          handleWakeWordTriggered();
        });
      } catch {
        // Tauri event system unavailable (web or mock environment)
      }
    };

    setupWakeWord();

    // DOM event listener for testing wake word detection
    const onCustomWake = () => handleWakeWordTriggered();
    window.addEventListener("wake_word_detected", onCustomWake);

    // Global Hotkey fallback: Ctrl+Shift+Space & Escape key
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && (e.code === "Space" || e.key === " ")) {
        e.preventDefault();
        handleWakeWordTriggered();
      } else if (e.key === "Escape") {
        e.preventDefault();
        handleStopAndClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      if (unlistenTauriEvent) unlistenTauriEvent();
      window.removeEventListener("wake_word_detected", onCustomWake);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [handleWakeWordTriggered, handleStopAndClose]);

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          className="hud-container"
          data-testid="overlay-container"
          initial={{ opacity: 0, y: 50, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 40, scale: 0.96 }}
          transition={{
            type: "spring",
            stiffness: 300,
            damping: 26,
            mass: 0.8,
          }}
        >
          {/* HUD Header */}
          <div className="hud-header">
            <div className="hud-title">
              {/* Animated Voice Visualizer (Replacing static dot) */}
              <div
                className="hud-visualizer"
                data-testid="hud-visualizer"
                title={
                  isListening
                    ? "Listening..."
                    : isSpeaking
                    ? "HeyBloopie speaking..."
                    : isWorking
                    ? "Thinking..."
                    : "HeyBloopie ready"
                }
              >
                {isListening ? (
                  <div className="waveform-bars listening">
                    <span className="bar bar-1"></span>
                    <span className="bar bar-2"></span>
                    <span className="bar bar-3"></span>
                    <span className="bar bar-4"></span>
                    <span className="bar bar-5"></span>
                  </div>
                ) : isSpeaking ? (
                  <div className="waveform-bars speaking">
                    <span className="s-wave wave-1"></span>
                    <span className="s-wave wave-2"></span>
                    <span className="s-wave wave-3"></span>
                    <span className="s-wave wave-4"></span>
                    <span className="s-wave wave-5"></span>
                  </div>
                ) : isWorking ? (
                  <div className="hud-orb working"></div>
                ) : (
                  <div className="hud-orb idle"></div>
                )}
              </div>
              HeyBloopie
            </div>

            <div className="hud-actions">
              {/* Stop Button */}
              <button
                className="hud-btn-stop"
                data-testid="stop-btn"
                onClick={handleStopAndClose}
                title="Stop speaking & close overlay"
              >
                <Square size={11} fill="currentColor" />
                <span>Stop</span>
              </button>

              {/* Mute Toggle Button */}
              <button
                className="hud-btn-icon"
                data-testid="mute-btn"
                onClick={() => {
                  if (!isMuted && isSpeaking) {
                    stopSpeaking();
                  }
                  setIsMuted((prev) => !prev);
                }}
                title={isMuted ? "Unmute voice responses" : "Mute voice responses"}
                aria-label={isMuted ? "Unmute voice responses" : "Mute voice responses"}
              >
                {isMuted ? <VolumeX size={15} /> : <Volume2 size={15} />}
                <span style={{ display: "none" }}>{isMuted ? "🔇" : "🔊"}</span>
              </button>

              {/* Settings Button */}
              {onOpenSettings && (
                <button
                  className="hud-btn-icon"
                  data-testid="settings-btn"
                  onClick={onOpenSettings}
                  title="Open Settings"
                  aria-label="Open Settings"
                >
                  <SettingsIcon size={15} />
                </button>
              )}

              {/* Close Button */}
              <button
                className="hud-btn-icon"
                data-testid="close-btn"
                onClick={handleStopAndClose}
                title="Close overlay (Esc)"
                aria-label="Close overlay"
              >
                <X size={15} />
              </button>
            </div>
          </div>

          {/* HUD Body */}
          <div className="hud-body">
            {isWorking ? (
              <div className="working-indicator" data-testid="working-indicator">
                <div className="spinner"></div>
                <span>Thinking & searching...</span>
              </div>
            ) : isListening ? (
              <div className="listening-stage" data-testid="listening-stage">
                <div className="siri-waveform">
                  <span className="siri-bar b1"></span>
                  <span className="siri-bar b2"></span>
                  <span className="siri-bar b3"></span>
                  <span className="siri-bar b4"></span>
                  <span className="siri-bar b5"></span>
                  <span className="siri-bar b6"></span>
                  <span className="siri-bar b7"></span>
                </div>
                <p className="listening-caption">Listening... Speak your request.</p>
              </div>
            ) : report ? (
              <div className="report-card" data-testid="report-card">
                {isSpeaking && (
                  <div className="speaking-badge">
                    <Volume2 size={13} />
                    <div className="speaking-mini-bars">
                      <span className="smb smb-1"></span>
                      <span className="smb smb-2"></span>
                      <span className="smb smb-3"></span>
                      <span className="smb smb-4"></span>
                    </div>
                    <span>HeyBloopie speaking...</span>
                  </div>
                )}
                <div className="report-summary" data-testid="report-summary">
                  {report.summary}
                </div>

                {/* Display details visually (e.g. file list) without speaking them */}
                {report.details &&
                  report.details.map((detail, idx) => (
                    <div key={idx}>
                      {Array.isArray(detail.data) && detail.data.length > 0 && (
                        <div className="file-list">
                          {detail.data.map((item: any, fIdx: number) => (
                            <div key={fIdx} className="file-item">
                              <div className="file-item-left">
                                <FileText size={14} className="file-icon" />
                                <span className="file-name">{item.name || item.path}</span>
                              </div>
                              {item.path && item.name && (
                                <span className="file-path">{item.path}</span>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                      {detail.warning && (
                        <div className="report-warning">
                          <AlertTriangle size={14} />
                          <span>{detail.warning}</span>
                        </div>
                      )}
                    </div>
                  ))}
              </div>
            ) : (
              <p className="hud-prompt-placeholder">
                Say 'Hey Bloopie' or type a command to manage your files...
              </p>
            )}
          </div>

          {/* HUD Input Bar */}
          <form
            className="hud-input-bar"
            onSubmit={(e) => {
              e.preventDefault();
              executeRequest(inputText);
            }}
          >
            <button
              type="button"
              className={`mic-button ${isListening ? "mic-pulsing" : ""}`}
              data-testid="mic-btn"
              onClick={handleMicClick}
              title={isListening ? "Listening..." : "Click to speak"}
              aria-label={isListening ? "Listening..." : "Click to speak"}
            >
              <Mic size={17} />
            </button>

            <input
              type="text"
              data-testid="query-input"
              placeholder="e.g. Find all receipts from last month in Downloads"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              autoFocus
            />

            <button type="submit" className="hud-btn" data-testid="submit-btn">
              <Sparkles size={14} />
              <span>Ask</span>
            </button>
          </form>
        </motion.div>
      )}
    </AnimatePresence>
  );

};

export default Overlay;
