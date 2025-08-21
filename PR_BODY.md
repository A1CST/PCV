## What’s new
- AI provider switch (Gemini/Ollama), Windows folder picker.
- Responsive UI + larger modals.
- Node clustering + adaptive forces; zoom-to-fit; refit on resize/slide change.
- Nodes include `file_path` for reliable inline saves.

## Why
- Reduce visual crowding, improve legibility and interaction.
- Enable local AI (Ollama) without external dependencies.

## How
- Backend:
  - Provider settings; provider-agnostic analysis; Ollama `/api/generate` calls via `requests`.
  - New `/browse-directory` using PowerShell FolderBrowserDialog (fallback to Tk).
  - Added `file_path` to all nodes; fixed `get_current_workspace_path`.
- Frontend:
  - D3 `createGraph`: clustering, adaptive forces, zoom-to-fit, ResizeObserver, slide-change refit.
  - Settings UI additions; browse buttons on first-run/add/new project.
  - Styles: responsive font/containers; larger modals; balanced card sizes.

## Test
- First-run browse works; Add/New Project browse works.
- On small/large files, graphs fit the card and remain centered after resize.
- AI: Ollama model returns analysis; Gemini works when configured.

## Follow-ups
- Recursive analysis + import/alias resolution.
- Label declutter (show-on-hover when zoomed out).
- PR overlays and metrics layers (complexity/coverage).
