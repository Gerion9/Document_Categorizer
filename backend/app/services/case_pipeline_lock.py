"""In-process per-case lock for OCR and indexing work.

This serializes expensive case-level OCR/indexing flows while the backend runs
with a single worker. If production scales to multiple workers or hosts, replace
this with a distributed lock such as PostgreSQL advisory locks or Redis SETNX.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


_REGISTRY_LOCK = threading.Lock()
_CASE_LOCKS: dict[str, threading.Lock] = {}


class CasePipelineBusy(RuntimeError):
    """Raised when another OCR/indexing pipeline is already running for a case."""

    def __init__(self, case_id: str) -> None:
        super().__init__(f"Case pipeline already running for case {case_id}")
        self.case_id = case_id


def _get_lock(case_id: str) -> threading.Lock:
    normalized_case_id = str(case_id or "").strip()
    with _REGISTRY_LOCK:
        lock = _CASE_LOCKS.get(normalized_case_id)
        if lock is None:
            lock = threading.Lock()
            _CASE_LOCKS[normalized_case_id] = lock
        return lock


@contextmanager
def case_pipeline_lock(
    case_id: str,
    *,
    blocking: bool = True,
    timeout: float = -1,
) -> Iterator[None]:
    """Acquire the case-level OCR/indexing lock.

    `timeout` is only meaningful for blocking acquisition. Non-blocking calls
    intentionally skip timeout because `threading.Lock` rejects that combination.
    """

    lock = _get_lock(case_id)
    acquired = lock.acquire(timeout=timeout) if blocking else lock.acquire(blocking=False)
    if not acquired:
        raise CasePipelineBusy(case_id)
    try:
        yield
    finally:
        lock.release()
