"""Move files/folders to .trash inside media_root instead of permanent deletion."""
from __future__ import annotations
import datetime
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


def list_trash(media_root: Path) -> list[dict]:
    """Walk .trash/ and return artist→album→tracks hierarchy."""
    trash_dir = media_root / ".trash"
    if not trash_dir.exists():
        return []
    result = []
    for artist_dir in sorted(trash_dir.iterdir()):
        if not artist_dir.is_dir() or artist_dir.name.startswith("."):
            continue
        albums = []
        for album_dir in sorted(artist_dir.iterdir()):
            if not album_dir.is_dir() or album_dir.name.startswith("."):
                continue
            tracks = []
            for f in sorted(album_dir.iterdir()):
                if not f.is_file() or f.name.startswith("."):
                    continue
                try:
                    st = f.stat()
                    tracks.append({
                        "path": str(f),
                        "filename": f.name,
                        "size": st.st_size,
                        "trashed_at": datetime.datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d"),
                    })
                except OSError:
                    pass
            if not tracks:
                continue
            albums.append({
                "album": album_dir.name,
                "tracks": tracks,
                "total_size": sum(t["size"] for t in tracks),
                "track_count": len(tracks),
            })
        if albums:
            result.append({"artist": artist_dir.name, "albums": albums})
    return result


def _cleanup_empty_dirs(start: Path, stop: Path) -> None:
    """Remove empty directories walking upward from start toward stop."""
    current = start
    while current != stop:
        try:
            if current.is_dir() and not any(current.iterdir()):
                current.rmdir()
            else:
                break
        except OSError:
            break
        current = current.parent


def restore_path(path: str, media_root: Path) -> Path:
    """Move a trashed file back to its original location.

    Raises FileExistsError if the destination already exists.
    """
    src = Path(path)
    trash_dir = media_root / ".trash"
    rel = src.relative_to(trash_dir)
    dest = media_root / rel
    if dest.exists():
        raise FileExistsError(f"A file already exists at the original location: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    _cleanup_empty_dirs(src.parent, trash_dir)
    return dest


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
