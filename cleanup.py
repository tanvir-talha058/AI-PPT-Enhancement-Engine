"""File cleanup utilities for managing old uploads and outputs."""

import time
from pathlib import Path

from config import FILE_CLEANUP_AGE_HOURS, OUTPUT_FOLDER, UPLOAD_FOLDER, setup_logging

logger = setup_logging(__name__)


def cleanup_old_files() -> None:
    """Remove files older than FILE_CLEANUP_AGE_HOURS from upload and output folders."""
    cutoff_time = time.time() - (FILE_CLEANUP_AGE_HOURS * 3600)
    
    for folder, folder_name in [(UPLOAD_FOLDER, "uploads"), (OUTPUT_FOLDER, "outputs")]:
        if not folder.exists():
            continue
            
        for file_path in folder.glob("*"):
            if not file_path.is_file():
                continue
                
            if file_path.stat().st_mtime < cutoff_time:
                try:
                    file_path.unlink()
                    logger.info(f"Deleted old {folder_name} file: {file_path.name}")
                except Exception as exc:
                    logger.error(f"Failed to delete {file_path}: {exc}")
