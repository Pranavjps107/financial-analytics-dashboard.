# main.py - Complete Financial Analytics Dashboard API with ML Integration
# All-in-one solution with multi-API key routing, complete Alpha Vantage integration, and ML-powered analytics

import os
import time
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
import logging
from contextlib import asynccontextmanager
from enum import Enum
from dataclasses import dataclass, field
from collections import deque
import json

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import requests

# Import ML Financial Analytics Service from your ml_financial_api.py module
try:
    from ml_financial_api import (
        MLFinancialAnalyticsService, 
        AlphaVantageClient,
        ComprehensiveAnalysisResponse,
        ConnectionManager
    )
    ML_AVAILABLE = True
    print("✅ ML Financial Analytics module loaded successfully")
except ImportError as e:
    print(f"⚠️ ML module not available: {e}")
    ML_AVAILABLE = False

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===================================
# API KEY ROUTER SYSTEM
# ===================================

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

class APIKeyRouter:
    """Intelligent router for managing multiple Alpha Vantage API keys"""
    
    def __init__(self, api_keys: List[str], strategy: LoadBalancingStrategy = LoadBalancingStrategy.LEAST_USED):
        self.api_keys = self._initialize_api_keys(api_keys)
        self.strategy = strategy
        self._round_robin_index = 0
        
        # Performance tracking
        self.global_stats = {
            "total_requests": 0,
            "total_successes": 0,
            "total_failures": 0,
            "start_time": time.time()
        }
        
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
            self._round_robin_index = (self._round_robin_index + 1) % len(available_keys)
            return available_keys[self._round_robin_index]
        elif self.strategy == LoadBalancingStrategy.LEAST_USED:
            return min(available_keys, key=lambda x: x[1].requests_made)
        elif self.strategy == LoadBalancingStrategy.BEST_PERFORMANCE:
            return max(available_keys, key=lambda x: x[1].success_rate)
        else:
            return available_keys[0]  # Fallback to first available
    
    def record_request(self, key_id: str, success: bool, error_message: Optional[str] = None):
        """Record the result of a request"""
        if key_id in self.api_keys:
            metrics = self.api_keys[key_id]
            metrics.requests_made += 1
            metrics.last_request_time = time.time()
            
            if success:
                metrics.requests_successful += 1
                metrics.daily_quota_used += 1
                metrics.status = APIKeyStatus.ACTIVE
                self.global_stats["total_successes"] += 1
            else:
                metrics.requests_failed += 1
                metrics.last_error_time = time.time()
                metrics.last_error_message = error_message
                
                # Handle specific errors
                if error_message and "rate limit" in error_message.lower():
                    metrics.status = APIKeyStatus.RATE_LIMITED
                    metrics.rate_limit_reset_time = time.time() + 60  # 1 minute cooldown
                elif error_message and "quota" in error_message.lower():
                    metrics.status = APIKeyStatus.QUOTA_EXCEEDED
                else:
                    metrics.status = APIKeyStatus.ERROR
                
                self.global_stats["total_failures"] += 1
            
            self.global_stats["total_requests"] += 1
            
            # Add to history
            metrics.request_history.append({
                "timestamp": time.time(),
                "success": success,
                "error": error_message if not success else None
            })
    
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
                "strategy": self.strategy.value
            },
            "global_stats": {
                "uptime_seconds": uptime,
                "total_requests": total_requests,
                "total_successes": self.global_stats["total_successes"],
                "total_failures": self.global_stats["total_failures"],
                "global_success_rate": global_success_rate,
                "requests_per_minute": (
                    (total_requests / (uptime / 60)) if uptime > 0 else 0
                )
            },
            "key_stats": key_stats,
            "health_status": "healthy" if available_keys > 0 else "degraded"
        }

# ===================================
# COMPLETE ALPHA VANTAGE CLIENT
# ===================================

