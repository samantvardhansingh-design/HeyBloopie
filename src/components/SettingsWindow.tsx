import React, { useState, useEffect } from "react";
import { useUpdater } from "../hooks/useUpdater";

export interface SettingsWindowProps {
  onClose: () => void;
  onChangeProvider?: () => void;
  invokeFn?: (cmd: string, args?: any) => Promise<any>;
}

export interface TaskRecord {
  id: number;
  timestamp: string;
  user_request: string;
  status: string;
  duration_ms: number;
  provider?: string;
  model?: string;
}

export const SettingsWindow: React.FC<SettingsWindowProps> = ({
  onClose,
  onChangeProvider,
  invokeFn,
}) => {
  const [activeTab, setActiveTab] = useState<"provider" | "models" | "wake" | "log" | "updates">("provider");

  // Preferences state
  const [activeProvider, setActiveProvider] = useState<string>("gemini");
  const [preferFree, setPreferFree] = useState<boolean>(true);
  const [allowPaid, setAllowPaid] = useState<boolean>(false);
  const [allowLocal, setAllowLocal] = useState<boolean>(false);
  const [wakeWord, setWakeWord] = useState<string>("Hey Bloopie");
  const [wakeWordEnabled, setWakeWordEnabled] = useState<boolean>(true);

  // Action log state
  const [actionLog, setActionLog] = useState<TaskRecord[]>([]);
  const [isLoadingLog, setIsLoadingLog] = useState<boolean>(false);
  const [exportNotice, setExportNotice] = useState<string | null>(null);

  const { checkForUpdates, isUpdating, progress, statusMessage } = useUpdater();

  const callTauri = async (cmd: string, args?: any): Promise<any> => {
    if (invokeFn) {
      return invokeFn(cmd, args);
    }
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      return await invoke(cmd, args);
    } catch (err) {
      console.warn(`Tauri invoke('${cmd}') fallback:`, err);
      return null;
    }
  };

  useEffect(() => {
    loadPreferences();
    loadActionLog();
  }, []);

  const loadPreferences = async () => {
    try {
      const prefs = await callTauri("get_preferences");
      if (prefs && typeof prefs === "object") {
        if (prefs.active_provider) setActiveProvider(prefs.active_provider);
        if (prefs.prefer_free_models !== undefined) setPreferFree(prefs.prefer_free_models === "true" || prefs.prefer_free_models === true);
        if (prefs.allow_paid_fallback !== undefined) setAllowPaid(prefs.allow_paid_fallback === "true" || prefs.allow_paid_fallback === true);
        if (prefs.allow_local_fallback !== undefined) setAllowLocal(prefs.allow_local_fallback === "true" || prefs.allow_local_fallback === true);
        if (prefs.wake_word) setWakeWord(prefs.wake_word);
        if (prefs.wake_word_enabled !== undefined) setWakeWordEnabled(prefs.wake_word_enabled === "true" || prefs.wake_word_enabled === true);
      }
    } catch (e) {
      console.warn("Failed to load preferences:", e);
    }
  };

  const loadActionLog = async () => {
    setIsLoadingLog(true);
    try {
      const logs = await callTauri("get_action_log", { limit: 50 });
      if (Array.isArray(logs)) {
        setActionLog(logs);
      } else if (typeof logs === "string") {
        setActionLog(JSON.parse(logs));
      }
    } catch (e) {
      console.warn("Failed to load action log:", e);
    } finally {
      setIsLoadingLog(false);
    }
  };

  const savePref = async (key: string, value: string | boolean) => {
    try {
      await callTauri("set_preference", { key, value: String(value) });
    } catch (e) {
      console.warn(`Failed to set preference ${key}:`, e);
    }
  };

  const handleExportLog = async () => {
    try {
      const res = await callTauri("export_action_log");
      if (res && res.path) {
        setExportNotice(`Exported to: ${res.path}`);
      } else {
        setExportNotice("Action log exported successfully.");
      }
      setTimeout(() => setExportNotice(null), 5000);
    } catch (e) {
      setExportNotice("Failed to export log.");
    }
  };

  return (
    <div className="settings-window-backdrop" data-testid="settings-window" style={{
      position: "fixed",
      top: 0,
      left: 0,
      width: "100%",
      height: "100%",
      background: "rgba(10, 10, 15, 0.85)",
      backdropFilter: "blur(12px)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      zIndex: 10000,
      fontFamily: "Inter, -apple-system, sans-serif",
      color: "#e2e8f0",
    }}>
      <div style={{
        width: "90%",
        maxWidth: "680px",
        height: "85%",
        maxHeight: "560px",
        background: "#16161f",
        border: "1px solid rgba(255, 255, 255, 0.1)",
        borderRadius: "16px",
        boxShadow: "0 24px 64px rgba(0, 0, 0, 0.6)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{
          padding: "16px 24px",
          borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: "#1a1a24",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ fontSize: "18px", fontWeight: "600", color: "#f8fafc" }}>
              HeyBloopie Settings
            </span>
            <span style={{
              fontSize: "11px",
              padding: "2px 8px",
              background: "rgba(99, 102, 241, 0.2)",
              color: "#818cf8",
              borderRadius: "12px",
              fontWeight: "500",
            }}>
              v0.1.0
            </span>
          </div>
          <button
            onClick={onClose}
            data-testid="btn-close-settings"
            style={{
              background: "transparent",
              border: "none",
              color: "#94a3b8",
              cursor: "pointer",
              fontSize: "20px",
              padding: "4px 8px",
              borderRadius: "6px",
            }}
          >
            ✕
          </button>
        </div>

        {/* Navigation Tabs */}
        <div style={{
          display: "flex",
          gap: "8px",
          padding: "10px 24px",
          borderBottom: "1px solid rgba(255, 255, 255, 0.06)",
          background: "#13131b",
        }}>
          {(["provider", "models", "wake", "log", "updates"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              data-testid={`tab-${tab}`}
              style={{
                background: activeTab === tab ? "rgba(99, 102, 241, 0.25)" : "transparent",
                color: activeTab === tab ? "#c7d2fe" : "#94a3b8",
                border: activeTab === tab ? "1px solid rgba(99, 102, 241, 0.4)" : "1px solid transparent",
                padding: "6px 14px",
                borderRadius: "8px",
                cursor: "pointer",
                fontSize: "13px",
                fontWeight: activeTab === tab ? "600" : "500",
                textTransform: "capitalize",
                transition: "all 0.15s ease",
              }}
            >
              {tab === "models" ? "Models" : tab === "wake" ? "Wake Word" : tab === "log" ? "Action Log" : tab}
            </button>
          ))}
        </div>

        {/* Content Body */}
        <div style={{ flex: 1, padding: "24px", overflowY: "auto" }}>
          {/* TAB 1: Provider Management */}
          {activeTab === "provider" && (
            <div data-testid="tab-content-provider" style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
              <div>
                <h3 style={{ margin: "0 0 6px 0", fontSize: "15px", color: "#f8fafc" }}>
                  Active Provider
                </h3>
                <p style={{ margin: 0, fontSize: "13px", color: "#94a3b8" }}>
                  HeyBloopie delegates execution planning to this foundation provider.
                </p>
              </div>

              <div style={{
                background: "rgba(255, 255, 255, 0.03)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "12px",
                padding: "16px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}>
                <div>
                  <div style={{ fontSize: "16px", fontWeight: "600", textTransform: "capitalize", color: "#ffffff" }}>
                    {activeProvider}
                  </div>
                  <div style={{ fontSize: "12px", color: "#22c55e", marginTop: "2px" }}>
                    ● Connected and Ready
                  </div>
                </div>
                {onChangeProvider && (
                  <button
                    onClick={onChangeProvider}
                    data-testid="btn-change-provider"
                    style={{
                      background: "#4f46e5",
                      color: "#ffffff",
                      border: "none",
                      padding: "8px 16px",
                      borderRadius: "8px",
                      fontSize: "13px",
                      fontWeight: "500",
                      cursor: "pointer",
                    }}
                  >
                    Change Provider
                  </button>
                )}
              </div>
            </div>
          )}

          {/* TAB 2: Model Routing Preferences */}
          {activeTab === "models" && (
            <div data-testid="tab-content-models" style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
              <div>
                <h3 style={{ margin: "0 0 6px 0", fontSize: "15px", color: "#f8fafc" }}>
                  Model Routing Rules
                </h3>
                <p style={{ margin: 0, fontSize: "13px", color: "#94a3b8" }}>
                  Control how tasks are prioritized across free, paid, and local models.
                </p>
              </div>

              <label style={{ display: "flex", alignItems: "flex-start", gap: "12px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={preferFree}
                  onChange={(e) => {
                    setPreferFree(e.target.checked);
                    savePref("prefer_free_models", e.target.checked);
                  }}
                  data-testid="pref-free"
                  style={{ marginTop: "3px" }}
                />
                <div>
                  <div style={{ fontSize: "14px", fontWeight: "500", color: "#f8fafc" }}>Prefer Free Models</div>
                  <div style={{ fontSize: "12px", color: "#94a3b8" }}>Always choose zero-cost models first if available.</div>
                </div>
              </label>

              <label style={{ display: "flex", alignItems: "flex-start", gap: "12px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={allowPaid}
                  onChange={(e) => {
                    setAllowPaid(e.target.checked);
                    savePref("allow_paid_fallback", e.target.checked);
                  }}
                  data-testid="pref-paid"
                  style={{ marginTop: "3px" }}
                />
                <div>
                  <div style={{ fontSize: "14px", fontWeight: "500", color: "#f8fafc" }}>Allow Paid Fallback</div>
                  <div style={{ fontSize: "12px", color: "#94a3b8" }}>Automatically fall back to lowest-cost paid model if free tier is unavailable.</div>
                </div>
              </label>

              <label style={{ display: "flex", alignItems: "flex-start", gap: "12px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={allowLocal}
                  onChange={(e) => {
                    setAllowLocal(e.target.checked);
                    savePref("allow_local_fallback", e.target.checked);
                  }}
                  data-testid="pref-local"
                  style={{ marginTop: "3px" }}
                />
                <div>
                  <div style={{ fontSize: "14px", fontWeight: "500", color: "#f8fafc" }}>Allow Local Fallback (Ollama)</div>
                  <div style={{ fontSize: "12px", color: "#94a3b8" }}>Fall back to local Ollama instance if network models cannot be reached.</div>
                </div>
              </label>
            </div>
          )}

          {/* TAB 3: Wake Word Configuration */}
          {activeTab === "wake" && (
            <div data-testid="tab-content-wake" style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
              <div>
                <h3 style={{ margin: "0 0 6px 0", fontSize: "15px", color: "#f8fafc" }}>
                  Wake Word
                </h3>
                <p style={{ margin: 0, fontSize: "13px", color: "#94a3b8" }}>
                  Configure the hands-free voice trigger phrase.
                </p>
              </div>

              <div>
                <label style={{ display: "block", fontSize: "13px", fontWeight: "500", marginBottom: "6px", color: "#cbd5e1" }}>
                  Activation Phrase
                </label>
                <div style={{ display: "flex", gap: "10px" }}>
                  <input
                    type="text"
                    value={wakeWord}
                    onChange={(e) => setWakeWord(e.target.value)}
                    data-testid="input-wake-word"
                    style={{
                      flex: 1,
                      padding: "8px 12px",
                      borderRadius: "8px",
                      background: "#0f0f15",
                      border: "1px solid rgba(255, 255, 255, 0.15)",
                      color: "#ffffff",
                      fontSize: "14px",
                    }}
                  />
                  <button
                    onClick={() => savePref("wake_word", wakeWord)}
                    data-testid="btn-save-wake"
                    style={{
                      background: "#4f46e5",
                      color: "#ffffff",
                      border: "none",
                      padding: "8px 16px",
                      borderRadius: "8px",
                      fontWeight: "500",
                      cursor: "pointer",
                      fontSize: "13px",
                    }}
                  >
                    Save
                  </button>
                </div>
              </div>

              <label style={{ display: "flex", alignItems: "center", gap: "10px", cursor: "pointer", marginTop: "4px" }}>
                <input
                  type="checkbox"
                  checked={wakeWordEnabled}
                  onChange={(e) => {
                    setWakeWordEnabled(e.target.checked);
                    savePref("wake_word_enabled", e.target.checked);
                  }}
                  data-testid="chk-wake-enabled"
                />
                <span style={{ fontSize: "13px", color: "#cbd5e1" }}>
                  Listen for wake word in background
                </span>
              </label>
            </div>
          )}

          {/* TAB 4: Action Log Viewer */}
          {activeTab === "log" && (
            <div data-testid="tab-content-log" style={{ display: "flex", flexDirection: "column", gap: "16px", height: "100%" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div>
                  <h3 style={{ margin: "0 0 4px 0", fontSize: "15px", color: "#f8fafc" }}>
                    Action Log
                  </h3>
                  <p style={{ margin: 0, fontSize: "12px", color: "#94a3b8" }}>
                    History of recent tasks recorded in SQLite database.
                  </p>
                </div>
                <button
                  onClick={handleExportLog}
                  data-testid="btn-export-log"
                  style={{
                    background: "rgba(255, 255, 255, 0.08)",
                    border: "1px solid rgba(255, 255, 255, 0.15)",
                    color: "#f8fafc",
                    padding: "6px 14px",
                    borderRadius: "8px",
                    fontSize: "12px",
                    cursor: "pointer",
                    fontWeight: "500",
                  }}
                >
                  Export Log (JSON)
                </button>
              </div>

              {exportNotice && (
                <div style={{
                  padding: "8px 12px",
                  background: "rgba(34, 197, 94, 0.15)",
                  border: "1px solid rgba(34, 197, 94, 0.3)",
                  borderRadius: "8px",
                  fontSize: "12px",
                  color: "#4ade80",
                }}>
                  {exportNotice}
                </div>
              )}

              <div style={{
                flex: 1,
                overflowY: "auto",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "8px",
                background: "#0f0f15",
              }}>
                {isLoadingLog ? (
                  <div style={{ padding: "20px", textAlign: "center", color: "#94a3b8", fontSize: "13px" }}>
                    Loading log records...
                  </div>
                ) : actionLog.length === 0 ? (
                  <div style={{ padding: "20px", textAlign: "center", color: "#64748b", fontSize: "13px" }}>
                    No tasks logged yet.
                  </div>
                ) : (
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.08)", color: "#94a3b8", textAlign: "left" }}>
                        <th style={{ padding: "8px 12px" }}>Time</th>
                        <th style={{ padding: "8px 12px" }}>Request</th>
                        <th style={{ padding: "8px 12px" }}>Status</th>
                        <th style={{ padding: "8px 12px" }}>Duration</th>
                      </tr>
                    </thead>
                    <tbody>
                      {actionLog.map((task) => (
                        <tr key={task.id} style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.04)" }}>
                          <td style={{ padding: "8px 12px", color: "#94a3b8", whiteSpace: "nowrap" }}>
                            {task.timestamp ? new Date(task.timestamp).toLocaleTimeString() : "-"}
                          </td>
                          <td style={{ padding: "8px 12px", color: "#e2e8f0", maxWidth: "220px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {task.user_request}
                          </td>
                          <td style={{ padding: "8px 12px" }}>
                            <span style={{
                              padding: "2px 6px",
                              borderRadius: "4px",
                              fontSize: "10px",
                              fontWeight: "600",
                              textTransform: "uppercase",
                              background: task.status === "success" ? "rgba(34, 197, 94, 0.2)" : "rgba(239, 68, 68, 0.2)",
                              color: task.status === "success" ? "#4ade80" : "#f87171",
                            }}>
                              {task.status}
                            </span>
                          </td>
                          <td style={{ padding: "8px 12px", color: "#94a3b8" }}>
                            {task.duration_ms ? `${task.duration_ms}ms` : "-"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          )}

          {/* TAB 5: Updates */}
          {activeTab === "updates" && (
            <div data-testid="tab-content-updates" style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
              <div>
                <h3 style={{ margin: "0 0 6px 0", fontSize: "15px", color: "#f8fafc" }}>
                  Software Updates
                </h3>
                <p style={{ margin: 0, fontSize: "13px", color: "#94a3b8" }}>
                  HeyBloopie automatically checks for releases on startup.
                </p>
              </div>

              <div style={{
                background: "rgba(255, 255, 255, 0.03)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "12px",
                padding: "16px",
                display: "flex",
                flexDirection: "column",
                gap: "12px",
              }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div>
                    <div style={{ fontSize: "14px", fontWeight: "600", color: "#ffffff" }}>
                      Current Version
                    </div>
                    <div style={{ fontSize: "12px", color: "#94a3b8" }}>
                      v0.1.0 (Production Release)
                    </div>
                  </div>
                  <button
                    onClick={checkForUpdates}
                    disabled={isUpdating}
                    data-testid="btn-check-updates"
                    style={{
                      background: "#4f46e5",
                      color: "#ffffff",
                      border: "none",
                      padding: "8px 16px",
                      borderRadius: "8px",
                      fontWeight: "500",
                      fontSize: "13px",
                      cursor: isUpdating ? "not-allowed" : "pointer",
                      opacity: isUpdating ? 0.7 : 1,
                    }}
                  >
                    {isUpdating ? "Checking..." : "Check for Updates"}
                  </button>
                </div>

                {statusMessage && (
                  <div style={{ fontSize: "12px", color: "#cbd5e1", marginTop: "4px" }}>
                    {statusMessage}
                  </div>
                )}

                {isUpdating && progress > 0 && (
                  <div style={{ width: "100%", height: "4px", background: "#222", borderRadius: "2px", overflow: "hidden" }}>
                    <div style={{ width: `${progress}%`, height: "100%", background: "#4f46e5", transition: "width 0.2s ease" }} />
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SettingsWindow;
