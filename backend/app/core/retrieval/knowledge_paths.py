"""Confined physical file paths for the purpose/language/source layout."""
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat

LAYOUT_VERSION = "purpose_language_source_v1"

def resolve_knowledge_file(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("knowledge path must be POSIX relative")
    if PurePosixPath(relative).is_absolute() or PureWindowsPath(relative).drive or any(p in {"", ".", ".."} for p in relative.split("/")):
        raise ValueError("knowledge path escapes its root")
    root = Path(root).resolve()
    target = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink() or (current.exists() and getattr(current.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)):
            raise ValueError("knowledge path may not traverse reparse points")
    if not target.resolve(strict=False).is_relative_to(root):
        raise ValueError("knowledge path escapes its root")
    if target.exists() and not target.is_file():
        raise ValueError("knowledge asset must be a regular file")
    if must_exist and not target.is_file():
        raise FileNotFoundError(relative)
    return target
