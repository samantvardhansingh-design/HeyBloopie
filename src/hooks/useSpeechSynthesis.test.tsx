import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { useSpeechSynthesis } from "./useSpeechSynthesis";

function TestTTSComponent({ initialText = "Done. Found 3 files." }) {
  const { speak, stop, isSpeaking, selectedVoice, voices } = useSpeechSynthesis();

  return (
    <div>
      <span data-testid="status">{isSpeaking ? "speaking" : "idle"}</span>
      <span data-testid="voice">{selectedVoice ? selectedVoice.name : "none"}</span>
      <span data-testid="voice-count">{voices.length}</span>
      <button data-testid="speak-btn" onClick={() => speak(initialText)}>
        Speak
      </button>
      <button data-testid="stop-btn" onClick={stop}>
        Stop
      </button>
    </div>
  );
}

describe("useSpeechSynthesis", () => {
  let mockVoices: any[];
  let lastUtterance: any;
  let listeners: Record<string, Function[]> = {};

  class MockSpeechSynthesisUtterance {
    text: string;
    rate = 1;
    pitch = 1;
    volume = 1;
    voice: any = null;
    onstart: (() => void) | null = null;
    onend: (() => void) | null = null;
    onerror: ((e: any) => void) | null = null;

    constructor(text: string) {
      this.text = text;
      lastUtterance = this;
    }
  }

  const mockSpeechSynthesis = {
    getVoices: vi.fn(() => mockVoices),
    speak: vi.fn((utterance: any) => {
      lastUtterance = utterance;
      if (utterance.onstart) {
        utterance.onstart();
      }
    }),
    cancel: vi.fn(() => {
      if (lastUtterance && lastUtterance.onend) {
        lastUtterance.onend();
      }
    }),
    addEventListener: vi.fn((event: string, callback: Function) => {
      listeners[event] = listeners[event] || [];
      listeners[event].push(callback);
    }),
    removeEventListener: vi.fn((event: string, callback: Function) => {
      if (listeners[event]) {
        listeners[event] = listeners[event].filter((cb) => cb !== callback);
      }
    }),
  };

  beforeEach(() => {
    lastUtterance = null;
    listeners = {};
    mockVoices = [
      { name: "Default Voice", lang: "es-ES" },
      { name: "Microsoft Aria Online (Natural)", lang: "en-US" },
      { name: "Google US English", lang: "en-US" },
    ];

    (window as any).SpeechSynthesisUtterance = MockSpeechSynthesisUtterance;
    (window as any).speechSynthesis = mockSpeechSynthesis;
  });

  afterEach(() => {
    delete (window as any).SpeechSynthesisUtterance;
    delete (window as any).speechSynthesis;
    vi.clearAllMocks();
  });

  it("loads voices on mount and selects preferred voice", () => {
    render(<TestTTSComponent />);
    expect(screen.getByTestId("voice-count").textContent).toBe("3");
    // "Microsoft Aria" matches priority before Google US English in the mock order
    expect(screen.getByTestId("voice").textContent).toContain("Microsoft Aria");
  });

  it("calls speechSynthesis.speak with correct text, rate, pitch, and volume", () => {
    render(<TestTTSComponent initialText="Done. Found 3 files." />);

    fireEvent.click(screen.getByTestId("speak-btn"));

    expect(mockSpeechSynthesis.cancel).toHaveBeenCalled();
    expect(mockSpeechSynthesis.speak).toHaveBeenCalled();
    expect(lastUtterance.text).toBe("Done. Found 3 files.");
    expect(lastUtterance.rate).toBe(1.0);
    expect(lastUtterance.pitch).toBe(0.95);
    expect(lastUtterance.volume).toBe(1.0);
    expect(screen.getByTestId("status").textContent).toBe("speaking");
  });

  it("updates isSpeaking state when speech finishes", () => {
    render(<TestTTSComponent initialText="Search completed." />);

    fireEvent.click(screen.getByTestId("speak-btn"));
    expect(screen.getByTestId("status").textContent).toBe("speaking");

    act(() => {
      if (lastUtterance.onend) {
        lastUtterance.onend();
      }
    });

    expect(screen.getByTestId("status").textContent).toBe("idle");
  });

  it("calls speechSynthesis.cancel and sets isSpeaking to false on stop", () => {
    render(<TestTTSComponent initialText="Reading details..." />);

    fireEvent.click(screen.getByTestId("speak-btn"));
    expect(screen.getByTestId("status").textContent).toBe("speaking");

    fireEvent.click(screen.getByTestId("stop-btn"));
    expect(mockSpeechSynthesis.cancel).toHaveBeenCalled();
    expect(screen.getByTestId("status").textContent).toBe("idle");
  });
});
