# Architecture Specification — HeyBloopie

## 1. Architectural Philosophy & Principles
HeyBloopie is engineered on strict principles of **layer isolation**, **unidirectional data flow**, and **least-privilege boundaries**:
- **Separation of Concerns:** Planning is isolated from Execution; AI intelligence is isolated from Operating System tools.
- **The Planner has NO execution authority:** The Planner parses intent and formulates a plan, but possesses zero runtime handles to OS tools.
- **The Tool Layer has NO AI dependencies:** Every tool is a pure, deterministic, asynchronous Python/Rust function.
- **The Core NEVER calls AI APIs or Tools directly:** All actions are coordinated through structured interfaces (Provider Layer, Policy Engine, Tool Dispatcher).

---

## 2. System Architecture Diagram

```mermaid
graph TB
    subgraph UI_Layer["1. Desktop Shell (Tauri 2.0 / Native Webview)"]
        UI[Floating HUD / Voice Overlay]
        Tray[System Tray / Hotkey Listener]
    end

    subgraph Core_Engine["2. HeyBloopie Core"]
        Core[Orchestrator Loop]
    end

    subgraph Intelligence["3. Planning & AI Abstraction"]
        Planner[Planner Module]
        Provider[Provider Abstraction Layer]
        AIModels[(Gemini / OpenAI / Anthropic / Ollama / OpenRouter)]
    end

    subgraph Security_Gate["4. Security & Safety"]
        Policy[Policy Engine]
    end

    subgraph Execution["5. Sandboxed Tool Layer"]
        Dispatcher[Tool Dispatcher]
        ToolFind[find_files]
        ToolMove[move_file]
        ToolRename[rename_file]
        ToolFolder[create_folder / list_folder]
        ToolMeta[get_file_metadata / read_file_content]
    end

    subgraph Storage["6. Persistence & Context"]
        Memory[Memory Layer (SQLite)]
    end

    UI <-->|IPC / Events| Core
    Tray -->|Hotkey Trigger| Core
    Core <-->|Request / Plan| Planner
    Planner <-->|Standardized Prompts| Provider
    Provider <-->|API Calls| AIModels
    Core -->|Check Proposed Step| Policy
    Policy -->|Approval / Risk Preview| Core
    Core -->|Dispatch Verified Step| Dispatcher
    Dispatcher --> ToolFind
    Dispatcher --> ToolMove
    Dispatcher --> ToolRename
    Dispatcher --> ToolFolder
    Dispatcher --> ToolMeta
    Core <-->|Audit Log / Caches / History| Memory
```

---

## 3. Core Architectural Layers & Interfaces

### 3.1 HeyBloopie Core (The Orchestrator)
The Core manages the execution lifecycle state machine. It does not contain domain-specific file logic or provider-specific LLM logic.
- **Execution Loop:**
  1. `Receive Request` (from Voice/Text UI).
  2. `Request Plan` (from Planner).
  3. `Policy Check` (via Policy Engine for every step in the plan).
  4. `User Confirmation` (if step risk is Medium/High).
  5. `Dispatch Action` (via Tool Layer).
  6. `Verify Outcome` (confirm file state on disk matches expected outcome).
  7. `Report Status` (stream feedback to UI / TTS).

### 3.2 Planner Module
- **Responsibility:** Receives user intent and current environment context (allowed paths, recent history). Generates a strictly validated JSON execution plan.
- **Constraint:** Completely decoupled from tool binaries. It can only emit a structured step list (Schema: `PlanStep(tool_name, parameters, expected_outcome)`).
- **Interface:**
  ```python
  class Planner:
      async def generate_plan(self, user_prompt: str, context: SystemContext) -> ExecutionPlan:
          ...
  ```

### 3.3 Provider Abstraction Layer (PAL)
- **Responsibility:** Normalizes requests and streaming responses across diverse AI backends.
- **Supported Providers:**
  - Google Gemini (Gemini 2.5/3.x)
  - Anthropic Claude
  - OpenAI (GPT-4o, etc.)
  - OpenRouter (unified multi-model routing)
  - Ollama (fully local offline inference)
- **Interface:**
  ```python
  class AIProvider(ABC):
      @abstractmethod
      async def complete(self, prompt: str, schema: Optional[dict] = None) -> str: ...

      @abstractmethod
      async def stream_response(self, prompt: str) -> AsyncIterator[str]: ...
  ```

### 3.4 Policy Engine
- **Responsibility:** Intercepts every atomic action before execution. Validates paths against the whitelist sandbox and evaluates risk level.
- **Interface:**
  ```python
  class PolicyEngine:
      async def check_action(self, action: PlanStep) -> PolicyDecision:
          # Returns: ALLOWED, REQUIRES_CONFIRMATION, or BLOCKED
          ...
  ```

### 3.5 Tool Layer (Sandboxed Execution)
- **Responsibility:** Executes deterministic, isolated file-system operations asynchronously.
- **Standardized Tools:**
  - `find_files(query, directory, search_type, filters)`
  - `move_file(source_path, destination_path)`
  - `rename_file(target_path, new_name)`
  - `create_folder(folder_path)`
  - `list_folder(folder_path, recursive, depth)`
  - `get_file_metadata(file_path)`
  - `read_file_content(file_path, max_bytes)`
- **Constraint:** Zero imports from AI modules or prompt packages. Returns standard result schemas `ToolResult(success, data, error)`.

### 3.6 Memory Layer (SQLite)
- **Responsibility:** Manages all persistent storage and relational queries via SQLite (WAL mode).
- **Storage Domains:**
  - **Audit Logs:** Immutable record of every tool execution, path mutation, and user confirmation.
  - **Path Index & Caching:** Directory snapshots and hashes to optimize prompt caching and fast lookup.
  - **Session History:** Conversation trajectory for contextual multi-turn follow-ups.
  - **Preferences & Whitelisted Paths:** User directory permissions and custom preferences.

---

## 4. End-to-End Request Lifecycle
```text
[User Input: "Rename all receipt screenshots in Downloads to Receipt_YYYYMMDD"]
       |
       v
1. Core receives prompt -> passes context to Planner
       |
       v
2. Planner uses Provider Abstraction Layer to produce ExecutionPlan:
   - Step 1: list_folder(path="C:/Users/.../Downloads")
   - Step 2: filter & compute target names
   - Step 3: rename_file(src=..., dst=...) for each match
       |
       v
3. Core evaluates Step 1 with Policy Engine -> ALLOWED -> Core dispatches Tool
       |
       v
4. Tool returns file list -> Core feeds results to Planner for Step 2 & 3
       |
       v
5. Step 3 evaluated by Policy Engine -> Risk: MEDIUM (Bulk Rename)
   -> Policy Engine returns REQUIRES_CONFIRMATION with visual preview diff
       |
       v
6. Core surfaces Preview to User in UI: "Rename 14 files? [Approve / Cancel]"
       |
       +---> [If Cancelled]: Core halts execution, reports cancellation.
       |
       +---> [If Approved]: Core executes batch rename via Tool Layer
       |
       v
7. Core executes Verification: Checks files on disk match new names
       |
       v
8. Core logs transaction to SQLite Memory Layer -> Streams audio/text completion to user.
```
