"""Direct physical path safety; no historical path alias compatibility."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.core.retrieval.knowledge_paths import resolve_knowledge_file

@pytest.mark.parametrize("value", ["../x", "/x", "C:/x", "a/../x", "a\\x", ""])
def test_rejects_escape(value, tmp_path):
    with pytest.raises(ValueError):
        resolve_knowledge_file(tmp_path, value)

def test_missing_and_direct_paths(tmp_path):
    path = tmp_path/"content.md"
    path.write_text("正文", encoding="utf-8")
    assert resolve_knowledge_file(tmp_path, "content.md") == path
    assert resolve_knowledge_file(tmp_path, "future.md", must_exist=False) == tmp_path/"future.md"
    with pytest.raises(FileNotFoundError):
        resolve_knowledge_file(tmp_path, "future.md")

def test_reparse_point_rejected_without_symlink_privilege(tmp_path, monkeypatch):
    path = tmp_path/"content.md"
    path.write_text("正文", encoding="utf-8")
    original = Path.lstat
    def reparse(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=1024) if self == path else result
    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ValueError, match="reparse"):
        resolve_knowledge_file(tmp_path, "content.md")
