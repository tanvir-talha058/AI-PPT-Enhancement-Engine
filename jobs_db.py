"""Job persistence and tracking using SQLite."""

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from config import BASE_DIR, setup_logging

logger = setup_logging(__name__)

DB_PATH = BASE_DIR / "jobs.db"


def init_db() -> None:
    """Initialize the jobs database with schema."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            file_path TEXT NOT NULL,
            output_path TEXT,
            result_json TEXT,
            error_message TEXT,
            mode TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            cleanup_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    logger.debug("Jobs database initialized")


def save_job(
    job_id: str,
    status: str,
    file_path: str,
    mode: str,
    output_path: Optional[str] = None,
    result_json: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Store or update a job record."""
    now = datetime.now(timezone.utc).isoformat()
    cleanup_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO jobs 
        (job_id, status, file_path, output_path, result_json, error_message, mode, created_at, updated_at, cleanup_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM jobs WHERE job_id = ?), ?), ?, ?)
        """,
        (
            job_id,
            status,
            file_path,
            output_path,
            result_json,
            error_message,
            mode,
            job_id,
            now,
            now,
            cleanup_at,
        ),
    )
    conn.commit()
    conn.close()
    logger.debug(f"Job {job_id} saved with status {status}")


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    """Retrieve a job record by ID."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row is None:
        return None
    return dict(row)


def delete_job(job_id: str) -> bool:
    """Delete a job record."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    
    if success:
        logger.info(f"Job {job_id} deleted from database")
    return success


def cleanup_expired_jobs() -> None:
    """Remove jobs marked for cleanup that have passed their cleanup_at time."""
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT job_id FROM jobs WHERE cleanup_at IS NOT NULL AND cleanup_at < ?", (now,))
    expired = cursor.fetchall()
    
    for (job_id,) in expired:
        cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
    
    conn.commit()
    conn.close()
    
    if expired:
        logger.info(f"Cleaned up {len(expired)} expired jobs from database")
