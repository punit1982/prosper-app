"""
Bounded parallel fetching
=========================
Every data source in Prosper (yfinance, Finnhub, RSS, FX…) is fetched in a
thread pool with a timeout. The classic pattern

    with ThreadPoolExecutor() as pool:
        for f in as_completed(futures, timeout=30): ...

does NOT actually bound the wait: leaving the `with` block calls
`pool.shutdown(wait=True)`, which blocks until every thread finishes — so one
hung ticker could freeze a page for minutes. `gather()` below returns as soon as
the deadline passes and lets straggler threads finish in the background.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as _FutTimeout
from typing import Callable, Dict, Iterable, Optional, Tuple, TypeVar, Hashable

_log = logging.getLogger("prosper.parallel")

K = TypeVar("K", bound=Hashable)
R = TypeVar("R")


def gather(
    fn: Callable[..., R],
    items: Iterable[Tuple[K, tuple]],
    max_workers: int = 4,
    timeout: float = 30.0,
    per_item_timeout: Optional[float] = None,
) -> Tuple[Dict[K, R], set]:
    """Run `fn(*args)` for every (key, args) pair in parallel with a hard deadline.

    Returns (results, errored):
      results  — {key: return value} for calls that completed in time
      errored  — keys whose call raised (timed-out keys appear in neither)

    Keys that miss the deadline are simply absent so callers can retry later
    without treating them as permanent failures.
    """
    items = list(items)
    results: Dict[K, R] = {}
    errored: set = set()
    if not items:
        return results, errored

    workers = max(1, min(max_workers, len(items)))
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="prosper")
    futures = {pool.submit(fn, *args): key for key, args in items}
    try:
        for fut in as_completed(futures, timeout=timeout):
            key = futures[fut]
            try:
                results[key] = fut.result(timeout=per_item_timeout)
            except Exception as exc:  # noqa: BLE001 — one bad item must not sink the batch
                errored.add(key)
                _log.debug("parallel item %s failed: %s", key, exc)
    except _FutTimeout:
        _log.debug("parallel gather hit %.0fs deadline with %d/%d done",
                   timeout, len(results) + len(errored), len(items))
    except Exception as exc:  # noqa: BLE001
        _log.debug("parallel gather aborted: %s", exc)
    finally:
        # Do NOT wait for stragglers — that is the whole point.
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:  # Python < 3.9
            pool.shutdown(wait=False)
    return results, errored


def run_with_timeout(fn: Callable[..., R], *args, timeout: float = 5.0, default: R = None) -> R:
    """Run a single blocking call with a real timeout; return `default` on timeout/error."""
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="prosper1")
    try:
        fut = pool.submit(fn, *args)
        return fut.result(timeout=timeout)
    except Exception:
        return default
    finally:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)
