"""
Video Separator - single-command launcher.

Usage:
    python start.py

Flow:
  1. Detect currently-active Conda env (any name).
  2. If none active: use existing 'video_separator' OR auto-create it.
  3. Resolve the EXACT python interpreter inside the chosen env.
  4. Verify Flask/Flask-CORS inside that python -> auto-install if missing.
  5. Verify / auto-install Node deps.
  6. Pick free ports, launch Flask + Node as detached processes.
  7. Open browser at LAN URL. Save PIDs for stop.py.
"""

import os
import sys
import json
import time
import socket
import shutil
import signal
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PID_FILE = BASE_DIR / ".pids.json"
LOG_DIR = BASE_DIR / ".logs"
LOG_DIR.mkdir(exist_ok=True)

PREFERRED_ENV_NAME = "video_separator"
REQUIRED_PY = {(3, 10), (3, 11)}
FLASK_DEFAULT_PORT = 8000
NODE_DEFAULT_PORT = 5000


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------
def banner(msg):
    print("=" * 44)
    print(msg.center(44))
    print("=" * 44)


def step(label, ok, extra=""):
    mark = "OK" if ok else "FAIL"
    line = f"{label}: {mark}"
    if extra:
        line += f" ({extra})"
    print(line)


# ---------------------------------------------------------------------------
# Conda helpers
# ---------------------------------------------------------------------------
def which_or_none(cmd):
    return shutil.which(cmd)


def check_conda():
    return which_or_none("conda") is not None


