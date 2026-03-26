#!/usr/bin/env python3
"""
Cleanup utility to remove unnecessary files and directories from the workspace.
Run with: python cleanup_workspace.py
"""

import os
import shutil
from pathlib import Path

REMOVABLE_ITEMS = [
    "__pycache__",
    ".env.example",
    "plan.md",
    "jobs.db",
]

CLEARABLE_DIRS = [
    "uploads",
    "outputs",
    "logs",
]


def cleanup():
    """Remove unnecessary files and clear runtime directories."""
    workspace = Path(__file__).parent
    cleaned = []
    failed = []

    # Remove files and directories
    for item in REMOVABLE_ITEMS:
        path = workspace / item
        try:
            if path.is_dir():
                shutil.rmtree(path)
                cleaned.append(f"✓ Removed directory: {item}")
            elif path.is_file():
                path.unlink()
                cleaned.append(f"✓ Removed file: {item}")
        except Exception as e:
            failed.append(f"✗ Failed to remove {item}: {e}")

    # Clear directories (keep them)
    for dir_name in CLEARABLE_DIRS:
        dir_path = workspace / dir_name
        try:
            if dir_path.exists():
                for item in dir_path.iterdir():
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                cleaned.append(f"✓ Cleared directory: {dir_name}/")
        except Exception as e:
            failed.append(f"✗ Failed to clear {dir_name}: {e}")

    # Print results
    print("\n=== Cleanup Results ===\n")
    for msg in cleaned:
        print(msg)
    for msg in failed:
        print(msg)

    if not failed:
        print("\n✓ Workspace cleanup complete!")
    else:
        print(f"\n⚠ {len(failed)} item(s) could not be cleaned.")


if __name__ == "__main__":
    cleanup()
