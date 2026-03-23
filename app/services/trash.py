"""Move files/folders to .trash inside media_root instead of permanent deletion."""
from __future__ import annotations
import shutil
from pathlib import Path


def _trash_target(path: Path, media_root: Path) -> Path:
    """Return the destination path inside .trash, preserving relative structure."""
    rel = path.relative_to(media_root)
    return media_root / ".trash" / rel


def empty_trash(media_root: Path) -> int:
    """Permanently delete everything inside .trash. Returns count of items removed."""
    trash_dir = media_root / ".trash"
    if not trash_dir.exists():
        return 0
    count = 0
    for item in trash_dir.iterdir():
        shutil.rmtree(item) if item.is_dir() else item.unlink()
        count += 1
    return count


def move_to_trash(path: Path, media_root: Path) -> Path:
    """Move path (file or directory) to .trash. Returns new location."""
    target = _trash_target(path, media_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # Avoid collision — append a counter suffix
        i = 1
        while target.exists():
            target = target.with_name(f"{target.name}.{i}")
            i += 1
    shutil.move(str(path), target)
    return target
