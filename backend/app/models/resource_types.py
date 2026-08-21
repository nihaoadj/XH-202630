"""Canonical public resource-type vocabulary shared by API and Agents."""

from __future__ import annotations


SUPPORTED_RESOURCE_TYPES = ("讲义", "实操指南", "分阶测试题")
RESOURCE_TYPE_ALIASES: dict[str, str] = {"定制讲义": "讲义"}


def canonical_resource_type(resource_type: str) -> str:
    normalized = str(resource_type or "").strip()
    normalized = RESOURCE_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in SUPPORTED_RESOURCE_TYPES:
        raise ValueError(f"unsupported resource_type: {normalized or '<blank>'}")
    return normalized
