"""
AI Response Caching Decorator
==============================
Reusable decorator for caching Claude API responses with TTL.

Usage:
  @ai_cache_decorator(ttl_days=7)
  def get_news_summary(title: str, ticker: str) -> str:
      return call_claude_api(...)

  result = get_news_summary("Apple beats earnings", "AAPL")
  # First call: hits Claude API, saves to cache
  # Second call (same args, within 7 days): returns cached result instantly
"""

import hashlib
from functools import wraps
from typing import Callable, Any
from core.database import get_ai_cache, save_ai_cache


def ai_cache_decorator(ttl_days: int = 7, namespace: str = ""):
    """
    Decorator to cache AI function results with TTL.

    Args:
        ttl_days: Cache expiration time in days (default: 7)
        namespace: Optional prefix for cache key (e.g., "news", "analyst")

    Example:
        @ai_cache_decorator(ttl_days=7, namespace="news")
        def summarize_news(title: str, publisher: str) -> str:
            return call_claude(...)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Build deterministic cache key from function name + args + kwargs
            cache_input = f"{namespace}|{func.__name__}|{str(args)}|{str(sorted(kwargs.items()))}"
            call_hash = hashlib.sha256(cache_input.encode()).hexdigest()

            # Check cache first
            cached = get_ai_cache(call_hash, ttl_days=ttl_days)
            if cached:
                return cached

            # Cache miss — call function
            result = func(*args, **kwargs)

            # Save to cache if result is not None
            if result is not None:
                save_ai_cache(call_hash, str(result), ttl_days=ttl_days)

            return result

        return wrapper
    return decorator
