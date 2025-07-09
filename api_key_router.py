# api_key_router.py - Multi-API Key Management System
import os
import time
import random
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import deque, defaultdict
from enum import Enum
import logging
from dataclasses import dataclass, field
import json

logger = logging.getLogger(__name__)

class APIKeyStatus(Enum):
    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    ERROR = "error"
    DISABLED = "disabled"

@dataclass
class APIKeyMetrics:
    """Track metrics for each API key"""
    key_id: str
    api_key: str
    status: APIKeyStatus = APIKeyStatus.ACTIVE
    requests_made: int = 0
    requests_successful: int = 0
    requests_failed: int = 0
    last_request_time: Optional[float] = None
    last_error_time: Optional[float] = None
    last_error_message: Optional[str] = None
    rate_limit_reset_time: Optional[float] = None
    daily_quota_used: int = 0
    daily_quota_limit: int = 500  # Alpha Vantage free tier limit
    request_history: deque = field(default_factory=lambda: deque(maxlen=100))
    
    def __post_init__(self):
        if isinstance(self.request_history, list):
            self.request_history = deque(self.request_history, maxlen=100)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.requests_made == 0:
            return 100.0
        return (self.requests_successful / self.requests_made) * 100
    
    @property
    def is_available(self) -> bool:
        """Check if API key is available for use"""
        now = time.time()
        
        # Check if disabled
        if self.status == APIKeyStatus.DISABLED:
            return False
        
        # Check if rate limited and if cooldown period has passed
        if self.status == APIKeyStatus.RATE_LIMITED:
            if self.rate_limit_reset_time and now < self.rate_limit_reset_time:
                return False
            else:
                # Reset status if cooldown period has passed
                self.status = APIKeyStatus.ACTIVE
                self.rate_limit_reset_time = None
        
        # Check daily quota
        if self.daily_quota_used >= self.daily_quota_limit:
            self.status = APIKeyStatus.QUOTA_EXCEEDED
            return False
        
        # Check if minimum time between requests has passed (12 seconds for 5 req/min)
        if self.last_request_time and (now - self.last_request_time) < 12:
            return False
        
        return self.status in [APIKeyStatus.ACTIVE, APIKeyStatus.ERROR]

class LoadBalancingStrategy(Enum):
    ROUND_ROBIN = "round_robin"
    LEAST_USED = "least_used"
    RANDOM = "random"
    BEST_PERFORMANCE = "best_performance"
    WEIGHTED = "weighted"

