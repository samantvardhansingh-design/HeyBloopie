# Security & Safety Model — HeyBloopie

## 1. Security Philosophy
HeyBloopie operates under a **Zero-Trust, Local-First, Fail-Safe** model. Because HeyBloopie manages local files on a user's machine, security cannot rely on model alignment or soft system prompts. Security is enforced through **hard code-level boundaries**, process isolation, cryptographic credential management, and human-in-the-loop verification gates.

---

## 2. Core Security Pillars

### 2.1 Principle of Least Privilege
- **Default State = Zero Permission:** Upon initial installation, HeyBloopie cannot access, read, or modify any folder on the system.
- **Explicit Granting:** The user must explicitly whitelist specific root directories (e.g., `C:\Users\Username\Downloads`, `C:\Users\Username\Documents\Invoices`).
- **Forbidden Windows Directories:** Critical operating system locations are hard-blocked at the kernel/code level and can never be whitelisted:
  - `C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`
  - `C:\Users\...\AppData\Local\Microsoft`, `System32`
  - Root system volumes (`C:\` root file-level mutations)

### 2.2 Sandboxed Execution
- The Tool Layer operates within a restricted process boundary.
- All incoming path parameters are strictly canonicalized using `os.path.realpath` / `Path.resolve()` to prevent directory traversal attacks (e.g., `../../Windows/System32`).
- Symlinks pointing outside permitted boundaries are automatically rejected.

### 2.3 Hard Code-Level Policy Engine (`policy.check_action`)
- Every tool call **must** pass through `policy.check_action(step)` before the Tool Dispatcher will invoke the function.
- **No LLM Bypass:** If the LLM produces a plan step targeting an unpermitted directory or attempting an unpermitted operation, `policy.check_action` will reject it immediately with an explicit error.
- The policy check is deterministic code, not a prompt instruction.

```python
# Conceptual Enforcement Pattern
decision = await policy_engine.check_action(proposed_step)
if decision.status == PolicyStatus.DENIED:
    logger.warn(f"Blocked unauthorized action: {proposed_step}")
    raise SecurityViolationException(decision.reason)
```

---

## 3. Action Risk Categorization & Human-in-the-Loop (HITL)

Actions are classified into three distinct risk tiers. Risk levels dictate UI confirmation requirements:

| Risk Level | Action Types | Enforcement Gate | UI Interaction |
| :--- | :--- | :--- | :--- |
| **LOW (Safe)** | `find_files`, `list_folder`, `get_file_metadata`, `read_file_content` (read-only) | Autonomous execution within whitelisted directories. | Instant execution, transparent status log. |
| **MEDIUM (Mutating)** | Single `move_file`, Single `rename_file`, `create_folder` | Action Preview Required. | Displays source, target destination, and requires user click or voice confirmation ("Confirm"). |
| **HIGH (Destructive / Bulk)** | Bulk renames (> 1 file), Bulk moves (> 1 file), Directory restructuring, File overwrites | Strict Multi-Modal Confirmation with diff preview. | Displays complete before/after table preview with an explicit *"Are you sure?"* prompt. |

> [!CAUTION]
> **No Permanent Deletions in V1:** Permanent file deletion (`rmdir /s`, `os.remove`) is completely disabled in V1 tools. Any removal operations must move files to the OS Recycle Bin (`send2trash`) with explicit High-Risk approval.

---

## 4. Credential Isolation & Key Storage
- **Zero Plaintext Storage:** API keys (OpenAI, Gemini, Anthropic, OpenRouter) are **never** stored in plain text configuration files, environment files (`.env`), databases, or application caches.
- **Windows Credential Manager Integration:** All credentials are encrypted and stored exclusively inside the native Windows Credential Manager via the `keyring` library (under the namespace `HeyBloopie_Vault`).
- **Redaction in Logs:** All logging pipelines implement automated regex redaction filters to sanitize API keys, session tokens, and sensitive file paths from crash dumps and debug traces.

---

## 5. No Ambient Authority & Network Sandboxing
- **Whitelisted Endpoints Only:** The agent has no generic network stack access or web browsing engine.
- Outbound HTTP requests are strictly locked to official AI provider domains:
  - `generativelanguage.googleapis.com` (Google Gemini)
  - `api.openai.com` (OpenAI)
  - `api.anthropic.com` (Anthropic)
  - `openrouter.ai` (OpenRouter)
  - `localhost:11434` / `127.0.0.1` (Ollama local inference)
- Any tool attempt to establish outbound network connections, sockets, or download remote scripts is rejected at the process level.

---

## 6. Audit Logging & Reversibility
- **Immutable Transaction Log:** Every executed mutating operation is written to an append-only SQLite audit log with timestamp, original path, new path, and verification checksum.
- **Undo Capability:** Because state changes are logged with source and destination pairs, mutations can be rolled back via an `undo` command.
