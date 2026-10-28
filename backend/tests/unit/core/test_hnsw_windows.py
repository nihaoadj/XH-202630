"""Windows HNSW path compatibility, including a new-process reload."""
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
import os
import subprocess
import sys

import numpy as np
import pytest

from app.core.retrieval import hnsw_windows as compat
from tests.paths import BACKEND_ROOT


def _fake():
    class Index:
        def init_index(self, *args, **kwargs):
            return args, kwargs

        def load_index(self, *args, **kwargs):
            return args, kwargs

    return Index


def test_persistent_paths_only_are_adapted_preserving_arguments(monkeypatch):
    monkeypatch.setattr(compat, "_native_path", lambda p: b"native" if p == "C:/中文" else p)
    index_type = _fake()
    compat._patch_index_type(index_type)
    instance = index_type()
    assert instance.init_index(100, persistence_location="C:/中文", M=24) == ((100,), {"persistence_location": b"native", "M": 24})
    assert instance.init_index(100, 16, 200, 100, False, True, "C:/中文")[0][-1] == b"native"
    assert instance.load_index("C:/中文", max_elements=100) == ((b"native",), {"max_elements": 100})
    assert instance.load_index(path_to_index="C:/中文")[1]["path_to_index"] == b"native"
    assert instance.init_index(100, 32, 200) == ((100, 32, 200), {})


def test_install_is_thread_safe_and_idempotent():
    index_type = _fake()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: compat._patch_index_type(index_type), range(32)))
    wrapped = index_type.init_index
    compat._patch_index_type(index_type)
    assert index_type.init_index is wrapped
    assert index_type().load_index("C:/ascii") == (("C:/ascii",), {})


@pytest.mark.parametrize("value", ["C:/ascii", b"already-native", None, 123])
def test_ascii_bytes_and_invalid_types_preserve_original_behavior(value):
    assert compat._native_path(value) is value


def test_platform_and_version_are_strictly_scoped(monkeypatch):
    patched = []
    monkeypatch.setattr(compat, "_patch_index_type", lambda t: patched.append(t))
    monkeypatch.setattr(compat.sys, "platform", "linux")
    compat.install_windows_hnsw_paths()
    assert not patched
    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setattr(compat, "version", lambda _: "future-fixed-version")
    compat.install_windows_hnsw_paths()
    assert not patched


@pytest.mark.skipif(sys.platform != "win32", reason="Windows system ANSI codec")
def test_native_codec_encodes_representable_paths_and_rejects_unsupported():
    value = "C:/中文"
    try:
        expected = value.encode("mbcs")
    except UnicodeEncodeError:
        with pytest.raises(ValueError, match="ANSI code page"):
            compat._native_path(value)
    else:
        assert compat._native_path(value) == expected
    # UTF-8 ACP can represent everything; legacy ACP rejects an unpaired
    # surrogate too, providing a portable explicit-error case.
    with pytest.raises(ValueError, match="ANSI code page"):
        compat._native_path("C:/\ud800")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native HNSW path regression")
def test_real_unicode_index_writes_four_files_and_loads_in_fresh_process(tmp_path):
    if version("chroma-hnswlib") != "0.7.6":
        pytest.skip("workaround only applies to the locked 0.7.6 wheel")
    try:
        "中文索引".encode("mbcs")
    except UnicodeEncodeError:
        pytest.skip("Chinese not representable in this Windows ACP; explicit rejection tested")
    import hnswlib

    compat.install_windows_hnsw_paths()
    path = tmp_path / "中文索引"
    path.mkdir()
    index = hnswlib.Index(space="cosine", dim=2)
    index.init_index(max_elements=10, is_persistent_index=True, persistence_location=str(path))
    index.add_items(np.array([[1., 0.]], dtype=np.float32), [7])
    index.persist_dirty()
    index.close_file_handles()
    assert {"header.bin", "data_level0.bin", "length.bin", "link_lists.bin"} <= {p.name for p in path.iterdir()}
    code = (
        "import sys,numpy as np,hnswlib; "
        "from app.core.retrieval.hnsw_windows import install_windows_hnsw_paths; "
        "install_windows_hnsw_paths(); i=hnswlib.Index(space='cosine',dim=2); "
        "i.load_index(sys.argv[1],is_persistent_index=True); "
        "assert i.get_current_count()==1; "
        "assert i.knn_query(np.array([[1.,0.]],dtype=np.float32),k=1)[0].tolist()==[[7]]; "
        "i.close_file_handles(); print('fresh-process reload passed')"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    result = subprocess.run([sys.executable, "-c", code, str(path)], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "fresh-process reload passed" in result.stdout
