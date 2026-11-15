"""Native-path boundary for the locked Windows chroma-hnswlib 0.7.6 wheel.

Its narrow C++ file API interprets bytes using the system ANSI code page, not
UTF-8. Python/Chroma still use the original Unicode path for SQLite/metadata.
No directory, installed package, model or vector data is changed here.
"""
from functools import wraps
from importlib.metadata import version
import sys
from threading import Lock


_INSTALL_LOCK = Lock()
_MARKER = "_xh_windows_native_paths_v1"


def _native_path(value):
    if not isinstance(value, str) or value.isascii():
        return value
    try:
        return value.encode("mbcs", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(
            "This Windows HNSW wheel requires a path representable in the system "
            "ANSI code page; choose an ASCII storage path for unsupported characters"
        ) from exc


def _adapt(args, kwargs, name, position):
    if name in kwargs:
        kwargs = {**kwargs, name: _native_path(kwargs[name])}
    elif len(args) > position:
        changed = list(args)
        changed[position] = _native_path(changed[position])
        args = tuple(changed)
    return args, kwargs


def _patch_index_type(index_type):
    with _INSTALL_LOCK:
        if getattr(index_type, _MARKER, False):
            return
        original_init = index_type.init_index
        original_load = index_type.load_index

        @wraps(original_init)
        def init_index(self, *args, **kwargs):
            args, kwargs = _adapt(args, kwargs, "persistence_location", 6)
            return original_init(self, *args, **kwargs)

        @wraps(original_load)
        def load_index(self, *args, **kwargs):
            args, kwargs = _adapt(args, kwargs, "path_to_index", 0)
            return original_load(self, *args, **kwargs)

        index_type.init_index = init_index
        index_type.load_index = load_index
        setattr(index_type, _MARKER, True)


def install_windows_hnsw_paths():
    """Install once, only for the wheel whose native-path bug was reproduced."""
    if sys.platform != "win32" or version("chroma-hnswlib") != "0.7.6":
        return
    import hnswlib

    _patch_index_type(hnswlib.Index)
