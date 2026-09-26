import { defineConfig, Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { execFile } from "node:child_process";

function tauriDevBridge(): Plugin {
  return {
    name: "tauri-dev-bridge",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (req.url === "/api/tauri" && req.method === "POST") {
          let body = "";
          req.on("data", (chunk) => {
            body += chunk;
          });
          req.on("end", async () => {
            try {
              const { cmd, args } = JSON.parse(body || "{}");
              let pyScript = "";

              if (cmd === "check_onboarding_needed") {
                pyScript = "from python import memory; val = memory.get_preference('active_provider'); print('false' if val else 'true')";
              } else if (cmd === "validate_provider_key") {
                const provider = args?.provider || "gemini";
                const key = args?.key || "";
                pyScript = `import asyncio, json; from python.provider import validate_provider_key; res = asyncio.run(validate_provider_key(${JSON.stringify(provider)}, ${JSON.stringify(key)})); print(json.dumps(res))`;
              } else if (cmd === "run_core") {
                const request = args?.request || "";
                pyScript = `import asyncio, json, dataclasses; from python import core; r = asyncio.run(core.run(${JSON.stringify(request)})); print('__JSON_START__' + json.dumps(dataclasses.asdict(r)))`;
              } else if (cmd === "check_ollama") {
                pyScript = "import asyncio, json; from python.provider import check_ollama; res = asyncio.run(check_ollama()); print(json.dumps(res))";
              } else if (cmd === "get_preferences") {
                pyScript = "import json; from python import memory; print(json.dumps(memory.get_all_preferences()))";
              } else if (cmd === "set_preference") {
                pyScript = `from python import memory; memory.set_preference(${JSON.stringify(args?.key)}, ${JSON.stringify(args?.value)}); print('true')`;
              } else if (cmd === "get_action_log") {
                const lim = args?.limit || 50;
                pyScript = `import json; from python import memory; tasks = memory.get_recent_tasks(limit=${lim}); print(json.dumps(tasks))`;
              } else if (cmd === "set_tray_ready" || cmd === "start_wake_word") {
                res.setHeader("Content-Type", "application/json");
                res.end(JSON.stringify({ result: true }));
                return;
              } else {
                res.setHeader("Content-Type", "application/json");
                res.end(JSON.stringify({ result: null }));
                return;
              }

              execFile("python", ["-u", "-c", pyScript], { cwd: process.cwd() }, (err, stdout, stderr) => {
                if (err) {
                  res.setHeader("Content-Type", "application/json");
                  res.end(JSON.stringify({ error: stderr || err.message }));
                  return;
                }
                const output = stdout.trim();
                let result: any = output;
                const events: any[] = [];
                for (const line of output.split("\n")) {
                  const trimmed = line.trim();
                  if (trimmed.startsWith("__TAURI_EVENT__")) {
                    try {
                      events.push(JSON.parse(trimmed.slice("__TAURI_EVENT__".length)));
                    } catch {}
                  }
                }
                for (const line of output.split("\n").reverse()) {
                  const trimmed = line.trim();
                  if (trimmed.startsWith("__JSON_START__")) {
                    try {
                      result = JSON.parse(trimmed.slice("__JSON_START__".length));
                      break;
                    } catch {}
                  }
                  try {
                    result = JSON.parse(trimmed);
                    break;
                  } catch {}
                }
                res.setHeader("Content-Type", "application/json");
                res.end(JSON.stringify({ result, events }));
              });
            } catch (e: any) {
              res.statusCode = 500;
              res.setHeader("Content-Type", "application/json");
              res.end(JSON.stringify({ error: e.message }));
            }
          });
          return;
        }
        next();
      });
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tauriDevBridge()],
  // @ts-ignore
  test: {
    environment: "jsdom",
    globals: true,
    exclude: ["**/node_modules/**", "**/.kilo/**", "**/dist/**"],
  },
});
