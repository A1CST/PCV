import json
import threading
import time
import socket
import requests
from app import app, socketio


def _find_free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    addr, port = s.getsockname()
    s.close()
    return port


def _run_server(port):
    socketio.run(app, debug=False, port=port, host='127.0.0.1', allow_unsafe_werkzeug=True)


def test_health_endpoints_startup_and_settings():
    port = _find_free_port()
    t = threading.Thread(target=_run_server, args=(port,), daemon=True)
    t.start()
    time.sleep(1.0)

    base = f"http://127.0.0.1:{port}"

    # check first-run flag endpoint
    r = requests.get(base + "/check-first-run")
    assert r.status_code == 200
    data = r.json()
    assert "is_first_run" in data

    # get settings
    r = requests.get(base + "/settings")
    assert r.status_code == 200
    settings = r.json()
    assert "ai_provider" in settings
    assert "theme" in settings

    # update settings (toggle debug flag)
    payload = {
        "gemini_enabled": False,
        "gemini_initialize_on_startup": False,
        "ai_provider": "none",
        "ai_model": "qwen2.5-coder",
        "ai_base_url": "http://localhost:11434",
        "ai_timeout_sec": 5,
        "theme": "default",
        "custom_primary": "#00ff00",
        "custom_secondary": "#121212",
        "auto_save_gemini": False,
        "debug_log_ai": False,
    }
    r = requests.post(base + "/settings", json=payload)
    assert r.status_code == 200
    assert r.json().get("success") is True

    # console output should be reachable
    r = requests.get(base + "/console-output")
    assert r.status_code == 200
    assert "logs" in r.json()