class CompleteAlphaVantageClient:
    """Complete Alpha Vantage client with ALL available APIs and intelligent routing"""
    
    def __init__(self, api_keys: List[str]):
        self.router = APIKeyRouter(api_keys, LoadBalancingStrategy.LEAST_USED)
        self.base_url = "https://www.alphavantage.co/query"
        self.session = requests.Session()
        
    async def _make_request(self, params: Dict[str, str], endpoint_name: str) -> Dict[str, Any]:
        """Make a request with intelligent API key routing"""
        # Get best available API key
        key_selection = self.router.get_best_api_key()
        
        if not key_selection:
            raise HTTPException(status_code=503, detail="No available API keys")
        
        key_id, key_metrics = key_selection
        params['apikey'] = key_metrics.api_key
        
        try:
            logger.info(f"Fetching {endpoint_name} with {key_id}")
            response = self.session.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            # Handle CSV responses
            if params.get('datatype') == 'csv' or 'csv' in response.headers.get('content-type', ''):
                data = {"csv_data": response.text}
            else:
                data = response.json()
                
                # Check for API errors
                if "Error Message" in data:
                    raise ValueError(f"API Error: {data['Error Message']}")
                elif "Note" in data:
                    raise ValueError(f"API Limit: {data['Note']}")
                elif "Information" in data:
                    raise ValueError(f"API Info: {data['Information']}")
            
            # Record successful request
            self.router.record_request(key_id, True)
            return data
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Request failed for {endpoint_name} with {key_id}: {error_msg}")
            
            # Record failed request
            self.router.record_request(key_id, False, error_msg)
            raise
    
    # ===================================
    # CORE STOCK DATA APIs (8 endpoints)
    # ===================================
    
    async def get_intraday(self, symbol: str, interval: str = "5min", outputsize: str = "compact") -> Dict[str, Any]:
        """TIME_SERIES_INTRADAY - Intraday time series data"""
        params = {
            "function": "TIME_SERIES_INTRADAY",
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "adjusted": "true"
        }
        return await self._make_request(params, "Intraday")
    
    async def get_daily(self, symbol: str, outputsize: str = "compact") -> Dict[str, Any]:
        """TIME_SERIES_DAILY - Daily time series data"""
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": outputsize
        }
        return await self._make_request(params, "Daily")
    
    async def get_daily_adjusted(self, symbol: str, outputsize: str = "compact") -> Dict[str, Any]:
        """TIME_SERIES_DAILY_ADJUSTED - Daily adjusted time series data"""
        params = {
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": symbol,
            "outputsize": outputsize
        }
        return await self._make_request(params, "Daily Adjusted")
    
    async def get_weekly(self, symbol: str) -> Dict[str, Any]:
        """TIME_SERIES_WEEKLY - Weekly time series data"""
        params = {
            "function": "TIME_SERIES_WEEKLY",
            "symbol": symbol
        }
        return await self._make_request(params, "Weekly")
    
    async def get_weekly_adjusted(self, symbol: str) -> Dict[str, Any]:
        """TIME_SERIES_WEEKLY_ADJUSTED - Weekly adjusted time series data"""
        params = {
            "function": "TIME_SERIES_WEEKLY_ADJUSTED",
            "symbol": symbol
        }
        return await self._make_request(params, "Weekly Adjusted")
    
    async def get_monthly(self, symbol: str) -> Dict[str, Any]:
        """TIME_SERIES_MONTHLY - Monthly time series data"""
        params = {
            "function": "TIME_SERIES_MONTHLY",
            "symbol": symbol
        }
        return await self._make_request(params, "Monthly")
    
    async def get_monthly_adjusted(self, symbol: str) -> Dict[str, Any]:
        """TIME_SERIES_MONTHLY_ADJUSTED - Monthly adjusted time series data"""
        params = {
            "function": "TIME_SERIES_MONTHLY_ADJUSTED",
            "symbol": symbol
        }
        return await self._make_request(params, "Monthly Adjusted")
    
    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """GLOBAL_QUOTE - Latest price and volume information"""
        params = {
            "function": "GLOBAL_QUOTE",
            "symbol": symbol
        }
        return await self._make_request(params, "Quote")
    
    # ===================================
    # FUNDAMENTAL DATA APIs (10 endpoints)
    # ===================================
    
    async def get_company_overview(self, symbol: str) -> Dict[str, Any]:
        """OVERVIEW - Company information and financial ratios"""
        params = {
            "function": "OVERVIEW",
            "symbol": symbol
        }
        return await self._make_request(params, "Company Overview")
    
    async def get_income_statement(self, symbol: str) -> Dict[str, Any]:
        """INCOME_STATEMENT - Annual and quarterly income statements"""
        params = {
            "function": "INCOME_STATEMENT",
            "symbol": symbol
        }
        return await self._make_request(params, "Income Statement")
    
    async def get_balance_sheet(self, symbol: str) -> Dict[str, Any]:
        """BALANCE_SHEET - Annual and quarterly balance sheets"""
        params = {
            "function": "BALANCE_SHEET",
            "symbol": symbol
        }
        return await self._make_request(params, "Balance Sheet")
    
    async def get_cash_flow(self, symbol: str) -> Dict[str, Any]:
        """CASH_FLOW - Annual and quarterly cash flow statements"""
        params = {
            "function": "CASH_FLOW",
            "symbol": symbol
        }
        return await self._make_request(params, "Cash Flow")
    
    async def get_earnings(self, symbol: str) -> Dict[str, Any]:
        """EARNINGS - Annual and quarterly earnings data"""
        params = {
            "function": "EARNINGS",
            "symbol": symbol
        }
        return await self._make_request(params, "Earnings")
    
    async def get_dividends(self, symbol: str) -> Dict[str, Any]:
        """DIVIDENDS - Historical and future dividend distributions"""
        params = {
            "function": "DIVIDENDS",
            "symbol": symbol
        }
        return await self._make_request(params, "Dividends")
    
    async def get_splits(self, symbol: str) -> Dict[str, Any]:
        """SPLITS - Historical split events"""
        params = {
            "function": "SPLITS",
            "symbol": symbol
        }
        return await self._make_request(params, "Splits")
    
    async def get_etf_profile(self, symbol: str) -> Dict[str, Any]:
        """ETF_PROFILE - ETF profile and holdings"""
        params = {
            "function": "ETF_PROFILE",
            "symbol": symbol
        }
        return await self._make_request(params, "ETF Profile")
    
    async def get_listing_status(self, state: str = "active", date: Optional[str] = None) -> Dict[str, Any]:
        """LISTING_STATUS - Active or delisted stocks and ETFs"""
        params = {
            "function": "LISTING_STATUS",
            "state": state
        }
        if date:
            params["date"] = date
        return await self._make_request(params, "Listing Status")
    
    async def get_earnings_calendar(self, symbol: Optional[str] = None, horizon: str = "3month") -> Dict[str, Any]:
        """EARNINGS_CALENDAR - Company earnings expected in coming months"""
        params = {
            "function": "EARNINGS_CALENDAR",
            "horizon": horizon
        }
        if symbol:
            params["symbol"] = symbol
        return await self._make_request(params, "Earnings Calendar")
    
    async def get_ipo_calendar(self) -> Dict[str, Any]:
        """IPO_CALENDAR - IPOs expected in the next 3 months"""
        params = {
            "function": "IPO_CALENDAR"
        }
        return await self._make_request(params, "IPO Calendar")
    
    # ===================================
    # OPTIONS DATA APIs (3 endpoints - Premium)
    # ===================================
    
    async def get_realtime_options(self, symbol: str, require_greeks: bool = False, contract: Optional[str] = None) -> Dict[str, Any]:
        """REALTIME_OPTIONS - Real-time options data"""
        params = {
            "function": "REALTIME_OPTIONS",
            "symbol": symbol,
            "require_greeks": str(require_greeks).lower()
        }
        if contract:
            params["contract"] = contract
        return await self._make_request(params, "Realtime Options")
    
    async def get_historical_options(self, symbol: str, date: Optional[str] = None) -> Dict[str, Any]:
        """HISTORICAL_OPTIONS - Historical options data"""
        params = {
            "function": "HISTORICAL_OPTIONS",
            "symbol": symbol
        }
        if date:
            params["date"] = date
        return await self._make_request(params, "Historical Options")
    
    # ===================================
    # UTILITY APIs (3 endpoints)
    # ===================================
    
    async def search_symbol(self, keywords: str) -> Dict[str, Any]:
        """SYMBOL_SEARCH - Search for symbols by keywords"""
        params = {
            "function": "SYMBOL_SEARCH",
            "keywords": keywords
        }
        return await self._make_request(params, "Symbol Search")
    
    async def get_market_status(self) -> Dict[str, Any]:
        """MARKET_STATUS - Current market status globally"""
        params = {
            "function": "MARKET_STATUS"
        }
        return await self._make_request(params, "Market Status")
    
    # ===================================
    # ALPHA INTELLIGENCE APIs (1 endpoint)
    # ===================================
    
    async def get_news_sentiment(self, tickers: Optional[str] = None, topics: Optional[str] = None, 
                               time_from: Optional[str] = None, time_to: Optional[str] = None,
                               sort: str = "LATEST", limit: int = 50) -> Dict[str, Any]:
        """NEWS_SENTIMENT - Market news and sentiment data"""
        params = {
            "function": "NEWS_SENTIMENT",
            "sort": sort,
            "limit": str(limit)
        }
        if tickers:
            params["tickers"] = tickers
        if topics:
            params["topics"] = topics
        if time_from:
            params["time_from"] = time_from
        if time_to:
            params["time_to"] = time_to
        return await self._make_request(params, "News Sentiment")

# ===================================
# RESPONSE MODELS
# ===================================

class CompleteCompanyDataResponse(BaseModel):
    """Complete response model with all Alpha Vantage data categories"""
    symbol: str
    timestamp: datetime
    
    # Core Stock Data
    core_stock_data: Dict[str, Any] = Field(default_factory=dict)
    
    # Fundamental Data
    fundamental_data: Dict[str, Any] = Field(default_factory=dict)
    
    # Options Data
    options_data: Dict[str, Any] = Field(default_factory=dict)
    
    # Utility Data
    utility_data: Dict[str, Any] = Field(default_factory=dict)
    
    # Alpha Intelligence
    alpha_intelligence: Dict[str, Any] = Field(default_factory=dict)
    
    # Metadata
    errors: List[str] = Field(default_factory=list)
    success_count: int = 0
    total_endpoints: int = 0
    router_stats: Dict[str, Any] = Field(default_factory=dict)
    execution_time_ms: float = 0

# ===================================
# DATA SERVICE
# ===================================

