
import os
import ast
import json
import subprocess
import threading
import time
import shutil
import re
from collections import deque
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    tk = None
    filedialog = None
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

app = Flask(__name__)
# Restrict CORS to local origins by default
ALLOWED_ORIGINS = ['http://127.0.0.1:7000', 'http://localhost:7000']
socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, async_mode="threading")
directory_data = {}
directory_data_lock = threading.RLock()
initial_analysis = ""
analysis_complete = False
GEMINI_ENABLED = False  # Backward-compatible flag for AI enablement
GEMINI_INITIALIZE_ON_STARTUP = False  # Whether to auto-initialize AI on startup
GEMINI_INITIALIZED = False  # Whether AI has been initialized
DEBUG_LOG_AI_RESPONSES = False  # Gate verbose AI logs

# Generic AI settings
AI_PROVIDER = 'none'  # 'none' | 'gemini' | 'ollama'
AI_MODEL = 'qwen2.5-coder'
AI_BASE_URL = 'http://localhost:11434'
AI_TIMEOUT_SEC = 120
GEMINI_CLI_PATH = None  # Optional override for gemini CLI path

# Console logging system
console_logs = deque(maxlen=1000)  # Keep last 1000 log entries

# File monitoring
file_observer = None
current_monitoring_directory = None

def log_to_console(message, level="INFO"):
    """Add a message to the console log"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "level": level,
        "message": message
    }
    console_logs.append(log_entry)
    print(f"[{level}] {message}")  # Also print to server console
    
    # Emit to WebSocket clients
    socketio.emit('console_update', log_entry)

class CodeFileHandler(FileSystemEventHandler):
    """Handle file system events for Python files"""
    
    def on_modified(self, event):
        if event.is_directory:
            return
        
        if event.src_path.endswith('.py'):
            filename = os.path.basename(event.src_path)
            log_to_console(f"File modified: {filename}", "INFO")
            
            # Re-analyze the specific file
            threading.Thread(target=self.reanalyze_file, args=(event.src_path,), daemon=True).start()
    
    def reanalyze_file(self, file_path):
        """Re-analyze a single modified file"""
        try:
            filename = os.path.basename(file_path)
            
            log_to_console(f"Re-analyzing {filename}...", "INFO")
            
            # Parse the updated file
            functions, classes, content = parse_python_file(file_path)
            
            if not content:  # Skip if file couldn't be parsed
                return
            
            # Update directory_data under lock
            with directory_data_lock:
                if 'nodes' not in directory_data or 'edges' not in directory_data:
                    directory_data['nodes'] = []
                    directory_data['edges'] = []
                # Remove old nodes for this file
                directory_data['nodes'] = [n for n in directory_data['nodes'] 
                                         if not (n.get('file') == filename or n['id'] == filename)]
                directory_data['edges'] = [e for e in directory_data['edges'] 
                                         if e['source'] != filename]
                
                # Add updated file node
                directory_data['nodes'].append({
                    "id": filename, 
                    "name": filename, 
                    "type": "file", 
                    "code": content,
                    "file_path": file_path
                })
                
                # Add updated function and class nodes
                for func in functions:
                    func_id = f"{filename}::{func['name']}"
                    directory_data['nodes'].append({
                        "id": func_id, 
                        "name": func['name'], 
                        "type": "function", 
                        "code": func['code'],
                        "returns": func.get('returns', []),
                        "called_by": [],
                        "file": filename,
                        "file_path": file_path
                    })
                    directory_data['edges'].append({"source": filename, "target": func_id})
                
                for cls in classes:
                    class_id = f"{filename}::{cls['name']}"
                    directory_data['nodes'].append({
                        "id": class_id, 
                        "name": cls['name'], 
                        "type": "class", 
                        "code": cls['code'],
                        "file": filename,
                        "file_path": file_path
                    })
                    directory_data['edges'].append({"source": filename, "target": class_id})
            
            log_to_console(f"Successfully updated {filename}", "SUCCESS")
            
            # Emit file change event to frontend
            socketio.emit('file_changed', {
                'filename': filename,
                'type': 'modified',
                'data': directory_data
            })
            
        except Exception as e:
            log_to_console(f"Error re-analyzing {filename}: {str(e)}", "ERROR")

def start_file_monitoring(directory):
    """Start monitoring a directory for file changes"""
    global file_observer, current_monitoring_directory
    
    # Stop existing observer if any
    stop_file_monitoring()
    
    try:
        current_monitoring_directory = directory
        file_observer = Observer()
        file_observer.schedule(CodeFileHandler(), directory, recursive=True)
        file_observer.start()
        log_to_console(f"Started monitoring directory: {directory}", "SUCCESS")
    except Exception as e:
        log_to_console(f"Error starting file monitor: {str(e)}", "ERROR")

def stop_file_monitoring():
    """Stop file monitoring"""
    global file_observer
    if file_observer and file_observer.is_alive():
        file_observer.stop()
        file_observer.join()
        log_to_console("Stopped file monitoring", "INFO")

CONFIG_FILE = "visualizer_config.json"
WORKSPACES_DIR = "workspaces"
GLOBAL_PREFERENCES_FILE = "global_preferences.json"
LAYOUTS_FILENAME = "layouts.json"

def load_config():
    global GEMINI_ENABLED, GEMINI_INITIALIZE_ON_STARTUP, AI_PROVIDER, AI_MODEL, AI_BASE_URL, AI_TIMEOUT_SEC, GEMINI_CLI_PATH
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                GEMINI_ENABLED = config.get('gemini_enabled', False)
                GEMINI_INITIALIZE_ON_STARTUP = config.get('gemini_initialize_on_startup', False)
                AI_PROVIDER = config.get('ai_provider', 'none')
                AI_MODEL = config.get('ai_model', 'qwen2.5-coder')
                AI_BASE_URL = config.get('ai_base_url', 'http://localhost:11434')
                AI_TIMEOUT_SEC = config.get('ai_timeout_sec', 120)
                GEMINI_CLI_PATH = config.get('gemini_cli_path')
                print(f"Loaded config: Gemini enabled={GEMINI_ENABLED}, Auto-initialize={GEMINI_INITIALIZE_ON_STARTUP}")
        else:
            print("No config file found, using default settings")
    except Exception as e:
        print(f"Error loading config: {e}, using default settings")

# Thread-safe helpers for directory_data
def get_directory_data_snapshot():
    try:
        with directory_data_lock:
            return json.loads(json.dumps(directory_data))
    except Exception:
        return {"nodes": [], "edges": []}

def set_directory_data(new_data):
    global directory_data
    with directory_data_lock:
        directory_data = new_data

def is_first_run():
    """Check if this is the first run of the program"""
    try:
        # Check if workspaces directory exists and has any workspace folders
        if os.path.exists(WORKSPACES_DIR):
            workspace_folders = [item for item in os.listdir(WORKSPACES_DIR) 
                               if os.path.isdir(os.path.join(WORKSPACES_DIR, item)) 
                               and item.startswith('workspace_')]
            if workspace_folders:
                return False
        
        # Also check config file as fallback
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                for key in config.keys():
                    if key.startswith('workspace_') and config[key].get('directory'):
                        return False
        return True
    except:
        return True

def get_workspaces():
    """Get all available workspaces from both config and workspace folders"""
    try:
        workspaces = {}
        
        # Load from main config file
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                for key, value in config.items():
                    if key.startswith('workspace_') and isinstance(value, dict) and 'directory' in value:
                        workspaces[key] = value
        
        # Also check workspace folders and load workspace.json files
        if os.path.exists(WORKSPACES_DIR):
            for item in os.listdir(WORKSPACES_DIR):
                workspace_path = os.path.join(WORKSPACES_DIR, item)
                if os.path.isdir(workspace_path) and item.startswith('workspace_'):
                    workspace_json_path = os.path.join(workspace_path, 'workspace.json')
                    if os.path.exists(workspace_json_path):
                        try:
                            with open(workspace_json_path, 'r') as f:
                                workspace_data = json.load(f)
                                # Ensure this workspace is in our main config
                                if item not in workspaces:
                                    workspaces[item] = {
                                        'name': workspace_data.get('name', item),
                                        'directory': workspace_data.get('directory', ''),
                                        'workspace_folder': workspace_path
                                    }
                                
                                # Check if explanations.json exists, if not create it
                                explanations_path = os.path.join(workspace_path, 'explanations.json')
                                if not os.path.exists(explanations_path):
                                    _create_explanations_for_workspace(item, workspace_data.get('name', item), workspace_data.get('directory', ''), workspace_path)
                        except Exception as e:
                            print(f"Error loading workspace {item}: {e}")
        
        print(f"Found workspaces: {list(workspaces.keys())}")
        return workspaces
    except Exception as e:
        print(f"Error loading workspaces: {e}")
        return {}

def get_current_workspace():
    """Get the current active workspace"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                current = config.get('current_workspace', 'workspace_1')
                print(f"Current workspace: {current}")
                return current
        print("No config file found, using default workspace_1")
        return 'workspace_1'
    except Exception as e:
        print(f"Error getting current workspace: {e}")
        return 'workspace_1'

