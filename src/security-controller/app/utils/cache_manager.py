"""
Cache Manager - TTL-based in-memory caching with LRU eviction

Purpose:
- Reduce DynamoDB/CloudWatch query costs
- Improve API response times (500ms → <5ms for cached data)
- Prevent rate limiting on AWS APIs

Design:
- In-memory cache (dict-based)
- TTL-based expiration (configurable per cache key)
- LRU eviction when cache size limit reached
- Thread-safe operations
- Configurable via environment variables

Usage:
    cache = CacheManager()
    
    # Set with TTL
    cache.set("agents_list", agents_data, ttl=60)
    
    # Get (returns None if expired or not found)
    data = cache.get("agents_list")
    
    # Invalidate specific key
    cache.invalidate("agents_list")
    
    # Clear all cache
    cache.clear()

Reference: LLD 05 Section 5.2, Workstream 5 Task 1
"""

import time
import logging
from typing import Any, Optional, Dict, Tuple
from threading import Lock

logger = logging.getLogger(__name__)


class CacheManager:
    """
    TTL-based in-memory cache with LRU eviction.
    
    Thread-safe cache manager for reducing AWS API calls.
    """
    
    def __init__(
        self,
        enabled: bool = True,
        max_size: int = 1000,
        default_ttl: int = 300
    ):
        """
        Initialize cache manager.
        
        Args:
            enabled: Enable/disable caching (default: True)
            max_size: Maximum number of cached items (default: 1000)
            default_ttl: Default TTL in seconds (default: 300 = 5 minutes)
        """
        self._enabled = enabled
        self._max_size = max_size
        self._default_ttl = default_ttl
        
        # Cache storage: {key: (value, expiry_timestamp, access_seq)}
        # The 3rd element is a strictly-monotonic access sequence number, NOT a
        # wall-clock timestamp. LRU eviction picks min(access_seq); a counter
        # guarantees a total order so two entries touched within the same
        # time.time() tick can never tie (which would make eviction fall back to
        # dict-insertion order and evict the wrong key under fast execution).
        self._cache: Dict[str, Tuple[Any, float, int]] = {}
        # Monotonic access counter — bumped on every get-hit and set.
        self._access_seq = 0

        # Thread lock for thread-safe operations
        self._lock = Lock()
        
        # Metrics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        
        logger.info(
            f"CacheManager initialized: enabled={enabled}, "
            f"max_size={max_size}, default_ttl={default_ttl}s"
        )
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value if found and not expired, None otherwise
        """
        if not self._enabled:
            return None
        
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                logger.debug(f"Cache miss: {key}")
                return None
            
            value, expiry, _ = self._cache[key]
            current_time = time.time()
            
            # Check if expired
            if current_time > expiry:
                # Remove expired entry
                del self._cache[key]
                self._misses += 1
                logger.debug(f"Cache expired: {key}")
                return None
            
            # Bump the access sequence so this key becomes most-recently-used.
            self._access_seq += 1
            self._cache[key] = (value, expiry, self._access_seq)
            self._hits += 1
            logger.debug(f"Cache hit: {key}")
            return value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set value in cache with TTL.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (default: use default_ttl)
        """
        if not self._enabled:
            return
        
        ttl = ttl if ttl is not None else self._default_ttl
        current_time = time.time()
        expiry = current_time + ttl
        
        with self._lock:
            # Check if cache is full
            if key not in self._cache and len(self._cache) >= self._max_size:
                # Evict least recently used (LRU)
                self._evict_lru()

            # Bump the access sequence so a freshly-set key is most-recently-used.
            self._access_seq += 1
            self._cache[key] = (value, expiry, self._access_seq)
            logger.debug(f"Cache set: {key} (ttl={ttl}s)")
    
    def invalidate(self, key: str) -> bool:
        """
        Invalidate (remove) a specific cache entry.
        
        Args:
            key: Cache key to invalidate
            
        Returns:
            True if key was found and removed, False otherwise
        """
        if not self._enabled:
            return False
        
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"Cache invalidated: {key}")
                return True
            return False
    
    def invalidate_prefix(self, prefix: str) -> int:
        """
        Invalidate every cache entry whose key starts with ``prefix``.

        Used for targeted cache busts when a single write affects a whole family
        of cached reads (e.g. toggling one Sigma rule's status must drop both the
        per-rule entry ``sigma_rule:<id>`` AND every list entry
        ``sigma_rules:status=...:...`` so the next read reloads from DynamoDB).
        Preferred over ``clear()`` because the cache is a process-wide singleton
        shared by policies/agents/sigma — we only want to evict the affected family.

        Args:
            prefix: Key prefix to match.

        Returns:
            Number of entries removed.
        """
        if not self._enabled:
            return 0

        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._cache[k]
            if keys_to_remove:
                logger.debug(
                    f"Cache invalidated by prefix {prefix!r}: "
                    f"{len(keys_to_remove)} entries removed"
                )
            return len(keys_to_remove)
    
    def clear(self) -> None:
        """
        Clear all cache entries.
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cache cleared: {count} entries removed")
    
    def _evict_lru(self) -> None:
        """
        Evict least recently used entry (internal method).
        
        Called when cache is full and new entry needs to be added.
        """
        if not self._cache:
            return
        
        # Find entry with the lowest access_seq (least recently used). The
        # counter gives a strict total order, so no two entries can tie.
        lru_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k][2]  # access_seq
        )
        
        del self._cache[lru_key]
        self._evictions += 1
        logger.warning(
            f"Cache eviction (LRU): {lru_key} "
            f"(total evictions: {self._evictions})"
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache metrics
        """
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
            
            return {
                "enabled": self._enabled,
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate_percent": round(hit_rate, 2),
                "total_requests": total_requests,
            }
    
    def reset_stats(self) -> None:
        """
        Reset cache statistics (for testing).
        """
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            logger.debug("Cache stats reset")


# Global cache instance (singleton pattern)
_cache_instance: Optional[CacheManager] = None


def get_cache_manager(
    enabled: Optional[bool] = None,
    max_size: Optional[int] = None,
    default_ttl: Optional[int] = None
) -> CacheManager:
    """
    Get global cache manager instance (singleton).
    
    Args:
        enabled: Override enabled setting (default: from config)
        max_size: Override max size (default: from config)
        default_ttl: Override default TTL (default: from config)
        
    Returns:
        Global CacheManager instance
    """
    global _cache_instance
    
    if _cache_instance is None:
        # Import here to avoid circular dependency
        from app.config import settings
        
        _cache_instance = CacheManager(
            enabled=enabled if enabled is not None else settings.cache_enabled,
            max_size=max_size if max_size is not None else settings.max_cache_size,
            default_ttl=default_ttl if default_ttl is not None else 300
        )
    
    return _cache_instance
