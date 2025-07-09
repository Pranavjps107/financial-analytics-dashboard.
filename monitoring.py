
# ===================================
# monitoring.py - Advanced Monitoring
# ===================================

import psutil
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any
import asyncio
from collections import defaultdict, deque
import json

class SystemMonitor:
    """Advanced system monitoring"""
    
    def __init__(self, max_history=1000):
        self.max_history = max_history
        self.metrics_history = deque(maxlen=max_history)
        self.alert_thresholds = {
            "cpu_percent": 80,
            "memory_percent": 85,
            "response_time_ms": 5000,
            "error_rate_percent": 10
        }
        self.alerts = []
        
    def collect_metrics(self) -> Dict[str, Any]:
        """Collect current system metrics"""
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "cpu": {
                "percent": cpu_percent,
                "count": psutil.cpu_count(),
                "load_avg": psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None
            },
            "memory": {
                "percent": memory.percent,
                "available_gb": memory.available / (1024**3),
                "used_gb": memory.used / (1024**3),
                "total_gb": memory.total / (1024**3)
            },
            "disk": {
                "percent": disk.percent,
                "free_gb": disk.free / (1024**3),
                "used_gb": disk.used / (1024**3),
                "total_gb": disk.total / (1024**3)
            },
            "network": self._get_network_stats()
        }
        
        self.metrics_history.append(metrics)
        self._check_alerts(metrics)
        
        return metrics
    
    def _get_network_stats(self) -> Dict[str, Any]:
        """Get network statistics"""
        try:
            net_io = psutil.net_io_counters()
            return {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv
            }
        except:
            return {}
    
    def _check_alerts(self, metrics: Dict[str, Any]):
        """Check for alert conditions"""
        alerts = []
        
        if metrics["cpu"]["percent"] > self.alert_thresholds["cpu_percent"]:
            alerts.append({
                "type": "high_cpu",
                "message": f"High CPU usage: {metrics['cpu']['percent']:.1f}%",
                "severity": "warning",
                "timestamp": metrics["timestamp"]
            })
        
        if metrics["memory"]["percent"] > self.alert_thresholds["memory_percent"]:
            alerts.append({
                "type": "high_memory",
                "message": f"High memory usage: {metrics['memory']['percent']:.1f}%",
                "severity": "critical",
                "timestamp": metrics["timestamp"]
            })
        
        self.alerts.extend(alerts)
        
        # Keep only recent alerts (last 24 hours)
        cutoff = datetime.now() - timedelta(hours=24)
        self.alerts = [
            alert for alert in self.alerts 
            if datetime.fromisoformat(alert["timestamp"]) > cutoff
        ]

class APIMetrics:
    """Track API-specific metrics"""
    
    def __init__(self):
        self.request_counts = defaultdict(int)
        self.response_times = defaultdict(list)
        self.error_counts = defaultdict(int)
        self.endpoint_stats = defaultdict(lambda: {
            "total_requests": 0,
            "total_errors": 0,
            "avg_response_time": 0,
            "min_response_time": float('inf'),
            "max_response_time": 0
        })
    
    def record_request(self, endpoint: str, response_time_ms: float, success: bool = True):
        """Record a request"""
        self.request_counts[endpoint] += 1
        self.response_times[endpoint].append(response_time_ms)
        
        if not success:
            self.error_counts[endpoint] += 1
        
        # Update endpoint stats
        stats = self.endpoint_stats[endpoint]
        stats["total_requests"] += 1
        if not success:
            stats["total_errors"] += 1
        
        stats["min_response_time"] = min(stats["min_response_time"], response_time_ms)
        stats["max_response_time"] = max(stats["max_response_time"], response_time_ms)
        
        # Calculate rolling average
        recent_times = self.response_times[endpoint][-100:]  # Last 100 requests
        stats["avg_response_time"] = sum(recent_times) / len(recent_times)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary"""
        total_requests = sum(self.request_counts.values())
        total_errors = sum(self.error_counts.values())
        
        return {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate": (total_errors / total_requests * 100) if total_requests > 0 else 0,
            "endpoints": dict(self.endpoint_stats),
            "top_endpoints": sorted(
                self.request_counts.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:10]
        }

# Global monitoring instances
system_monitor = SystemMonitor()
api_metrics = APIMetrics()