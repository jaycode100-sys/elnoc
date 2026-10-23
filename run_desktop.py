"""ELNOC Desktop Launcher
Starts FastAPI with uvicorn in a background thread, opens in PyWebView.
No terminal window required.
"""
import os
import sys
import socket
import threading
import webbrowser
from pathlib import Path

def resource_path(rel):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(os.path.abspath('.'), rel)

# ensure bundled resources resolve
os.chdir(resource_path('.'))

import uvicorn
import webview

from app.main import app

def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def run_server(port):
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')

def main():
    port = get_free_port()
    t = threading.Thread(target=run_server, args=(port,), daemon=True)
    t.start()
    url = f'http://127.0.0.1:{port}/auth/desktop/splash'
    webview.create_window('ELNOC', url, width=1500, height=950, min_size=(1100, 800), resizable=True)
    webview.start()

if __name__ == '__main__':
    main()