def save_config():
    try:
        # Load existing config to preserve workspace data
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        
        # Update AI settings
        config['gemini_enabled'] = GEMINI_ENABLED
        config['gemini_initialize_on_startup'] = GEMINI_INITIALIZE_ON_STARTUP
        config['ai_provider'] = AI_PROVIDER
        config['ai_model'] = AI_MODEL
        config['ai_base_url'] = AI_BASE_URL
        config['ai_timeout_sec'] = AI_TIMEOUT_SEC
        if GEMINI_CLI_PATH:
            config['gemini_cli_path'] = GEMINI_CLI_PATH
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"Config saved: AI provider={AI_PROVIDER}, Enabled={GEMINI_ENABLED}, Auto-init={GEMINI_INITIALIZE_ON_STARTUP}")
    except Exception as e:
        print(f"Error saving config: {e}")

def create_workspace_structure():
    """Create the workspaces directory and global files if they don't exist"""
    try:
        # Create workspaces directory
        if not os.path.exists(WORKSPACES_DIR):
            os.makedirs(WORKSPACES_DIR)
            print(f"Created workspaces directory: {WORKSPACES_DIR}")
        
        # Create global preferences file
        global_prefs_path = os.path.join(WORKSPACES_DIR, GLOBAL_PREFERENCES_FILE)
        if not os.path.exists(global_prefs_path):
            global_preferences = {
                "theme": "default",
                "custom_primary": "#00ff00",
                "custom_secondary": "#121212",
                "auto_save": True,
                "auto_save_gemini": False,
                "gemini_enabled": False,
                "gemini_initialize_on_startup": False,
                "default_view": "graph",
                "show_file_extensions": True,
                "auto_refresh": False,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "last_modified": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(global_prefs_path, 'w') as f:
                json.dump(global_preferences, f, indent=2)
            print(f"Created global preferences file: {global_prefs_path}")
        
        # Remove any existing global explanations.json file (legacy)
        global_explanations_path = os.path.join(WORKSPACES_DIR, "explanations.json")
        if os.path.exists(global_explanations_path):
            os.remove(global_explanations_path)
            print(f"Removed legacy global explanations file: {global_explanations_path}")
        
        return True
    except Exception as e:
        print(f"Error creating workspace structure: {e}")
        return False

def create_workspace_files(workspace_id, workspace_name, directory_path):
    """Create individual JSON files for a workspace"""
    try:
        workspace_folder = os.path.join(WORKSPACES_DIR, workspace_id)
        if not os.path.exists(workspace_folder):
            os.makedirs(workspace_folder)
            print(f"Created workspace folder: {workspace_folder}")
        
        # Create workspace.json
        workspace_config = {
            "id": workspace_id,
            "name": workspace_name,
            "directory": directory_path,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_accessed": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_analyzed": None,
            "status": "active"
        }
        with open(os.path.join(workspace_folder, "workspace.json"), 'w') as f:
            json.dump(workspace_config, f, indent=2)
        
        # Create overview.json
        overview = {
            "project_stats": {
                "total_files": 0,
                "total_functions": 0,
                "total_classes": 0,
                "total_lines": 0
            },
            "last_analysis": None,
            "key_files": [],
            "main_modules": [],
            "complexity_score": None,
            "gemini_summary": None,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(os.path.join(workspace_folder, "overview.json"), 'w') as f:
            json.dump(overview, f, indent=2)
        
        # Create recent_changes.json
        recent_changes = {
            "file_modifications": [],
            "analysis_updates": [],
            "user_actions": [],
            "gemini_queries": [],
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(os.path.join(workspace_folder, "recent_changes.json"), 'w') as f:
            json.dump(recent_changes, f, indent=2)
        
        # Create preferences.json
        preferences = {
            "view_settings": {
                "default_layout": "coverflow",
                "show_thumbnails": True,
                "auto_expand_functions": False
            },
            "analysis_settings": {
                "auto_analyze_on_change": False,
                "include_test_files": True,
                "max_function_depth": 10
            },
            "display_settings": {
                "font_size": "medium",
                "color_scheme": "default",
                "show_line_numbers": True
            },
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_modified": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(os.path.join(workspace_folder, "preferences.json"), 'w') as f:
            json.dump(preferences, f, indent=2)
        
        # Create explanations.json (workspace-specific)
        explanations = {
            "workspace_info": {
                "description": f"Workspace '{workspace_name}' contains analysis and visualization data for the Python project at {directory_path}",
                "files_in_workspace": {
                    "workspace.json": "Main workspace configuration (name, directory path, metadata)",
                    "overview.json": "Project overview, statistics, and summary information", 
                    "recent_changes.json": "Track recent files modified, analysis updates, and user actions",
                    "preferences.json": "Workspace-specific settings and preferences",
                    "explanations.json": "This file - explanations specific to this workspace"
                }
            },
            "project_analysis": {
                "file_types": {
                    "function": "Python functions found in the codebase",
                    "class": "Python classes found in the codebase",
                    "file": "Python files in the workspace directory"
                },
                "visualization_features": {
                    "gemini_analysis": "AI-powered code analysis and insights for this project",
                    "call_graph": "Visual representation of function calls and dependencies",
                    "code_visualization": "Interactive graphs showing code structure",
                    "function_returns": "Track what each function returns",
                    "caller_tracking": "See where functions are called from"
                }
            },
            "workspace_structure": {
                "source_directory": directory_path,
                "workspace_id": workspace_id,
                "created_for": workspace_name
            },
            "usage_notes": {
                "navigation": "Use the carousel to browse through Python files in your project",
                "interaction": "Click on nodes in the graph to see code details and relationships",
                "panels": "Side panels show function callers (left) and returns/code (right)",
                "gemini": "Ask Gemini questions about your code using the input bars"
            },
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(os.path.join(workspace_folder, "explanations.json"), 'w') as f:
            json.dump(explanations, f, indent=2)
        
        print(f"Created all JSON files for workspace: {workspace_id}")
        return True
    except Exception as e:
        print(f"Error creating workspace files: {e}")
        return False

def _create_explanations_for_workspace(workspace_id, workspace_name, directory_path, workspace_folder):
    """Helper function to create explanations.json for a workspace"""
    try:
        explanations = {
            "workspace_info": {
                "description": f"Workspace '{workspace_name}' contains analysis and visualization data for the Python project at {directory_path}",
                "files_in_workspace": {
                    "workspace.json": "Main workspace configuration (name, directory path, metadata)",
                    "overview.json": "Project overview, statistics, and summary information", 
                    "recent_changes.json": "Track recent files modified, analysis updates, and user actions",
                    "preferences.json": "Workspace-specific settings and preferences",
                    "explanations.json": "This file - explanations specific to this workspace"
                }
            },
            "project_analysis": {
                "file_types": {
                    "function": "Python functions found in the codebase",
                    "class": "Python classes found in the codebase",
                    "file": "Python files in the workspace directory"
                },
                "visualization_features": {
                    "gemini_analysis": "AI-powered code analysis and insights for this project",
                    "call_graph": "Visual representation of function calls and dependencies",
                    "code_visualization": "Interactive graphs showing code structure",
                    "function_returns": "Track what each function returns",
                    "caller_tracking": "See where functions are called from"
                }
            },
            "workspace_structure": {
                "source_directory": directory_path,
                "workspace_id": workspace_id,
                "created_for": workspace_name
            },
            "usage_notes": {
                "navigation": "Use the carousel to browse through Python files in your project",
                "interaction": "Click on nodes in the graph to see code details and relationships",
                "panels": "Side panels show function callers (left) and returns/code (right)",
                "gemini": "Ask Gemini questions about your code using the input bars"
            },
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(os.path.join(workspace_folder, "explanations.json"), 'w') as f:
            json.dump(explanations, f, indent=2)
        print(f"Created explanations.json for workspace: {workspace_id}")
    except Exception as e:
        print(f"Error creating explanations for workspace {workspace_id}: {e}")

def save_workspace_config(workspace_name, directory_path):
    """Save workspace configuration to config file and create workspace structure"""
    try:
        # Create workspace structure first
        if not create_workspace_structure():
            return False
        
        # Load existing config
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        
        print(f"Current config before adding workspace: {list(config.keys())}")
        
        # Find next available workspace ID
        workspace_id = None
        for i in range(1, 100):  # Limit to 99 workspaces
            potential_id = f'workspace_{i}'
            print(f"Checking potential_id: {potential_id}, exists: {potential_id in config}")
            if potential_id not in config:
                workspace_id = potential_id
                break
        
        if not workspace_id:
            print("Error: Too many workspaces")
            return False
        
        print(f"Selected workspace ID: {workspace_id}")
        
        # Create workspace files
        if not create_workspace_files(workspace_id, workspace_name, directory_path):
            return False
        
        # Add workspace configuration to main config
        config[workspace_id] = {
            'name': workspace_name,
            'directory': directory_path,
            'workspace_folder': os.path.join(WORKSPACES_DIR, workspace_id)
        }
        
        # Set as current workspace
        config['current_workspace'] = workspace_id
        
        print(f"Config after adding workspace: {list(config.keys())}")
        
        # Save updated config
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"Workspace config saved: {workspace_name} -> {directory_path} (ID: {workspace_id})")
        return True
    except Exception as e:
        print(f"Error saving workspace config: {e}")
        return False

# Load config on startup
load_config()

def parse_python_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        tree = ast.parse(content)
        
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Extract return statements
                returns = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Return):
                        if child.value:
                            return_code = ast.get_source_segment(content, child)
                            if return_code:
                                returns.append(return_code.strip())
                        else:
                            returns.append("None")
                
                functions.append({
                    "name": node.name,
                    "code": ast.get_source_segment(content, node),
                    "returns": returns,
                    "file": os.path.basename(file_path)
                })

        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append({
                    "name": node.name,
                    "code": ast.get_source_segment(content, node),
                    "file": os.path.basename(file_path)
                })
                
        return functions, classes, content
    except (UnicodeDecodeError, TypeError, SyntaxError) as e:
        print(f"Warning: Could not parse file {file_path} due to {type(e).__name__}: {e}. Skipping.")
        return [], [], ""

def analyze_directory(directory):
    log_to_console(f"Starting analysis of directory: {directory}", "INFO")
    
    nodes = []
    edges = []
    all_functions = {}  # Store all functions for call analysis
    call_graph = {}  # Store who calls what
    
    try:
        files = []
        skip_dirs = {'.git', '.venv', 'venv', '__pycache__', '.mypy_cache', '.pytest_cache', 'node_modules'}
        for root, dirnames, filenames in os.walk(directory):
            # Filter out common large/noisy directories
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fn in filenames:
                if fn.endswith('.py'):
                    files.append(os.path.join(root, fn))
        log_to_console(f"Found {len(files)} Python files to analyze (recursive)", "INFO")
        
        # Limit the number of files to prevent performance issues
        if len(files) > 50:
            log_to_console(f"Too many files ({len(files)}). Limiting to first 50 for performance.", "WARNING")
            files = files[:50]
    except Exception as e:
        log_to_console(f"Error listing files in directory: {str(e)}", "ERROR")
        return {"nodes": [], "edges": []}
    
    # First pass: collect all functions and their details
    for i, file_path in enumerate(files):
        rel_name = os.path.relpath(file_path, directory).replace('\\', '/')
        log_to_console(f"Parsing file {i+1}/{len(files)}: {rel_name}", "INFO")
        
        try:
            functions, classes, content = parse_python_file(file_path)
            
            # Skip files that couldn't be parsed (empty content)
            if not content:
                log_to_console(f"Skipping {rel_name} - could not parse", "WARNING")
                continue
            
            for func in functions:
                func_id = f"{rel_name}::{func['name']}"
                all_functions[func_id] = func
                all_functions[func_id]['file'] = rel_name
                all_functions[func_id]['called_by'] = []
        except Exception as e:
            log_to_console(f"Error parsing {rel_name}: {str(e)}", "ERROR")
            continue
    
    # Second pass: analyze function calls (optimized)
    log_to_console(f"Analyzing function calls in {len(files)} files...", "INFO")
    for i, file_path in enumerate(files):
        rel_name = os.path.relpath(file_path, directory).replace('\\', '/')
        log_to_console(f"Analyzing calls in file {i+1}/{len(files)}: {rel_name}", "INFO")
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
            tree = ast.parse(content)
            
            # Build a mapping of line numbers to function definitions for efficiency
            func_line_map = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_line_map[node.lineno] = node.name
            
            # Find all function calls in this file
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = None
                    if hasattr(node.func, 'id'):  # Direct function call
                        func_name = node.func.id
                    elif hasattr(node.func, 'attr'):  # Method call
                        func_name = node.func.attr
                    
                    if func_name:
                        # Check if this function exists in our analysis
                        for func_id, func_data in all_functions.items():
                            if func_data['name'] == func_name:
                                # Find which function contains this call using line numbers
                                current_func = None
                                call_line = node.lineno
                                
                                # Find the function that contains this call
                                best_match_line = 0
                                for func_line, func_name_def in func_line_map.items():
                                    if func_line <= call_line and func_line > best_match_line:
                                        current_func = func_name_def
                                        best_match_line = func_line
                                
                                if current_func:
                                    caller_id = f"{rel_name}::{current_func}"
                                    if caller_id in all_functions:
                                        if caller_id not in all_functions[func_id]['called_by']:
                                            all_functions[func_id]['called_by'].append(caller_id)
        except Exception as e:
            log_to_console(f"Error analyzing calls in {rel_name}: {str(e)}", "WARNING")
            continue
    
    # Build nodes and edges
    log_to_console(f"Building graph nodes and edges...", "INFO")
    for i, file_path in enumerate(files):
        rel_name = os.path.relpath(file_path, directory).replace('\\', '/')
        log_to_console(f"Building nodes for file {i+1}/{len(files)}: {rel_name}", "INFO")
        file_id = rel_name
        functions, classes, content = parse_python_file(file_path)
        
        if not content:
            continue
        
        nodes.append({"id": file_id, "name": rel_name, "type": "file", "code": content, "file_path": file_path})
        
        for func in functions:
            func_id = f"{rel_name}::{func['name']}"
            func_data = all_functions.get(func_id, func)
            nodes.append({
                "id": func_id, 
                "name": func['name'], 
                "type": "function", 
                "code": func['code'],
                "returns": func_data.get('returns', []),
                "called_by": func_data.get('called_by', []),
                "file": rel_name,
                "file_path": file_path
            })
            edges.append({"source": file_id, "target": func_id})
            
        for cls in classes:
            class_id = f"{rel_name}::{cls['name']}"
            nodes.append({
                "id": class_id, 
                "name": cls['name'], 
                "type": "class", 
                "code": cls['code'],
                "file": rel_name,
                "file_path": file_path
            })
            edges.append({"source": file_id, "target": class_id})

    return {"nodes": nodes, "edges": edges}

def parse_gemini_commands(gemini_response_text):
    commands = []
    try:
        # Extract ```file_create ... ``` blocks
        create_blocks = re.findall(r"```file_create\s*\n([\s\S]*?)```", gemini_response_text)
        for block in create_blocks:
            path_match = re.search(r"(?m)^path:\s*(.+)\s*$", block)
            if not path_match:
                continue
            path = path_match.group(1).strip()
            content_match = re.search(r"(?ms)^content:\s*\n(.*)\Z", block)
            content = content_match.group(1) if content_match else ""
            commands.append({'type': 'create_file', 'path': path, 'content': content})

        # Extract ```file_modify ... ``` blocks
        modify_blocks = re.findall(r"```file_modify\s*\n([\s\S]*?)```", gemini_response_text)
        for block in modify_blocks:
            path_match = re.search(r"(?m)^path:\s*(.+)\s*$", block)
            if not path_match:
                continue
            path = path_match.group(1).strip()
            find_match = re.search(r"(?ms)^find:\s*\n(.*?)\n^replace:\s*\n", block)
            replace_match = re.search(r"(?ms)^replace:\s*\n(.*)\Z", block)
            find_str = find_match.group(1) if find_match else ""
            replace_str = replace_match.group(1) if replace_match else ""
            commands.append({'type': 'modify_file', 'path': path, 'find': find_str, 'replace': replace_str})
    except Exception as e:
        log_to_console(f"Error parsing AI commands: {str(e)}", "WARNING")
    return commands

def execute_commands(commands, base_directory):
    results = []
    for cmd in commands:
        try:
            full_path = os.path.join(base_directory, cmd['path'])
            
            if cmd['type'] == 'create_file':
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(cmd['content'])
                log_to_console(f"Created file: {cmd['path']}", "SUCCESS")
                results.append(f"Created file: {cmd['path']}")
                
            elif cmd['type'] == 'modify_file':
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if cmd['find'] not in content:
                    log_to_console(f"Modification failed for {cmd['path']}: 'find' string not found.", "WARNING")
                    results.append(f"Modification failed for {cmd['path']}: 'find' string not found.")
                    continue
                    
                new_content = content.replace(cmd['find'], cmd['replace'], 1) # Replace only first occurrence
                
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                log_to_console(f"Modified file: {cmd['path']}", "SUCCESS")
                results.append(f"Modified file: {cmd['path']}")
                
        except Exception as e:
            log_to_console(f"Error executing command {cmd['type']} for {cmd.get('path', 'unknown')}: {str(e)}", "ERROR")
            results.append(f"Error executing command {cmd['type']} for {cmd.get('path', 'unknown')}: {str(e)}")
            
    return results

def perform_ai_analysis():
    global initial_analysis, analysis_complete
    
    # Check for cached overview first
    current_workspace = get_current_workspace()
    workspace_folder = os.path.join(WORKSPACES_DIR, current_workspace)
    overview_path = os.path.join(workspace_folder, 'overview.json')
    
    try:
        if os.path.exists(overview_path):
            with open(overview_path, 'r', encoding='utf-8') as f:
                overview_data = json.load(f)
                cached_summary = overview_data.get('gemini_summary')
                last_analysis = overview_data.get('last_analysis')
                
                # Only skip analysis if we have a cached summary AND last_analysis is not null
                if cached_summary and last_analysis is not None:
                    log_to_console("Loading cached AI analysis...", "INFO")
                    initial_analysis = cached_summary
                    analysis_complete = True
                    log_to_console("Cached analysis loaded successfully", "SUCCESS")
                    return
                else:
                    log_to_console("No valid cached analysis found - will run new analysis", "INFO")
    except Exception as e:
        log_to_console(f"Error loading cached analysis: {str(e)}", "ERROR")
    
    # Run new analysis if no cache found
    try:
        log_to_console("Initializing AI analysis...", "INFO")
        
        all_code = ""
        file_count = 0
        snapshot = get_directory_data_snapshot()
        for node in snapshot.get('nodes', []):
            if node['type'] == 'file':
                try:
                    # Ensure the code is properly encoded and clean
                    code_content = node.get('code', '')
                    if code_content:
                        # Remove any problematic characters and ensure UTF-8
                        clean_code = code_content.encode('utf-8', errors='replace').decode('utf-8')
                        all_code += f"\n\n--- {node['name']} ---\n{clean_code}"
                        file_count += 1
                except Exception as e:
                    log_to_console(f"Warning: Skipping file {node.get('name', 'unknown')} due to encoding issue: {str(e)}", "WARNING")
                    continue
        
        log_to_console(f"Processing {file_count} Python files...", "INFO")
        
        analysis_prompt = "Analyze this codebase and provide a high-level overview. Focus on:\n1. Main purpose and functionality\n2. Key components and their relationships\n3. Architecture patterns used\n4. Potential areas of interest or complexity\n\nDo not change anything, just analyze and explain."
        
        response_text = None
        if AI_PROVIDER == 'ollama':
            try:
                import requests
                log_to_console(f"Calling Ollama at {AI_BASE_URL} model={AI_MODEL}", "INFO")
                payload = {"model": AI_MODEL, "prompt": analysis_prompt + "\n\n" + all_code, "stream": False}
                r = requests.post(f"{AI_BASE_URL}/api/generate", json=payload, timeout=AI_TIMEOUT_SEC)
                r.raise_for_status()
                data = r.json()
                response_text = data.get('response', '')
            except Exception as e:
                log_to_console(f"Ollama request failed: {str(e)}", "ERROR")
        elif AI_PROVIDER == 'gemini':
            try:
                command = [GEMINI_CLI_PATH or "gemini", "-p", "-"]
                result = subprocess.run(
                    command,
                    input=analysis_prompt + "\n\n" + all_code,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    check=True,
                    timeout=AI_TIMEOUT_SEC
                )
                response_text = result.stdout
            except Exception as e:
                log_to_console(f"Gemini CLI failed: {str(e)}", "ERROR")
        else:
            log_to_console("AI provider is 'none'; skipping analysis.", "INFO")
            response_text = "AI analysis disabled."

        if response_text is None:
            response_text = "Initial analysis could not be completed."

        log_to_console("Caching analysis results...", "INFO")
        initial_analysis = response_text
        analysis_complete = True
        
        # Save analysis to overview.json
        save_gemini_overview(initial_analysis)
        
        log_to_console("Analysis cached and ready for user queries", "SUCCESS")
        
    except Exception as e:
        log_to_console(f"Error during AI analysis: {str(e)}", "ERROR")
        initial_analysis = "Initial analysis could not be completed."
        analysis_complete = True

def save_gemini_overview(analysis_text):
    """Save Gemini analysis to the current workspace's overview.json"""
    try:
        current_workspace = get_current_workspace()
        workspace_folder = os.path.join(WORKSPACES_DIR, current_workspace)
        overview_path = os.path.join(workspace_folder, 'overview.json')
        
        # Ensure the workspace folder exists
        os.makedirs(workspace_folder, exist_ok=True)
        
        # Load existing overview or create new one
        overview_data = {}
        if os.path.exists(overview_path):
            with open(overview_path, 'r', encoding='utf-8') as f:
                overview_data = json.load(f)
        
        # Update with Gemini analysis and project stats
        snapshot = get_directory_data_snapshot()
        file_count = len([n for n in snapshot.get('nodes', []) if n['type'] == 'file'])
        function_count = len([n for n in snapshot.get('nodes', []) if n['type'] == 'function'])
        class_count = len([n for n in snapshot.get('nodes', []) if n['type'] == 'class'])
        
        overview_data.update({
            'project_stats': {
                'total_files': file_count,
                'total_functions': function_count,
                'total_classes': class_count,
                'total_lines': sum(len(n.get('code', '').split('\n')) for n in snapshot.get('nodes', []) if n['type'] == 'file')
            },
            'last_analysis': time.strftime("%Y-%m-%d %H:%M:%S"),
            'gemini_summary': analysis_text,
            'last_updated': time.strftime("%Y-%m-%d %H:%M:%S")
        })
        
        # Save updated overview
        with open(overview_path, 'w', encoding='utf-8') as f:
            json.dump(overview_data, f, indent=2, ensure_ascii=False)
        
        log_to_console(f"Overview saved to {overview_path}", "SUCCESS")
        
    except Exception as e:
        log_to_console(f"Error saving overview: {str(e)}", "ERROR")

def select_directory_and_analyze():
    print("=== select_directory_and_analyze() called ===")
    if tk is None or filedialog is None:
        print("GUI not available in this environment.")
        return False
    root = tk.Tk()
    root.withdraw()
    directory_path = filedialog.askdirectory(title="Select a folder with Python scripts")
    
    if not directory_path:
        print("No directory selected. Exiting.")
        return False
        
    set_directory_data(analyze_directory(directory_path))
    print(f"Analyzed directory: {directory_path}")
    print(f"Found {len(directory_data['nodes'])} nodes and {len(directory_data['edges'])} edges.")
    
    # Start AI analysis in a separate thread (only if enabled and auto-initialize is on)
    if GEMINI_ENABLED and GEMINI_INITIALIZE_ON_STARTUP and AI_PROVIDER != 'none':
        analysis_thread = threading.Thread(target=perform_ai_analysis, daemon=True)
        analysis_thread.start()
        print("AI analysis started in background thread. Web server will start immediately.")
    else:
        print("AI analysis disabled or not auto-initializing. Web server starting immediately.")
    
    return True

@app.route('/')
def index():
    if is_first_run():
        return render_template_string(open('first_run.html', 'r', encoding='utf-8').read())
    else:
        # Load current workspace data if not already loaded
        with directory_data_lock:
            is_loaded = bool(directory_data)
        if not is_loaded:
            try:
                current_workspace = get_current_workspace()
                workspaces = get_workspaces()
                log_to_console(f"Loading workspace: {current_workspace}", "INFO")
                
                if current_workspace and current_workspace in workspaces:
                    workspace_dir = workspaces[current_workspace]['directory']
                    log_to_console(f"Analyzing directory: {workspace_dir}", "INFO")
                    
                    # Check if directory exists
                    if not os.path.exists(workspace_dir):
                        log_to_console(f"Workspace directory does not exist: {workspace_dir}", "ERROR")
                        set_directory_data({"nodes": [], "edges": []})
                    else:
                        analyzed = analyze_directory(workspace_dir)
                        set_directory_data(analyzed)
                        log_to_console(f"Analysis complete. Found {len(analyzed['nodes'])} nodes and {len(analyzed['edges'])} edges.", "INFO")
                        
                        # Start file monitoring
                        start_file_monitoring(workspace_dir)
                else:
                    log_to_console(f"No valid workspace found. Current: {current_workspace}, Available: {list(workspaces.keys())}", "WARNING")
                    set_directory_data({"nodes": [], "edges": []})
            except Exception as e:
                log_to_console(f"Error loading workspace: {str(e)}", "ERROR")
                set_directory_data({"nodes": [], "edges": []})
        
        return render_template_string(open('index.html', 'r', encoding='utf-8').read())

@app.route('/styles.css')
def styles():
    return send_from_directory('.', 'styles.css')

@app.route('/data')
def data():
    return jsonify(get_directory_data_snapshot())

@app.route('/initial-analysis')
def get_initial_analysis():
    if not GEMINI_ENABLED or AI_PROVIDER == 'none':
        return jsonify({
            'analysis': 'AI analysis is disabled.',
            'complete': True
        })
    return jsonify({
        'analysis': initial_analysis,
        'complete': analysis_complete
    })

@app.route('/settings')
def get_settings():
    # Load theme settings from global preferences
    theme_settings = {
        'theme': 'default',
        'custom_primary': '#00ff00',
        'custom_secondary': '#121212'
    }
    
    try:
        global_prefs_path = os.path.join(WORKSPACES_DIR, GLOBAL_PREFERENCES_FILE)
        if os.path.exists(global_prefs_path):
            with open(global_prefs_path, 'r') as f:
                global_prefs = json.load(f)
                theme_settings = {
                    'theme': global_prefs.get('theme', 'default'),
                    'custom_primary': global_prefs.get('custom_primary', '#00ff00'),
                    'custom_secondary': global_prefs.get('custom_secondary', '#121212'),
                    'auto_save_gemini': global_prefs.get('auto_save_gemini', False)
                }
                # Also load gemini settings from global prefs
                global GEMINI_ENABLED, GEMINI_INITIALIZE_ON_STARTUP, AI_PROVIDER, AI_MODEL, AI_BASE_URL, AI_TIMEOUT_SEC, GEMINI_CLI_PATH
                GEMINI_ENABLED = global_prefs.get('gemini_enabled', False)
                GEMINI_INITIALIZE_ON_STARTUP = global_prefs.get('gemini_initialize_on_startup', False)
                AI_PROVIDER = global_prefs.get('ai_provider', AI_PROVIDER)
                AI_MODEL = global_prefs.get('ai_model', AI_MODEL)
                AI_BASE_URL = global_prefs.get('ai_base_url', AI_BASE_URL)
                AI_TIMEOUT_SEC = global_prefs.get('ai_timeout_sec', AI_TIMEOUT_SEC)
                GEMINI_CLI_PATH = global_prefs.get('gemini_cli_path', GEMINI_CLI_PATH)
                global DEBUG_LOG_AI_RESPONSES
                DEBUG_LOG_AI_RESPONSES = global_prefs.get('debug_log_ai', False)
    except Exception as e:
        print(f"Error loading global preferences: {e}")
    
    # Try to enumerate local Ollama models if provider is ollama
    ollama_models = []
    try:
        if AI_PROVIDER == 'ollama':
            ollama_models = _list_ollama_models(AI_BASE_URL, AI_TIMEOUT_SEC)
    except Exception as e:
        print(f"Failed to list Ollama models: {e}")

    return jsonify({
        'gemini_enabled': GEMINI_ENABLED,
        'gemini_initialize_on_startup': GEMINI_INITIALIZE_ON_STARTUP,
        'gemini_initialized': GEMINI_INITIALIZED,
        'ai_provider': AI_PROVIDER,
        'ai_model': AI_MODEL,
        'ollama_models': ollama_models,
        'ai_base_url': AI_BASE_URL,
        'ai_timeout_sec': AI_TIMEOUT_SEC,
        'debug_log_ai': DEBUG_LOG_AI_RESPONSES,
        **theme_settings
    })

@app.route('/settings', methods=['POST'])
def update_settings():
    global GEMINI_ENABLED, GEMINI_INITIALIZE_ON_STARTUP, AI_PROVIDER, AI_MODEL, AI_BASE_URL, AI_TIMEOUT_SEC, GEMINI_CLI_PATH
    data = request.json
    GEMINI_ENABLED = data.get('gemini_enabled', False)
    GEMINI_INITIALIZE_ON_STARTUP = data.get('gemini_initialize_on_startup', False)
    AI_PROVIDER = data.get('ai_provider', AI_PROVIDER)
    AI_MODEL = data.get('ai_model', AI_MODEL)
    AI_BASE_URL = data.get('ai_base_url', AI_BASE_URL)
    AI_TIMEOUT_SEC = data.get('ai_timeout_sec', AI_TIMEOUT_SEC)
    GEMINI_CLI_PATH = data.get('gemini_cli_path', GEMINI_CLI_PATH)
    
    # Save all settings to global preferences
    try:
        # Ensure workspaces directory exists
        if not os.path.exists(WORKSPACES_DIR):
            os.makedirs(WORKSPACES_DIR)
        
        global_prefs_path = os.path.join(WORKSPACES_DIR, GLOBAL_PREFERENCES_FILE)
        
        # Load existing global preferences
        global_prefs = {}
        if os.path.exists(global_prefs_path):
            with open(global_prefs_path, 'r') as f:
                global_prefs = json.load(f)
        
        # Update all settings
        global_prefs.update({
            'gemini_enabled': GEMINI_ENABLED,
            'gemini_initialize_on_startup': GEMINI_INITIALIZE_ON_STARTUP,
            'ai_provider': AI_PROVIDER,
            'ai_model': AI_MODEL,
            'ai_base_url': AI_BASE_URL,
            'ai_timeout_sec': AI_TIMEOUT_SEC,
            'gemini_cli_path': GEMINI_CLI_PATH,
            'theme': data.get('theme', 'default'),
            'custom_primary': data.get('custom_primary', '#00ff00'),
            'custom_secondary': data.get('custom_secondary', '#121212'),
            'auto_save_gemini': data.get('auto_save_gemini', False),
            'debug_log_ai': data.get('debug_log_ai', False),
            'last_modified': time.strftime("%Y-%m-%d %H:%M:%S")
        })
        
        # Save updated global preferences
        with open(global_prefs_path, 'w') as f:
            json.dump(global_prefs, f, indent=2)
        
        print(f"Global settings saved: Gemini enabled={GEMINI_ENABLED}, Theme={global_prefs['theme']}")
        
        # Also update the old config file for backward compatibility
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        
        config['gemini_enabled'] = GEMINI_ENABLED
        config['gemini_initialize_on_startup'] = GEMINI_INITIALIZE_ON_STARTUP
        config['ai_provider'] = AI_PROVIDER
        config['ai_model'] = AI_MODEL
        config['ai_base_url'] = AI_BASE_URL
        config['ai_timeout_sec'] = AI_TIMEOUT_SEC
        if GEMINI_CLI_PATH:
            config['gemini_cli_path'] = GEMINI_CLI_PATH
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
            
    except Exception as e:
        print(f"Error saving settings: {e}")
        return jsonify({'success': False, 'error': str(e)})
    
    # Return updated settings including any discovered models
    extra = {}
    try:
        if AI_PROVIDER == 'ollama':
            extra['ollama_models'] = _list_ollama_models(AI_BASE_URL, AI_TIMEOUT_SEC)
    except Exception as e:
        print(f"Failed to list Ollama models: {e}")

    return jsonify({'success': True, **extra})


def _list_ollama_models(base_url: str, timeout_sec: int):
    try:
        import requests
        resp = requests.get(f"{base_url}/api/tags", timeout=timeout_sec)
        if resp.ok:
            data = resp.json()
            if isinstance(data, dict) and 'models' in data:
                return [m.get('name') for m in data.get('models', []) if m.get('name')]
    except Exception as e:
        print(f"_list_ollama_models error: {e}")
    return []


@app.route('/ai/models')
def list_ai_models():
    """Provider-agnostic model listing endpoint used by the settings UI."""
    provider = request.args.get('provider', AI_PROVIDER)
    base_url = request.args.get('base_url', AI_BASE_URL)
    models = []
    try:
        if provider == 'ollama':
            models = _list_ollama_models(base_url, AI_TIMEOUT_SEC)
        elif provider == 'gemini':
            # Gemini CLI doesn't easily expose models without auth; defer to manual entry later
            models = []
    except Exception as e:
        print(f"/ai/models error: {e}")
    return jsonify({'provider': provider, 'models': models})

@app.route('/save-layout', methods=['POST'])
def save_layout():
    """Persist front-end node positions per file id."""
    try:
        data = request.json or {}
        file_id = data.get('file_id')  # e.g., relative file name id used in nodes
        positions = data.get('positions')  # [{id, x, y}]
        if not file_id or not isinstance(positions, list):
            return jsonify({'success': False, 'error': 'Invalid payload'}), 400

        layouts = _read_layouts()
        layouts[file_id] = positions
        if not _write_layouts(layouts):
            return jsonify({'success': False, 'error': 'Failed to write layouts'}), 500
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/load-layout', methods=['GET'])
def load_layout():
    """Return saved positions for a given file id if any."""
    try:
        file_id = request.args.get('file_id')
        if not file_id:
            return jsonify({'success': False, 'error': 'file_id required'}), 400
        layouts = _read_layouts()
        return jsonify({'success': True, 'positions': layouts.get(file_id, [])})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/initialize-gemini', methods=['POST'])
def initialize_gemini():
    global GEMINI_INITIALIZED
    if not GEMINI_ENABLED or AI_PROVIDER == 'none':
        return jsonify({'error': 'AI must be enabled first'}), 400
    
    if not GEMINI_INITIALIZED:
        analysis_thread = threading.Thread(target=perform_ai_analysis, daemon=True)
        analysis_thread.start()
        GEMINI_INITIALIZED = True
        return jsonify({'success': True, 'message': 'AI analysis started'})
    else:
        return jsonify({'success': True, 'message': 'AI already initialized'})

@app.route('/first-run')
def first_run_page():
    return render_template_string(open('first_run.html', 'r', encoding='utf-8').read())

@app.route('/check-first-run')
def check_first_run():
    return jsonify({'is_first_run': is_first_run()})

@app.route('/workspaces')
def get_workspaces_endpoint():
    workspaces = get_workspaces()
    current_workspace = get_current_workspace()
    print(f"API /workspaces called - Found {len(workspaces)} workspaces, current: {current_workspace}")
    return jsonify({
        'workspaces': workspaces,
        'current_workspace': current_workspace
    })

@app.route('/switch-workspace', methods=['POST'])
def switch_workspace():
    try:
        data = request.json
        workspace_id = data.get('workspace_id')
        
        if not workspace_id:
            return jsonify({'success': False, 'error': 'No workspace ID provided'})
        
        workspaces = get_workspaces()
        if workspace_id not in workspaces:
            return jsonify({'success': False, 'error': 'Workspace not found'})
        
        # Update current workspace in config
        try:
            config = {}
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
            
            config['current_workspace'] = workspace_id
            
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Analyze the new workspace directory
            workspace_dir = workspaces[workspace_id]['directory']
            analyzed = analyze_directory(workspace_dir)
            set_directory_data(analyzed)
            # Reset AI state so UI can re-init analysis if needed
            global GEMINI_INITIALIZED
            GEMINI_INITIALIZED = False
            print(f"Switched to workspace: {workspace_id} -> {workspace_dir}")
            print(f"Found {len(analyzed['nodes'])} nodes and {len(analyzed['edges'])} edges.")
            
            # Start file monitoring for the new workspace
            start_file_monitoring(workspace_dir)
            
            return jsonify({'success': True, 'message': f'Switched to {workspaces[workspace_id]["name"]}'})
            
        except Exception as e:
            return jsonify({'success': False, 'error': f'Failed to switch workspace: {str(e)}'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/remove-workspace', methods=['POST'])
def remove_workspace():
    try:
        data = request.json
        workspace_id = data.get('workspace_id')
        
        if not workspace_id:
            return jsonify({'success': False, 'error': 'No workspace ID provided'})
        
        if workspace_id == 'workspace_1':
            return jsonify({'success': False, 'error': 'Cannot remove the primary workspace'})
        
        workspaces = get_workspaces()
        if workspace_id not in workspaces:
            return jsonify({'success': False, 'error': 'Workspace not found'})
        
        workspace_name = workspaces[workspace_id]['name']
        
        # Remove workspace folder and its contents
        workspace_folder = os.path.join(WORKSPACES_DIR, workspace_id)
        if os.path.exists(workspace_folder):
            shutil.rmtree(workspace_folder)
            print(f"Removed workspace folder: {workspace_folder}")
        
        # Load current config and remove workspace entry
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        
        if workspace_id in config:
            del config[workspace_id]
        
        # If this was the current workspace, switch to workspace_1
        current_workspace = config.get('current_workspace')
        if current_workspace == workspace_id:
            config['current_workspace'] = 'workspace_1'
            
            # Reload data for workspace_1
            remaining_workspaces = get_workspaces()
            if 'workspace_1' in remaining_workspaces:
                workspace_dir = remaining_workspaces['workspace_1']['directory']
                set_directory_data(analyze_directory(workspace_dir))
                print(f"Switched to default workspace: workspace_1 -> {workspace_dir}")
        
        # Save updated config
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"Removed workspace: {workspace_id} ({workspace_name})")
        return jsonify({'success': True, 'message': f'Removed workspace "{workspace_name}"'})
        
    except Exception as e:
        print(f"Error removing workspace: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/validate-directory', methods=['POST'])
def validate_directory():
    try:
        print("Validate directory endpoint called")
        data = request.json
        print(f"Received data: {data}")
        directory_path = data.get('directory_path', '')
        print(f"Directory path: {directory_path}")
        
        if not directory_path:
            print("No directory path provided")
            return jsonify({'success': False, 'error': 'No directory path provided'})
        
        # Check if directory exists
        if not os.path.exists(directory_path):
            print(f"Directory does not exist: {directory_path}")
            return jsonify({'success': False, 'error': 'Directory does not exist'})
        
        # Check if it's actually a directory
        if not os.path.isdir(directory_path):
            print(f"Path is not a directory: {directory_path}")
            return jsonify({'success': False, 'error': 'Path is not a directory'})
        
        # Check if it contains Python files
        python_files = [f for f in os.listdir(directory_path) if f.endswith('.py')]
        print(f"Found Python files: {python_files}")
        if not python_files:
            print("No Python files found")
            return jsonify({'success': False, 'error': 'No Python files found in directory'})
        
        print(f"Validation successful, found {len(python_files)} Python files")
        return jsonify({'success': True, 'message': f'Found {len(python_files)} Python files'})
        
    except Exception as e:
        print(f"Error in validate_directory: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/validate-parent-directory', methods=['POST'])
def validate_parent_directory():
    """Validate a parent directory for creating new projects"""
    try:
        data = request.json
        directory_path = data.get('directory_path')
        
        if not directory_path:
            return jsonify({'success': False, 'error': 'No directory path provided'})
        
        print(f"Validating parent directory: {directory_path}")
        
        # Check if directory exists
        if not os.path.exists(directory_path):
            print("Parent directory does not exist")
            return jsonify({'success': False, 'error': 'Directory does not exist'})
        
        # Check if it's actually a directory
        if not os.path.isdir(directory_path):
            print("Path is not a directory")
            return jsonify({'success': False, 'error': 'Path is not a directory'})
        
        # Check if we have write permissions
        if not os.access(directory_path, os.W_OK):
            print("No write permissions for directory")
            return jsonify({'success': False, 'error': 'No write permissions for this directory'})
        
        print(f"Parent directory validation successful")
        return jsonify({'success': True, 'message': 'Directory is valid for creating new projects'})
        
    except Exception as e:
        print(f"Error in validate_parent_directory: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/browse-directory', methods=['POST'])
def browse_directory():
    """Open a native folder picker and return the selected directory path."""
    try:
        # Prefer a Windows-native dialog via PowerShell to avoid Tk threading issues
        if os.name == 'nt':
            try:
                ps_cmd = [
                    'powershell', '-NoProfile', '-STA', '-Command',
                    "[void][reflection.assembly]::LoadWithPartialName('System.Windows.Forms');"
                    "$fbd = New-Object System.Windows.Forms.FolderBrowserDialog;"
                    "$fbd.Description='Select a folder';"
                    "if($fbd.ShowDialog() -eq 'OK'){ Write-Output $fbd.SelectedPath }"
                ]
                result = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=120)
                path = (result.stdout or '').strip()
                if path:
                    return jsonify({'success': True, 'directory_path': path})
            except Exception as e:
                print(f"PowerShell folder dialog failed: {e}")

        # Fallback to Tkinter if available
        if tk is None or filedialog is None:
            return jsonify({'success': False, 'error': 'GUI not available in this environment'})
        root = tk.Tk()
        root.withdraw()
        selected = filedialog.askdirectory(title="Select a folder")
        try:
            root.destroy()
        except Exception:
            pass
        if not selected:
            return jsonify({'success': False, 'error': 'No directory selected'})
        return jsonify({'success': True, 'directory_path': selected})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/save-workspace', methods=['POST'])
def save_workspace():
    data = request.json
    workspace_name = data.get('workspace_name')
    directory_path = data.get('directory_path')
    
    if not workspace_name or not directory_path:
        return jsonify({'success': False, 'error': 'Missing workspace name or directory path'})
    
    if save_workspace_config(workspace_name, directory_path):
        # Analyze the directory and start the main app
        analyzed = analyze_directory(directory_path)
        set_directory_data(analyzed)
        print(f"Analyzed directory: {directory_path}")
        print(f"Found {len(analyzed['nodes'])} nodes and {len(analyzed['edges'])} edges.")
        
        # Start file monitoring
        start_file_monitoring(directory_path)
        
        # Start AI analysis if enabled and auto-initialize is on
        if GEMINI_ENABLED and GEMINI_INITIALIZE_ON_STARTUP and AI_PROVIDER != 'none':
            analysis_thread = threading.Thread(target=perform_ai_analysis, daemon=True)
            analysis_thread.start()
            print("AI analysis started in background thread.")
        
        return jsonify({'success': True, 'message': 'Workspace saved and analysis started'})
    else:
        return jsonify({'success': False, 'error': 'Failed to save workspace configuration'})

@app.route('/create-new-project', methods=['POST'])
def create_new_project():
    """Create a new project with a blank main.py file"""
    try:
        data = request.json
        parent_directory = data.get('parent_directory')
        project_name = data.get('project_name')
        
        if not parent_directory or not project_name:
            return jsonify({'success': False, 'error': 'Missing parent directory or project name'})
        
        # Validate parent directory exists
        if not os.path.exists(parent_directory) or not os.path.isdir(parent_directory):
            return jsonify({'success': False, 'error': 'Parent directory does not exist or is not a directory'})
        
        project_path = os.path.join(parent_directory, project_name)
        
        # Check if project directory already exists and is not empty
        if os.path.exists(project_path) and os.listdir(project_path):
            return jsonify({'success': False, 'error': f'Directory "{project_name}" already exists and is not empty'})
        
        # Create the project directory if it doesn't exist
        if not os.path.exists(project_path):
            os.makedirs(project_path)
            log_to_console(f"Created project directory: {project_path}", "INFO")
        
        # Create an empty main.py file
        main_py_path = os.path.join(project_path, 'main.py')
        main_py_content = '' # Empty content
        
        with open(main_py_path, 'w', encoding='utf-8') as f:
            f.write(main_py_content)
        
        log_to_console(f"Created main.py file in {project_name}", "INFO")
        
        # Create a basic README.md file
        readme_path = os.path.join(project_path, 'README.md')
        readme_content = f'''# {project_name}

A new Python project created with Python Code Visualizer.

## Getting Started

Run the main script:
```bash
python main.py
```

## Project Structure

- `main.py` - Main application entry point
- `README.md` - This file

## Development

Add your Python modules and packages to this directory and start coding!
'''
        
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(readme_content)
        
        log_to_console(f"Created README.md file in {project_name}", "INFO")
        
        # Save the new project as a workspace
        if save_workspace_config(project_name, project_path):
            # Analyze the new directory
            global directory_data
            directory_data = analyze_directory(project_path)
            log_to_console(f"Analyzed new project: {project_path}", "INFO")
            
            # Start file monitoring
            start_file_monitoring(project_path)
            
            return jsonify({
                'success': True, 
                'message': f'New project "{project_name}" created successfully with main.py',
                'project_path': project_path
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to save workspace configuration'})
            
    except Exception as e:
        log_to_console(f"Error creating new project: {str(e)}", "ERROR")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/ask-gemini', methods=['POST'])
def ask_gemini():
    data = request.json
    user_prompt = data.get('user_prompt')
    full_project_context = data.get('full_project_context', False)

    if not user_prompt:
        return jsonify({'error': 'Missing prompt'}), 400

    if full_project_context:
        # Get all code from directory_data
        all_code = ""
        snapshot = get_directory_data_snapshot()
        for node in snapshot.get('nodes', []):
            if node.get('type') == 'file':
                all_code += f"\n\n--- {node.get('name', 'unknown')} ---\n{node.get('code', '')}"
        
        full_prompt = f"""Here is an entire Python project:
{all_code}

Based on the entire project, please respond to the following request: {user_prompt}"""

    else:
        script_code = data.get('script_code')
        target_code = data.get('target_code')
        
        full_prompt = f"""Here is a Python script:

```python
{script_code}
```

"""
        if target_code:
            full_prompt += f"""Within that script, focus on this specific function/class:

```python
{target_code}
```

"""
        full_prompt += f"Now, please respond to the following request: {user_prompt}"

    try:
        response_text = None
        if AI_PROVIDER == 'ollama':
            import requests
            payload = {"model": AI_MODEL, "prompt": full_prompt, "stream": False}
            r = requests.post(f"{AI_BASE_URL}/api/generate", json=payload, timeout=AI_TIMEOUT_SEC)
            r.raise_for_status()
            response_text = r.json().get('response', '')
        elif AI_PROVIDER == 'gemini':
            command = [GEMINI_CLI_PATH or "gemini", "-p", "-"]
            result = subprocess.run(
                command,
                input=full_prompt,
                capture_output=True,
                text=True,
                check=True,
                timeout=AI_TIMEOUT_SEC
            )
            response_text = result.stdout
        else:
            return jsonify({'error': 'AI provider disabled'}), 400

        if DEBUG_LOG_AI_RESPONSES:
            log_to_console(f"Raw AI response: {response_text}", "DEBUG")
        
        # Parse commands from AI response (if using the fenced format)
        commands = parse_gemini_commands(response_text)
        
        action_results = []
        if commands:
            # Get the current workspace directory to use as base for file operations
            current_workspace_path = get_current_workspace_path()
            if current_workspace_path:
                action_results = execute_commands(commands, current_workspace_path)
            else:
                log_to_console("Cannot execute commands: No active workspace directory found.", "ERROR")
                action_results.append("Cannot execute commands: No active workspace directory found.")
        
        # Combine Gemini's original response with action results
        final_response = response_text
        if action_results:
            final_response += "\n\n--- Actions Performed ---" + "\n".join(action_results)
            
        if DEBUG_LOG_AI_RESPONSES:
            log_to_console(f"Final response sent to frontend: {final_response}", "DEBUG")
        return jsonify({'response': final_response})

    except FileNotFoundError:
        return jsonify({'error': 'AI CLI not found'}), 500
    except subprocess.CalledProcessError as e:
        error_message = f"Gemini CLI failed with exit code {e.returncode}:\n{e.stderr}"
        return jsonify({'error': error_message}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'The Gemini request timed out after 120 seconds.'}), 500
    except Exception as e:
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500


@app.route('/global-preferences')
def get_global_preferences():
    """Get global preferences that persist across workspaces"""
    try:
        global_prefs_path = os.path.join(WORKSPACES_DIR, GLOBAL_PREFERENCES_FILE)
        if os.path.exists(global_prefs_path):
            with open(global_prefs_path, 'r') as f:
                global_prefs = json.load(f)
                return jsonify({
                    'theme': global_prefs.get('theme', 'default'),
                    'custom_primary': global_prefs.get('custom_primary', '#00ff00'),
                    'custom_secondary': global_prefs.get('custom_secondary', '#121212'),
                    'auto_save_gemini': global_prefs.get('auto_save_gemini', False)
                })
    except Exception as e:
        print(f"Error loading global preferences: {e}")
    
    # Return defaults if file doesn't exist or error occurred
    return jsonify({
        'theme': 'default',
        'custom_primary': '#00ff00',
        'custom_secondary': '#121212',
        'auto_save_gemini': False
    })

@app.route('/console-output')
def get_console_output():
    """Get console log entries"""
    return jsonify({
        'logs': list(console_logs)
    })

@app.route('/save-code', methods=['POST'])
def save_code():
    """Save edited code to a file"""
    try:
        data = request.json
        file_path = data.get('file_path')
        content = data.get('content')
        modal_type = data.get('modal_type', 'main')
        
        if not file_path or content is None:
            return jsonify({'success': False, 'error': 'Missing file path or content'})
        
        # Ensure the file path is within the current workspace directory
        current_workspace = get_current_workspace_path()
        if not current_workspace:
            return jsonify({'success': False, 'error': 'No active workspace'})
        
        # Normalize and validate the file path robustly (Windows-safe)
        abs_file_path = os.path.realpath(file_path)
        abs_workspace_path = os.path.realpath(current_workspace)
        norm_file = os.path.normcase(abs_file_path)
        norm_ws = os.path.normcase(abs_workspace_path)
        common = os.path.commonpath([norm_file, norm_ws])
        if common != norm_ws:
            return jsonify({'success': False, 'error': 'File path is outside the workspace directory'})
        
        # Check if file exists
        if not os.path.exists(abs_file_path):
            return jsonify({'success': False, 'error': 'File does not exist'})
        
        # Create a backup of the original file
        backup_path = abs_file_path + '.backup'
        shutil.copy2(abs_file_path, backup_path)
        
        # Write the new content to the file
        with open(abs_file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        log_to_console(f"Code saved to {os.path.basename(abs_file_path)} from {modal_type} modal", "INFO")
        
        # Check if auto-save Gemini analysis is enabled
        global_prefs = load_global_preferences()
        if global_prefs.get('auto_save_gemini', False):
            log_to_console(f"Auto-save enabled, triggering Gemini analysis for {os.path.basename(abs_file_path)}", "INFO")
            # The file watcher will automatically detect the change and trigger re-analysis
        
        return jsonify({
            'success': True, 
            'message': f'File saved successfully',
            'backup_created': backup_path
        })
        
    except Exception as e:
        log_to_console(f"Error saving code: {str(e)}", "ERROR")
        return jsonify({'success': False, 'error': str(e)})

def get_current_workspace_path():
    """Get the path of the currently active workspace"""
    # Try to get from the current monitoring directory
    if current_monitoring_directory:
        return current_monitoring_directory
    
    # Fallback: read from our config and workspaces
    try:
        current_ws = get_current_workspace()
        workspaces = get_workspaces()
        if current_ws in workspaces:
            return workspaces[current_ws].get('directory')
    except Exception as e:
        print(f"Error getting current workspace path: {e}")
    
    return None

def get_current_workspace_meta_folder():
    """Return the workspace meta folder path (workspaces/workspace_X)."""
    try:
        current_ws = get_current_workspace()
        # Open config to get the workspace folder
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                ws = config.get(current_ws)
                if isinstance(ws, dict):
                    folder = ws.get('workspace_folder')
                    if folder and os.path.isdir(folder):
                        return folder
        # Fallback: construct default path
        default_folder = os.path.join(WORKSPACES_DIR, current_ws)
        return default_folder
    except Exception as e:
        print(f"Error getting workspace meta folder: {e}")
        return os.path.join(WORKSPACES_DIR, get_current_workspace())

def _read_layouts():
    try:
        meta_folder = get_current_workspace_meta_folder()
        os.makedirs(meta_folder, exist_ok=True)
        layouts_path = os.path.join(meta_folder, LAYOUTS_FILENAME)
        if os.path.exists(layouts_path):
            with open(layouts_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error reading layouts: {e}")
    return {}

def _write_layouts(layouts):
    try:
        meta_folder = get_current_workspace_meta_folder()
        os.makedirs(meta_folder, exist_ok=True)
        layouts_path = os.path.join(meta_folder, LAYOUTS_FILENAME)
        with open(layouts_path, 'w', encoding='utf-8') as f:
            json.dump(layouts, f, indent=2)
        return True
    except Exception as e:
        print(f"Error writing layouts: {e}")
        return False

def load_global_preferences():
    """Load global preferences from file"""
    try:
        global_prefs_path = os.path.join(WORKSPACES_DIR, GLOBAL_PREFERENCES_FILE)
        if os.path.exists(global_prefs_path):
            with open(global_prefs_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading global preferences: {e}")
    
    return {}

if __name__ == '__main__':
    print("Starting the web server. Open http://127.0.0.1:7000 in your browser.")
    try:
        socketio.run(app, debug=False, port=7000, host='127.0.0.1')
    finally:
        stop_file_monitoring()

