import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useUpdater } from "./useUpdater";
import { check } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";

vi.mock("@tauri-apps/plugin-updater", () => ({
  check: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-process", () => ({
  relaunch: vi.fn(),
}));

describe("useUpdater", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("checks for updates and does nothing if no update is available", async () => {
    vi.mocked(check).mockResolvedValueOnce(null);

    const { result } = renderHook(() => useUpdater());

    await act(async () => {
      await result.current.checkForUpdates();
    });

    expect(check).toHaveBeenCalledTimes(1);
    expect(relaunch).not.toHaveBeenCalled();
    expect(result.current.isUpdating).toBe(false);
    expect(result.current.statusMessage).toBe("HeyBloopie is up to date.");
  });

  it("downloads update, reports progress, and calls relaunch on success", async () => {
    const mockUpdate = {
      version: "0.1.1",
      downloadAndInstall: vi.fn().mockImplementation(async (callback) => {
        callback({ event: "Started", data: { contentLength: 1000 } });
        callback({ event: "Progress", data: { chunkLength: 500 } });
        callback({ event: "Finished" });
      }),
    };

    vi.mocked(check).mockResolvedValueOnce(mockUpdate as any);

    const { result } = renderHook(() => useUpdater());

    await act(async () => {
      await result.current.checkForUpdates();
    });

    expect(mockUpdate.downloadAndInstall).toHaveBeenCalledTimes(1);
    expect(relaunch).toHaveBeenCalledTimes(1);
    expect(result.current.progress).toBe(100);
    expect(result.current.statusMessage).toBe("Update complete. Relaunching...");
  });

  it("handles update failure gracefully without crashing", async () => {
    vi.mocked(check).mockRejectedValueOnce(new Error("Network connection lost"));

    const { result } = renderHook(() => useUpdater());

    await act(async () => {
      await result.current.checkForUpdates();
    });

    expect(result.current.isUpdating).toBe(false);
    expect(result.current.statusMessage).toBe("Update check encountered an error.");
    expect(relaunch).not.toHaveBeenCalled();
  });
});
