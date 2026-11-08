"""Neutral extraction has one execution entry point; Judge remains adjacent."""


def execute_extraction(*args, **kwargs):
    from .executor import execute_extraction as execute
    return execute(*args, **kwargs)


__all__ = ["execute_extraction"]
