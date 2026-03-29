"""Flask API for PPT enhancement."""

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

from ai_engine import validate_providers
from cleanup import cleanup_old_files
from config import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    OUTPUT_FOLDER,
    QUEUE_NAME,
    RATE_LIMIT_PER_HOUR,
    REDIS_URL,
    UPLOAD_FOLDER,
    USE_REDIS,
    ensure_directories,
    get_ai_provider_label,
    setup_logging,
)
from jobs_db import delete_job, get_job, init_db, save_job
from tasks import process_ppt

logger = setup_logging(__name__)


ensure_directories()
init_db()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE_BYTES + (2 * 1024 * 1024)
redis_conn = None
queue = None
local_jobs: dict[str, dict] = {}
local_jobs_lock = threading.Lock()
request_counts: dict[str, list[float]] = {}


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


def _json_error(message: str, status_code: int, **extra):
    payload = {"error": message, **extra}
    response = jsonify(payload)
    response.status_code = status_code
    return response


def _use_redis() -> bool:
    """Check if Redis should be used based on configuration."""
    return USE_REDIS in {"1", "true", "yes", "on", "auto"}


def _client_ip() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded_for or request.remote_addr or "unknown"


def _is_rate_limited(client_ip: str) -> bool:
    """Check if client has exceeded rate limit."""
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - 3600

    timestamps = request_counts.setdefault(client_ip, [])
    request_counts[client_ip] = [ts for ts in timestamps if ts > cutoff]

    if len(request_counts[client_ip]) >= RATE_LIMIT_PER_HOUR:
        return True

    request_counts[client_ip].append(now)
    return False


def initialize_queue() -> bool:
    """Initialize Redis queue if configured and available."""
    global redis_conn, queue

    if not _use_redis():
        logger.info("Redis queue disabled, using local threaded mode")
        return False

    try:
        redis_conn = Redis.from_url(REDIS_URL)
        redis_conn.ping()
        queue = Queue(QUEUE_NAME, connection=redis_conn)
        logger.info("Redis queue initialized successfully")
        return True
    except RedisError as exc:
        redis_conn = None
        queue = None
        logger.warning("Redis connection failed: %s. Falling back to threaded mode.", exc)
        return False


QUEUE_ENABLED = initialize_queue()
AI_PROVIDER_LABEL = get_ai_provider_label()


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    else:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(413)
def handle_file_too_large(_error):
    return _json_error(
        f"File too large. Maximum size is {int(MAX_FILE_SIZE_BYTES / 1024 / 1024)}MB.",
        413,
    )


def is_allowed_file(filename: str) -> bool:
    """Check if file has an allowed extension."""
    suffix = Path(filename).suffix.lower()
    return suffix in ALLOWED_EXTENSIONS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_local_job(job_id: str, file_path: Path) -> None:
    """Create a local job record in memory and database."""
    with local_jobs_lock:
        local_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "file_path": str(file_path),
            "result": None,
            "error": None,
            "created_at": _now_iso(),
            "mode": "threaded",
            "can_cancel": False,
        }

    save_job(job_id, "queued", str(file_path), "threaded")
    logger.info("Local job %s created for %s", job_id, file_path.name)


def _run_local_job(job_id: str, file_path: Path) -> None:
    """Execute a local job in a thread."""
    with local_jobs_lock:
        if job_id not in local_jobs:
            return
        local_jobs[job_id]["status"] = "started"

    save_job(job_id, "started", str(file_path), "threaded")
    logger.info("Local job %s started processing", job_id)

    try:
        result = process_ppt(str(file_path))
        with local_jobs_lock:
            if job_id not in local_jobs:
                return
            local_jobs[job_id]["status"] = "finished"
            local_jobs[job_id]["result"] = result

        save_job(
            job_id,
            "finished",
            str(file_path),
            "threaded",
            output_path=result.get("output_path"),
            result_json=str(result),
        )
        logger.info("Local job %s completed successfully", job_id)
    except Exception as exc:
        with local_jobs_lock:
            if job_id in local_jobs:
                local_jobs[job_id]["status"] = "failed"
                local_jobs[job_id]["error"] = str(exc)

        save_job(job_id, "failed", str(file_path), "threaded", error_message=str(exc))
        logger.error("Local job %s failed: %s", job_id, exc, exc_info=True)


