"""Bounded, knowledge-base-local bilingual retrieval query aliases.

This module only produces optional keyword probes. Callers must preserve and
use the original user query for ordinary retrieval and final reranking.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.core.retrieval.knowledge_base import resolve_knowledge_base_dir_by_id


CONFIG_FILENAME = "query_aliases.json"
MAX_CONFIG_BYTES = 64 * 1024
MAX_RULES = 128
MAX_TERMS_PER_RULE = 16
MAX_TERM_CHARS = 80
MAX_ENGLISH_KEYWORDS_CHARS = 160
MAX_MATCHED_RULES = 6
MAX_PROBE_CHARS = 400
MAX_QUERY_CHARS = 8192

_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z")
_ENGLISH_KEYWORDS_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_-]*(?:\s+[A-Za-z0-9][A-Za-z0-9_-]*)*\Z"
)
_LATIN_WORD_CHAR = re.compile(r"[A-Za-z0-9_]")
_CJK_CHAR = re.compile(r"[\u4e00-\u9fff]")
_CONTROL_CHAR = re.compile(r"[\x00-\x1f\x7f]")

_EMPTY_HASHES = {
    "kb_not_found": hashlib.sha256(b"query-aliases:kb-not-found").hexdigest(),
    "kb_unavailable": hashlib.sha256(b"query-aliases:kb-unavailable").hexdigest(),
    "config_missing": hashlib.sha256(b"query-aliases:missing").hexdigest(),
    "config_unsafe_path": hashlib.sha256(b"query-aliases:unsafe-path").hexdigest(),
    "config_unreadable": hashlib.sha256(b"query-aliases:unreadable").hexdigest(),
}


def _profile(
    status: str,
    *,
    version: str = "",
    config_hash: str,
    term_count: int = 0,
) -> dict[str, str | int]:
    """Build the intentionally text-free profile contract."""
    return {
        "query_expansion_status": status,
        "query_expansion_version": version,
        "query_expansion_config_hash": config_hash,
        "query_expansion_term_count": term_count,
    }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _valid_source_term(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value == value.strip()
        and len(value) <= MAX_TERM_CHARS
        and not _CONTROL_CHAR.search(value)
    )


def _validate_config(data: object) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(data, dict) or set(data) != {"version", "rules"}:
        raise ValueError("invalid query alias config shape")

    version = data["version"]
    rules = data["rules"]
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise ValueError("invalid query alias version")
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise ValueError("invalid query alias rule count")

    validated: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("invalid query alias rule")
        keys = set(rule)
        if keys not in (
            {"match_terms", "english_keywords"},
            {"match_terms", "exclude_terms", "english_keywords"},
        ):
            raise ValueError("invalid query alias rule fields")

        match_terms = rule["match_terms"]
        exclude_terms = rule.get("exclude_terms", [])
        english_keywords = rule["english_keywords"]
        if (
            not isinstance(match_terms, list)
            or not 1 <= len(match_terms) <= MAX_TERMS_PER_RULE
            or not all(_valid_source_term(term) for term in match_terms)
        ):
            raise ValueError("invalid query alias match terms")
        if (
            not isinstance(exclude_terms, list)
            or len(exclude_terms) > MAX_TERMS_PER_RULE
            or not all(_valid_source_term(term) for term in exclude_terms)
        ):
            raise ValueError("invalid query alias exclusions")
        if (
            not isinstance(english_keywords, str)
            or not english_keywords
            or len(english_keywords) > MAX_ENGLISH_KEYWORDS_CHARS
            or not _ENGLISH_KEYWORDS_RE.fullmatch(english_keywords)
        ):
            raise ValueError("invalid English keyword alias")

        validated.append(
            {
                "match_terms": tuple(match_terms),
                "exclude_terms": tuple(exclude_terms),
                "english_keywords": english_keywords,
            }
        )
    return version, validated


def _load_config(
    knowledge_base_id: str,
) -> tuple[list[dict[str, Any]], str, str, str]:
    """Load one fixed, size-bounded file from the resolved KB directory."""
    try:
        base_dir = resolve_knowledge_base_dir_by_id(knowledge_base_id)
    except FileNotFoundError:
        return [], "", _EMPTY_HASHES["kb_not_found"], "kb_not_found"
    except Exception:
        return [], "", _EMPTY_HASHES["kb_unavailable"], "kb_unavailable"

    try:
        root = Path(base_dir).resolve(strict=True)
        candidate = root / CONFIG_FILENAME
        config_path = candidate.resolve(strict=True)
    except FileNotFoundError:
        return [], "", _EMPTY_HASHES["config_missing"], "config_missing"
    except (OSError, RuntimeError):
        return [], "", _EMPTY_HASHES["config_unreadable"], "config_unreadable"

    # The filename is fixed, and resolving it also rejects a symlink that
    # escapes the selected knowledge-base directory.
    if config_path.parent != root or not config_path.is_file():
        return [], "", _EMPTY_HASHES["config_unsafe_path"], "config_unsafe_path"

    try:
        with config_path.open("rb") as file:
            raw = file.read(MAX_CONFIG_BYTES + 1)
    except OSError:
        return [], "", _EMPTY_HASHES["config_unreadable"], "config_unreadable"

    config_hash = hashlib.sha256(raw).hexdigest()
    if len(raw) > MAX_CONFIG_BYTES:
        return [], "oversize", config_hash, "config_too_large"

    try:
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
        version, rules = _validate_config(data)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError):
        return [], "invalid", config_hash, "config_invalid"
    return rules, version, config_hash, "loaded"


def _term_pattern(term: str) -> re.Pattern[str]:
    """Compile whitespace-flexible phrases with Latin identifier boundaries."""
    body = r"\s+".join(re.escape(part) for part in term.split())
    prefix = r"(?<![A-Za-z0-9_])" if _LATIN_WORD_CHAR.fullmatch(term[0]) else ""
    suffix = r"(?![A-Za-z0-9_])" if _LATIN_WORD_CHAR.fullmatch(term[-1]) else ""
    flags = re.IGNORECASE if any(ord(char) < 128 for char in term) else 0
    return re.compile(prefix + body + suffix, flags)


def _find_matches(
    query: str,
    rules: list[dict[str, Any]],
) -> list[tuple[int, int, int, int]]:
    """Return non-overlapping rule matches, longest phrase first."""
    rule_matches: list[tuple[int, int, int, int]] = []
    for rule_index, rule in enumerate(rules):
        if any(_term_pattern(term).search(query) for term in rule["exclude_terms"]):
            continue
        for term in rule["match_terms"]:
            match = _term_pattern(term).search(query)
            if match is not None:
                rule_matches.append(
                    (len(term), match.start(), match.end(), rule_index)
                )

    rule_matches.sort(key=lambda item: (-item[0], item[1], item[3]))
    accepted: list[tuple[int, int, int, int]] = []
    accepted_rules: set[int] = set()
    occupied: list[tuple[int, int]] = []
    for match in rule_matches:
        term_length, start, end, rule_index = match
        if rule_index in accepted_rules:
            continue
        if any(start < previous_end and previous_start < end for previous_start, previous_end in occupied):
            continue
        accepted.append(match)
        accepted_rules.add(rule_index)
        occupied.append((start, end))
        # One look-ahead match lets the caller report that the bound applied;
        # it is never included in the generated probe.
        if len(accepted) > MAX_MATCHED_RULES:
            break
    return accepted


def expand_query(
    query: str,
    knowledge_base_id: str,
) -> tuple[list[str], dict[str, str | int]]:
    """Return at most one English keyword probe plus a text-free profile.

    The returned list contains aliases only; the original query is never
    rewritten or included in this result. Configuration is loaded even for
    English-only and empty queries so callers can bind the profile fingerprint
    to the active KB configuration.
    """
    rules, version, config_hash, config_status = _load_config(knowledge_base_id)
    if config_status != "loaded":
        return [], _profile(config_status, version=version, config_hash=config_hash)
    if not isinstance(query, str) or not query.strip():
        return [], _profile("empty_query", version=version, config_hash=config_hash)
    if len(query) > MAX_QUERY_CHARS:
        return [], _profile("query_too_long", version=version, config_hash=config_hash)
    if not _CJK_CHAR.search(query):
        return [], _profile("english_query", version=version, config_hash=config_hash)

    matches = _find_matches(query, rules)
    if not matches:
        return [], _profile("no_match", version=version, config_hash=config_hash)
    match_limit_applied = len(matches) > MAX_MATCHED_RULES
    matches = matches[:MAX_MATCHED_RULES]

    alias_parts: list[str] = []
    seen_aliases: set[str] = set()
    for _length, _start, _end, rule_index in matches:
        alias = rules[rule_index]["english_keywords"]
        normalized_alias = " ".join(alias.lower().split())
        if normalized_alias in seen_aliases:
            continue
        proposed = " ".join([*alias_parts, alias])
        if len(proposed) > MAX_PROBE_CHARS:
            continue
        alias_parts.append(alias)
        seen_aliases.add(normalized_alias)

    if not alias_parts:
        return [], _profile("probe_limit", version=version, config_hash=config_hash)
    probe = " ".join(alias_parts)
    status = "expanded_limited" if match_limit_applied or len(alias_parts) < len(matches) else "expanded"
    return [probe], _profile(
        status,
        version=version,
        config_hash=config_hash,
        term_count=len(alias_parts),
    )
