"""Opt-in QC timings: operation names/counts only, never URLs, tokens or payloads."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4
import json
import logging

_current = ContextVar('qc_performance', default=None)
logger = logging.getLogger('uvicorn.error')


def trace_id():
    current = _current.get()
    return current[0] if current else ''


def enabled():
    return _current.get() is not None


@contextmanager
def trace(operation):
    entries = []
    token = _current.set((uuid4().hex, entries))
    try:
        with measure(operation):
            yield entries
    finally:
        _current.reset(token)


def record(operation, elapsed, ok=True, **counts):
    current = _current.get()
    if current is None:
        return
    identifier, entries = current
    item = {'operation':operation,'ms':round(elapsed * 1000, 3),'ok':ok,**counts}
    entries.append(item)
    logger.info('QC_PERF %s', json.dumps({'trace':identifier,**item}, separators=(',', ':')))


@contextmanager
def measure(operation, **counts):
    start, ok = perf_counter(), False
    try:
        yield
        ok = True
    finally:
        record(operation, perf_counter() - start, ok, **counts)
