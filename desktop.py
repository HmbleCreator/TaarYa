"""TaarYa Desktop Launcher — wraps the web app in a native window using pywebview.

Usage:
    python desktop.py

Requirements:
    pip install pywebview

This starts the FastAPI server in a background thread and opens
the TaarYa dashboard in a native OS window (no browser needed).
Works on Windows, macOS, and Linux.
"""
import threading
import time
import sys


def start_server():
    """Start FastAPI in a background thread."""
    import uvicorn
    uvicorn.run("src.main:app", host="127.0.0.1", port=8000, log_level="warning")


def main():
    # Start server in background
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Wait briefly for server to start
    time.sleep(2)
    
    try:
        import webview
    except ImportError:
        print("pywebview not installed. Install it with:")
        print("  pip install pywebview")
        print("\nFalling back to browser mode...")
        import webbrowser
        webbrowser.open("http://127.0.0.1:8000")
        input("Press Enter to stop the server...")
        return
    
    # Create native window
    window = webview.create_window(
        title="TaarYa — Astronomy Intelligence",
        url="http://127.0.0.1:8000",
        width=1280,
        height=800,
        min_size=(800, 600),
        text_select=True,
    )
    
    webview.start(debug=False)


if __name__ == "__main__":
    main()
