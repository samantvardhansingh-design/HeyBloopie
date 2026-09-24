import { useState, useEffect, useCallback, useRef } from "react";

export interface UseSpeechSynthesisReturn {
  speak: (text: string) => void;
  stop: () => void;
  isSpeaking: boolean;
  voices: SpeechSynthesisVoice[];
  selectedVoice: SpeechSynthesisVoice | null;
  setSelectedVoice: (voice: SpeechSynthesisVoice | null) => void;
}

/**
 * Chooses the default voice according to HeyBloopie voice priority:
 * 1. Prefer "Google US English", "Microsoft Aria", or "Samantha".
 * 2. Fall back to the first English voice.
 * 3. Fall back to the first available voice.
 */
function chooseDefaultVoice(
  availableVoices: SpeechSynthesisVoice[]
): SpeechSynthesisVoice | null {
  if (availableVoices.length === 0) {
    return null;
  }

  const preferred = availableVoices.find(
    (v) =>
      v.name.includes("Google US English") ||
      v.name.includes("Microsoft Aria") ||
      v.name.includes("Samantha")
  );
  if (preferred) {
    return preferred;
  }

  const english = availableVoices.find((v) =>
    v.lang.toLowerCase().startsWith("en")
  );
  if (english) {
    return english;
  }

  return availableVoices[0] || null;
}

/**
 * Custom React hook for Text-to-Speech using browser's built-in speechSynthesis API.
 * Operates entirely on-device within Chromium webview with zero external API key requirements.
 */
export function useSpeechSynthesis(): UseSpeechSynthesisReturn {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [selectedVoice, setSelectedVoice] =
    useState<SpeechSynthesisVoice | null>(null);
  const [isSpeaking, setIsSpeaking] = useState<boolean>(false);
  const currentUtteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  // Load available voices on mount and listen to voiceschanged event
  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      return;
    }

    const updateVoices = () => {
      const available = window.speechSynthesis.getVoices();
      if (available && available.length > 0) {
        setVoices(available);
        setSelectedVoice((prev) => prev ?? chooseDefaultVoice(available));
      }
    };

    updateVoices();
    window.speechSynthesis.addEventListener("voiceschanged", updateVoices);

    return () => {
      if (typeof window !== "undefined" && window.speechSynthesis) {
        if (typeof window.speechSynthesis.removeEventListener === "function") {
          window.speechSynthesis.removeEventListener(
            "voiceschanged",
            updateVoices
          );
        }
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  const stop = useCallback(() => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    currentUtteranceRef.current = null;
    setIsSpeaking(false);
  }, []);

  const speak = useCallback(
    (text: string) => {
      if (typeof window === "undefined" || !("speechSynthesis" in window)) {
        console.warn("speechSynthesis is not available in this environment.");
        return;
      }

      if (!text || text.trim() === "") {
        return;
      }

      // Cancel any ongoing speech before starting new utterance
      window.speechSynthesis.cancel();

      try {
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.0;
        utterance.pitch = 0.95; // slightly lower for calm, professional tone
        utterance.volume = 1.0;

        if (selectedVoice) {
          utterance.voice = selectedVoice;
        }

        utterance.onstart = () => {
          setIsSpeaking(true);
        };

        utterance.onend = () => {
          setIsSpeaking(false);
          currentUtteranceRef.current = null;
        };

        utterance.onerror = (e) => {
          console.error("SpeechSynthesis error:", e);
          setIsSpeaking(false);
          currentUtteranceRef.current = null;
        };

        currentUtteranceRef.current = utterance;
        window.speechSynthesis.speak(utterance);
        setIsSpeaking(true);
      } catch (err) {
        console.error("Failed to speak text:", err);
        setIsSpeaking(false);
      }
    },
    [selectedVoice]
  );

  return {
    speak,
    stop,
    isSpeaking,
    voices,
    selectedVoice,
    setSelectedVoice,
  };
}

export default useSpeechSynthesis;
