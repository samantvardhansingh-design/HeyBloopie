import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import App from "./App";

vi.mock("./hooks/useUpdater", () => ({
  useUpdater: () => ({
    checkForUpdates: vi.fn(),
    isUpdating: false,
    progress: 0,
    statusMessage: "Idle",
  }),
}));

vi.mock("./hooks/useSpeechRecognition", () => ({
  useSpeechRecognition: () => ({
    transcript: "",
    isListening: false,
    startListening: vi.fn(),
    stopListening: vi.fn(),
  }),
}));

vi.mock("./hooks/useSpeechSynthesis", () => ({
  useSpeechSynthesis: () => ({
    speak: vi.fn(),
    stop: vi.fn(),
    isSpeaking: false,
    voices: [],
    selectedVoice: null,
    setSelectedVoice: vi.fn(),
  }),
}));

describe("App Component", () => {
  let mockInvoke: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockInvoke = vi.fn().mockImplementation((cmd: string, _args?: any) => {
      if (cmd === "check_onboarding_needed") {
        return Promise.resolve(false);
      }
      return Promise.resolve(true);
    });
  });

  it("Renders SetupWizard when check_onboarding_needed returns true", async () => {
    mockInvoke.mockImplementation((cmd: string) => {
      if (cmd === "check_onboarding_needed") return Promise.resolve(true);
      return Promise.resolve(true);
    });

    render(<App invokeFn={mockInvoke} />);

    await waitFor(() => {
      expect(screen.getByTestId("setup-wizard")).toBeDefined();
      expect(mockInvoke).toHaveBeenCalledWith("set_tray_ready", { ready: false });
    });
  });

  it("Renders Overlay and starts wake word when check_onboarding_needed returns false", async () => {
    mockInvoke.mockImplementation((cmd: string) => {
      if (cmd === "check_onboarding_needed") return Promise.resolve(false);
      return Promise.resolve(true);
    });

    render(<App invokeFn={mockInvoke} />);

    await waitFor(() => {
      expect(screen.getByTestId("overlay-container")).toBeDefined();
      expect(mockInvoke).toHaveBeenCalledWith("set_tray_ready", { ready: true });
      expect(mockInvoke).toHaveBeenCalledWith("start_wake_word", undefined);
    });

    // Opening settings from HUD button
    const settingsBtn = screen.getByTestId("settings-btn");
    fireEvent.click(settingsBtn);

    await waitFor(() => {
      expect(screen.getByTestId("settings-window")).toBeDefined();
    });

    // Closing settings returns to overlay
    const closeBtn = screen.getByTestId("btn-close-settings");
    fireEvent.click(closeBtn);

    await waitFor(() => {
      expect(screen.getByTestId("overlay-container")).toBeDefined();
    });
  });
});
