r"""ELNOC Desktop Launcher
Starts FastAPI with uvicorn in a background thread, opens in PyWebView.
No terminal window required.

Usage:
  py run_desktop.py          # local desktop app only (127.0.0.1)
  py run_desktop.py --tunnel # desktop app + public web address via cloudflared
                               (like Telegram/WhatsApp: desktop + web URL)

When bundled with PyInstaller (--onefile), the app is unpacked into a
read-only temp folder (_MEIPASS). SQLite cannot write there, so on first
launch we seed a writable copy of data/elnoc.db into %LOCALAPPDATA%\ELNOC
and point ELNOC_DB_PATH at it. Templates/static still resolve from the bundle.

Window behavior:
  - Closing the window (X button) does NOT exit the app. The server keeps
    running and a new window opens immediately.
  - To fully exit, use Ctrl+Alt+X (AutoHotkey) or End Task in Task Manager.
  - AutoHotkey (resources/elnoc.ahk) provides global hotkeys:
      Ctrl+Alt+E  -> ELNOC command palette
      Ctrl+Alt+Q  -> Quick Log
      Ctrl+Alt+M  -> MyShift
      Ctrl+Alt+P  -> Power log
      Ctrl+Alt+A  -> AI Assistant
      Ctrl+Alt+D  -> Dashboard
      Ctrl+Alt+H  -> Handover
      Ctrl+Alt+L  -> Quick Log
      Ctrl+Alt+X  -> EXIT ELNOC completely
"""

import os
import sys
import shutil
import socket
import threading
import subprocess
import webbrowser
import ctypes
import argparse
from pathlib import Path


def resource_path(rel):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(os.path.abspath('.'), rel)


def _seed_writable_db():
    """In frozen mode, copy the bundled DB into a writable app-data folder so
    SQLite (WAL mode, schema migrations) can write to it. Returns the path."""
    if not getattr(sys, 'frozen', False):
        return None
    meipass = getattr(sys, '_MEIPASS', None)
    if not meipass:
        return None
    appdata = os.getenv('LOCALAPPDATA') or os.path.expanduser('~')
    data_dir = Path(appdata) / 'ELNOC'
    data_dir.mkdir(parents=True, exist_ok=True)
    user_db = data_dir / 'elnoc.db'
    bundled_db = Path(meipass) / 'data' / 'elnoc.db'
    # Seed on first run only; never overwrite an existing user database.
    if bundled_db.exists() and not user_db.exists():
        shutil.copy2(bundled_db, user_db)
    return str(user_db)


# Before importing the app (which loads config + database at import time),
# arrange a writable database location when bundled.
writable_db = _seed_writable_db()
if writable_db:
    os.environ.setdefault('ELNOC_DB_PATH', writable_db)

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


def run_server(port, public=False):
    host = '0.0.0.0' if public else '127.0.0.1'
    uvicorn.run(app, host=host, port=port, log_level='warning')


def start_cloudflared(local_port):
    """Start a Cloudflare quick tunnel and return (process, public_url or None)."""
    exe = resource_path('tools/cloudflared.exe')
    if not os.path.exists(exe):
        exe = 'cloudflared'
    try:
        proc = subprocess.Popen(
            [exe, 'tunnel', '--url', f'http://127.0.0.1:{local_port}'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
    except (FileNotFoundError, OSError):
        return None, None
    import time
    url = None
    deadline = time.time() + 10
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        m = __import__('re').search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
        if m:
            url = m.group(0)
            break
    return proc, url


def main():
    parser = argparse.ArgumentParser(description='ELNOC desktop launcher')
    parser.add_argument('--tunnel', action='store_true',
                        help='also open a public cloudflared web address')
    args = parser.parse_args()

    port = get_free_port()
    public = args.tunnel
    t = threading.Thread(target=run_server, args=(port, public), daemon=True)
    t.start()

    tunnel_proc = None
    public_url = None
    if public:
        tunnel_proc, public_url = start_cloudflared(port)

    # Window loop: when the user closes the ELNOC window, a new one opens
    # immediately. The server keeps running in the background thread.
    # To fully exit, use Ctrl+Alt+X (AutoHotkey) or End Task in Task Manager.
    while True:
        url = f'http://127.0.0.1:{port}/auth/desktop/splash'
        webview.create_window('ELNOC', url, width=1500, height=950,
                              min_size=(1100, 800), resizable=True)
        icon_path = resource_path('ELNOC.ico')
        try:
            if os.path.exists(icon_path):
                webview.start(icon=icon_path)
            else:
                webview.start()
        except (TypeError, NotImplementedError):
            webview.start()
        except Exception as exc:
            ctypes.windll.user32.MessageBoxW(
                0,
                "ELNOC requires the Microsoft Edge WebView2 Runtime to open its window.\n\n"
                "Download and install it from:\nhttps://aka.ms/WebView2Setup\n\n"
                "Then re-run ELNOC.",
                "ELNOC – prerequisite missing",
                0x30,  # MB_ICONWARNING
            )
            sys.exit(1)
        # Window was closed - loop back to create a new one.
        # Server thread keeps running in the background.

    # cleanup tunnel on exit (unreachable in normal loop)
    if tunnel_proc:
        tunnel_proc.terminate()


if __name__ == '__main__':
    main()