class CompleteDataService:
    """Service to fetch ALL available Alpha Vantage data for a company"""
    
    def __init__(self, client: CompleteAlphaVantageClient):
        self.client = client
    
    async def fetch_all_company_data(self, symbol: str, 
                                   include_options: bool = False,
                                   include_news: bool = True,
                                   include_historical: bool = False) -> CompleteCompanyDataResponse:
        """
        Fetch ALL available data for a company from Alpha Vantage
        """
        start_time = time.time()
        response = CompleteCompanyDataResponse(
            symbol=symbol,
            timestamp=datetime.now()
        )
        
        # ===================================
        # DEFINE ALL ENDPOINTS
        # ===================================
        
        # Core Stock Data (8 endpoints)
        core_endpoints = [
            ("intraday", lambda: self.client.get_intraday(symbol)),
            ("daily", lambda: self.client.get_daily(symbol)),
            ("daily_adjusted", lambda: self.client.get_daily_adjusted(symbol)),
            ("weekly", lambda: self.client.get_weekly(symbol)),
            ("weekly_adjusted", lambda: self.client.get_weekly_adjusted(symbol)),
            ("monthly", lambda: self.client.get_monthly(symbol)),
            ("monthly_adjusted", lambda: self.client.get_monthly_adjusted(symbol)),
            ("quote", lambda: self.client.get_quote(symbol)),
        ]
        
        # Add full historical data if requested
        if include_historical:
            core_endpoints.extend([
                ("daily_full", lambda: self.client.get_daily(symbol, outputsize="full")),
                ("intraday_full", lambda: self.client.get_intraday(symbol, outputsize="full")),
            ])
        
        # Fundamental Data (10 endpoints)
        fundamental_endpoints = [
            ("overview", lambda: self.client.get_company_overview(symbol)),
            ("income_statement", lambda: self.client.get_income_statement(symbol)),
            ("balance_sheet", lambda: self.client.get_balance_sheet(symbol)),
            ("cash_flow", lambda: self.client.get_cash_flow(symbol)),
            ("earnings", lambda: self.client.get_earnings(symbol)),
            ("dividends", lambda: self.client.get_dividends(symbol)),
            ("splits", lambda: self.client.get_splits(symbol)),
            ("earnings_calendar", lambda: self.client.get_earnings_calendar(symbol)),
        ]
        
        # Try ETF profile (will fail for regular stocks)
        try:
            await self.client.get_etf_profile(symbol)
            fundamental_endpoints.append(("etf_profile", lambda: self.client.get_etf_profile(symbol)))
        except:
            pass  # Not an ETF
        
        # Options Data (3 endpoints - Premium)
        options_endpoints = []
        if include_options:
            options_endpoints = [
                ("realtime_options", lambda: self.client.get_realtime_options(symbol)),
                ("realtime_options_greeks", lambda: self.client.get_realtime_options(symbol, require_greeks=True)),
                ("historical_options", lambda: self.client.get_historical_options(symbol)),
            ]
        
        # Utility Data (3 endpoints)
        utility_endpoints = [
            ("search", lambda: self.client.search_symbol(symbol)),
            ("market_status", lambda: self.client.get_market_status()),
            ("listing_status", lambda: self.client.get_listing_status()),
            ("ipo_calendar", lambda: self.client.get_ipo_calendar()),
        ]
        
        # Alpha Intelligence (1 endpoint)
        intelligence_endpoints = []
        if include_news:
            intelligence_endpoints = [
                ("news_sentiment", lambda: self.client.get_news_sentiment(tickers=symbol, limit=50)),
            ]
        
        # Calculate total endpoints
        all_endpoints = (core_endpoints + fundamental_endpoints + 
                        options_endpoints + utility_endpoints + intelligence_endpoints)
        response.total_endpoints = len(all_endpoints)
        
        # ===================================
        # FETCH ALL DATA
        # ===================================
        
        # Fetch Core Stock Data
        for name, func in core_endpoints:
            try:
                data = await func()
                response.core_stock_data[name] = data
                response.success_count += 1
                logger.info(f"✅ Successfully fetched {name} for {symbol}")
            except Exception as e:
                error_msg = f"Failed to fetch {name}: {str(e)}"
                response.errors.append(error_msg)
                logger.error(f"❌ {error_msg}")
        
        # Fetch Fundamental Data
        for name, func in fundamental_endpoints:
            try:
                data = await func()
                response.fundamental_data[name] = data
                response.success_count += 1
                logger.info(f"✅ Successfully fetched {name} for {symbol}")
            except Exception as e:
                error_msg = f"Failed to fetch {name}: {str(e)}"
                response.errors.append(error_msg)
                logger.error(f"❌ {error_msg}")
        
        # Fetch Options Data
        for name, func in options_endpoints:
            try:
                data = await func()
                response.options_data[name] = data
                response.success_count += 1
                logger.info(f"✅ Successfully fetched {name} for {symbol}")
            except Exception as e:
                error_msg = f"Failed to fetch {name}: {str(e)}"
                response.errors.append(error_msg)
                logger.warning(f"⚠️ {error_msg} (Premium feature)")
        
        # Fetch Utility Data
        for name, func in utility_endpoints:
            try:
                data = await func()
                response.utility_data[name] = data
                response.success_count += 1
                logger.info(f"✅ Successfully fetched {name}")
            except Exception as e:
                error_msg = f"Failed to fetch {name}: {str(e)}"
                response.errors.append(error_msg)
                logger.error(f"❌ {error_msg}")
        
        # Fetch Alpha Intelligence Data
        for name, func in intelligence_endpoints:
            try:
                data = await func()
                response.alpha_intelligence[name] = data
                response.success_count += 1
                logger.info(f"✅ Successfully fetched {name} for {symbol}")
            except Exception as e:
                error_msg = f"Failed to fetch {name}: {str(e)}"
                response.errors.append(error_msg)
                logger.error(f"❌ {error_msg}")
        
        # Add execution metadata
        response.execution_time_ms = (time.time() - start_time) * 1000
        response.router_stats = self.client.router.get_router_stats()
        
        return response

# ===================================
# LOAD API KEYS FUNCTION
# ===================================

def load_api_keys_from_env() -> List[str]:
    """Load API keys from environment variables"""
    api_keys = []
    
    # Method 1: Comma-separated list
    keys_string = os.getenv("ALPHA_VANTAGE_API_KEYS")
    if keys_string:
        api_keys.extend([key.strip() for key in keys_string.split(",") if key.strip()])
    
    # Method 2: Individual numbered keys
    i = 1
    while True:
        key = os.getenv(f"ALPHA_VANTAGE_API_KEY_{i}")
        if key and key.strip():
            api_keys.append(key.strip())
            i += 1
        else:
            break
    
    # Method 3: Single key fallback
# Method 3: Single key fallback
    if not api_keys:
       single_key = os.getenv("ALPHA_VANTAGE_API_KEY")
       if single_key and single_key.strip():
           api_keys.append(single_key.strip())
   
    if not api_keys:
       raise ValueError("No Alpha Vantage API keys found in environment variables")
   
    logger.info(f"Loaded {len(api_keys)} API keys from environment")
    return api_keys

# ===================================
# GLOBAL VARIABLES
# ===================================

alpha_vantage_client = None
complete_data_service = None
ml_service = None
websocket_manager = None

# ===================================
# FASTAPI LIFESPAN MANAGEMENT
# ===================================

@asynccontextmanager
async def lifespan(app: FastAPI):
   """Modern FastAPI lifespan event handler"""
   global alpha_vantage_client, complete_data_service, ml_service, websocket_manager
   
   # Startup
   logger.info("🚀 Starting Complete Financial Analytics Dashboard API with ML Integration")
   
   try:
       # Load API keys
       api_keys = load_api_keys_from_env()
       
       # Initialize Alpha Vantage client
       alpha_vantage_client = CompleteAlphaVantageClient(api_keys)
       complete_data_service = CompleteDataService(alpha_vantage_client)
       
       # Initialize ML services if available
       if ML_AVAILABLE:
           try:
               # Create Alpha Vantage client compatible with ML service
               ml_alpha_client = AlphaVantageClient(api_keys)
               ml_service = MLFinancialAnalyticsService(ml_alpha_client)
               websocket_manager = ConnectionManager()
               
               logger.info("🤖 ML Features Initialized:")
               logger.info("   🔮 LSTM Time Series Forecasting")
               logger.info("   📊 20+ Technical Indicators")
               logger.info("   ⚠️ Advanced Risk Assessment")
               logger.info("   💡 AI-Powered Recommendations")
               logger.info("   📈 Real-Time Market Sentiment")
               logger.info("   🔄 WebSocket Real-Time Updates")
           except Exception as e:
               logger.warning(f"⚠️ ML services failed to initialize: {e}")
               ML_AVAILABLE = False
       
       logger.info(f"✅ Initialized with {len(api_keys)} API keys")
       logger.info("📊 Available APIs:")
       logger.info("   🔹 Core Stock Data: 8 endpoints")
       logger.info("   🔹 Fundamental Data: 10 endpoints")
       logger.info("   🔹 Options Data: 3 endpoints (Premium)")
       logger.info("   🔹 Utility APIs: 4 endpoints")
       logger.info("   🔹 Alpha Intelligence: 1 endpoint")
       if ML_AVAILABLE:
           logger.info("   🤖 ML Analytics: 15+ ML endpoints")
       logger.info("   📈 Total: 26+ endpoints for complete analysis!")
       
   except Exception as e:
       logger.error(f"❌ Failed to initialize: {e}")
       raise
   
   # App is running
   yield
   
   # Shutdown
   logger.info("🛑 Shutting down Complete Financial Analytics Dashboard API")
   if alpha_vantage_client:
       alpha_vantage_client.session.close()

