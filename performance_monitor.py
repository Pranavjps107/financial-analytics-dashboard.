
# ===================================
# performance_monitor.py - Performance Monitoring
# ===================================

import time
import psutil
import logging
from datetime import datetime
from typing import Dict, Any

class PerformanceMonitor:
    """Monitor API performance and system resources"""
    
    def __init__(self):
        self.start_time = time.time()
        self.request_count = 0
        self.total_response_time = 0
        self.errors = 0
        
    def log_request(self, response_time: float, success: bool = True):
        """Log a request with its response time"""
        self.request_count += 1
        self.total_response_time += response_time
        
        if not success:
            self.errors += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current performance statistics"""
        uptime = time.time() - self.start_time
        avg_response_time = (
            self.total_response_time / self.request_count 
            if self.request_count > 0 else 0
        )
        
        # System resources
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
        return {
            "uptime_seconds": uptime,
            "total_requests": self.request_count,
            "total_errors": self.errors,
            "success_rate": (
                (self.request_count - self.errors) / self.request_count * 100
                if self.request_count > 0 else 0
            ),
            "average_response_time_ms": avg_response_time * 1000,
            "requests_per_minute": (
                self.request_count / (uptime / 60)
                if uptime > 0 else 0
            ),
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_available_gb": memory.available / (1024**3)
            },
            "timestamp": datetime.now().isoformat()
        }
    
    def reset_stats(self):
        """Reset all statistics"""
        self.start_time = time.time()
        self.request_count = 0
        self.total_response_time = 0
        self.errors = 0

# Global performance monitor
performance_monitor = PerformanceMonitor()

# ===================================
# Run tests with: python -m pytest test_main.py -v
# Run examples with: python examples.py
# ===================================