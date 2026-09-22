# HeyBloopie

**HeyBloopie** is a privacy-first, desktop AI agent for Windows that helps users manage files through natural language. Press a global hotkey (`Ctrl+Shift+Space`), speak or type a request, and HeyBloopie either accomplishes the task (finding, organizing, renaming, moving files) or honestly states what it cannot do.

---

## Architecture Overview

HeyBloopie is built on a modular, decoupled multi-layer architecture:
1. **Desktop Shell (Tauri 2.0 / Native Webview):** Lightweight HUD overlay triggered via global hotkey (`Ctrl+Shift+Space`), running with an ~80MB memory footprint.
2. **HeyBloopie Core:** Orchestrates the primary execution loop (receive request $\rightarrow$ plan $\rightarrow$ policy check $\rightarrow$ dispatch $\rightarrow$ verify $\rightarrow$ report).
3. **Planner:** Translates natural language into structured plans without direct execution access.
4. **Sandboxed Tool Layer:** Independent, asynchronous file operations with zero AI dependencies.
5. **Policy Engine:** Hard code-level security gate checking every tool action against allowed whitelists and risk tiers.
6. **Provider Abstraction Layer (PAL):** Communicates with AI models (Google Gemini, OpenAI, Claude, Ollama) via unified interfaces.
7. **Memory Layer:** Manages persistent audit logs, directory caching, and user whitelists via SQLite.

---

## Directory Structure

```text
heybloopie/
├── docs/
│   ├── PRD.md              # Product requirements, personas, scope, and success metrics
│   ├── ARCHITECTURE.md     # Multi-layer architecture design and component interfaces
│   ├── SECURITY.md         # Zero-trust safety model, policy gating, and sandboxing
│   └── PERFORMANCE.md      # Performance budgets, async I/O, and latency limits
├── src-tauri/
│   ├── src/
│   │   └── main.rs         # Tauri backend, tray icon management, and global hotkey
│   ├── Cargo.toml          # Rust dependencies (Tauri 2.0, global shortcut)
│   └── tauri.conf.json     # Windowless tray-first desktop app configuration
├── src/
│   ├── main.tsx            # React application entrypoint
│   ├── App.tsx             # Root UI component
│   ├── components/
│   │   ├── Overlay.tsx     # Floating HUD overlay triggered on hotkey
│   │   └── SetupWizard.tsx # Initial onboarding (folders & credentials)
│   └── styles.css          # Translucent HUD glassmorphic styling
├── python/
│   ├── core.py             # Orchestrator loop (plan -> policy -> dispatch -> verify)
│   ├── planner.py          # Intent parser generating structured execution plans
│   ├── tools.py            # Sandboxed, isolated async file operations
│   ├── policy.py           # Hard code-level security gate & risk evaluation
│   ├── provider.py         # AI provider abstraction (Gemini, OpenRouter, etc.)
│   ├── model_registry.py   # Model catalog, limits, and capability metadata
│   ├── model_router.py     # Dynamic routing based on task complexity/offline needs
│   ├── memory.py           # SQLite persistence for audit logs and directory caching
│   └── requirements.txt    # Python dependencies
├── tests/
│   ├── test_tools.py       # Test suite for file tool operations
│   ├── test_policy.py      # Test suite for security checks and sandbox limits
│   └── test_core.py        # Test suite for core orchestrator loop
├── agents.md               # Specialized AI engineering team roles & constraints
├── package.json            # Node.js frontend dependencies & build scripts
├── tsconfig.json           # TypeScript configuration
└── README.md               # Project documentation
```

---

## Security Model

- **Zero-Trust Default:** No folder access permitted without explicit user whitelist.
- **Code-Level Policy Gate:** Every action must pass `policy.check_action()` before execution.
- **Protected Windows Paths:** System directories (`Windows`, `System32`, `Program Files`) cannot be accessed or whitelisted.
- **Safe Credentials:** API keys are stored exclusively in the Windows Credential Manager (`keyring`).
