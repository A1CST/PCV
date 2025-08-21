# Development

## Run (Windows PowerShell)
1. Create venv and install
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```
2. Start server
```
python app.py
```
3. Open in browser: http://127.0.0.1:7000

## Branch & PR
- Branch: `feature/ai-ollama-clusters-browse-resize`
- Push to fork
```
git push -u origin feature/ai-ollama-clusters-browse-resize
```
- Open PR from fork to upstream `A1CST/PCV:main`.

## Notes
- Provider settings live in `/settings`; provider must not be 'none' to run analysis.
- Folder browsing uses PowerShell on Windows; Tk fallback otherwise.
