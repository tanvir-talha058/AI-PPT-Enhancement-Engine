import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import Flask, jsonify, render_template, request, send_file
from redis import Redis
from redis.exceptions import RedisError
from rq import Queue
from rq.job import Job
from werkzeug.utils import secure_filename

from config import (
    ALLOWED_EXTENSIONS,
    OUTPUT_FOLDER,
    QUEUE_NAME,
    REDIS_URL,
    UPLOAD_FOLDER,
    USE_REDIS,
    ensure_directories,
)
from tasks import process_ppt


ensure_directories()

app = Flask(__name__)
redis_conn = None
queue = None
local_jobs: dict[str, dict] = {}
local_jobs_lock = threading.Lock()


DEFAULT_PREVIEW = {
    "slide_key": "slide_1",
    "before": [
        "We need to improve the onboarding process for new enterprise clients.",
        "There are a lot of delays in the approval workflow.",
        "This slide talks about our growth opportunity in Asia Pacific.",
    ],
    "after": [
        "Improve onboarding for new enterprise clients.",
        "Approval workflow delays are slowing execution.",
        "Asia Pacific remains a strong growth opportunity.",
    ],
}


def _use_redis() -> bool:
    return USE_REDIS in {"1", "true", "yes", "on", "auto"}


def initialize_queue() -> bool:
    global redis_conn, queue

    if not _use_redis():
        return False

    try:
        redis_conn = Redis.from_url(REDIS_URL)
        redis_conn.ping()
        queue = Queue(QUEUE_NAME, connection=redis_conn)
        return True
    except RedisError:
        redis_conn = None
        queue = None
        return False


QUEUE_ENABLED = initialize_queue()


def is_allowed_file(filename: str) -> bool:
    suffix = Path(filename).suffix.lower()
    return suffix in ALLOWED_EXTENSIONS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_local_job(job_id: str, file_path: Path) -> None:
    with local_jobs_lock:
        local_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "file_path": str(file_path),
            "result": None,
            "error": None,
            "created_at": _now_iso(),
            "mode": "local",
        }


def _run_local_job(job_id: str, file_path: Path) -> None:
    with local_jobs_lock:
        local_jobs[job_id]["status"] = "started"

    try:
        result = process_ppt(str(file_path))
        with local_jobs_lock:
            local_jobs[job_id]["status"] = "finished"
            local_jobs[job_id]["result"] = result
    except Exception as exc:
        with local_jobs_lock:
            local_jobs[job_id]["status"] = "failed"
            local_jobs[job_id]["error"] = str(exc)


def enqueue_job(file_path: Path) -> tuple[str, str]:
    if QUEUE_ENABLED and queue is not None:
        job = queue.enqueue(process_ppt, str(file_path))
        return job.id, "redis"

    job_id = uuid4().hex
    _create_local_job(job_id, file_path)
    thread = threading.Thread(target=_run_local_job, args=(job_id, file_path), daemon=True)
    thread.start()
    return job_id, "local"


def _serialize_result(result: dict | None, job_id: str) -> dict | None:
    if not isinstance(result, dict):
        return None
    return {
        "output_file": Path(result["output_path"]).name,
        "download_url": f"/download/{job_id}",
        "preview": result.get("preview") or DEFAULT_PREVIEW,
    }


def _get_local_job(job_id: str) -> dict | None:
    with local_jobs_lock:
        job = local_jobs.get(job_id)
        return dict(job) if job else None


@app.get("/")
def index():
    return render_template(
        "index.html",
        queue_mode="redis" if QUEUE_ENABLED else "local",
        default_preview=DEFAULT_PREVIEW,
    )


@app.get("/health")
def health_check():
    return jsonify({"status": "ok", "queue_mode": "redis" if QUEUE_ENABLED else "local"})


@app.post("/upload")
def upload_ppt():
    uploaded_file = request.files.get("file")
    if uploaded_file is None or uploaded_file.filename == "":
        return jsonify({"error": "No file provided"}), 400

    if not is_allowed_file(uploaded_file.filename):
        return jsonify({"error": "Only .pptx files are supported"}), 400

    original_name = secure_filename(uploaded_file.filename)
    unique_name = f"{uuid4().hex}_{original_name}"
    file_path = UPLOAD_FOLDER / unique_name
    uploaded_file.save(file_path)

    job_id, mode = enqueue_job(file_path)
    return jsonify({"job_id": job_id, "mode": mode}), 202


@app.get("/status/<job_id>")
def get_status(job_id: str):
    if not QUEUE_ENABLED:
        job = _get_local_job(job_id)
        if job is None:
            return jsonify({"error": "Job not found"}), 404

        response = {
            "job_id": job["job_id"],
            "status": job["status"],
            "mode": job["mode"],
        }
        result = _serialize_result(job.get("result"), job_id)
        if result:
            response["result"] = result
        if job.get("error"):
            response["error"] = job["error"]
        return jsonify(response)

    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception:
        return jsonify({"error": "Job not found"}), 404

    response = {
        "job_id": job.id,
        "status": job.get_status(refresh=True),
        "mode": "redis",
    }

    result = _serialize_result(job.result if isinstance(job.result, dict) else None, job.id)
    if result:
        response["result"] = result
    elif job.is_failed:
        response["error"] = str(job.exc_info).splitlines()[-1] if job.exc_info else "Unknown worker error"

    return jsonify(response)


@app.get("/download/<job_id>")
def download_result(job_id: str):
    if not QUEUE_ENABLED:
        job = _get_local_job(job_id)
        if job is None:
            return jsonify({"error": "Job not found"}), 404
        if job["status"] != "finished" or not isinstance(job.get("result"), dict):
            return jsonify({"error": "Processed file is not ready"}), 409

        output_path = Path(job["result"]["output_path"])
        if not output_path.exists() or output_path.parent != OUTPUT_FOLDER:
            return jsonify({"error": "Output file not available"}), 404

        return send_file(output_path, as_attachment=True, download_name=output_path.name)

    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception:
        return jsonify({"error": "Job not found"}), 404

    if not job.is_finished or not isinstance(job.result, dict):
        return jsonify({"error": "Processed file is not ready"}), 409

    output_path = Path(job.result["output_path"])
    if not output_path.exists() or output_path.parent != OUTPUT_FOLDER:
        return jsonify({"error": "Output file not available"}), 404

    return send_file(output_path, as_attachment=True, download_name=output_path.name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