def enqueue_job(file_path: Path) -> tuple[str, str]:
    """Enqueue a job to Redis or local thread pool."""
    if QUEUE_ENABLED and queue is not None:
        job = queue.enqueue(process_ppt, str(file_path))
        save_job(job.id, "queued", str(file_path), "redis")
        logger.info("Job %s enqueued to Redis", job.id)
        return job.id, "redis"

    job_id = uuid4().hex
    _create_local_job(job_id, file_path)
    thread = threading.Thread(target=_run_local_job, args=(job_id, file_path), daemon=True)
    thread.start()
    logger.info("Job %s queued to local thread pool", job_id)
    return job_id, "threaded"


def _serialize_result(result: dict | None, job_id: str) -> dict | None:
    if not isinstance(result, dict):
        return None

    output_path = result.get("output_path")
    if not output_path:
        return None

    return {
        "output_file": Path(output_path).name,
        "download_url": f"/download/{job_id}",
        "preview": result.get("preview") or DEFAULT_PREVIEW,
    }


def _get_local_job(job_id: str) -> dict | None:
    with local_jobs_lock:
        job = local_jobs.get(job_id)
        return dict(job) if job else None


def _status_payload(job_id: str, status: str, mode: str, *, result=None, error=None) -> dict:
    payload = {
        "job_id": job_id,
        "status": status,
        "mode": mode,
        "can_cancel": mode == "redis" and status in {"queued", "started", "deferred"},
    }
    if result:
        payload["result"] = result
    if error:
        payload["error"] = error
    return payload


@app.get("/")
def index():
    return render_template(
        "index.html",
        queue_mode="redis" if QUEUE_ENABLED else "threaded",
        ai_provider=AI_PROVIDER_LABEL,
        default_preview=DEFAULT_PREVIEW,
    )


@app.get("/health")
def health_check():
    return jsonify(
        {
            "status": "ok",
            "queue_mode": "redis" if QUEUE_ENABLED else "threaded",
            "ai_provider": AI_PROVIDER_LABEL,
        }
    )


@app.get("/metrics")
def get_metrics():
    local_count = len(local_jobs)
    redis_count = 0

    if QUEUE_ENABLED and queue is not None:
        try:
            redis_count = len(queue.jobs)
        except Exception as exc:
            logger.warning("Could not fetch Redis queue metrics: %s", exc)

    return jsonify(
        {
            "local_jobs": local_count,
            "redis_jobs": redis_count,
            "queue_mode": "redis" if QUEUE_ENABLED else "threaded",
        }
    )


@app.get("/config/providers")
def check_providers():
    available = validate_providers()
    return jsonify(
        {
            "configured_providers": available,
            "provider_count": len(available),
            "status": "ready" if available else "error",
            "message": "All providers ready" if available else "No AI providers configured",
            "help_url": "https://github.com/your-repo/docs/AI_SETUP.md",
        }
    )


@app.post("/upload")
def upload_ppt():
    """Handle PPT file upload and enqueue processing."""
    client_ip = _client_ip()

    if _is_rate_limited(client_ip):
        logger.warning("Rate limit exceeded for IP %s", client_ip)
        return _json_error("Rate limit exceeded. Maximum 100 uploads per hour.", 429)

    uploaded_file = request.files.get("file")
    if uploaded_file is None or uploaded_file.filename == "":
        logger.warning("Upload rejected: no file provided from %s", client_ip)
        return _json_error("No file provided.", 400)

    if not is_allowed_file(uploaded_file.filename):
        logger.warning("Upload rejected: invalid extension %s", uploaded_file.filename)
        return _json_error("Only .pptx files are supported.", 400)

    content_length = request.content_length
    if content_length and content_length > app.config["MAX_CONTENT_LENGTH"]:
        logger.warning("Upload rejected: payload too large (%s bytes) from %s", content_length, client_ip)
        return _json_error(
            f"File too large. Maximum size is {int(MAX_FILE_SIZE_BYTES / 1024 / 1024)}MB.",
            413,
        )

    original_name = secure_filename(uploaded_file.filename)
    unique_name = f"{uuid4().hex}_{original_name}"
    file_path = UPLOAD_FOLDER / unique_name

    try:
        uploaded_file.save(file_path)

        if file_path.stat().st_size == 0:
            file_path.unlink(missing_ok=True)
            logger.warning("Upload rejected: empty file")
            return _json_error("File is empty.", 400)

        if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            file_path.unlink(missing_ok=True)
            logger.warning("Upload rejected: saved file exceeded max size")
            return _json_error(
                f"File too large. Maximum size is {int(MAX_FILE_SIZE_BYTES / 1024 / 1024)}MB.",
                413,
            )

        job_id, mode = enqueue_job(file_path)
        logger.info("File %s uploaded and queued as %s", original_name, job_id)
        return jsonify({
            "job_id": job_id,
            "mode": mode,
            "can_cancel": mode == "redis",
        }), 202
    except Exception as exc:
        logger.error("Upload failed: %s", exc, exc_info=True)
        if file_path.exists():
            file_path.unlink(missing_ok=True)
        return _json_error("Upload failed. Please try again.", 500)