# ===================================
# FASTAPI APPLICATION
# ===================================

app = FastAPI(
   title="Complete Financial Analytics Dashboard API with ML Integration",
   description="Comprehensive stock data service with ALL Alpha Vantage APIs, intelligent multi-key routing, and ML-powered analytics",
   version="4.0.0",
   docs_url="/docs",
   redoc_url="/redoc",
   lifespan=lifespan
)

# CORS middleware
app.add_middleware(
   CORSMiddleware,
   allow_origins=["*"],
   allow_credentials=True,
   allow_methods=["*"],
   allow_headers=["*"],
)

# ===================================
# API ENDPOINTS - CORE ALPHA VANTAGE
# ===================================

@app.get("/")
async def root():
   """Health check endpoint with complete API information"""
   if not alpha_vantage_client:
       return {"error": "API client not initialized"}
   
   router_stats = alpha_vantage_client.router.get_router_stats()
   
   base_features = {
       "core_stock_apis": 8,
       "fundamental_apis": 10,
       "options_apis": 3,
       "utility_apis": 4,
       "intelligence_apis": 1,
       "total_alpha_vantage_endpoints": 26
   }
   
   if ML_AVAILABLE and ml_service:
       base_features.update({
           "ml_lstm_forecasting": "✅ Real-time LSTM price predictions",
           "ml_technical_analysis": "✅ 20+ technical indicators",
           "ml_risk_assessment": "✅ Advanced risk metrics",
           "ml_ai_recommendations": "✅ Investment recommendations",
           "ml_market_sentiment": "✅ Real-time sentiment analysis",
           "ml_portfolio_optimization": "✅ Position sizing & optimization",
           "ml_websocket_updates": "✅ Real-time ML updates",
           "total_ml_endpoints": 15
       })
   
   return {
       "message": "Complete Financial Analytics Dashboard API with ML Integration",
       "status": "healthy",
       "timestamp": datetime.now(),
       "version": "4.0.0",
       "features": base_features,
       "ml_available": ML_AVAILABLE,
       "router_info": {
           "total_api_keys": router_stats["router_config"]["total_keys"],
           "available_keys": router_stats["router_config"]["available_keys"],
           "strategy": router_stats["router_config"]["strategy"],
           "health": router_stats["health_status"]
       },
       "docs": "/docs"
   }

@app.get("/fetch_complete_data/{symbol}", response_model=CompleteCompanyDataResponse)
async def fetch_complete_company_data(
   symbol: str,
   background_tasks: BackgroundTasks,
   include_options: bool = Query(False, description="Include options data (requires premium)"),
   include_news: bool = Query(True, description="Include news and sentiment data"),
   include_historical: bool = Query(False, description="Include full historical data")
) -> CompleteCompanyDataResponse:
   """
   Fetch ALL available Alpha Vantage data for a company
   
   This endpoint fetches data from ALL 26+ Alpha Vantage APIs:
   - Core Stock Data (8 APIs): Intraday, Daily, Weekly, Monthly, Quote, etc.
   - Fundamental Data (10 APIs): Overview, Financials, Earnings, Dividends, etc.
   - Options Data (3 APIs): Realtime & Historical Options (Premium)
   - Utility APIs (4 APIs): Search, Market Status, Calendars, etc.
   - Alpha Intelligence (1 API): News & Sentiment
   
   Args:
       symbol: Stock symbol (e.g., 'AAPL', 'MSFT', 'GOOGL')
       include_options: Include options data (requires premium subscription)
       include_news: Include news and sentiment analysis
       include_historical: Include full historical data (more API calls)
       
   Returns:
       CompleteCompanyDataResponse: ALL available data categorized by type
   """
   if not complete_data_service:
       raise HTTPException(status_code=503, detail="Service not initialized")
   
   try:
       # Validate symbol
       if not symbol or len(symbol.strip()) == 0:
           raise HTTPException(status_code=400, detail="Symbol cannot be empty")
       
       symbol = symbol.upper().strip()
       logger.info(f"🚀 Starting COMPLETE data fetch for symbol: {symbol}")
       logger.info(f"📊 Options: include_options={include_options}, include_news={include_news}, include_historical={include_historical}")
       
       # Fetch ALL data
       start_time = time.time()
       response = await complete_data_service.fetch_all_company_data(
           symbol=symbol,
           include_options=include_options,
           include_news=include_news,
           include_historical=include_historical
       )
       end_time = time.time()
       
       logger.info(
           f"🎯 COMPLETE data fetch completed for {symbol}. "
           f"Success: {response.success_count}/{response.total_endpoints} "
           f"Time: {end_time - start_time:.2f}s"
       )
       
       # Add background task to log request
       background_tasks.add_task(
           log_complete_request, 
           symbol, 
           response.success_count, 
           response.total_endpoints,
           include_options,
           include_news,
           include_historical
       )
       
       return response
       
   except Exception as e:
       logger.error(f"❌ Error fetching complete data for {symbol}: {str(e)}")
       raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Category-specific endpoints for targeted data fetching
@app.get("/fetch_core_data/{symbol}")
async def fetch_core_stock_data(symbol: str, include_historical: bool = False):
   """Fetch only core stock data (time series, quotes)"""
   if not alpha_vantage_client:
       raise HTTPException(status_code=503, detail="Service not initialized")
   
   symbol = symbol.upper().strip()
   data = {}
   errors = []
   
   # Core endpoints
   core_endpoints = [
       ("intraday", lambda: alpha_vantage_client.get_intraday(symbol)),
       ("daily", lambda: alpha_vantage_client.get_daily(symbol)),
       ("daily_adjusted", lambda: alpha_vantage_client.get_daily_adjusted(symbol)),
       ("weekly", lambda: alpha_vantage_client.get_weekly(symbol)),
       ("weekly_adjusted", lambda: alpha_vantage_client.get_weekly_adjusted(symbol)),
       ("monthly", lambda: alpha_vantage_client.get_monthly(symbol)),
       ("monthly_adjusted", lambda: alpha_vantage_client.get_monthly_adjusted(symbol)),
       ("quote", lambda: alpha_vantage_client.get_quote(symbol)),
   ]
   
   if include_historical:
       core_endpoints.append(("daily_full", lambda: alpha_vantage_client.get_daily(symbol, outputsize="full")))
   
   for name, func in core_endpoints:
       try:
           data[name] = await func()
       except Exception as e:
           errors.append(f"Failed to fetch {name}: {str(e)}")
   
   return {
       "symbol": symbol,
       "core_stock_data": data,
       "errors": errors,
       "success_count": len(data),
       "total_endpoints": len(core_endpoints),
       "timestamp": datetime.now()
   }

@app.get("/fetch_fundamental_data/{symbol}")
async def fetch_fundamental_data(symbol: str):
   """Fetch only fundamental data (financials, ratios, etc.)"""
   if not alpha_vantage_client:
       raise HTTPException(status_code=503, detail="Service not initialized")
   
   symbol = symbol.upper().strip()
   data = {}
   errors = []
   
   # Fundamental endpoints
   fundamental_endpoints = [
       ("overview", lambda: alpha_vantage_client.get_company_overview(symbol)),
       ("income_statement", lambda: alpha_vantage_client.get_income_statement(symbol)),
       ("balance_sheet", lambda: alpha_vantage_client.get_balance_sheet(symbol)),
       ("cash_flow", lambda: alpha_vantage_client.get_cash_flow(symbol)),
       ("earnings", lambda: alpha_vantage_client.get_earnings(symbol)),
       ("dividends", lambda: alpha_vantage_client.get_dividends(symbol)),
       ("splits", lambda: alpha_vantage_client.get_splits(symbol)),
   ]
   
   for name, func in fundamental_endpoints:
       try:
           data[name] = await func()
       except Exception as e:
           errors.append(f"Failed to fetch {name}: {str(e)}")
   
   return {
       "symbol": symbol,
       "fundamental_data": data,
       "errors": errors,
       "success_count": len(data),
       "total_endpoints": len(fundamental_endpoints),
       "timestamp": datetime.now()
   }

