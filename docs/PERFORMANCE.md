# Performance Requirements & Benchmarks — HeyBloopie

## 1. Performance Goals & Core Targets
HeyBloopie is designed as an always-available desktop companion. It must feel instantaneous, whisper-quiet in resource consumption, and responsive without ever blocking the user interface.

| Metric | Target | Measurement Condition |
| :--- | :--- | :--- |
| **Voice End-to-Response Latency** | **< 1.0 s** | End of user utterance detected $\rightarrow$ first audio chunk played from TTS. |
| **Streaming First-Token Latency (TTFT)** | **< 400 ms** | Dispatch of prompt to Provider $\rightarrow$ first UI token render. |
| **Idle Memory Footprint (RAM)** | **~80 MB** | Application resident in system tray / background idle state. |
| **Active Memory Footprint (RAM)** | **< 200 MB** | Active planning, tool execution, and voice streaming. |
| **UI Frame Rate** | **60 FPS** | Zero dropped frames or stuttering during background file I/O operations. |

---

## 2. Desktop Framework Selection: Tauri 2.0 vs. Electron

HeyBloopie is built on **Tauri 2.0** with a Rust/Python backend core rather than Electron:

| Characteristic | Tauri 2.0 (HeyBloopie Choice) | Electron (Rejected) | Rationale |
| :--- | :--- | :--- | :--- |
| **Idle Memory (RAM)** | **~80 MB** | ~600 MB+ | HeyBloopie sits in memory all day; 600MB idle is unacceptable for non-technical users. |
| **Binary Size** | **~15–30 MB** | ~120–200 MB | Fast installation, light download, minimal disk footprint. |
| **Webview Engine** | Native Windows WebView2 (Evergreen) | Bundled Chromium instance | Leverages existing OS-level components already kept updated by Windows. |
| **Security Architecture** | Strict Rust IPC boundaries, granular capability permissions | Node.js integration inside renderer process | Tauri enforces compile-time least privilege. |

---

## 3. Asynchronous Non-Blocking File I/O
- **Zero Synchronous File Calls:** Synchronous blocking file system operations (`os.walk`, `shutil.copyfile`, synchronous reads) in the main thread are strictly forbidden.
- **Async Execution:** All disk I/O runs asynchronously using `asyncio` with threadpool executors (`aiofiles`, `asyncio.to_thread`) to ensure the UI event loop and global hotkey listener remain completely unblocked.
- **Batched I/O & Throttling:** When processing bulk operations (e.g. scanning or renaming 1,000 files), file operations are batched in chunks with progress emissions every $50\text{ ms}$ to give responsive UI feedback without saturating system queues.

---

## 4. Real-Time LLM Response Streaming
- **Token-by-Token Rendering:** Responses from AI providers are consumed as asynchronous iterators and pushed immediately over IPC to the webview UI.
- **Early Execution Planning:** When a multi-step plan is being formulated, the UI displays step skeletons in real-time as individual JSON tokens arrive rather than waiting for full completion payload generation.

---

## 5. Voice Pipeline Latency Optimization (< 1 Second)
To achieve sub-second conversational latency from voice input to voice output:
```text
[User finishes speaking]
       | (VAD: Voice Activity Detection cut-off: ~150ms)
       v
[Local/Edge STT transcription]: ~200ms
       |
       v
[Streaming LLM Intent Classification / Plan]: ~250ms (First Chunk)
       |
       v
[Streaming TTS Engine]: ~200ms
       |
       v
[First Audio Chunk Played to User]: Total Latency <= 800-950ms
```
- **Voice Activity Detection (VAD):** Employs Silero VAD for low-latency speech endpoint detection.
- **Streaming Audio Pipeline:** Audio playback starts on the first synthesized sentence buffer rather than waiting for the complete response to generate.

---

## 6. Prompt Caching & Context Efficiency
- **Directory Structure Caching:** Rather than recursing through approved folder trees on every prompt, directory trees and metadata hashes are cached in SQLite.
- **Differential Context Ingestion:** If a folder's `mtime` has not changed, cached representations are used in the context window.
- **Provider-Native Prompt Caching:** Uses provider prompt caching features (e.g., Anthropic prompt caching / Gemini system instruction caching) to avoid redundant token billing and reduce round-trip latency by up to 80%.

---

## 7. Performance Profiling (`--profile` Flag)
HeyBloopie includes a dedicated profiling mode enabled via the `--profile` command-line argument.

When active, high-resolution timestamps ($t_{\mu s}$) are recorded for every stage of the execution lifecycle:
```json
{
  "request_id": "req_8f190a",
  "total_duration_ms": 782.4,
  "breakdown": {
    "stt_transcription_ms": 184.2,
    "prompt_assembly_ms": 12.1,
    "planner_ttft_ms": 230.5,
    "planner_total_ms": 310.0,
    "policy_check_ms": 4.8,
    "tool_execution_ms": 120.3,
    "verification_ms": 15.2,
    "tts_first_chunk_ms": 195.3
  }
}
```
All profile traces are written to local debug logs and can be viewed in the developer console to detect bottlenecks and prevent performance regressions.
