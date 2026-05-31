"""
Unit tests for Cache Manager

Tests:
- Basic get/set operations
- TTL expiration
- LRU eviction
- Cache statistics
- Thread safety
- Disabled cache behavior

Reference: Workstream 5, Task 1
"""

import pytest
import time
from unittest.mock import patch
from app.utils.cache_manager import CacheManager


class TestCacheManager:
    """Test suite for CacheManager"""
    
    def test_cache_set_and_get(self):
        """Test basic set and get operations"""
        cache = CacheManager(enabled=True)
        
        # Set value
        cache.set("test_key", "test_value", ttl=60)
        
        # Get value
        value = cache.get("test_key")
        assert value == "test_value"
    
    def test_cache_miss(self):
        """Test cache miss returns None"""
        cache = CacheManager(enabled=True)
        
        # Get non-existent key
        value = cache.get("nonexistent_key")
        assert value is None
    
    def test_cache_ttl_expiration(self):
        """Test TTL expiration removes entries"""
        cache = CacheManager(enabled=True)
        
        # Set value with 1 second TTL
        cache.set("test_key", "test_value", ttl=1)
        
        # Immediately get - should exist
        value = cache.get("test_key")
        assert value == "test_value"
        
        # Wait for expiration
        time.sleep(1.1)
        
        # Get after expiration - should be None
        value = cache.get("test_key")
        assert value is None
    
    def test_cache_invalidate(self):
        """Test manual cache invalidation"""
        cache = CacheManager(enabled=True)
        
        # Set value
        cache.set("test_key", "test_value", ttl=60)
        
        # Invalidate
        result = cache.invalidate("test_key")
        assert result is True
        
        # Get after invalidation - should be None
        value = cache.get("test_key")
        assert value is None
        
        # Invalidate non-existent key
        result = cache.invalidate("nonexistent_key")
        assert result is False
    
    def test_cache_clear(self):
        """Test clearing all cache entries"""
        cache = CacheManager(enabled=True)
        
        # Set multiple values
        cache.set("key1", "value1", ttl=60)
        cache.set("key2", "value2", ttl=60)
        cache.set("key3", "value3", ttl=60)
        
        # Clear cache
        cache.clear()
        
        # All keys should be gone
        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert cache.get("key3") is None
    
    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full"""
        cache = CacheManager(enabled=True, max_size=3)
        
        # Fill cache to max size
        cache.set("key1", "value1", ttl=60)
        cache.set("key2", "value2", ttl=60)
        cache.set("key3", "value3", ttl=60)
        
        # Access key1 and key2 to update their last_access time
        cache.get("key1")
        cache.get("key2")
        
        # Add new key - should evict key3 (least recently used)
        cache.set("key4", "value4", ttl=60)
        
        # key3 should be evicted
        assert cache.get("key3") is None
        
        # Other keys should still exist
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("key4") == "value4"
    
    def test_cache_disabled(self):
        """Test cache behavior when disabled"""
        cache = CacheManager(enabled=False)
        
        # Set value
        cache.set("test_key", "test_value", ttl=60)
        
        # Get should return None (cache disabled)
        value = cache.get("test_key")
        assert value is None
        
        # Invalidate should return False
        result = cache.invalidate("test_key")
        assert result is False
    
    def test_cache_stats(self):
        """Test cache statistics tracking"""
        cache = CacheManager(enabled=True)
        
        # Set values
        cache.set("key1", "value1", ttl=60)
        cache.set("key2", "value2", ttl=60)
        
        # Generate hits and misses
        cache.get("key1")  # Hit
        cache.get("key1")  # Hit
        cache.get("key3")  # Miss
        cache.get("key4")  # Miss
        
        # Get stats
        stats = cache.get_stats()
        
        assert stats["enabled"] is True
        assert stats["size"] == 2
        assert stats["hits"] == 2
        assert stats["misses"] == 2
        assert stats["total_requests"] == 4
        assert stats["hit_rate_percent"] == 50.0
    
    def test_cache_reset_stats(self):
        """Test resetting cache statistics"""
        cache = CacheManager(enabled=True)
        
        # Generate some stats
        cache.set("key1", "value1", ttl=60)
        cache.get("key1")
        cache.get("key2")
        
        # Reset stats
        cache.reset_stats()
        
        # Stats should be reset
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["total_requests"] == 0
    
    def test_cache_default_ttl(self):
        """Test default TTL is used when not specified"""
        cache = CacheManager(enabled=True, default_ttl=2)
        
        # Set without TTL (should use default)
        cache.set("test_key", "test_value")
        
        # Should exist immediately
        assert cache.get("test_key") == "test_value"
        
        # Wait for default TTL to expire
        time.sleep(2.1)
        
        # Should be expired
        assert cache.get("test_key") is None
    
    def test_cache_update_existing_key(self):
        """Test updating an existing cache key"""
        cache = CacheManager(enabled=True)
        
        # Set initial value
        cache.set("test_key", "value1", ttl=60)
        assert cache.get("test_key") == "value1"
        
        # Update value
        cache.set("test_key", "value2", ttl=60)
        assert cache.get("test_key") == "value2"
    
    def test_cache_complex_values(self):
        """Test caching complex data types"""
        cache = CacheManager(enabled=True)
        
        # Test dict
        dict_value = {"name": "test", "count": 42}
        cache.set("dict_key", dict_value, ttl=60)
        assert cache.get("dict_key") == dict_value
        
        # Test list
        list_value = [1, 2, 3, 4, 5]
        cache.set("list_key", list_value, ttl=60)
        assert cache.get("list_key") == list_value
        
        # Test nested structure
        nested_value = {
            "agents": [
                {"id": "agent1", "status": "active"},
                {"id": "agent2", "status": "inactive"}
            ]
        }
        cache.set("nested_key", nested_value, ttl=60)
        assert cache.get("nested_key") == nested_value


class TestCacheManagerSingleton:
    """Test singleton pattern for global cache instance"""
    
    def test_get_cache_manager_singleton(self):
        """Test get_cache_manager returns same instance"""
        from app.utils.cache_manager import get_cache_manager, _cache_instance
        
        # Reset global instance
        import app.utils.cache_manager as cache_module
        cache_module._cache_instance = None
        
        # Mock settings. cache_manager.py imports settings lazily inside
        # get_cache_manager (`from app.config import settings`) to avoid a
        # circular dependency, so we patch the attributes on the actual
        # settings instance, not at the cache_manager module level.
        from app.config import settings as _settings
        with patch.object(_settings, 'cache_enabled', True), \
             patch.object(_settings, 'max_cache_size', 1000):
            
            # Get instance twice
            cache1 = get_cache_manager()
            cache2 = get_cache_manager()
            
            # Should be same instance
            assert cache1 is cache2
    
    def test_get_cache_manager_with_overrides(self):
        """Test get_cache_manager with parameter overrides"""
        from app.utils.cache_manager import get_cache_manager
        
        # Reset global instance
        import app.utils.cache_manager as cache_module
        cache_module._cache_instance = None
        
        # Mock settings. cache_manager.py imports settings lazily inside
        # get_cache_manager (`from app.config import settings`) to avoid a
        # circular dependency, so we patch the attributes on the actual
        # settings instance, not at the cache_manager module level.
        from app.config import settings as _settings
        with patch.object(_settings, 'cache_enabled', True), \
             patch.object(_settings, 'max_cache_size', 1000):
            
            # Get instance with overrides
            cache = get_cache_manager(enabled=False, max_size=500)
            
            # Should use overridden values
            assert cache._enabled is False
            assert cache._max_size == 500


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