@app.get("/fetch_options_data/{symbol}")
async def fetch_options_data(symbol: str, include_greeks: bool = False):
   """Fetch only options data (requires premium)"""
   if not alpha_vantage_client:
       raise HTTPException(status_code=503, detail="Service not initialized")
   
   symbol = symbol.upper().strip()
   data = {}
   errors = []
   
   # Options endpoints
   options_endpoints = [
       ("realtime_options", lambda: alpha_vantage_client.get_realtime_options(symbol, require_greeks=include_greeks)),
       ("historical_options", lambda: alpha_vantage_client.get_historical_options(symbol)),
   ]
   
   for name, func in options_endpoints:
       try:
           data[name] = await func()
       except Exception as e:
           errors.append(f"Failed to fetch {name}: {str(e)} (Premium feature)")
   
   return {
       "symbol": symbol,
       "options_data": data,
       "errors": errors,
       "success_count": len(data),
       "total_endpoints": len(options_endpoints),
       "timestamp": datetime.now()
   }

@app.get("/fetch_news_sentiment/{symbol}")
async def fetch_news_sentiment(symbol: str, limit: int = 50):
   """Fetch news and sentiment data for a symbol"""
   if not alpha_vantage_client:
       raise HTTPException(status_code=503, detail="Service not initialized")
   
   try:
       symbol = symbol.upper().strip()
       data = await alpha_vantage_client.get_news_sentiment(tickers=symbol, limit=limit)
       
       return {
           "symbol": symbol,
           "news_sentiment": data,
           "timestamp": datetime.now()
       }
   except Exception as e:
       raise HTTPException(status_code=500, detail=str(e))

# Quick access endpoints
@app.get("/quote/{symbol}")
async def get_quick_quote(symbol: str):
   """Get quick quote for a symbol"""
   if not alpha_vantage_client:
       raise HTTPException(status_code=503, detail="Service not initialized")
   
   try:
       symbol = symbol.upper().strip()
       data = await alpha_vantage_client.get_quote(symbol)
       return {"symbol": symbol, "quote": data, "timestamp": datetime.now()}
   except Exception as e:
       raise HTTPException(status_code=500, detail=str(e))

@app.get("/search/{keywords}")
async def search_symbols(keywords: str):
   """Search for symbols by keywords"""
   if not alpha_vantage_client:
       raise HTTPException(status_code=503, detail="Service not initialized")
   
   try:
       data = await alpha_vantage_client.search_symbol(keywords)
       return {"keywords": keywords, "results": data, "timestamp": datetime.now()}
   except Exception as e:
       raise HTTPException(status_code=500, detail=str(e))

@app.get("/market-status")
async def get_market_status():
   """Get current market status"""
   if not alpha_vantage_client:
       raise HTTPException(status_code=503, detail="Service not initialized")
   
   try:
       data = await alpha_vantage_client.get_market_status()
       return {"market_status": data, "timestamp": datetime.now()}
   except Exception as e:
       raise HTTPException(status_code=500, detail=str(e))

# ===================================
# ML ENDPOINTS - Integrated from ml_financial_api.py
# ===================================

@app.get("/ml/comprehensive_analysis/{symbol}")
async def ml_comprehensive_analysis(
   symbol: str,
   days_ahead: int = Query(30, ge=1, le=90, description="Days ahead to predict (1-90)"),
   retrain: bool = Query(False, description="Force model retraining")
):
   """
   🎯 FLAGSHIP ML ENDPOINT: Complete ML-powered financial analysis
   
   Returns comprehensive analysis including:
   - 🤖 LSTM price predictions with confidence scoring
   - 📊 Technical analysis with 20+ indicators
   - ⚠️ Risk assessment and portfolio metrics
   - 💡 AI-powered investment recommendations
   - 📈 Market sentiment analysis
   """
   if not ML_AVAILABLE or not ml_service:
       raise HTTPException(status_code=503, detail="ML service not available")
   
   try:
       return await ml_service.comprehensive_analysis(symbol, days_ahead, retrain)
   except Exception as e:
       logger.error(f"Error in ML comprehensive analysis for {symbol}: {str(e)}")
       raise HTTPException(status_code=500, detail=f"ML analysis failed: {str(e)}")

@app.get("/ml/predict/{symbol}")
async def ml_lstm_predictions(
   symbol: str,
   days_ahead: int = Query(30, ge=1, le=90, description="Days ahead to predict"),
   retrain: bool = Query(False, description="Force model retraining")
):
   """
   🔮 LSTM Price Predictions
   
   Returns machine learning price predictions using LSTM neural networks
   """
   if not ML_AVAILABLE or not ml_service:
       raise HTTPException(status_code=503, detail="ML service not available")
   
   try:
       # Get data and train/load model
       df = await ml_service.get_stock_data(symbol)
       
       if retrain or symbol not in ml_service.lstm_manager.models:
           await ml_service.lstm_manager.train_model(symbol, df)
       
       # Generate predictions
       predictions = await ml_service.lstm_manager.predict(symbol, df, days_ahead)
       
       return {
           "symbol": symbol,
           "predictions": predictions.predictions,
           "confidence_metrics": predictions.confidence_metrics,
           "model_info": predictions.model_info,
           "timestamp": datetime.now()
       }
       
   except Exception as e:
       logger.error(f"Error in LSTM predictions for {symbol}: {str(e)}")
       raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")

@app.get("/ml/technical_analysis/{symbol}")
async def ml_technical_analysis(symbol: str):
   """
   📊 Technical Analysis
   
   Returns comprehensive technical analysis with 20+ indicators
   """
   if not ML_AVAILABLE or not ml_service:
       raise HTTPException(status_code=503, detail="ML service not available")
   
   try:
       df = await ml_service.get_stock_data(symbol)
       
       # Calculate indicators and signals
       indicators = ml_service.technical_engine.calculate_indicators(df)
       signals = ml_service.technical_engine.generate_signals(df, indicators)
       support_levels, resistance_levels = ml_service.technical_engine.find_support_resistance(df)
       patterns = ml_service.technical_engine.analyze_candlestick_patterns(df)
       
       return {
           "symbol": symbol,
           "indicators": indicators.dict(),
           "signals": signals,
           "support_levels": support_levels,
           "resistance_levels": resistance_levels,
           "candlestick_patterns": patterns,
           "timestamp": datetime.now()
       }
       
   except Exception as e:
       logger.error(f"Error in technical analysis for {symbol}: {str(e)}")
       raise HTTPException(status_code=500, detail=f"Technical analysis failed: {str(e)}")

@app.get("/ml/quick_insights/{symbol}")
async def ml_quick_insights(symbol: str):
   """
   ⚡ Quick Insights (< 5 seconds)
   
   Returns essential information for rapid decision making
   """
   if not ML_AVAILABLE or not ml_service:
       raise HTTPException(status_code=503, detail="ML service not available")
   
   try:
       return await ml_service.quick_insights(symbol)
   except Exception as e:
       logger.error(f"Error in quick insights for {symbol}: {str(e)}")
       raise HTTPException(status_code=500, detail=f"Quick insights failed: {str(e)}")

