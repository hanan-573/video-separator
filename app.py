"""
Video Separator - Flask backend
Extracts audio from video files using FFmpeg.
"""

import os
import sys
import json
import uuid
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_VIDEO_EXT = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv",
    ".flv", ".webm", ".m4v", ".ts", ".3gp",
}

ALLOWED_OUTPUT_FORMATS = {"mp3", "wav"}

# In-memory task registry
TASKS = {}          # task_id -> task dict
TASKS_LOCK = threading.Lock()

# SSE subscriber queues: stream_key -> list of lists (queues)
SSE_SUBSCRIBERS = {}
SSE_LOCK = threading.Lock()

app = Flask(__name__, static_folder=None)
CORS(app, resources={r"/*": {"origins": "*"}})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _safe_filename(name: str) -> str:
    """Sanitize a filename, prevent path traversal and command injection."""
    name = os.path.basename(name)
    name = name.replace("\x00", "")
    # Keep only safe characters
    safe = "".join(c for c in name if c.isalnum() or c in "._- ()")
    safe = safe.strip().strip(".")
    return safe or "video"


def _broadcast(task_id: str, payload: dict):
    """Push an SSE event to all subscribers of a task AND the global stream."""
    # Notify per-task subscribers
    with SSE_LOCK:
        subs = list(SSE_SUBSCRIBERS.get(task_id, []))
    for q in subs:
        try:
            q.append(payload)
        except Exception:
            pass

    # Notify global subscribers
    with SSE_LOCK:
        global_subs = list(SSE_SUBSCRIBERS.get("__all__", []))
    for q in global_subs:
        try:
            q.append({"type": "task_update", "task": payload})
        except Exception:
            pass


def _update_task(task_id: str, **kwargs):
    with TASKS_LOCK:
        task = TASKS.get(task_id)
        if not task:
            return
        task.update(kwargs)
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        snapshot = dict(task)
    _broadcast(task_id, snapshot)


