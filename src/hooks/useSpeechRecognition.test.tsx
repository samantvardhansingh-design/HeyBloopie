import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { useSpeechRecognition } from "./useSpeechRecognition";

// Test component consuming the hook
function TestSpeechComponent() {
  const { transcript, isListening, startListening, stopListening } =
    useSpeechRecognition();

  return (
    <div>
      <span data-testid="transcript">{transcript}</span>
      <span data-testid="status">{isListening ? "listening" : "idle"}</span>
      <button data-testid="start-btn" onClick={startListening}>
        Start
      </button>
      <button data-testid="stop-btn" onClick={stopListening}>
        Stop
      </button>
    </div>
  );
}

describe("useSpeechRecognition", () => {
  let mockRecognitionInstance: any;

  class MockSpeechRecognition {
    continuous = false;
    interimResults = false;
    lang = "";
    onstart: (() => void) | null = null;
    onresult: ((event: any) => void) | null = null;
    onerror: ((event: any) => void) | null = null;
    onend: (() => void) | null = null;

    constructor() {
      mockRecognitionInstance = this;
    }

    start = vi.fn(() => {
      if (this.onstart) {
        this.onstart();
      }
    });

    stop = vi.fn(() => {
      if (this.onend) {
        this.onend();
      }
    });

    abort = vi.fn(() => {
      if (this.onend) {
        this.onend();
      }
    });
  }

  beforeEach(() => {
    mockRecognitionInstance = null;
    (window as any).SpeechRecognition = MockSpeechRecognition;
  });

  afterEach(() => {
    delete (window as any).SpeechRecognition;
    delete (window as any).webkitSpeechRecognition;
  });

  it("initializes with empty transcript and idle state", () => {
    render(<TestSpeechComponent />);
    expect(screen.getByTestId("transcript").textContent).toBe("");
    expect(screen.getByTestId("status").textContent).toBe("idle");
  });

  it("starts listening when startListening is called", () => {
    render(<TestSpeechComponent />);
    fireEvent.click(screen.getByTestId("start-btn"));

    expect(screen.getByTestId("status").textContent).toBe("listening");
    expect(mockRecognitionInstance.start).toHaveBeenCalled();
  });

  it("updates transcript on interim results", () => {
    render(<TestSpeechComponent />);
    fireEvent.click(screen.getByTestId("start-btn"));

    act(() => {
      mockRecognitionInstance.onresult({
        resultIndex: 0,
        results: [
          Object.assign([{ transcript: "find my" }], { isFinal: false }),
        ],
      });
    });

    expect(screen.getByTestId("transcript").textContent).toBe("find my");
    expect(screen.getByTestId("status").textContent).toBe("listening");
  });

  it("updates transcript and stops listening on final result", () => {
    render(<TestSpeechComponent />);
    fireEvent.click(screen.getByTestId("start-btn"));

    act(() => {
      mockRecognitionInstance.onresult({
        resultIndex: 0,
        results: [
          Object.assign([{ transcript: "find my report" }], { isFinal: true }),
        ],
      });
    });

    expect(screen.getByTestId("transcript").textContent).toBe("find my report");
    expect(screen.getByTestId("status").textContent).toBe("idle");
    expect(mockRecognitionInstance.stop).toHaveBeenCalled();
  });

  it("stops listening cleanly when stopListening is invoked", () => {
    render(<TestSpeechComponent />);
    fireEvent.click(screen.getByTestId("start-btn"));
    expect(screen.getByTestId("status").textContent).toBe("listening");

    fireEvent.click(screen.getByTestId("stop-btn"));
    expect(screen.getByTestId("status").textContent).toBe("idle");
    expect(mockRecognitionInstance.stop).toHaveBeenCalled();
  });

  it("handles speech recognition error and sets listening to false", () => {
    render(<TestSpeechComponent />);
    fireEvent.click(screen.getByTestId("start-btn"));
    expect(screen.getByTestId("status").textContent).toBe("listening");

    act(() => {
      mockRecognitionInstance.onerror({ error: "audio-capture" });
    });

    expect(screen.getByTestId("status").textContent).toBe("idle");
  });
});
