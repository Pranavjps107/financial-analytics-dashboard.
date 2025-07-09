# supabase_client.py - Supabase Integration (Optional)
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
from supabase import create_client, Client
import json
import logging

logger = logging.getLogger(__name__)

class SupabaseClient:
    """Client for storing and retrieving data from Supabase"""
    
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        
        if self.url and self.key:
            self.client: Client = create_client(self.url, self.key)
            self.enabled = True
            logger.info("Supabase client initialized")
        else:
            self.client = None
            self.enabled = False
            logger.warning("Supabase credentials not found. Database features disabled.")
    
    async def save_company_data(self, symbol: str, data: Dict[str, Any]) -> bool:
        """Save comprehensive company data to Supabase"""
        if not self.enabled:
            return False
        
        try:
            # Prepare data for storage
            record = {
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "core_stock_data": json.dumps(data.get("core_stock_data", {})),
                "fundamental_data": json.dumps(data.get("fundamental_data", {})),
                "utility_data": json.dumps(data.get("utility_data", {})),
                "success_count": data.get("success_count", 0),
                "total_endpoints": data.get("total_endpoints", 0),
                "errors": json.dumps(data.get("errors", []))
            }
            
            # Insert or update record
            result = self.client.table("company_data").upsert(record).execute()
            
            if result.data:
                logger.info(f"Successfully saved data for {symbol} to Supabase")
                return True
            else:
                logger.error(f"Failed to save data for {symbol}: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error saving to Supabase: {e}")
            return False
    
    async def get_company_data(self, symbol: str, hours_old: int = 24) -> Optional[Dict[str, Any]]:
        """Retrieve company data from Supabase if it's recent enough"""
        if not self.enabled:
            return None
        
        try:
            # Calculate cutoff time
            cutoff_time = datetime.now().timestamp() - (hours_old * 3600)
            
            result = self.client.table("company_data")\
                .select("*")\
                .eq("symbol", symbol)\
                .gte("timestamp", datetime.fromtimestamp(cutoff_time).isoformat())\
                .order("timestamp", desc=True)\
                .limit(1)\
                .execute()
            
            if result.data:
                data = result.data[0]
                # Parse JSON fields back to dict
                return {
                    "symbol": data["symbol"],
                    "timestamp": data["timestamp"],
                    "core_stock_data": json.loads(data["core_stock_data"]),
                    "fundamental_data": json.loads(data["fundamental_data"]),
                    "utility_data": json.loads(data["utility_data"]),
                    "success_count": data["success_count"],
                    "total_endpoints": data["total_endpoints"],
                    "errors": json.loads(data["errors"])
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving from Supabase: {e}")
            return None
    
    async def save_request_log(self, symbol: str, endpoint: str, success: bool, response_time_ms: float):
        """Log API requests for analytics"""
        if not self.enabled:
            return
        
        try:
            record = {
                "symbol": symbol,
                "endpoint": endpoint,
                "success": success,
                "response_time_ms": response_time_ms,
                "timestamp": datetime.now().isoformat()
            }
            
            self.client.table("request_logs").insert(record).execute()
            
        except Exception as e:
            logger.error(f"Error logging request: {e}")

# Global Supabase client
supabase_client = SupabaseClient()