def _probe_duration(video_path: Path) -> float:
    """Return duration in seconds via ffprobe. 0.0 if unknown."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        out = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip() or 0.0)
    except Exception:
        return 0.0


def _human_size(num: int) -> str:
    try:
        num = float(num)
    except Exception:
        return "-"
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def _run_extraction(task_id: str, video_path: Path, output_format: str, base_name: str):
    """Run FFmpeg extraction and stream progress into the task registry."""
    duration = _probe_duration(video_path)
    output_path = OUTPUT_DIR / f"{base_name}.{output_format}"

    if output_format == "mp3":
        codec_args = ["-vn", "-acodec", "libmp3lame", "-b:a", "320k"]
    else:  # wav
        codec_args = ["-vn", "-acodec", "pcm_s16le"]

    cmd = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-y",
        "-i", str(video_path),
        *codec_args,
        "-progress", "pipe:1",
        "-nostats",
        str(output_path),
    ]

    _update_task(
        task_id,
        status="processing",
        progress=0,
        message=f"Encoding {output_format.upper()} ...",
    )

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        _update_task(
            task_id,
            status="error",
            message="FFmpeg not found. Please install FFmpeg and add it to PATH.",
        )
        return

    # Parse ffmpeg -progress output
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key == "out_time_ms" and duration > 0:
                try:
                    seconds = int(value) / 1_000_000
                    pct = max(0, min(99, int((seconds / duration) * 100)))
                    _update_task(task_id, progress=pct, message=f"Extracting audio... {pct}%")
                except ValueError:
                    pass
    except Exception:
        pass

    _, stderr_data = proc.communicate()
    returncode = proc.returncode

    if returncode != 0 or not output_path.exists():
        err_tail = (stderr_data or "").strip().splitlines()[-3:]
        err_msg = " | ".join(err_tail) if err_tail else "Unknown extraction error."
        _update_task(
            task_id,
            status="error",
            progress=0,
            message=f"Extraction failed: {err_msg[:300]}",
        )
        return

    size_bytes = output_path.stat().st_size
    _update_task(
        task_id,
        status="completed",
        progress=100,
        message="Completed",
        size=size_bytes,
        size_human=_human_size(size_bytes),
        output_file=output_path.name,
        download_url=f"/api/download/{task_id}",
        completed_at=datetime.now().isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "ffmpeg": _ffmpeg_available(),
        "time": datetime.now().isoformat(timespec="seconds"),
    })


@app.route("/api/network")
def network_info():
    """Return the LAN URL that clients should use to reach this app."""
    lan_ip = os.environ.get("LAN_IP", "").strip()
    node_port = os.environ.get("NODE_PORT_FOR_FLASK", "").strip() or os.environ.get("NODE_PORT", "").strip()
    if not lan_ip:
        try:
            import socket as _s
            _sock = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
            _sock.connect(("8.8.8.8", 80))
            lan_ip = _sock.getsockname()[0]
            _sock.close()
        except Exception:
            lan_ip = "127.0.0.1"
    if not node_port or not node_port.isdigit():
        node_port = "5000"
    return jsonify({
        "lan_ip": lan_ip,
        "node_port": int(node_port),
        "lan_url": f"http://{lan_ip}:{node_port}",
    })


@app.route("/api/upload", methods=["POST"])
def upload():
    if "video" not in request.files:
        return jsonify({"error": "No video file provided."}), 400

    file = request.files["video"]
    if not file or file.filename == "":
        return jsonify({"error": "Empty filename."}), 400

    output_format = (request.form.get("format") or "mp3").lower().strip()
    if output_format not in ALLOWED_OUTPUT_FORMATS:
        return jsonify({"error": "Invalid output format. Use mp3 or wav."}), 400

    safe_name = _safe_filename(file.filename)
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXT:
        return jsonify({
            "error": f"Unsupported video format '{ext}'. Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXT))}",
        }), 400

    if not _ffmpeg_available():
        return jsonify({"error": "FFmpeg is not installed on the server."}), 500

    base_name = Path(safe_name).stem or "video"

    task_id = uuid.uuid4().hex
    saved_video = UPLOAD_DIR / f"{task_id}_{safe_name}"
    try:
        file.save(str(saved_video))
    except Exception as e:
        return jsonify({"error": f"Failed to save upload: {e}"}), 500

    if saved_video.stat().st_size == 0:
        try:
            saved_video.unlink()
        except Exception:
            pass
        return jsonify({"error": "Uploaded file is empty."}), 400

    task = {
        "id": task_id,
        "original_name": safe_name,
        "base_name": base_name,
        "format": output_format,
        "status": "queued",
        "progress": 0,
        "message": "Queued",
        "size": 0,
        "size_human": "-",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "output_file": None,
        "download_url": None,
    }

    with TASKS_LOCK:
        TASKS[task_id] = task

    _broadcast(task_id, dict(task))

    thread = threading.Thread(
        target=_run_extraction,
        args=(task_id, saved_video, output_format, base_name),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "task": task}), 202


@app.route("/api/tasks")
def list_tasks():
    with TASKS_LOCK:
        items = sorted(
            (dict(t) for t in TASKS.values()),
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )
    return jsonify({"tasks": items})


@app.route("/api/task/<task_id>")
def get_task(task_id):
    with TASKS_LOCK:
        task = TASKS.get(task_id)
        if not task:
            return jsonify({"error": "Task not found."}), 404
        return jsonify(dict(task))


@app.route("/api/download/<task_id>")
def download(task_id):
    with TASKS_LOCK:
        task = TASKS.get(task_id)
    if not task or task.get("status") != "completed":
        return jsonify({"error": "File not ready."}), 404

    out_name = task.get("output_file")
    if not out_name:
        return jsonify({"error": "Output missing."}), 404

    out_path = OUTPUT_DIR / out_name
    if not out_path.exists():
        return jsonify({"error": "Output file not found on disk."}), 404

    return send_file(
        str(out_path),
        as_attachment=True,
        download_name=out_name,
        mimetype="audio/mpeg" if out_path.suffix == ".mp3" else "audio/wav",
    )


@app.route("/api/events/<task_id>")
def events(task_id):
    """SSE endpoint for a single task's live updates."""
    def stream():
        q = []
        with SSE_LOCK:
            SSE_SUBSCRIBERS.setdefault(task_id, []).append(q)

        try:
            # Send initial snapshot
            with TASKS_LOCK:
                initial = TASKS.get(task_id)
            if initial:
                yield f"data: {json.dumps(initial)}\n\n"

            last_heartbeat = time.time()
            while True:
                if q:
                    payload = q.pop(0)
                    yield f"data: {json.dumps(payload)}\n\n"
                    if payload.get("status") in ("completed", "error"):
                        break
                else:
                    time.sleep(0.25)

                if time.time() - last_heartbeat > 15:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.time()
        finally:
            with SSE_LOCK:
                subs = SSE_SUBSCRIBERS.get(task_id, [])
                if q in subs:
                    subs.remove(q)
                if not subs:
                    SSE_SUBSCRIBERS.pop(task_id, None)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(stream_with_context(stream()), mimetype="text/event-stream", headers=headers)


@app.route("/api/events")
def events_all():
    """SSE endpoint for global task list updates."""
    def stream():
        q = []
        with SSE_LOCK:
            SSE_SUBSCRIBERS.setdefault("__all__", []).append(q)
        try:
            with TASKS_LOCK:
                snapshot = [dict(t) for t in TASKS.values()]
            yield f"data: {json.dumps({'tasks': snapshot})}\n\n"

            last_heartbeat = time.time()
            while True:
                if q:
                    payload = q.pop(0)
                    yield f"data: {json.dumps(payload)}\n\n"
                else:
                    time.sleep(0.3)
                if time.time() - last_heartbeat > 15:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.time()
        finally:
            with SSE_LOCK:
                subs = SSE_SUBSCRIBERS.get("__all__", [])
                if q in subs:
                    subs.remove(q)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(stream_with_context(stream()), mimetype="text/event-stream", headers=headers)


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "File too large. Maximum size is 4 GB."}), 413


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB
    port = int(os.environ.get("FLASK_PORT", "8000"))
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    print(f"[flask] Starting on {host}:{port}", flush=True)
    app.run(host=host, port=port, threaded=True, debug=False, use_reloader=False)