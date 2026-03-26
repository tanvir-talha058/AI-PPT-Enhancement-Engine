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

from cleanup import cleanup_old_files
from config import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    OUTPUT_FOLDER,
    PREVIEW_LIMIT,
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
redis_conn = None
queue = None
local_jobs: dict[str, dict] = {}
local_jobs_lock = threading.Lock()
request_counts: dict[str, list[float]] = {}  # IP -> [timestamps]


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
    """Check if Redis should be used based on configuration."""
    return USE_REDIS in {"1", "true", "yes", "on", "auto"}


def _is_rate_limited(client_ip: str) -> bool:
    """Check if client has exceeded rate limit."""
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - 3600
    
    if client_ip not in request_counts:
        request_counts[client_ip] = []
    
    request_counts[client_ip] = [ts for ts in request_counts[client_ip] if ts > cutoff]
    
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
        logger.warning(f"Redis connection failed: {exc}. Falling back to threaded mode.")
        return False


QUEUE_ENABLED = initialize_queue()
AI_PROVIDER_LABEL = get_ai_provider_label()


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
        }
    
    save_job(job_id, "queued", str(file_path), "threaded")
    logger.info(f"Local job {job_id} created for {file_path.name}")


def _run_local_job(job_id: str, file_path: Path) -> None:
    """Execute a local job in a thread."""
    with local_jobs_lock:
        local_jobs[job_id]["status"] = "started"
    
    save_job(job_id, "started", str(file_path), "threaded")
    logger.info(f"Local job {job_id} started processing")

    try:
        result = process_ppt(str(file_path))
        with local_jobs_lock:
            local_jobs[job_id]["status"] = "finished"
            local_jobs[job_id]["result"] = result
        
        save_job(job_id, "finished", str(file_path), "threaded", 
                output_path=result.get("output_path"),
                result_json=str(result))
        logger.info(f"Local job {job_id} completed successfully")
    except Exception as exc:
        with local_jobs_lock:
            local_jobs[job_id]["status"] = "failed"
            local_jobs[job_id]["error"] = str(exc)
        
        save_job(job_id, "failed", str(file_path), "threaded", 
                error_message=str(exc))
        logger.error(f"Local job {job_id} failed: {exc}", exc_info=True)


def enqueue_job(file_path: Path) -> tuple[str, str]:
    """Enqueue a job to Redis or local thread pool."""
    if QUEUE_ENABLED and queue is not None:
        job = queue.enqueue(process_ppt, str(file_path))
        save_job(job.id, "queued", str(file_path), "redis")
        logger.info(f"Job {job.id} enqueued to Redis")
        return job.id, "redis"

    job_id = uuid4().hex
    _create_local_job(job_id, file_path)
    thread = threading.Thread(target=_run_local_job, args=(job_id, file_path), daemon=True)
    thread.start()
    logger.info(f"Job {job_id} queued to local thread pool")
    return job_id, "threaded"


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
        queue_mode="redis" if QUEUE_ENABLED else "threaded",
        ai_provider=AI_PROVIDER_LABEL,
        default_preview=DEFAULT_PREVIEW,
    )


@app.get("/health")
def health_check():
    """Health check endpoint with service status."""
    return jsonify(
        {
            "status": "ok",
            "queue_mode": "redis" if QUEUE_ENABLED else "threaded",
            "ai_provider": AI_PROVIDER_LABEL,
        }
    )


@app.get("/metrics")
def get_metrics():
    """Basic metrics endpoint."""
    local_count = len(local_jobs)
    redis_count = 0
    
    if QUEUE_ENABLED and queue is not None:
        try:
            redis_count = len(queue.jobs)
        except Exception as exc:
            logger.warning(f"Could not fetch Redis queue metrics: {exc}")
    
    return jsonify({
        "local_jobs": local_count,
        "redis_jobs": redis_count,
        "queue_mode": "redis" if QUEUE_ENABLED else "threaded",
    })


@app.post("/upload")
def upload_ppt():
    """Handle PPT file upload and enqueue processing."""
    client_ip = request.remote_addr
    
    if _is_rate_limited(client_ip):
        logger.warning(f"Rate limit exceeded for IP {client_ip}")
        return jsonify({"error": "Rate limit exceeded. Maximum 100 uploads per hour."}), 429

    uploaded_file = request.files.get("file")
    if uploaded_file is None or uploaded_file.filename == "":
        logger.warning(f"Upload rejected: no file provided from {client_ip}")
        return jsonify({"error": "No file provided"}), 400

    if not is_allowed_file(uploaded_file.filename):
        logger.warning(f"Upload rejected: invalid extension {uploaded_file.filename}")
        return jsonify({"error": "Only .pptx files are supported"}), 400

    # Check file size before saving
    content_length = request.content_length
    if content_length and content_length > MAX_FILE_SIZE_BYTES:
        logger.warning(f"Upload rejected: file too large ({content_length} bytes) from {client_ip}")
        return jsonify({
            "error": f"File too large. Maximum size is {int(MAX_FILE_SIZE_BYTES / 1024 / 1024)}MB"
        }), 413

    original_name = secure_filename(uploaded_file.filename)
    unique_name = f"{uuid4().hex}_{original_name}"
    file_path = UPLOAD_FOLDER / unique_name
    
    try:
        uploaded_file.save(file_path)
        
        # Validate file is actual PPTX (basic check)
        if file_path.stat().st_size == 0:
            file_path.unlink()
            logger.warning("Upload rejected: empty file")
            return jsonify({"error": "File is empty"}), 400
        
        job_id, mode = enqueue_job(file_path)
        logger.info(f"File {original_name} uploaded and queued as {job_id}")
        return jsonify({"job_id": job_id, "mode": mode}), 202
    except Exception as exc:
        logger.error(f"Upload failed: {exc}", exc_info=True)
        if file_path.exists():
            file_path.unlink()
        return jsonify({"error": "Upload failed"}), 500


