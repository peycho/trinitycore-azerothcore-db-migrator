"""Domain errors shared by cleanup planning and execution."""

from __future__ import annotations

from typing import NoReturn


class CleanupError(Exception):
    """Cleanup failure with a stable operator-facing code and recovery hint."""

    code: str
    hint: str

    def __init__(self, code: str, message: str, hint: str = '') -> None:
        super().__init__(message)
        self.code, self.hint = code, hint


def fail(code: str, message: str, hint: str = '') -> NoReturn:
    raise CleanupError(code, message, hint)
