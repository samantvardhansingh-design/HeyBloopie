import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SettingsWindow } from "./SettingsWindow";

// Mock useUpdater hook
const mockCheckForUpdates = vi.fn();
vi.mock("../hooks/useUpdater", () => ({
  useUpdater: () => ({
    checkForUpdates: mockCheckForUpdates,
    isUpdating: false,
    progress: 0,
    statusMessage: "Up to date",
  }),
}));

describe("SettingsWindow Component", () => {
  let mockInvoke: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockInvoke = vi.fn().mockImplementation((cmd: string, _args?: any) => {
      if (cmd === "get_preferences") {
        return Promise.resolve({
          active_provider: "gemini",
          prefer_free_models: "true",
          allow_paid_fallback: "false",
          allow_local_fallback: "true",
          wake_word: "Hey Bloopie",
          wake_word_enabled: "true",
        });
      }
      if (cmd === "get_action_log") {
        return Promise.resolve([
          {
            id: 1,
            timestamp: "2026-09-24T12:00:00Z",
            user_request: "find tax receipts on desktop",
            status: "success",
            duration_ms: 1420,
            provider: "gemini",
            model: "gemini-2.5-flash",
          },
          {
            id: 2,
            timestamp: "2026-09-24T12:05:00Z",
            user_request: "move downloads to archive",
            status: "failed",
            duration_ms: 850,
            provider: "gemini",
            model: "gemini-2.5-flash",
          },
        ]);
      }
      if (cmd === "set_preference") {
        return Promise.resolve(true);
      }
      if (cmd === "export_action_log") {
        return Promise.resolve({ success: true, path: "C:/Users/test/export.json" });
      }
      return Promise.resolve(null);
    });
  });

  const renderSettings = async (onClose = vi.fn()) => {
    const utils = render(<SettingsWindow onClose={onClose} invokeFn={mockInvoke} />);
    await waitFor(() => {
      expect(screen.getByTestId("settings-window")).toBeDefined();
      expect(screen.getByText("Active Provider")).toBeDefined();
    });
    return { ...utils, onClose };
  };

  it("Renders settings window with all tabs", async () => {
    await renderSettings();

    expect(screen.getByTestId("settings-window")).toBeDefined();
    expect(screen.getByTestId("tab-provider")).toBeDefined();
    expect(screen.getByTestId("tab-models")).toBeDefined();
    expect(screen.getByTestId("tab-wake")).toBeDefined();
    expect(screen.getByTestId("tab-log")).toBeDefined();
    expect(screen.getByTestId("tab-updates")).toBeDefined();

    // Provider tab is active by default
    expect(screen.getByText("Active Provider")).toBeDefined();
  });

  it("Switches tabs and toggles model preferences", async () => {
    await renderSettings();

    // Switch to Models tab
    fireEvent.click(screen.getByTestId("tab-models"));
    expect(screen.getByText("Model Routing Rules")).toBeDefined();

    // Toggle 'Allow Paid Fallback'
    const paidCheckbox = screen.getByTestId("pref-paid");
    expect(paidCheckbox).toBeDefined();
    fireEvent.click(paidCheckbox);

    await waitFor(() => {
      expect(mockInvoke).toHaveBeenCalledWith("set_preference", {
        key: "allow_paid_fallback",
        value: "true",
      });
    });
  });

  it("Displays SQLite action log and exports log on button click", async () => {
    await renderSettings();

    // Switch to Action Log tab
    fireEvent.click(screen.getByTestId("tab-log"));

    await waitFor(() => {
      expect(screen.getByText("find tax receipts on desktop")).toBeDefined();
      expect(screen.getByText("move downloads to archive")).toBeDefined();
    });

    // Click Export Log button
    const exportBtn = screen.getByTestId("btn-export-log");
    fireEvent.click(exportBtn);

    await waitFor(() => {
      expect(mockInvoke).toHaveBeenCalledWith("export_action_log", undefined);
      expect(screen.getByText(/Exported to: C:\/Users\/test\/export.json/i)).toBeDefined();
    });
  });

  it("Switches to Software Updates tab and triggers check for updates", async () => {
    await renderSettings();

    // Switch to Updates tab
    fireEvent.click(screen.getByTestId("tab-updates"));
    expect(screen.getByText("Software Updates")).toBeDefined();

    const checkBtn = screen.getByTestId("btn-check-updates");
    fireEvent.click(checkBtn);
    expect(mockCheckForUpdates).toHaveBeenCalled();
  });

  it("Calls onClose when close button is clicked", async () => {
    const onClose = vi.fn();
    await renderSettings(onClose);

    const closeBtn = screen.getByTestId("btn-close-settings");
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalled();
  });
});
