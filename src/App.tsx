import React, { useEffect, useState, useRef } from "react";
import Overlay from "./components/Overlay";
import SetupWizard from "./components/SetupWizard";
import SettingsWindow from "./components/SettingsWindow";
import { useUpdater } from "./hooks/useUpdater";
import { useSpeechSynthesis } from "./hooks/useSpeechSynthesis";
import { safeInvoke } from "./utils/tauriBridge";

export interface AppProps {
  initialView?: "overlay" | "setup" | "settings";
  invokeFn?: (cmd: string, args?: any) => Promise<any>;
}

export const App: React.FC<AppProps> = ({ initialView, invokeFn }) => {
  const [view, setView] = useState<"overlay" | "setup" | "settings">(initialView || "overlay");
  const { checkForUpdates, isUpdating, progress, statusMessage } = useUpdater();
  const { speak } = useSpeechSynthesis();
  const speakRef = useRef(speak);

  useEffect(() => {
    speakRef.current = speak;
  }, [speak]);

  const callTauri = async (cmd: string, args?: any): Promise<any> => {
    if (invokeFn) {
      return invokeFn(cmd, args);
    }
    return await safeInvoke(cmd, args);
  };

  useEffect(() => {
    // Check for updates
    checkForUpdates();

    // Check onboarding on mount unless an initialView was explicitly forced
    const initApp = async () => {
      try {
        const onboardingNeeded = await callTauri("check_onboarding_needed");
        if (onboardingNeeded === true) {
          setView("setup");
          await callTauri("set_tray_ready", { ready: false });
        } else if (onboardingNeeded === false) {
          if (!initialView) {
            setView("overlay");
          }
          await callTauri("set_tray_ready", { ready: true });
          await callTauri("start_wake_word");
        }
      } catch (err) {
        console.warn("Failed checking onboarding status:", err);
      }
    };

    initApp();

    // Listen to tray, backend, and streaming TTS events
    let unlisteners: Array<() => void> = [];
    const setupListeners = async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        const u1 = await listen("open_overlay", () => setView("overlay"));
        const u2 = await listen("open_settings", () => setView("settings"));
        const u3 = await listen("check_updates", () => checkForUpdates());
        const u4 = await listen<any>("speak-sentence", (event) => {
          const payload = event.payload;
          const sentence =
            typeof payload === "string"
              ? payload
              : payload?.text || payload?.sentence || String(payload ?? "");
          if (sentence && sentence.trim()) {
            console.log("Received speak-sentence event:", sentence.trim());
            speakRef.current(sentence.trim(), { enqueue: true });
          }
        });
        unlisteners.push(u1, u2, u3, u4);
      } catch (err) {
        // Ignored outside Tauri
      }
    };
    setupListeners();

    // Custom DOM event listener for browser dev mode and unit tests
    const onCustomSpeakSentence = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      const sentence =
        typeof detail === "string"
          ? detail
          : detail?.text || detail?.sentence || String(detail ?? "");
      if (sentence && sentence.trim()) {
        console.log("Received custom speak-sentence event:", sentence.trim());
        speakRef.current(sentence.trim(), { enqueue: true });
      }
    };
    window.addEventListener("speak-sentence", onCustomSpeakSentence);

    return () => {
      unlisteners.forEach((u) => u());
      window.removeEventListener("speak-sentence", onCustomSpeakSentence);
    };
  }, []);

  const handleSetupComplete = async (_provider: string) => {
    await callTauri("set_tray_ready", { ready: true });
    await callTauri("start_wake_word");
    setView("overlay");
  };

  const handleRunCore = async (userRequest: string) => {
    console.log("Sending request to backend...", "run_core", { request: userRequest });
    return await callTauri("run_core", { request: userRequest });
  };

  return (
    <main style={{ width: "100%", height: "100%" }}>
      {isUpdating && (
        <div
          data-testid="updater-progress"
          style={{
            position: "fixed",
            bottom: "16px",
            right: "16px",
            background: "#1e1e24",
            color: "#ffffff",
            padding: "10px 16px",
            borderRadius: "8px",
            boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
            zIndex: 9999,
            fontSize: "12px",
          }}
        >
          <div>{statusMessage}</div>
          {progress > 0 && (
            <div
              style={{
                width: "100%",
                height: "4px",
                background: "#333",
                borderRadius: "2px",
                marginTop: "6px",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${progress}%`,
                  height: "100%",
                  background: "#4f46e5",
                  transition: "width 0.2s ease",
                }}
              />
            </div>
          )}
        </div>
      )}

      {view === "setup" && (
        <SetupWizard
          onComplete={handleSetupComplete}
          onCancel={() => setView("overlay")}
          invokeFn={invokeFn}
        />
      )}

      {view === "settings" && (
        <SettingsWindow
          onClose={() => setView("overlay")}
          onChangeProvider={() => setView("setup")}
          invokeFn={invokeFn}
        />
      )}

      {view === "overlay" && (
        <Overlay
          onOpenSettings={() => setView("settings")}
          onRun={handleRunCore}
        />
      )}
    </main>
  );
};

export default App;