@app.get("/ml/portfolio_analysis")
async def ml_portfolio_analysis(symbols: str = Query(..., description="Comma-separated symbols (e.g., AAPL,MSFT,GOOGL)")):
   """
   📈 Portfolio Analysis
   
   Analyze multiple stocks for portfolio optimization
   """
   if not ML_AVAILABLE or not ml_service:
       raise HTTPException(status_code=503, detail="ML service not available")
   
   try:
       symbol_list = [s.strip().upper() for s in symbols.split(",")]
       results = {}
       
       for symbol in symbol_list[:10]:  # Limit to 10 symbols
           try:
               insights = await ml_service.quick_insights(symbol)
               results[symbol] = insights
           except Exception as e:
               results[symbol] = {"error": str(e)}
       
       # Calculate portfolio metrics
       total_confidence = sum(r.get('confidence', 0) for r in results.values() if 'confidence' in r)
       avg_confidence = total_confidence / len([r for r in results.values() if 'confidence' in r]) if results else 0
       
       buy_signals = len([r for r in results.values() if r.get('quick_signal') == 'BUY'])
       sell_signals = len([r for r in results.values() if r.get('quick_signal') == 'SELL'])
       
       return {
           "portfolio_summary": {
               "total_symbols": len(symbol_list),
               "analyzed_symbols": len([r for r in results.values() if 'error' not in r]),
               "average_confidence": round(avg_confidence, 2),
               "buy_signals": buy_signals,
               "sell_signals": sell_signals,
               "hold_signals": len(symbol_list) - buy_signals - sell_signals
           },
           "individual_analysis": results,
           "timestamp": datetime.now()
       }
       
   except Exception as e:
       logger.error(f"Error in portfolio analysis: {str(e)}")
       raise HTTPException(status_code=500, detail=f"Portfolio analysis failed: {str(e)}")

@app.get("/ml/market_sentiment")
async def ml_market_sentiment():
   """
   📊 Market Sentiment Analysis
   
   Returns overall market sentiment and conditions
   """
   if not ML_AVAILABLE or not ml_service:
       raise HTTPException(status_code=503, detail="ML service not available")
   
   try:
       sentiment = await ml_service.sentiment_analyzer.analyze_market_sentiment(ml_service.client)
       return {
           "market_sentiment": sentiment.dict(),
           "timestamp": datetime.now()
       }
       
   except Exception as e:
       logger.error(f"Error in market sentiment analysis: {str(e)}")
       raise HTTPException(status_code=500, detail=f"Market sentiment analysis failed: {str(e)}")

@app.post("/ml/train_model/{symbol}")
async def ml_train_model(
   symbol: str,
   epochs: int = Query(50, ge=10, le=200, description="Training epochs (10-200)"),
   background_tasks: BackgroundTasks = None
):
   """
   🔧 Train/Retrain LSTM Model
   
   Train a custom LSTM model for any symbol
   """
   if not ML_AVAILABLE or not ml_service:
       raise HTTPException(status_code=503, detail="ML service not available")
   
   try:
       df = await ml_service.get_stock_data(symbol)
       metrics = await ml_service.lstm_manager.train_model(symbol, df, epochs)
       
       return {
           "symbol": symbol,
           "training_completed": True,
           "model_metrics": {
               "epochs_trained": metrics.epochs_trained,
               "accuracy_score": metrics.accuracy_score,
               "confidence_score": metrics.confidence_score,
               "mse": metrics.mse,
               "mae": metrics.mae,
               "rmse": metrics.rmse,
               "data_points_used": metrics.data_points_used
           },
           "timestamp": datetime.now()
       }
       
   except Exception as e:
       logger.error(f"Error training model for {symbol}: {str(e)}")
       raise HTTPException(status_code=500, detail=f"Model training failed: {str(e)}")

@app.post("/ml/batch/train_multiple")
async def ml_batch_train_models(
   symbols: str = Query(..., description="Comma-separated symbols to train"),
   epochs: int = Query(50, ge=10, le=100, description="Training epochs"),
   background_tasks: BackgroundTasks = None
):
   """
   🔄 Batch Train Multiple Models
   
   Train LSTM models for multiple symbols in batch
   """
   if not ML_AVAILABLE or not ml_service:
       raise HTTPException(status_code=503, detail="ML service not available")
   
   symbol_list = [s.strip().upper() for s in symbols.split(",")]
   results = {}
   
   for symbol in symbol_list[:5]:  # Limit to 5 symbols to prevent overload
       try:
           df = await ml_service.get_stock_data(symbol)
           metrics = await ml_service.lstm_manager.train_model(symbol, df, epochs)
           
           results[symbol] = {
               "status": "success",
               "accuracy_score": metrics.accuracy_score,
               "confidence_score": metrics.confidence_score,
               "epochs_trained": metrics.epochs_trained
           }
           
       except Exception as e:
           results[symbol] = {
               "status": "error",
               "error": str(e)
           }
   
   return {
       "batch_training": "completed",
       "symbols_processed": len(symbol_list),
       "results": results,
       "timestamp": datetime.now()
   }

@app.get("/ml/batch/analyze_portfolio")
async def ml_batch_portfolio_analysis(
   symbols: str = Query(..., description="Comma-separated portfolio symbols"),
   include_predictions: bool = Query(True, description="Include ML predictions"),
   include_risk: bool = Query(True, description="Include risk analysis")
):
   """
   📊 Batch Portfolio Analysis
   
   Comprehensive analysis of an entire portfolio
   """
   if not ML_AVAILABLE or not ml_service:
       raise HTTPException(status_code=503, detail="ML service not available")
   
   symbol_list = [s.strip().upper() for s in symbols.split(",")]
   portfolio_analysis = {}
   
   for symbol in symbol_list[:10]:  # Limit to 10 symbols
       try:
           if include_predictions:
               # Get comprehensive analysis
               analysis = await ml_service.comprehensive_analysis(symbol, days_ahead=30, retrain=False)
               portfolio_analysis[symbol] = {
                   "current_price": float(analysis.current_data.get('quote', {}).get('Global Quote', {}).get('05. price', 0)),
                   "recommendation": analysis.recommendation.recommendation.value,
                   "expected_return": analysis.recommendation.expected_return_30d,
                   "risk_level": analysis.recommendation.risk_level.value,
                   "confidence": analysis.recommendation.confidence_score,
                   "volatility": analysis.risk_metrics.annual_volatility,
                   "sharpe_ratio": analysis.risk_metrics.sharpe_ratio
               }
           else:
               # Get just quick insights
               insights = await ml_service.quick_insights(symbol)
               portfolio_analysis[symbol] = {
                   "current_price": insights.get('current_price', 0),
                   "quick_signal": insights.get('quick_signal', 'HOLD'),
                   "confidence": insights.get('confidence', 0.5)
               }
               
       except Exception as e:
           portfolio_analysis[symbol] = {"error": str(e)}
   
   # Calculate portfolio metrics
   successful_analyses = {k: v for k, v in portfolio_analysis.items() if 'error' not in v}
   
   if successful_analyses:
       avg_expected_return = sum(a.get('expected_return', 0) for a in successful_analyses.values()) / len(successful_analyses)
       avg_confidence = sum(a.get('confidence', 0) for a in successful_analyses.values()) / len(successful_analyses)
       avg_volatility = sum(a.get('volatility', 0) for a in successful_analyses.values()) / len(successful_analyses) if include_risk else 0
       
       buy_count = len([a for a in successful_analyses.values() if a.get('recommendation') == 'BUY' or a.get('quick_signal') == 'BUY'])
       sell_count = len([a for a in successful_analyses.values() if a.get('recommendation') == 'SELL' or a.get('quick_signal') == 'SELL'])
       
       portfolio_summary = {
           "total_symbols": len(symbol_list),
           "analyzed_symbols": len(successful_analyses),
           "avg_expected_return_30d": round(avg_expected_return, 2),
           "avg_confidence": round(avg_confidence, 2),
           "avg_volatility": round(avg_volatility, 4),
           "buy_recommendations": buy_count,
           "sell_recommendations": sell_count,
           "hold_recommendations": len(successful_analyses) - buy_count - sell_count,
           "portfolio_sentiment": "Bullish" if buy_count > sell_count else "Bearish" if sell_count > buy_count else "Neutral"
       }
   else:
       portfolio_summary = {"error": "No successful analyses"}
   
   return {
       "portfolio_summary": portfolio_summary,
       "individual_analysis": portfolio_analysis,
       "analysis_timestamp": datetime.now()
   }

# ===================================
# WEBSOCKET ENDPOINTS (Real-time ML Updates)
# ===================================

