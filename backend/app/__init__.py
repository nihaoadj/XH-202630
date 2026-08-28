"""Application package initialization and runtime compatibility hooks.

The current dependency set still includes LangChain/LangSmith components that
use Pydantic v1's ``ForwardRef`` helper.  Python 3.13 made the
``type_params`` argument mandatory (and warns before it becomes an error in
Python 3.15).  Patch only Pydantic's compatibility helper at application
startup so the legacy dependency remains functional without emitting a
deprecation warning.  This can be removed once the dependency stack no longer
uses ``pydantic.v1``.
"""

from __future__ import annotations

import sys
from typing import Any, cast


def _patch_pydantic_v1_forwardref() -> None:
    if sys.version_info < (3, 13):
        return
    try:
        from pydantic.v1 import typing as pydantic_typing
    except ImportError:
        return

    current = pydantic_typing.evaluate_forwardref
    if getattr(current, "__module__", "") == __name__:
        return

    def evaluate_forwardref(type_: Any, globalns: Any, localns: Any) -> Any:
        return cast(Any, type_)._evaluate(
            globalns,
            localns,
            type_params=(),
            recursive_guard=set(),
        )

    pydantic_typing.evaluate_forwardref = evaluate_forwardref


_patch_pydantic_v1_forwardref()
