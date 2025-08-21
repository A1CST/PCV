## [Unreleased] - feature/ai-ollama-clusters-browse-resize

### Added
- AI provider switch with Ollama support (in addition to Gemini).
- Windows-native folder picker endpoint (`POST /browse-directory`) with PowerShell dialog; Tk fallback.
- Zoom-to-fit for D3 graphs + ResizeObserver re-fit; refit on slide change.
- Semantic clustering layout to reduce node crowding (verb-based clusters around file node).
- Adaptive forces: link distance / charge / collision scale with node count + degree-aware spacing.
- Larger, responsive modals (Settings, Add Project, New Project).
- Nodes include absolute `file_path` for correct inline saving.
- Settings UI: provider, model, base URL, Gemini CLI path.

### Changed
- First-run screen and global UI use responsive `clamp()` sizing for readability on varying monitor sizes.
- Restored main card sizing balance (card width/height) while keeping text legibility improvements.
- Initial analysis is provider-agnostic (Gemini/Ollama/None).

### Fixed
- Resolved Tk “main thread is not in main loop” for browsing by using PowerShell FolderBrowserDialog on Windows.
- `get_current_workspace_path()` now resolves from config/workspaces reliably.


