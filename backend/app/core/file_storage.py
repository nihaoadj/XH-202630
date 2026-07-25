"""生成资源文件存储工具

支持文本资源与多媒体文件（PPT、视频、PDF、音频、图片）的分类存储。
文件统一存放在 backend/data/generated_resources/ 下，按资源类型分子目录。
"""
import os
import uuid
from pathlib import Path
from typing import Optional, Tuple

from app.config import get_settings, resolve_backend_path


# 资源类型到存储子目录的映射
RESOURCE_TYPE_MAP = {
    "讲义": "text",
    "实操指南": "text",
    "分阶测试题": "text",
    "text": "text",
    "ppt": "ppt",
    "video": "video",
    "pdf": "pdf",
    "audio": "audio",
    "image": "image",
}

# 常见 MIME 类型映射
MIME_TYPE_MAP = {
    "text": "text/markdown",
    "ppt": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "video": "video/mp4",
    "pdf": "application/pdf",
    "audio": "audio/mpeg",
    "image": "image/png",
}


def _get_resources_dir() -> Path:
    """获取资源根目录"""
    settings = get_settings()
    return resolve_backend_path(settings.resources_dir)


def _guess_sub_dir(resource_type: str) -> str:
    """根据资源类型判断应存放的子目录"""
    return RESOURCE_TYPE_MAP.get(resource_type.lower(), "text")


def _guess_mime_type(resource_type: str) -> str:
    """根据资源类型推断 MIME 类型"""
    sub_dir = _guess_sub_dir(resource_type)
    return MIME_TYPE_MAP.get(sub_dir, "application/octet-stream")


def _guess_extension(resource_type: str) -> str:
    """根据资源类型推断文件扩展名"""
    ext_map = {
        "text": ".md",
        "ppt": ".pptx",
        "video": ".mp4",
        "pdf": ".pdf",
        "audio": ".mp3",
        "image": ".png",
    }
    sub_dir = _guess_sub_dir(resource_type)
    return ext_map.get(sub_dir, ".bin")


def save_resource_file(
    learner_id: str,
    resource_type: str,
    content: bytes,
    resource_id: Optional[str] = None,
) -> Tuple[str, int, str]:
    """保存文件类资源到磁盘

    Args:
        learner_id: 学习者 ID
        resource_type: 资源类型
        content: 文件二进制内容
        resource_id: 可选资源 ID，未提供则自动生成

    Returns:
        (file_path, file_size, mime_type)
        file_path 为相对于 backend 目录的相对路径，便于存入数据库与返回前端
    """
    if resource_id is None:
        resource_id = str(uuid.uuid4())

    sub_dir = _guess_sub_dir(resource_type)
    ext = _guess_extension(resource_type)
    mime_type = _guess_mime_type(resource_type)

    resources_dir = _get_resources_dir()
    target_dir = resources_dir / sub_dir / learner_id
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{resource_id}{ext}"
    file_path = target_dir / filename

    with open(file_path, "wb") as f:
        f.write(content)

    file_size = os.path.getsize(file_path)

    # 返回相对路径，便于数据库保存与 API 返回
    relative_path = str(Path("data/generated_resources") / sub_dir / learner_id / filename)
    return relative_path, file_size, mime_type


def save_text_resource(
    learner_id: str,
    resource_type: str,
    text: str,
    resource_id: Optional[str] = None,
) -> Tuple[str, int, str]:
    """保存文本类资源到磁盘，返回文件路径信息"""
    return save_resource_file(learner_id, resource_type, text.encode("utf-8"), resource_id)


def load_resource_file(relative_path: str) -> bytes:
    """根据相对路径读取资源文件内容"""
    full_path = resolve_backend_path(relative_path)
    resources_dir = _get_resources_dir().resolve()
    try:
        full_path.relative_to(resources_dir)
    except ValueError as exc:
        raise ValueError("资源文件路径不在受控目录内") from exc
    with open(full_path, "rb") as f:
        return f.read()
