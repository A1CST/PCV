# Features

## Core
- Interactive per-file graph with file node centered and function/class leaves.
- Live file watching; re-parse and update graph on save.
- Inline code editing with safe backup and re-analysis hook.

## AI Integration
- Provider switch: `none | gemini | ollama`.
- Provider-agnostic initial analysis and Q&A endpoint.
- Settings UI for model/base URL/CLI path.

### Logging
- Optional `debug_log_ai` flag in global preferences to log raw AI responses (off by default).

## Visualization
- Semantic clustering: functions grouped by verb-like prefix (e.g., get/set/extract/process/calculate/...).
- Concentric placement: classes on inner ring; function clusters on outer ring around file node.
- Adaptive forces by node count and node degree; collision radius scales with size.
- Zoom-to-fit after layout; auto-refit on resize and slide change; label hiding when zoomed out to reduce clutter.

### Scalability & Safety
- Recursive analysis with directory skip list (`.git`, `venv`, `__pycache__`, etc.).
- Thread-safe shared state with a global lock and snapshot helpers.

## UI/UX
- Responsive `clamp()` sizing for readability on half-screen monitors.
- Larger Settings / Add Project / New Project modals.
- Browse buttons with Windows-native folder picker.