@app.get("/status/<job_id>")
def get_status(job_id: str):
    """Get the current status of a processing job."""
    if not QUEUE_ENABLED:
        job = _get_local_job(job_id)
        if job is None:
            logger.warning(f"Status check for non-existent local job {job_id}")
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
        logger.debug(f"Fetched Redis job {job_id}, status: {job.get_status()}")
    except Exception as exc:
        logger.warning(f"Status check failed for Redis job {job_id}: {exc}")
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
        error_msg = str(job.exc_info).splitlines()[-1] if job.exc_info else "Unknown worker error"
        response["error"] = error_msg
        logger.error(f"Job {job_id} failed: {error_msg}")

    return jsonify(response)


@app.delete("/job/<job_id>")
def cancel_job(job_id: str):
    """Cancel a pending or running job."""
    logger.info(f"Cancel request for job {job_id}")
    
    if not QUEUE_ENABLED:
        job = _get_local_job(job_id)
        if job is None:
            logger.warning(f"Cancel failed: local job {job_id} not found")
            return jsonify({"error": "Job not found"}), 404
        
        # Can only cancel queued jobs
        if job["status"] != "queued":
            logger.warning(f"Cannot cancel job {job_id}: status is {job['status']}")
            return jsonify({"error": f"Cannot cancel job with status {job['status']}"}), 409
        
        with local_jobs_lock:
            del local_jobs[job_id]
        delete_job(job_id)
        logger.info(f"Local job {job_id} cancelled")
        return jsonify({"status": "cancelled"}), 200

    try:
        job = Job.fetch(job_id, connection=redis_conn)
        if job.is_finished or job.is_failed:
            logger.warning(f"Cannot cancel job {job_id}: already {job.get_status()}")
            return jsonify({"error": f"Cannot cancel job with status {job.get_status()}"}), 409
        
        job.cancel()
        delete_job(job_id)
        logger.info(f"Redis job {job_id} cancelled")
        return jsonify({"status": "cancelled"}), 200
    except Exception as exc:
        logger.error(f"Cancel failed for job {job_id}: {exc}")
        return jsonify({"error": "Job not found"}), 404


@app.get("/download/<job_id>")
def download_result(job_id: str):
    """Download the enhanced presentation file."""
    logger.info(f"Download request for job {job_id}")
    
    if not QUEUE_ENABLED:
        job = _get_local_job(job_id)
        if job is None:
            logger.warning(f"Download failed: local job {job_id} not found")
            return jsonify({"error": "Job not found"}), 404
        if job["status"] != "finished" or not isinstance(job.get("result"), dict):
            logger.warning(f"Download failed: job {job_id} not ready (status: {job['status']})")
            return jsonify({"error": "Processed file is not ready"}), 409

        output_path = Path(job["result"]["output_path"])
        if not output_path.exists() or output_path.parent != OUTPUT_FOLDER:
            logger.error(f"Download failed: output file invalid for job {job_id}")
            return jsonify({"error": "Output file not available"}), 404

        logger.info(f"Downloading local job {job_id}: {output_path.name}")
        return send_file(output_path, as_attachment=True, download_name=output_path.name)

    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception:
        logger.warning(f"Download failed: Redis job {job_id} not found")
        return jsonify({"error": "Job not found"}), 404

    if not job.is_finished or not isinstance(job.result, dict):
        logger.warning(f"Download failed: Redis job {job_id} not ready (status: {job.get_status()})")
        return jsonify({"error": "Processed file is not ready"}), 409

    output_path = Path(job.result["output_path"])
    if not output_path.exists() or output_path.parent != OUTPUT_FOLDER:
        logger.error(f"Download failed: output file invalid for job {job_id}")
        return jsonify({"error": "Output file not available"}), 404

    logger.info(f"Downloading Redis job {job_id}: {output_path.name}")
    return send_file(output_path, as_attachment=True, download_name=output_path.name)


if __name__ == "__main__":
    logger.info("Starting AI PPT Enhancement Engine")
    
    # Run initial cleanup
    cleanup_old_files()
    
    # Start background cleanup thread
    def periodic_cleanup():
        """Periodically clean up old files."""
        import time
        while True:
            try:
                time.sleep(3600)  # Every hour
                cleanup_old_files()
            except Exception as exc:
                logger.error(f"Cleanup task failed: {exc}")
    
    cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
    cleanup_thread.start()
    logger.info("Periodic cleanup thread started")
    
    app.run(host="0.0.0.0", port=5000, debug=False)