@app.websocket("/ws/realtime/{symbol}")
async def websocket_realtime_updates(websocket: WebSocket, symbol: str):
   """
   🔄 Real-time Stock Updates via WebSocket
   
   Provides real-time ML updates for a specific stock symbol
   """
   if not ML_AVAILABLE or not ml_service or not websocket_manager:
       await websocket.close(code=1003, reason="ML service not available")
       return
   
   await websocket_manager.connect(websocket)
   try:
       while True:
           # Get real-time updates every 30 seconds
           try:
               insights = await ml_service.quick_insights(symbol)
               await websocket_manager.send_personal_message(json.dumps(insights, default=str), websocket)
               await asyncio.sleep(30)  # Update every 30 seconds
           except Exception as e:
               error_msg = {"error": f"Failed to get updates for {symbol}: {str(e)}"}
               await websocket_manager.send_personal_message(json.dumps(error_msg), websocket)
               await asyncio.sleep(60)  # Wait longer on error
               
   except WebSocketDisconnect:
       websocket_manager.disconnect(websocket)

# ===================================
# ADMIN AND MONITORING ENDPOINTS
# ===================================

@app.get("/admin/router/stats")
async def get_router_stats():
   """Get comprehensive router statistics"""
   if not alpha_vantage_client:
       raise HTTPException(status_code=503, detail="Service not initialized")
   
   stats = alpha_vantage_client.router.get_router_stats()
   return {
       "router_stats": stats,
       "timestamp": datetime.now()
   }

@app.get("/admin/router/health")
async def get_router_health():
   """Get router health status"""
   if not alpha_vantage_client:
       raise HTTPException(status_code=503, detail="Service not initialized")
   
   stats = alpha_vantage_client.router.get_router_stats()
   
   health_details = {
       "overall_status": stats["health_status"],
       "available_keys": stats["router_config"]["available_keys"],
       "total_keys": stats["router_config"]["total_keys"],
       "success_rate": stats["global_stats"]["global_success_rate"],
       "uptime_hours": stats["global_stats"]["uptime_seconds"] / 3600,
       "key_health": {}
   }
   
   # Detailed key health
   for key_id, key_stats in stats["key_stats"].items():
       health_details["key_health"][key_id] = {
           "status": key_stats["status"],
           "available": key_stats["is_available"],
           "success_rate": key_stats["success_rate"],
           "quota_remaining": key_stats["daily_quota_remaining"]
       }
   
   return health_details

@app.get("/admin/ml/models")
async def get_ml_models_status():
   """
   🤖 ML Models Status
   
   Get status of all trained ML models
   """
   if not ML_AVAILABLE or not ml_service:
       return {
           "ml_available": False,
           "message": "ML service not available",
           "timestamp": datetime.now()
       }
   
   try:
       models_info = {}
       for symbol in ml_service.lstm_manager.models.keys():
           if symbol in ml_service.lstm_manager.model_metrics:
               metrics = ml_service.lstm_manager.model_metrics[symbol]
               models_info[symbol] = {
                   "status": "trained",
                   "training_date": metrics.training_date,
                   "epochs_trained": metrics.epochs_trained,
                   "accuracy_score": metrics.accuracy_score,
                   "confidence_score": metrics.confidence_score,
                   "data_points_used": metrics.data_points_used
               }
           else:
               models_info[symbol] = {"status": "loaded"}
       
       return {
           "ml_available": True,
           "total_models": len(ml_service.lstm_manager.models),
           "models": models_info,
           "timestamp": datetime.now()
       }
   except Exception as e:
       logger.error(f"Error getting ML models status: {str(e)}")
       raise HTTPException(status_code=500, detail=f"Failed to get ML models status: {str(e)}")

@app.get("/admin/system/health")
async def get_system_health():
   """
   ❤️ System Health Check
   
   Comprehensive system health and performance metrics
   """
   health_status = {
       "status": "healthy",
       "timestamp": datetime.now(),
       "components": {
           "alpha_vantage_client": "healthy" if alpha_vantage_client else "unhealthy",
           "complete_data_service": "healthy" if complete_data_service else "unhealthy",
           "ml_service": "healthy" if ML_AVAILABLE and ml_service else "unhealthy",
           "websocket_manager": "healthy" if ML_AVAILABLE and websocket_manager else "unhealthy"
       },
       "performance": {
           "ml_models_loaded": len(ml_service.lstm_manager.models) if ML_AVAILABLE and ml_service else 0,
           "api_keys_available": len([m for m in alpha_vantage_client.router.api_keys.values() if m.is_available]) if alpha_vantage_client else 0,
           "ml_features_available": ML_AVAILABLE
       }
   }
   
   # Determine overall health
   if any(status == "unhealthy" for status in health_status["components"].values()):
       health_status["status"] = "degraded"
   
   return health_status

@app.get("/admin/api/coverage")
async def get_api_coverage():
   """Get complete API coverage information"""
   base_coverage = {
       "alpha_vantage_apis": {
           "core_stock_data": {
               "count": 8,
               "endpoints": [
                   "TIME_SERIES_INTRADAY",
                   "TIME_SERIES_DAILY", 
                   "TIME_SERIES_DAILY_ADJUSTED",
                   "TIME_SERIES_WEEKLY",
                   "TIME_SERIES_WEEKLY_ADJUSTED", 
                   "TIME_SERIES_MONTHLY",
                   "TIME_SERIES_MONTHLY_ADJUSTED",
                   "GLOBAL_QUOTE"
               ]
           },
           "fundamental_data": {
               "count": 10,
               "endpoints": [
                   "OVERVIEW",
                   "INCOME_STATEMENT",
                   "BALANCE_SHEET", 
                   "CASH_FLOW",
                   "EARNINGS",
                   "DIVIDENDS",
                   "SPLITS",
                   "ETF_PROFILE",
                   "LISTING_STATUS",
                   "EARNINGS_CALENDAR"
               ]
           },
           "options_data": {
               "count": 3,
               "endpoints": [
                   "REALTIME_OPTIONS",
                   "HISTORICAL_OPTIONS"
               ],
               "note": "Premium subscription required"
           },
           "utility_apis": {
               "count": 4,
               "endpoints": [
                   "SYMBOL_SEARCH",
                   "MARKET_STATUS",
                   "LISTING_STATUS",
                   "IPO_CALENDAR"
               ]
           },
           "alpha_intelligence": {
               "count": 1,
               "endpoints": [
                   "NEWS_SENTIMENT"
               ]
           }
       },
       "total_alpha_vantage_endpoints": 26
   }
   
   if ML_AVAILABLE:
       base_coverage["ml_apis"] = {
           "prediction_endpoints": {
               "count": 4,
               "endpoints": [
                   "/ml/comprehensive_analysis/{symbol}",
                   "/ml/predict/{symbol}",
                   "/ml/technical_analysis/{symbol}",
                   "/ml/quick_insights/{symbol}"
               ]
           },
           "portfolio_endpoints": {
               "count": 3,
               "endpoints": [
                   "/ml/portfolio_analysis",
                   "/ml/batch/analyze_portfolio",
                   "/ml/market_sentiment"
               ]
           },
           "training_endpoints": {
               "count": 2,
               "endpoints": [
                   "/ml/train_model/{symbol}",
                   "/ml/batch/train_multiple"
               ]
           },
           "realtime_endpoints": {
               "count": 1,
               "endpoints": [
                   "/ws/realtime/{symbol}"
               ]
           }
       }
       base_coverage["total_ml_endpoints"] = 10
       base_coverage["total_endpoints"] = 36
   else:
       base_coverage["ml_apis"] = {
           "status": "not_available",
           "reason": "ML module not loaded"
       }
       base_coverage["total_ml_endpoints"] = 0
       base_coverage["total_endpoints"] = 26
   
   base_coverage.update({
       "implementation_status": "complete",
       "ml_available": ML_AVAILABLE,
       "timestamp": datetime.now()
   })
   
   return base_coverage

# ===================================
# EXAMPLE AND TESTING ENDPOINTS
# ===================================

