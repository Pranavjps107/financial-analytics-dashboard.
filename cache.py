
import redis
import json
import pickle
from typing import Any, Optional
import os

class CacheClient:
    """Redis-based caching client"""
    
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        
        try:
            self.client = redis.from_url(self.redis_url, decode_responses=True)
            # Test connection
            self.client.ping()
            self.enabled = True
            logger.info("Redis cache client initialized")
        except Exception as e:
            self.client = None
            self.enabled = False
            logger.warning(f"Redis not available: {e}")
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not self.enabled:
            return None
        
        try:
            data = self.client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """Set value in cache with TTL"""
        if not self.enabled:
            return False
        
        try:
            self.client.setex(key, ttl, json.dumps(value, default=str))
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self.enabled:
            return False
        
        try:
            self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    def get_cache_key(self, symbol: str, endpoint: str) -> str:
        """Generate cache key"""
        return f"stock_data:{symbol}:{endpoint}"

# Global cache client
cache_client = CacheClient()