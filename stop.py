"""
Video Separator - stop script.

Usage:
    python stop.py

Reads the PID file created by start.py and terminates only the
project-owned Flask and Node.js processes.
"""

import os
import sys
import json
import time
import signal
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PID_FILE = BASE_DIR / ".pids.json"


def banner(msg):
    print("=" * 44)
    print(msg.center(44))
    print("=" * 44)


def pid_running(pid):
    if not pid:
        return False
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True,
            )
            return str(pid) in out.stdout
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def terminate(pid):
    if not pid or not pid_running(pid):
        return False
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, text=True,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                os.kill(pid, signal.SIGTERM)
            # Give it a moment, then force if needed
            for _ in range(20):
                if not pid_running(pid):
                    break
                time.sleep(0.1)
            if pid_running(pid):
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except Exception:
                    os.kill(pid, signal.SIGKILL)
        return True
    except Exception as e:
        print(f"Failed to terminate PID {pid}: {e}")
        return False


def main():
    banner("VIDEO SEPARATOR - STOPPING")

    if not PID_FILE.exists():
        print("No PID file found. Project does not appear to be running.")
        return

    try:
        data = json.loads(PID_FILE.read_text())
    except Exception:
        print("PID file is corrupted. Removing it.")
        PID_FILE.unlink(missing_ok=True)
        return

    flask_pid = data.get("flask")
    node_pid = data.get("node")

    stopped_any = False

    if node_pid:
        if terminate(node_pid):
            print(f"Stopped Node.js (PID {node_pid}).")
            stopped_any = True
        else:
            print(f"Node.js (PID {node_pid}) was not running.")

    if flask_pid:
        if terminate(flask_pid):
            print(f"Stopped Flask (PID {flask_pid}).")
            stopped_any = True
        else:
            print(f"Flask (PID {flask_pid}) was not running.")

    # Clean up PID file
    try:
        PID_FILE.unlink()
    except Exception:
        pass

    print()
    if stopped_any:
        banner("PROJECT STOPPED SUCCESSFULLY")
    else:
        banner("NOTHING TO STOP")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStop cancelled.")