# Settings and Endpoints

## Theme and AI Settings
- GET `/settings`: returns theme and AI configuration.
- POST `/settings` body:
  - `gemini_enabled` (bool)
  - `gemini_initialize_on_startup` (bool)
  - `ai_provider` ('none'|'gemini'|'ollama')
  - `ai_model` (string)
  - `ai_base_url` (string; for Ollama)
  - `gemini_cli_path` (string; optional)
  - `theme`, `custom_primary`, `custom_secondary`, `auto_save_gemini`
  - `debug_log_ai` (bool; default false) gates verbose AI response logging

## Analysis
- GET `/initial-analysis`: cached or latest analysis text (provider-aware).
- POST `/initialize-gemini`: starts background analysis when provider != 'none'.

## Data
- GET `/data`: graph nodes/edges. Nodes now include `file_path`.

## Save Code
- POST `/save-code`: validates `file_path` within workspace; writes backup and new content.

## Folder Browsing
- POST `/browse-directory`: returns `{ success, directory_path }` using PowerShell folder dialog on Windows; Tk fallback else.

Note: In CI/headless environments, Tk is disabled; fallback returns an error JSON.