@app.get("/examples/comprehensive/{symbol}")
async def example_comprehensive_analysis(symbol: str = "AAPL"):
   """
   📋 Example: Complete Analysis
   
   Shows example of comprehensive ML analysis for a stock
   """
   if not ML_AVAILABLE or not ml_service:
       return {
           "example_type": "Complete Analysis",
           "error": "ML service not available",
           "note": "ML features require the ml_financial_api module to be properly loaded",
           "alternative": f"Try /fetch_complete_data/{symbol} for Alpha Vantage data"
       }
   
   try:
       result = await ml_comprehensive_analysis(symbol, days_ahead=30, retrain=False)
       return {
           "example_type": "Comprehensive ML Analysis",
           "description": "Complete analysis including ML predictions, technical analysis, risk assessment, and AI recommendations",
           "sample_data": result,
           "api_endpoint": f"/ml/comprehensive_analysis/{symbol}",
           "use_cases": [
               "Investment decision making",
               "Portfolio optimization",
               "Risk assessment",
               "Trading signal generation",
               "Financial dashboard backends"
           ]
       }
   except Exception as e:
       return {
           "example_type": "Comprehensive ML Analysis",
           "error": str(e),
           "note": "This is an example endpoint. Real analysis requires valid API keys and data."
       }

@app.get("/examples/predictions/{symbol}")
async def example_predictions(symbol: str = "AAPL"):
   """
   📈 Example: LSTM Predictions
   
   Shows example of ML price predictions
   """
   if not ML_AVAILABLE or not ml_service:
       return {
           "example_type": "LSTM Predictions",
           "error": "ML service not available",
           "note": "ML features require the ml_financial_api module to be properly loaded"
       }
   
   try:
       result = await ml_lstm_predictions(symbol, days_ahead=7, retrain=False)
       return {
           "example_type": "LSTM Price Predictions",
           "description": "Machine learning price predictions using LSTM neural networks",
           "sample_data": result,
           "api_endpoint": f"/ml/predict/{symbol}",
           "use_cases": [
               "Price forecasting",
               "Trading algorithms",
               "Investment timing",
               "Risk management"
           ]
       }
   except Exception as e:
       return {
           "example_type": "LSTM Price Predictions",
           "error": str(e),
           "note": "This is an example endpoint. Real predictions require valid API keys and trained models."
       }

@app.get("/examples/alpha_vantage/{symbol}")
async def example_alpha_vantage(symbol: str = "AAPL"):
   """
   📊 Example: Alpha Vantage Complete Data
   
   Shows example of complete Alpha Vantage data fetching
   """
   try:
       result = await fetch_complete_company_data(
           symbol=symbol, 
           background_tasks=BackgroundTasks(),
           include_options=False,
           include_news=True,
           include_historical=False
       )
       return {
           "example_type": "Complete Alpha Vantage Data",
           "description": "All available Alpha Vantage data for comprehensive company analysis",
           "sample_data": result,
           "api_endpoint": f"/fetch_complete_data/{symbol}",
           "use_cases": [
               "Company research",
               "Fundamental analysis",
               "Market data aggregation",
               "Financial reporting",
               "Investment research platforms"
           ]
       }
   except Exception as e:
       return {
           "example_type": "Complete Alpha Vantage Data",
           "error": str(e),
           "note": "This is an example endpoint. Real data requires valid API keys."
       }

# Background tasks
async def log_complete_request(symbol: str, success_count: int, total_endpoints: int,
                            include_options: bool, include_news: bool, include_historical: bool):
   """Background task to log complete request details"""
   logger.info(
       f"📊 Complete request logged - Symbol: {symbol}, "
       f"Success: {success_count}/{total_endpoints}, "
       f"Options: {include_options}, News: {include_news}, Historical: {include_historical}"
   )

# ===================================
# MAIN EXECUTION
# ===================================

if __name__ == "__main__":
   import uvicorn
   
   print("🚀 Complete Financial Analytics Dashboard API with ML Integration")
   print("=" * 80)
   print("📊 ALL Alpha Vantage APIs Integrated:")
   print("   🔹 Core Stock Data: 8 endpoints")
   print("     └ Intraday, Daily, Weekly, Monthly, Quote, Adjusted data")
   print("   🔹 Fundamental Data: 10 endpoints") 
   print("     └ Overview, Financials, Earnings, Dividends, Splits, ETF, Calendars")
   print("   🔹 Options Data: 3 endpoints (Premium)")
   print("     └ Realtime Options, Historical Options, Greeks")
   print("   🔹 Utility APIs: 4 endpoints")
   print("     └ Search, Market Status, Listings, IPO Calendar")
   print("   🔹 Alpha Intelligence: 1 endpoint")
   print("     └ News & Sentiment Analysis")
   print()
   if ML_AVAILABLE:
       print("🤖 ML-Powered Analytics Available:")
       print("   🔹 LSTM Prediction APIs: 4 endpoints")
       print("     └ Comprehensive Analysis, Price Predictions, Technical Analysis, Quick Insights")
       print("   🔹 Portfolio Analytics: 3 endpoints")
       print("     └ Portfolio Analysis, Batch Analysis, Market Sentiment")
       print("   🔹 Model Training: 2 endpoints")
       print("     └ Single Training, Batch Training")
       print("   🔹 Real-time Updates: 1 WebSocket endpoint")
       print("     └ Live ML-powered stock updates")
       print()
       print("📈 Total: 36+ endpoints (26 Alpha Vantage + 10 ML) for complete analysis!")
   else:
       print("⚠️ ML Features Not Available:")
       print("   └ ml_financial_api module not loaded")
       print("   └ Only Alpha Vantage APIs available (26 endpoints)")
       print()
       print("📈 Total: 26 Alpha Vantage endpoints for complete fundamental analysis!")
   
   print()
   print("🔑 Multi-API Key Router Features:")
   print("   ✅ Intelligent load balancing (least-used strategy)")
   print("   ✅ Automatic rate limit handling")
   print("   ✅ Real-time performance monitoring")
   print("   ✅ Graceful error handling and recovery")
   print("   ✅ Comprehensive statistics and health checks")
   print()
   print("🌐 Key API Endpoints:")
   print("   📊 Complete Alpha Vantage: /fetch_complete_data/AAPL")
   print("   📈 Core Data: /fetch_core_data/AAPL")
   print("   📋 Fundamental: /fetch_fundamental_data/AAPL")
   print("   📊 Options: /fetch_options_data/AAPL")
   print("   📰 News: /fetch_news_sentiment/AAPL")
   print("   💹 Quote: /quote/AAPL")
   print("   🔍 Search: /search/apple")
   print("   📅 Market: /market-status")
   
   if ML_AVAILABLE:
       print()
       print("🤖 ML API Endpoints:")
       print("   🎯 ML Complete Analysis: /ml/comprehensive_analysis/AAPL")
       print("   🔮 LSTM Predictions: /ml/predict/AAPL")
       print("   📊 Technical Analysis: /ml/technical_analysis/AAPL")
       print("   ⚡ Quick Insights: /ml/quick_insights/AAPL")
       print("   📈 Portfolio Analysis: /ml/portfolio_analysis?symbols=AAPL,MSFT,GOOGL")
       print("   🔧 Train Model: /ml/train_model/AAPL")
       print("   🔄 Real-time Updates: ws://localhost:8000/ws/realtime/AAPL")
   
   print()
   print("📚 Documentation & Admin:")
   print("   📖 API Docs: http://localhost:8000/docs")
   print("   📊 Router Stats: http://localhost:8000/admin/router/stats")
   print("   🏥 Health Check: http://localhost:8000/admin/system/health")
   print("   📋 API Coverage: http://localhost:8000/admin/api/coverage")
   if ML_AVAILABLE:
       print("   🤖 ML Models: http://localhost:8000/admin/ml/models")
   
   print()
   print("🔧 Configuration:")
   print("   📁 Add your API keys to .env file:")
   print("   ALPHA_VANTAGE_API_KEYS=key1,key2,key3,key4,key5")
   print("   📁 Ensure ml_financial_api.py is in the same directory for ML features")
   print("=" * 80)
   
   uvicorn.run(
       "main:app",
       host="0.0.0.0",
       port=8000,
       reload=True,
       log_level="info"
   )
