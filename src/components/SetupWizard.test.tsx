import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SetupWizard } from "./SetupWizard";

// Mock Tauri invoke from @tauri-apps/api/core
const mockInvoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: any[]) => mockInvoke(...args),
}));

// Mock useSpeechSynthesis hook
const mockSpeak = vi.fn();
vi.mock("../hooks/useSpeechSynthesis", () => ({
  useSpeechSynthesis: () => ({
    speak: mockSpeak,
    stop: vi.fn(),
    isSpeaking: false,
    voices: [],
    selectedVoice: null,
    setSelectedVoice: vi.fn(),
  }),
}));

describe("SetupWizard Component (Part 4)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("Screen 0: Renders Welcome screen and transitions to Screen 1 on next", () => {
    render(<SetupWizard />);

    expect(screen.getByTestId("screen-welcome")).toBeDefined();
    expect(screen.getByText("Welcome to HeyBloopie")).toBeDefined();
    expect(
      screen.getByText(/HeyBloopie is your background executive/i)
    ).toBeDefined();

    const nextBtn = screen.getByTestId("btn-welcome-next");
    fireEvent.click(nextBtn);

    expect(screen.getByTestId("screen-1")).toBeDefined();

    // Verify back button on Screen 1 returns to Screen 0
    const backBtn = screen.getByTestId("btn-back-to-welcome");
    fireEvent.click(backBtn);
    expect(screen.getByTestId("screen-welcome")).toBeDefined();
  });

  it("Screen 1: Renders 5 provider cards with Gemini pre-selected", () => {
    render(<SetupWizard initialScreen={1} />);

    expect(screen.getByTestId("screen-1")).toBeDefined();

    const geminiCard = screen.getByTestId("provider-card-gemini");
    const openRouterCard = screen.getByTestId("provider-card-openrouter");
    const openAICard = screen.getByTestId("provider-card-openai");
    const anthropicCard = screen.getByTestId("provider-card-anthropic");
    const ollamaCard = screen.getByTestId("provider-card-ollama");

    expect(geminiCard).toBeDefined();
    expect(openRouterCard).toBeDefined();
    expect(openAICard).toBeDefined();
    expect(anthropicCard).toBeDefined();
    expect(ollamaCard).toBeDefined();

    // Verify Gemini is pre-selected
    expect(geminiCard.className).toContain("selected");
    expect(openAICard.className).not.toContain("selected");
  });

  it("Screen 1: Allows selecting a different provider and transitions on Continue", () => {
    render(<SetupWizard initialScreen={1} />);

    // Select OpenAI
    const openAICard = screen.getByTestId("provider-card-openai");
    fireEvent.click(openAICard);
    expect(openAICard.className).toContain("selected");

    // Click Continue
    const continueBtn = screen.getByTestId("btn-continue");
    fireEvent.click(continueBtn);

    // Verify transition to Screen 2 for OpenAI
    expect(screen.getByTestId("screen-2")).toBeDefined();
    expect(screen.getByText("Set Up OpenAI")).toBeDefined();
  });

  it("Screen 2: Allows navigation back to Screen 1", () => {
    render(<SetupWizard initialScreen={1} />);

    fireEvent.click(screen.getByTestId("btn-continue"));
    expect(screen.getByTestId("screen-2")).toBeDefined();

    // Click Back
    const backBtn = screen.getByTestId("btn-back");
    fireEvent.click(backBtn);

    expect(screen.getByTestId("screen-1")).toBeDefined();
  });

  it("Screen 2 -> Screen 3: Validates API key, transitions to Screen 3, speaks prompt and calls onComplete", async () => {
    mockInvoke.mockResolvedValueOnce({ success: true, provider: "gemini" });
    const onComplete = vi.fn();

    render(<SetupWizard initialScreen={1} onComplete={onComplete} />);

    // Continue with Gemini
    fireEvent.click(screen.getByTestId("btn-continue"));

    const keyInput = screen.getByTestId("input-api-key");
    fireEvent.change(keyInput, { target: { value: "AIzaSyTestValidKey123" } });

    const saveBtn = screen.getByTestId("btn-test-save");
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockInvoke).toHaveBeenCalledWith("validate_provider_key", {
        provider: "gemini",
        key: "AIzaSyTestValidKey123",
      });
    });

    // Screen 3 is shown
    await waitFor(() => {
      expect(screen.getByTestId("screen-ready")).toBeDefined();
      expect(screen.getByText(/HeyBloopie is ready. Press/i)).toBeDefined();
      expect(mockSpeak).toHaveBeenCalledWith(
        "HeyBloopie is ready. Press Ctrl+Shift+Space or say 'Hey Bloopie' to start."
      );
    });

    // Click Finish / Start button
    const finishBtn = screen.getByTestId("btn-finish-ready");
    fireEvent.click(finishBtn);
    expect(onComplete).toHaveBeenCalledWith("gemini");
  });

  it("Screen 2: Displays exact human-readable error message on validation failure", async () => {
    mockInvoke.mockResolvedValueOnce({
      success: false,
      error: "Gemini didn't recognize this key. It may have been deleted or copied incorrectly.",
    });

    render(<SetupWizard initialScreen={1} />);

    fireEvent.click(screen.getByTestId("btn-continue"));

    const keyInput = screen.getByTestId("input-api-key");
    fireEvent.change(keyInput, { target: { value: "AIzaSyInvalidKey" } });

    fireEvent.click(screen.getByTestId("btn-test-save"));

    await waitFor(() => {
      const errorBanner = screen.getByTestId("error-message");
      expect(errorBanner).toBeDefined();
      expect(errorBanner.textContent).toContain(
        "Gemini didn't recognize this key. It may have been deleted or copied incorrectly."
      );
    });

    expect(mockSpeak).not.toHaveBeenCalled();
  });

  it("Screen 2: Ollama flow auto-detects local server and completes to Screen 3", async () => {
    mockInvoke.mockResolvedValueOnce({
      success: true,
      detected: true,
      models: ["llama3.2:latest", "mistral:latest"],
    });
    const onComplete = vi.fn();

    render(<SetupWizard initialProvider="ollama" initialScreen={1} onComplete={onComplete} />);

    // Transition to Screen 2
    fireEvent.click(screen.getByTestId("btn-continue"));

    await waitFor(() => {
      expect(mockInvoke).toHaveBeenCalledWith("check_ollama", undefined);
    });

    await waitFor(() => {
      expect(screen.getByTestId("ollama-models")).toBeDefined();
      expect(screen.getByText("llama3.2:latest")).toBeDefined();
      expect(screen.getByText("mistral:latest")).toBeDefined();
      expect(screen.getByTestId("btn-ollama-finish")).toBeDefined();
    });

    // Clicking Connect & Save transitions to Screen 3 and speaks
    fireEvent.click(screen.getByTestId("btn-ollama-finish"));
    await waitFor(() => {
      expect(screen.getByTestId("screen-ready")).toBeDefined();
      expect(mockSpeak).toHaveBeenCalledWith(
        "HeyBloopie is ready. Press Ctrl+Shift+Space or say 'Hey Bloopie' to start."
      );
    });

    fireEvent.click(screen.getByTestId("btn-finish-ready"));
    expect(onComplete).toHaveBeenCalledWith("ollama");
  });

  it("Screen 2: Ollama flow shows retry button when server is not running", async () => {
    mockInvoke.mockResolvedValueOnce({
      success: false,
      detected: false,
      models: [],
    });

    render(<SetupWizard initialProvider="ollama" initialScreen={1} />);

    fireEvent.click(screen.getByTestId("btn-continue"));

    await waitFor(() => {
      expect(screen.getByTestId("btn-check-ollama")).toBeDefined();
      expect(screen.getByText(/Ollama was not detected at/i)).toBeDefined();
    });
  });
});
