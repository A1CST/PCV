Python Code Visualizer
An interactive, web-based tool for visualizing, analyzing, and managing your Python codebases. This application provides a dynamic graph representation of your project's structure, enabling you to see relationships between files, functions, and classes at a glance. It also includes real-time file monitoring, an AI-powered analysis engine, and integrated code editing.

Features
Interactive Code Visualization: Explore your project with a D3.js-powered force-directed graph. Navigate through files, functions, and classes to understand their structure and connections.

Real-time File Monitoring: The application automatically detects changes to your Python files and updates the visualization and analysis in real-time without requiring a page refresh.

AI-Powered Analysis (Gemini Integration): Leverage the power of the Gemini API to get intelligent, high-level overviews of your entire codebase, or ask specific questions about individual files or functions.

Multi-Workspace Management: Easily add, switch, and remove different Python projects, each with its own workspace and configuration.

Real-time Console Output: A dedicated panel displays real-time logs from the server, providing immediate feedback on analysis, file changes, and potential errors.

Inline Code Editing: Edit code directly within the application and save your changes back to the file system.

Customizable Themes: Choose from a selection of pre-defined themes or create your own custom color scheme to personalize your workspace.

Prerequisites
To run this application, you will need:

Python 3.8 or higher

pip (Python package installer)

The gemini command-line tool configured for your system.

Setting up the Gemini API:

Go to the Google Cloud Console.

Create a new project or select an existing one.

Navigate to APIs & Services > Dashboard and click Enable APIs and Services.

Search for "Gemini API" and enable it.

Go to APIs & Services > Credentials and create an API key.

Copy the API key and follow the instructions for the gemini command-line tool to configure it with the new key.

Installation & Setup
Clone or Download: Get the project files onto your local machine.

Install Dependencies: Navigate to the project's root directory in your terminal and install the required Python packages. We recommend using a virtual environment.

pip install Flask Flask-SocketIO watchdog

Run the Application: Start the Flask server by running the main Python file.

python app.py

Open in Browser: The terminal will display a message indicating the server is running. Open your web browser and navigate to the address provided (e.g., http://127.0.0.1:7000).

Usage
First Run Setup: On the first run, you will be directed to a setup page. Enter the full path to the directory containing your Python project and a name for your new workspace.

Main Visualizer: After setup, the main interface will load, displaying a graph of your codebase.

Navigate Files: Use the file navigation buttons at the top to switch between different Python files in your project.

Interact with the Graph: Click on nodes in the graph to view their source code in a pop-up modal.

Gemini Integration: Use the input bars at the bottom of the modals and the main page to ask questions about your code and get AI-powered insights.

Project Structure
app.py: The core backend Flask application. It handles routing, file analysis, and communication with the front-end.

index.html: The main front-end HTML file for the visualizer interface.

first_run.html: The HTML for the initial setup page.

styles.css: The stylesheet for the entire application, including themes and animations.

visualizer_config.json: A configuration file that stores project and user settings.

workspaces/: The directory where all workspace-specific data is stored.

Tech Stack
Backend: Python, Flask, Flask-SocketIO

File System Monitoring: watchdog

Frontend: HTML5, CSS3, JavaScript

Visualization: D3.js (for graph rendering)

UI Libraries: Swiper.js (for the carousel)

AI Integration: Google's Gemini API (via a command-line tool)

Testing
Run the test suite with pytest:

```powershell
python -m pytest -q
```

Continuous Integration
GitHub Actions workflow is included at `.github/workflows/ci.yml` and runs the test suite on Ubuntu and Windows across Python 3.11 and 3.12 on pushes and pull requests to main, develop, and feature branches.

Manual Layout Editing
- Open the visualizer and navigate to a file's slide.
- Click "Edit Layout" in the top-right of the slide to enter edit mode.
- Drag function/class nodes to reposition them around the central file node (the file node remains fixed).
- Click "Save Layout" to persist positions. Your layout is restored on reload and across sessions.
- Saved layouts are stored per workspace at `workspaces/<workspace_X>/layouts.json`.