class APIKeyRouter:
    """Intelligent router for managing multiple Alpha Vantage API keys"""
    
    def __init__(self, 
                 api_keys: List[str], 
                 strategy: LoadBalancingStrategy = LoadBalancingStrategy.LEAST_USED,
                 max_retries: int = 3,
                 default_timeout: int = 30):
        
        self.api_keys = self._initialize_api_keys(api_keys)
        self.strategy = strategy
        self.max_retries = max_retries
        self.default_timeout = default_timeout
        
        # Round robin counter
        self._round_robin_index = 0
        
        # Performance tracking
        self.global_stats = {
            "total_requests": 0,
            "total_successes": 0,
            "total_failures": 0,
            "total_retries": 0,
            "start_time": time.time()
        }
        
        # Fallback handling
        self.fallback_enabled = True
        self.emergency_delay = 60  # 1 minute emergency delay when all keys are exhausted
        
        logger.info(f"APIKeyRouter initialized with {len(self.api_keys)} keys using {strategy.value} strategy")
    
    def _initialize_api_keys(self, api_keys: List[str]) -> Dict[str, APIKeyMetrics]:
        """Initialize API key metrics"""
        initialized_keys = {}
        
        for i, key in enumerate(api_keys):
            if key and key.strip():  # Validate non-empty keys
                key_id = f"key_{i+1}"
                initialized_keys[key_id] = APIKeyMetrics(
                    key_id=key_id,
                    api_key=key.strip()
                )
                logger.info(f"Initialized API key: {key_id} (ending in ...{key[-4:]})")
        
        if not initialized_keys:
            raise ValueError("No valid API keys provided")
        
        return initialized_keys
    
    def add_api_key(self, api_key: str, key_id: Optional[str] = None) -> str:
        """Add a new API key to the router"""
        if not api_key or not api_key.strip():
            raise ValueError("API key cannot be empty")
        
        if not key_id:
            key_id = f"key_{len(self.api_keys) + 1}"
        
        if key_id in self.api_keys:
            raise ValueError(f"Key ID {key_id} already exists")
        
        self.api_keys[key_id] = APIKeyMetrics(
            key_id=key_id,
            api_key=api_key.strip()
        )
        
        logger.info(f"Added new API key: {key_id}")
        return key_id
    
    def remove_api_key(self, key_id: str) -> bool:
        """Remove an API key from the router"""
        if key_id in self.api_keys:
            del self.api_keys[key_id]
            logger.info(f"Removed API key: {key_id}")
            return True
        return False
    
    def disable_api_key(self, key_id: str, reason: str = "Manual disable") -> bool:
        """Disable an API key"""
        if key_id in self.api_keys:
            self.api_keys[key_id].status = APIKeyStatus.DISABLED
            self.api_keys[key_id].last_error_message = reason
            logger.warning(f"Disabled API key {key_id}: {reason}")
            return True
        return False
    
    def enable_api_key(self, key_id: str) -> bool:
        """Re-enable a disabled API key"""
        if key_id in self.api_keys:
            self.api_keys[key_id].status = APIKeyStatus.ACTIVE
            self.api_keys[key_id].last_error_message = None
            logger.info(f"Enabled API key: {key_id}")
            return True
        return False
    
    def get_best_api_key(self) -> Optional[Tuple[str, APIKeyMetrics]]:
        """Get the best available API key based on the selected strategy"""
        available_keys = [
            (key_id, metrics) for key_id, metrics in self.api_keys.items()
            if metrics.is_available
        ]
        
        if not available_keys:
            logger.warning("No available API keys found")
            return None
        
        if self.strategy == LoadBalancingStrategy.ROUND_ROBIN:
            return self._round_robin_selection(available_keys)
        elif self.strategy == LoadBalancingStrategy.LEAST_USED:
            return self._least_used_selection(available_keys)
        elif self.strategy == LoadBalancingStrategy.RANDOM:
            return random.choice(available_keys)
        elif self.strategy == LoadBalancingStrategy.BEST_PERFORMANCE:
            return self._best_performance_selection(available_keys)
        elif self.strategy == LoadBalancingStrategy.WEIGHTED:
            return self._weighted_selection(available_keys)
        else:
            return available_keys[0]  # Fallback to first available
    
    def _round_robin_selection(self, available_keys: List[Tuple[str, APIKeyMetrics]]) -> Tuple[str, APIKeyMetrics]:
        """Round robin selection strategy"""
        self._round_robin_index = (self._round_robin_index + 1) % len(available_keys)
        return available_keys[self._round_robin_index]
    
    def _least_used_selection(self, available_keys: List[Tuple[str, APIKeyMetrics]]) -> Tuple[str, APIKeyMetrics]:
        """Select the least used API key"""
        return min(available_keys, key=lambda x: x[1].requests_made)
    
    def _best_performance_selection(self, available_keys: List[Tuple[str, APIKeyMetrics]]) -> Tuple[str, APIKeyMetrics]:
        """Select API key with best performance (highest success rate)"""
        return max(available_keys, key=lambda x: x[1].success_rate)
    
    def _weighted_selection(self, available_keys: List[Tuple[str, APIKeyMetrics]]) -> Tuple[str, APIKeyMetrics]:
        """Weighted selection based on success rate and usage"""
        weights = []
        for key_id, metrics in available_keys:
            # Higher success rate and lower usage = higher weight
            weight = metrics.success_rate * (1 / max(metrics.requests_made, 1))
            weights.append(weight)
        
        total_weight = sum(weights)
        if total_weight == 0:
            return random.choice(available_keys)
        
        r = random.uniform(0, total_weight)
        cumulative_weight = 0
        
        for i, (key_id, metrics) in enumerate(available_keys):
            cumulative_weight += weights[i]
            if r <= cumulative_weight:
                return key_id, metrics
        
        return available_keys[-1]  # Fallback
    
    async def execute_request(self, 
                            request_func,
                            *args, 
                            **kwargs) -> Tuple[Any, Dict[str, Any]]:
        """
        Execute a request using the best available API key with retry logic
        
        Args:
            request_func: Async function to execute
            *args, **kwargs: Arguments to pass to the request function
            
        Returns:
            Tuple of (response_data, execution_metadata)
        """
        start_time = time.time()
        last_exception = None
        attempts = []
        
        for attempt in range(self.max_retries + 1):
            # Get best available API key
            key_selection = self.get_best_api_key()
            
            if not key_selection:
                if self.fallback_enabled and attempt == 0:
                    logger.warning("No API keys available, waiting for emergency delay...")
                    await asyncio.sleep(self.emergency_delay)
                    continue
                else:
                    raise Exception("No available API keys for request execution")
            
            key_id, key_metrics = key_selection
            
            try:
                # Update request tracking
                key_metrics.requests_made += 1
                key_metrics.last_request_time = time.time()
                self.global_stats["total_requests"] += 1
                
                # Add API key to kwargs
                kwargs['apikey'] = key_metrics.api_key
                
                # Execute the request
                logger.debug(f"Executing request with {key_id} (attempt {attempt + 1})")
                
                result = await request_func(*args, **kwargs)
                
                # Record success
                key_metrics.requests_successful += 1
                key_metrics.daily_quota_used += 1
                key_metrics.status = APIKeyStatus.ACTIVE
                key_metrics.request_history.append({
                    "timestamp": time.time(),
                    "success": True,
                    "response_time": time.time() - start_time
                })
                
                self.global_stats["total_successes"] += 1
                
                # Execution metadata
                metadata = {
                    "key_id": key_id,
                    "attempt": attempt + 1,
                    "response_time_ms": (time.time() - start_time) * 1000,
                    "strategy_used": self.strategy.value,
                    "attempts": attempts + [{"key_id": key_id, "success": True}]
                }
                
                return result, metadata
                
            except Exception as e:
                # Record failure
                key_metrics.requests_failed += 1
                key_metrics.last_error_time = time.time()
                key_metrics.last_error_message = str(e)
                key_metrics.request_history.append({
                    "timestamp": time.time(),
                    "success": False,
                    "error": str(e)
                })
                
                # Handle specific errors
                error_str = str(e).lower()
                
                if "rate limit" in error_str or "too many requests" in error_str:
                    key_metrics.status = APIKeyStatus.RATE_LIMITED
                    key_metrics.rate_limit_reset_time = time.time() + 60  # 1 minute cooldown
                    logger.warning(f"Rate limit hit for {key_id}, cooling down for 60 seconds")
                    
                elif "quota" in error_str or "limit exceeded" in error_str:
                    key_metrics.status = APIKeyStatus.QUOTA_EXCEEDED
                    logger.warning(f"Quota exceeded for {key_id}")
                    
                elif "invalid api" in error_str or "unauthorized" in error_str:
                    key_metrics.status = APIKeyStatus.ERROR
                    logger.error(f"Invalid API key {key_id}: {e}")
                    
                else:
                    key_metrics.status = APIKeyStatus.ERROR
                    logger.error(f"Request failed with {key_id}: {e}")
                
                attempts.append({"key_id": key_id, "success": False, "error": str(e)})
                last_exception = e
                
                self.global_stats["total_failures"] += 1
                if attempt < self.max_retries:
                    self.global_stats["total_retries"] += 1
                    
                # Wait before retry (exponential backoff)
                if attempt < self.max_retries:
                    wait_time = min(2 ** attempt, 30)  # Max 30 seconds
                    logger.info(f"Retrying in {wait_time} seconds... (attempt {attempt + 2})")
                    await asyncio.sleep(wait_time)
        
        # All retries exhausted
        metadata = {
            "key_id": None,
            "attempt": self.max_retries + 1,
            "response_time_ms": (time.time() - start_time) * 1000,
            "strategy_used": self.strategy.value,
            "attempts": attempts,
            "final_error": str(last_exception)
        }
        
        raise Exception(f"Request failed after {self.max_retries + 1} attempts. Last error: {last_exception}")
    
    def get_router_stats(self) -> Dict[str, Any]:
        """Get comprehensive router statistics"""
        now = time.time()
        uptime = now - self.global_stats["start_time"]
        
        # Calculate global success rate
        total_requests = self.global_stats["total_requests"]
        global_success_rate = (
            (self.global_stats["total_successes"] / total_requests * 100)
            if total_requests > 0 else 0
        )
        
        # Key statistics
        key_stats = {}
        for key_id, metrics in self.api_keys.items():
            key_stats[key_id] = {
                "status": metrics.status.value,
                "requests_made": metrics.requests_made,
                "success_rate": metrics.success_rate,
                "daily_quota_used": metrics.daily_quota_used,
                "daily_quota_remaining": metrics.daily_quota_limit - metrics.daily_quota_used,
                "last_request_ago_seconds": (
                    now - metrics.last_request_time 
                    if metrics.last_request_time else None
                ),
                "is_available": metrics.is_available,
                "last_error": metrics.last_error_message
            }
        
        # Available keys count
        available_keys = sum(1 for metrics in self.api_keys.values() if metrics.is_available)
        
        return {
            "router_config": {
                "total_keys": len(self.api_keys),
                "available_keys": available_keys,
                "strategy": self.strategy.value,
                "max_retries": self.max_retries
            },
            "global_stats": {
                "uptime_seconds": uptime,
                "total_requests": total_requests,
                "total_successes": self.global_stats["total_successes"],
                "total_failures": self.global_stats["total_failures"],
                "total_retries": self.global_stats["total_retries"],
                "global_success_rate": global_success_rate,
                "requests_per_minute": (
                    (total_requests / (uptime / 60)) if uptime > 0 else 0
                )
            },
            "key_stats": key_stats,
            "health_status": "healthy" if available_keys > 0 else "degraded"
        }
    
    def reset_daily_quotas(self):
        """Reset daily quotas for all API keys (call this daily)"""
        for metrics in self.api_keys.values():
            metrics.daily_quota_used = 0
            if metrics.status == APIKeyStatus.QUOTA_EXCEEDED:
                metrics.status = APIKeyStatus.ACTIVE
        
        logger.info("Daily quotas reset for all API keys")
    
    def export_metrics(self) -> Dict[str, Any]:
        """Export detailed metrics for external monitoring"""
        return {
            "timestamp": datetime.now().isoformat(),
            "router_stats": self.get_router_stats(),
            "detailed_metrics": {
                key_id: {
                    "key_id": metrics.key_id,
                    "status": metrics.status.value,
                    "requests_made": metrics.requests_made,
                    "requests_successful": metrics.requests_successful,
                    "requests_failed": metrics.requests_failed,
                    "success_rate": metrics.success_rate,
                    "daily_quota_used": metrics.daily_quota_used,
                    "last_request_time": metrics.last_request_time,
                    "last_error_time": metrics.last_error_time,
                    "last_error_message": metrics.last_error_message,
                    "recent_history": list(metrics.request_history)[-10:]  # Last 10 requests
                }
                for key_id, metrics in self.api_keys.items()
            }
        }

# Example usage in main.py:
"""
# Replace the original client initialization with:
api_keys = load_api_keys_from_env()
enhanced_client = EnhancedAlphaVantageClient(
    api_keys=api_keys,
    strategy=LoadBalancingStrategy.LEAST_USED
)

# Update the data service to use enhanced client
data_service = DataService(enhanced_client)
"""

# ===================================
# API Management Endpoints
# ===================================

# Add these endpoints to your main FastAPI application:
