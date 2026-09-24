import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { Overlay } from "./Overlay";

describe("Overlay Component & Interruption Handling", () => {
  let mockRecognitionInstance: any = null;
  let mockSpeechSynthesis: any = null;
  let lastUtterance: any = null;

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
      if (this.onstart) this.onstart();
    });

    stop = vi.fn(() => {
      if (this.onend) this.onend();
    });

    abort = vi.fn(() => {
      if (this.onend) this.onend();
    });
  }

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

  beforeEach(() => {
    mockRecognitionInstance = null;
    lastUtterance = null;

    mockSpeechSynthesis = {
      getVoices: vi.fn(() => [
        { name: "Microsoft Aria Online (Natural)", lang: "en-US" },
      ]),
      speak: vi.fn((utterance: any) => {
        lastUtterance = utterance;
        if (utterance.onstart) utterance.onstart();
      }),
      cancel: vi.fn(() => {
        if (lastUtterance && lastUtterance.onend) lastUtterance.onend();
      }),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };

    (window as any).SpeechRecognition = MockSpeechRecognition;
    (window as any).SpeechSynthesisUtterance = MockSpeechSynthesisUtterance;
    (window as any).speechSynthesis = mockSpeechSynthesis;
  });

  afterEach(() => {
    delete (window as any).SpeechRecognition;
    delete (window as any).SpeechSynthesisUtterance;
    delete (window as any).speechSynthesis;
    vi.clearAllMocks();
  });

  it("Scenario a: Wake word event triggers speech recognition, execution, and voice output", async () => {
    const mockRun = vi.fn().mockResolvedValue({
      success: true,
      summary: "Done. Found 1 file.",
      details: [
        {
          step: "find_files",
          params: { query: "report" },
          data: [{ name: "report.pdf", path: "C:\\Docs\\report.pdf" }],
        },
      ],
      exceptions: [],
      total_steps: 1,
      steps_succeeded: 1,
      steps_failed: 0,
    });

    render(<Overlay onRun={mockRun} />);

    // 1. Trigger wake word event
    act(() => {
      window.dispatchEvent(new CustomEvent("wake_word_detected"));
    });

    expect(mockRecognitionInstance.start).toHaveBeenCalled();
    const micBtn = screen.getByTestId("mic-btn");
    expect(micBtn.className).toContain("mic-pulsing");

    // 2. Finalize speech
    act(() => {
      mockRecognitionInstance.onresult({
        resultIndex: 0,
        results: [
          Object.assign([{ transcript: "find my report" }], { isFinal: true }),
        ],
      });
    });

    // 3. Verify text in input
    const input = screen.getByTestId("query-input") as HTMLInputElement;
    expect(input.value).toBe("find my report");

    // 4. Verify execution and TTS playback
    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith("find my report");
      expect(screen.getByTestId("report-summary").textContent).toBe(
        "Done. Found 1 file."
      );
      expect(mockSpeechSynthesis.speak).toHaveBeenCalled();
      expect(lastUtterance.text).toBe("Done. Found 1 file.");
    });
  });

  it("Scenario b: Interrupts HeyBloopie mid-sentence when user speaks or clicks mic", async () => {
    const mockRun = vi.fn().mockResolvedValue({
      success: true,
      summary: "Done. Found 5 files.",
      details: [],
      exceptions: [],
      total_steps: 1,
      steps_succeeded: 1,
      steps_failed: 0,
    });

    render(<Overlay onRun={mockRun} />);

    // Type and ask to trigger speaking
    fireEvent.change(screen.getByTestId("query-input"), {
      target: { value: "find receipts" },
    });
    fireEvent.click(screen.getByTestId("submit-btn"));

    await waitFor(() => {
      expect(mockSpeechSynthesis.speak).toHaveBeenCalled();
    });

    // User interrupts by clicking mic or trigger wake word
    fireEvent.click(screen.getByTestId("mic-btn"));

    // Verify speaking was cancelled immediately without delay
    expect(mockSpeechSynthesis.cancel).toHaveBeenCalled();
    expect(mockRecognitionInstance.start).toHaveBeenCalled();
  });

  it("Scenario c: Pressing Escape stops audio and hides overlay", async () => {
    const handleClose = vi.fn();
    render(<Overlay onClose={handleClose} />);

    // Trigger hotkey to start
    fireEvent.keyDown(window, { key: "Escape" });

    expect(mockSpeechSynthesis.cancel).toHaveBeenCalled();
    expect(handleClose).toHaveBeenCalled();
  });

  it("Scenario d: Clicking 'Stop' button halts all audio and closes overlay", () => {
    const handleClose = vi.fn();
    render(<Overlay onClose={handleClose} />);

    fireEvent.click(screen.getByTestId("stop-btn"));

    expect(mockSpeechSynthesis.cancel).toHaveBeenCalled();
    expect(handleClose).toHaveBeenCalled();
  });

  it("Scenario e: Mute button suppresses TTS but displays text visually", async () => {
    const mockRun = vi.fn().mockResolvedValue({
      success: true,
      summary: "Done. Found 2 files.",
      details: [],
      exceptions: [],
      total_steps: 1,
      steps_succeeded: 1,
      steps_failed: 0,
    });

    render(<Overlay onRun={mockRun} />);

    // Click mute button
    const muteBtn = screen.getByTestId("mute-btn");
    fireEvent.click(muteBtn);
    expect(muteBtn.textContent).toBe("🔇");

    // Submit request
    fireEvent.change(screen.getByTestId("query-input"), {
      target: { value: "search invoices" },
    });
    fireEvent.click(screen.getByTestId("submit-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("report-summary").textContent).toBe(
        "Done. Found 2 files."
      );
      // speak was not called because it was muted
      expect(mockSpeechSynthesis.speak).not.toHaveBeenCalled();
    });
  });

  it("Scenario f: Close button stops audio and hides overlay", () => {
    const handleClose = vi.fn();
    render(<Overlay onClose={handleClose} />);

    fireEvent.click(screen.getByTestId("close-btn"));

    expect(mockSpeechSynthesis.cancel).toHaveBeenCalled();
    expect(handleClose).toHaveBeenCalled();
  });

  it("Scenario g: Global Hotkey (Ctrl+Shift+Space) activates overlay and speech recognition", () => {
    render(<Overlay />);

    fireEvent.keyDown(window, {
      ctrlKey: true,
      shiftKey: true,
      code: "Space",
    });

    expect(mockRecognitionInstance.start).toHaveBeenCalled();
    expect(screen.getByTestId("mic-btn").className).toContain("mic-pulsing");
  });
});