def conda_base_dir():
    """Return the absolute path of the Conda installation root."""
    conda = which_or_none("conda")
    if not conda:
        return None
    try:
        out = subprocess.run(
            [conda, "info", "--base"],
            capture_output=True, text=True, timeout=30,
        )
        lines = [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
        if lines:
            return lines[-1]
    except Exception:
        pass
    return None


def active_conda_env():
    """
    Detect the currently-active Conda env (any name).
    Returns None if none active / only base.
    """
    # 1. CONDA_DEFAULT_ENV
    name = os.environ.get("CONDA_DEFAULT_ENV")
    if name:
        base = os.path.basename(name)
        if base and base not in ("base", "root", "anaconda3", "miniconda3"):
            return base

    # 2. CONDA_PREFIX path ends with .../envs/<name>
    prefix = os.environ.get("CONDA_PREFIX", "")
    if prefix and (os.sep + "envs" + os.sep) in prefix:
        base = os.path.basename(prefix)
        if base and base not in ("base", "root"):
            return base

    # 3. sys.prefix inside envs/
    sp = sys.prefix
    if sp and (os.sep + "envs" + os.sep) in sp:
        base = os.path.basename(sp)
        if base and base not in ("base", "root"):
            return base

    return None


def conda_env_exists(name):
    conda = which_or_none("conda")
    if not conda:
        return False
    try:
        out = subprocess.run(
            [conda, "env", "list"],
            capture_output=True, text=True, timeout=90,
        )
        for line in out.stdout.splitlines():
            parts = line.split()
            if parts and parts[0] == name:
                return True
    except Exception:
        pass
    return False


def python_path_for_env(env_name):
    """
    Return the exact python interpreter path for a conda env.
    Built from `conda info --base` — no `conda run` needed.
    """
    base = conda_base_dir()
    if base:
        env_dir = Path(base) / "envs" / env_name
        if os.name == "nt":
            cand = env_dir / "python.exe"
        else:
            cand = env_dir / "bin" / "python"
        if cand.exists():
            return str(cand)
    return None


def env_python_version(python_exe):
    """Return (major, minor) for the given python executable, or None."""
    if not python_exe or not os.path.exists(python_exe):
        return None
    try:
        out = subprocess.run(
            [python_exe, "-c",
             "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture_output=True, text=True, timeout=30,
        )
        txt = (out.stdout or "").strip().splitlines()
        if txt:
            major, minor = txt[-1].split(".")
            return (int(major), int(minor))
    except Exception:
        pass
    return None


def python_has_flask(python_exe):
    """Return (ok, stderr)."""
    if not python_exe or not os.path.exists(python_exe):
        return False, "python not found"
    try:
        out = subprocess.run(
            [python_exe, "-c",
             "import flask, flask_cors; print('ok')"],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode == 0:
            return True, ""
        return False, (out.stderr or out.stdout or "").strip()[:400]
    except Exception as e:
        return False, str(e)


def pip_install_into(python_exe, requirements_file):
    """Install requirements.txt into the given python."""
    if not python_exe or not os.path.exists(python_exe):
        return False
    req = Path(requirements_file)
    if not req.exists():
        print(f"[setup] requirements file not found: {req}")
        return False
    print(f"\n[setup] Installing Python dependencies using:\n       {python_exe}")
    try:
        # Upgrade pip first (safe, quiet)
        subprocess.run(
            [python_exe, "-m", "pip", "install", "--upgrade", "pip"],
            capture_output=True, text=True, timeout=600,
        )
        result = subprocess.run(
            [python_exe, "-m", "pip", "install", "-r", str(req)],
            capture_output=True, text=True, timeout=1800,
        )
        if result.returncode != 0:
            print("[setup] pip install failed.")
            print(result.stdout[-1500:])
            print(result.stderr[-1500:])
            return False
        print("[setup] Python dependencies installed.")
        return True
    except Exception as e:
        print(f"[setup] pip install error: {e}")
        return False


def create_conda_env(name):
    conda = which_or_none("conda")
    if not conda:
        return False
    print(f"\n[setup] Creating Conda environment '{name}' with Python 3.11 ...")
    print("[setup] This may take a few minutes on first run...\n")
    try:
        result = subprocess.run(
            [conda, "create", "-n", name, "python=3.11", "-y"],
            capture_output=True, text=True, timeout=1800,
        )
        if result.returncode != 0:
            print("[setup] Conda env creation failed.")
            print(result.stdout[-1500:])
            print(result.stderr[-1500:])
            return False
        print(f"\n[setup] Conda environment '{name}' created.")
        return True
    except subprocess.TimeoutExpired:
        print("[setup] Conda env creation timed out (30 min).")
        return False
    except Exception as e:
        print(f"[setup] Conda env creation error: {e}")
        return False


def install_node_deps():
    if (BASE_DIR / "node_modules").exists():
        return True
    npm = which_or_none("npm")
    if not npm:
        return False
    print("\n[setup] Installing Node.js dependencies (npm install) ...")
    try:
        result = subprocess.run(
            [npm, "install"],
            cwd=str(BASE_DIR),
            capture_output=True, text=True, timeout=1800,
        )
        if result.returncode != 0:
            print("[setup] npm install failed.")
            print(result.stdout[-1500:])
            print(result.stderr[-1500:])
            return False
        print("[setup] Node.js dependencies installed.")
        return True
    except Exception as e:
        print(f"[setup] npm install error: {e}")
        return False


# ---------------------------------------------------------------------------
# Runtime helpers
# ---------------------------------------------------------------------------
def find_free_port(preferred):
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found near {preferred}")


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def check_node():
    return which_or_none("node") is not None, which_or_none("npm") is not None


def load_pids():
    if PID_FILE.exists():
        try:
            return json.loads(PID_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_pids(data):
    PID_FILE.write_text(json.dumps(data, indent=2))


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


def terminate_pid(pid):
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True)
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def start_flask(port, python_exe, node_port):
    log_path = LOG_DIR / "flask.log"
    env = os.environ.copy()
    env["FLASK_PORT"] = str(port)
    env["PYTHONUNBUFFERED"] = "1"
    env["LAN_IP"] = get_lan_ip()
    env["NODE_PORT_FOR_FLASK"] = str(node_port)

    creationflags = 0
    preexec_fn = None
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
    else:
        preexec_fn = os.setsid

    log = open(log_path, "ab")
    proc = subprocess.Popen(
        [python_exe, str(BASE_DIR / "app.py")],
        cwd=str(BASE_DIR),
        stdout=log, stderr=log, stdin=subprocess.DEVNULL,
        env=env,
        creationflags=creationflags,
        preexec_fn=preexec_fn,
        close_fds=(os.name != "nt"),
    )
    return proc.pid


def start_node(port, flask_port):
    log_path = LOG_DIR / "node.log"
    env = os.environ.copy()
    env["NODE_PORT"] = str(port)
    env["FLASK_TARGET"] = f"http://127.0.0.1:{flask_port}"

    creationflags = 0
    preexec_fn = None
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
    else:
        preexec_fn = os.setsid

    log = open(log_path, "ab")
    node_bin = which_or_none("node") or "node"
    proc = subprocess.Popen(
        [node_bin, str(BASE_DIR / "server.js")],
        cwd=str(BASE_DIR),
        stdout=log, stderr=log, stdin=subprocess.DEVNULL,
        env=env,
        creationflags=creationflags,
        preexec_fn=preexec_fn,
        close_fds=(os.name != "nt"),
    )
    return proc.pid


def wait_for_port(host, port, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def open_browser(url):
    try:
        if os.name == "nt":
            os.startfile(url)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
    except Exception:
        print(f"Could not open browser automatically. Open this URL: {url}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    banner("VIDEO SEPARATOR - STARTING")

    # ---- Existing instance check ----
    pids = load_pids()
    if pids.get("node") and pid_running(pids["node"]):
        print("Project already running. Run `python stop.py` first.")
        sys.exit(1)
    if pids.get("flask") and pid_running(pids["flask"]):
        print("Project already running. Run `python stop.py` first.")
        sys.exit(1)

    # ---- Conda check ----
    conda_ok = check_conda()
    step("Conda", conda_ok, "not found" if not conda_ok else "")
    if not conda_ok:
        print("\nConda is required. Install Miniconda/Anaconda and retry.")
        sys.exit(1)

    # ---- Decide which Conda env to use ----
    env_name = active_conda_env()

    if env_name:
        step("Conda env", True, f"using active: {env_name}")
    elif conda_env_exists(PREFERRED_ENV_NAME):
        env_name = PREFERRED_ENV_NAME
        step("Conda env", True, f"using existing: {env_name}")
    else:
        step("Conda env", False, f"creating: {PREFERRED_ENV_NAME}")
        if not create_conda_env(PREFERRED_ENV_NAME):
            print("\nCould not create the Conda environment automatically.")
            print("Please run manually:")
            print(f"  conda create -n {PREFERRED_ENV_NAME} python=3.11 -y")
            sys.exit(1)
        env_name = PREFERRED_ENV_NAME
        step("Conda env", True, f"created: {env_name}")

    # ---- Resolve EXACT python for the chosen env ----
    python_exe = python_path_for_env(env_name)
    if not python_exe:
        print(f"\nCould not locate python inside env '{env_name}'.")
        print("Try: conda env list   (verify the env exists)")
        sys.exit(1)
    print(f"[start] Using Python: {python_exe}")

    # ---- Verify python version ----
    py = env_python_version(python_exe)
    if py is None:
        print(f"\nCould not determine Python version of:\n  {python_exe}")
        sys.exit(1)
    py_ok = py in REQUIRED_PY
    step("Python", py_ok, f"{py[0]}.{py[1]} in env '{env_name}'")
    if not py_ok:
        print(f"\nEnv '{env_name}' has Python {py[0]}.{py[1]} — need 3.10 or 3.11.")
        print(f"Recreate it: conda create -n {env_name} python=3.11 -y")
        sys.exit(1)

    # ---- Verify Flask INSIDE that exact python; auto-install if missing ----
    flask_ok, err = python_has_flask(python_exe)
    if not flask_ok:
        print(f"[setup] Flask/Flask-CORS missing in '{env_name}':")
        print(f"        {err}")
        if not pip_install_into(python_exe, BASE_DIR / "requirements.txt"):
            print("\nCould not install Python dependencies automatically.")
            print(f"Please run manually:")
            print(f"  conda activate {env_name}")
            print(f"  pip install -r requirements.txt")
            sys.exit(1)
        flask_ok, err = python_has_flask(python_exe)
    step("Flask deps", flask_ok, "" if flask_ok else err)
    if not flask_ok:
        print("\nPython dependencies still missing after install attempt.")
        sys.exit(1)

    # ---- Node ----
    node_ok, npm_ok = check_node()
    step("Node.js", node_ok and npm_ok, "node/npm missing" if not (node_ok and npm_ok) else "")
    if not (node_ok and npm_ok):
        print("\nNode.js and npm are required. Install them and retry.")
        sys.exit(1)

    if not (BASE_DIR / "node_modules").exists():
        if not install_node_deps():
            print("\nCould not install Node dependencies automatically.")
            sys.exit(1)
    step("Node modules", True)

    # ---- FFmpeg ----
    ffmpeg_ok = which_or_none("ffmpeg") is not None
    step("FFmpeg", ffmpeg_ok, "" if ffmpeg_ok else "not found — extraction will fail")
    if not ffmpeg_ok:
        print("\nFFmpeg is required for audio extraction.")
        print("  Windows: choco install ffmpeg")
        print("  macOS:   brew install ffmpeg")
        print("  Linux:   sudo apt install ffmpeg")
        sys.exit(1)

    # ---- Ports ----
    try:
        flask_port = find_free_port(FLASK_DEFAULT_PORT)
        node_port = find_free_port(NODE_DEFAULT_PORT)
    except RuntimeError as e:
        print(f"Port error: {e}")
        sys.exit(1)

    # ---- LAN IP ----
    lan_ip = get_lan_ip()
    step("Network", lan_ip not in ("127.0.0.1", "localhost"), lan_ip)

    # ---- Launch ----
    print("\nStarting Flask backend...")
    flask_pid = start_flask(flask_port, python_exe, node_port)

    print("Starting Node.js frontend...")
    node_pid = start_node(node_port, flask_port)

    # ---- Wait for readiness ----
    if not wait_for_port("127.0.0.1", flask_port, 60):
        print("Flask did not become ready in time.")
        print(f"Check logs at: {LOG_DIR / 'flask.log'}")
        try:
            print("----- flask.log (tail) -----")
            print((LOG_DIR / "flask.log").read_text()[-2000:])
        except Exception:
            pass
        terminate_pid(flask_pid)
        terminate_pid(node_pid)
        sys.exit(1)

    if not wait_for_port("0.0.0.0", node_port, 60):
        print("Node.js did not become ready in time.")
        print(f"Check logs at: {LOG_DIR / 'node.log'}")
        try:
            print("----- node.log (tail) -----")
            print((LOG_DIR / "node.log").read_text()[-2000:])
        except Exception:
            pass
        terminate_pid(flask_pid)
        terminate_pid(node_pid)
        sys.exit(1)

    # ---- Save PIDs ----
    save_pids({
        "flask": flask_pid,
        "node": node_pid,
        "flask_port": flask_port,
        "node_port": node_port,
        "lan_ip": lan_ip,
        "env_name": env_name,
        "python_exe": python_exe,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })

    network_url = f"http://{lan_ip}:{node_port}"
    local_url = f"http://127.0.0.1:{node_port}"

    print()
    banner("PROJECT STARTED SUCCESSFULLY")
    print(f"Conda env   : {env_name}")
    print(f"Python      : {python_exe}")
    print(f"Local URL   : {local_url}")
    print(f"Network URL : {network_url}")
    print(f"Flask PID   : {flask_pid}")
    print(f"Node  PID   : {node_pid}")
    print(f"Logs        : {LOG_DIR}")
    print("\nShare the Network URL with other devices on the same Wi-Fi/LAN.")
    print("Stop the project with: python stop.py\n")

    target = local_url if lan_ip in ("127.0.0.1", "localhost") else network_url
    print(f"Opening web GUI: {target}")
    open_browser(target)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStartup cancelled.")