@app.get("/status/<job_id>")
def get_status(job_id: str):
    """Get the current status of a processing job."""
    if not QUEUE_ENABLED:
        job = _get_local_job(job_id)
        if job is None:
            logger.warning("Status check for non-existent local job %s", job_id)
            return _json_error("Job not found.", 404)

        result = _serialize_result(job.get("result"), job_id)
        return jsonify(
            _status_payload(
                job["job_id"],
                job["status"],
                job["mode"],
                result=result,
                error=job.get("error"),
            )
        )

    try:
        job = Job.fetch(job_id, connection=redis_conn)
        status = job.get_status(refresh=True)
        logger.debug("Fetched Redis job %s, status: %s", job_id, status)
    except Exception as exc:
        logger.warning("Status check failed for Redis job %s: %s", job_id, exc)
        return _json_error("Job not found.", 404)

    result = _serialize_result(job.result if isinstance(job.result, dict) else None, job.id)
    error = None
    if not result and job.is_failed:
        error = str(job.exc_info).splitlines()[-1] if job.exc_info else "Unknown worker error"
        logger.error("Job %s failed: %s", job_id, error)

    return jsonify(_status_payload(job.id, status, "redis", result=result, error=error))


@app.delete("/job/<job_id>")
def cancel_job(job_id: str):
    """Cancel a pending or running job."""
    logger.info("Cancel request for job %s", job_id)

    if not QUEUE_ENABLED:
        logger.warning("Cancel not supported in threaded mode for job %s", job_id)
        return _json_error("Cancellation is only available when Redis queue mode is enabled.", 409)

    try:
        job = Job.fetch(job_id, connection=redis_conn)
        if job.is_finished or job.is_failed:
            status = job.get_status()
            logger.warning("Cannot cancel job %s: already %s", job_id, status)
            return _json_error(f"Cannot cancel job with status {status}.", 409)

        job.cancel()
        delete_job(job_id)
        logger.info("Redis job %s cancelled", job_id)
        return jsonify({"status": "cancelled"}), 200
    except Exception as exc:
        logger.error("Cancel failed for job %s: %s", job_id, exc)
        return _json_error("Job not found.", 404)


@app.get("/download/<job_id>")
def download_result(job_id: str):
    """Download the enhanced presentation file."""
    logger.info("Download request for job %s", job_id)

    if not QUEUE_ENABLED:
        job = _get_local_job(job_id)
        if job is None:
            logger.warning("Download failed: local job %s not found", job_id)
            return _json_error("Job not found.", 404)
        if job["status"] != "finished" or not isinstance(job.get("result"), dict):
            logger.warning("Download failed: job %s not ready (status: %s)", job_id, job["status"])
            return _json_error("Processed file is not ready.", 409)

        output_path = Path(job["result"]["output_path"])
        if not output_path.exists() or output_path.parent != OUTPUT_FOLDER:
            logger.error("Download failed: output file invalid for job %s", job_id)
            return _json_error("Output file not available.", 404)

        logger.info("Downloading local job %s: %s", job_id, output_path.name)
        return send_file(output_path, as_attachment=True, download_name=output_path.name)

    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception:
        logger.warning("Download failed: Redis job %s not found", job_id)
        return _json_error("Job not found.", 404)

    if not job.is_finished or not isinstance(job.result, dict):
        logger.warning("Download failed: Redis job %s not ready (status: %s)", job_id, job.get_status())
        return _json_error("Processed file is not ready.", 409)

    output_path = Path(job.result["output_path"])
    if not output_path.exists() or output_path.parent != OUTPUT_FOLDER:
        logger.error("Download failed: output file invalid for job %s", job_id)
        return _json_error("Output file not available.", 404)

    logger.info("Downloading Redis job %s: %s", job_id, output_path.name)
    return send_file(output_path, as_attachment=True, download_name=output_path.name)


if __name__ == "__main__":
    logger.info("Starting AI PPT Enhancement Engine")

    cleanup_old_files()

    def periodic_cleanup():
        import time

        while True:
            try:
                time.sleep(3600)
                cleanup_old_files()
            except Exception as exc:
                logger.error("Cleanup task failed: %s", exc)

    cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
    cleanup_thread.start()
    logger.info("Periodic cleanup thread started")

    app.run(host="0.0.0.0", port=5000, debug=True)
