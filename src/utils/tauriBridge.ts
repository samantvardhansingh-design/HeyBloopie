/**
 * Unified Tauri Bridge Helper.
 * Automatically delegates to native Tauri `invoke` inside desktop webview (and unit test mocks),
 * or directly calls Vite dev server `/api/tauri` bridge when running in a standard web browser (Chrome, Edge).
 */
export async function safeInvoke<T = any>(
  cmd: string,
  args?: Record<string, any>
): Promise<T> {
  const isTauri =
    typeof window !== "undefined" &&
    Boolean((window as any).__TAURI_INTERNALS__ || (window as any).__TAURI__);

  const isTest =
    (typeof import.meta !== "undefined" &&
      Boolean(
        (import.meta as any).env?.MODE === "test" ||
          (import.meta as any).env?.VITEST
      )) ||
    (typeof globalThis !== "undefined" &&
      Boolean(
        (globalThis as any).process?.env?.VITEST ||
          (globalThis as any).process?.env?.NODE_ENV === "test"
      ));

  // 1. Native Tauri Desktop OR Unit Test Environment
  if (isTauri || isTest) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      return await invoke<T>(cmd, args);
    } catch (err: any) {
      const msg = String(err?.message || err || "");
      // If error is specifically due to running in browser without Tauri internals:
      if (
        !msg.includes("Cannot read properties of undefined") &&
        !msg.includes("__TAURI_INTERNALS__")
      ) {
        throw err;
      }
    }
  }

  // 2. Web Browser Environment (Chrome, Edge at http://localhost:5173)
  if (
    typeof window !== "undefined" &&
    window.location &&
    window.location.origin &&
    window.location.origin.startsWith("http")
  ) {
    const res = await fetch(`${window.location.origin}/api/tauri`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cmd, args: args || {} }),
    });

    if (res.ok) {
      const data = await res.json();
      if (data && data.error) {
        throw new Error(data.error);
      }
      return data ? (data.result as T) : (null as any);
    } else {
      const errText = await res.text();
      throw new Error(errText || `Server returned ${res.status}`);
    }
  }

  // 3. Fallbacks if unreachable
  if (cmd === "check_onboarding_needed") return false as any;
  if (cmd === "set_tray_ready" || cmd === "start_wake_word") return true as any;
  if (cmd === "get_preferences") return {} as any;

  throw new Error(`Desktop app is not active and browser bridge failed for: ${cmd}`);
}
