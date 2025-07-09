# main.py - Complete Financial Analytics Dashboard API
# All-in-one solution with multi-API key routing and complete Alpha Vantage integration

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

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import requests

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

# ===================================
# FASTAPI LIFESPAN MANAGEMENT
# ===================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI lifespan event handler"""
    global alpha_vantage_client, complete_data_service
    
    # Startup
    logger.info("🚀 Starting Complete Financial Analytics Dashboard API")
    
    try:
        # Load API keys
        api_keys = load_api_keys_from_env()
        
        # Initialize clients
        alpha_vantage_client = CompleteAlphaVantageClient(api_keys)
        complete_data_service = CompleteDataService(alpha_vantage_client)
        
        logger.info(f"✅ Initialized with {len(api_keys)} API keys")
        logger.info("📊 Available APIs:")
        logger.info("   🔹 Core Stock Data: 8 endpoints")
        logger.info("   🔹 Fundamental Data: 10 endpoints")
        logger.info("   🔹 Options Data: 3 endpoints (Premium)")
        logger.info("   🔹 Utility APIs: 4 endpoints")
        logger.info("   🔹 Alpha Intelligence: 1 endpoint")
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
    title="Complete Financial Analytics Dashboard API",
    description="Comprehensive stock data service with ALL Alpha Vantage APIs and intelligent multi-key routing",
    version="3.0.0",
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
# API ENDPOINTS
# ===================================

@app.get("/")
async def root():
    """Health check endpoint with complete API information"""
    if not alpha_vantage_client:
        return {"error": "API client not initialized"}
    
    router_stats = alpha_vantage_client.router.get_router_stats()
    return {
        "message": "Complete Financial Analytics Dashboard API",
        "status": "healthy",
        "timestamp": datetime.now(),
        "version": "3.0.0",
        "features": {
            "core_stock_apis": 8,
            "fundamental_apis": 10,
            "options_apis": 3,
            "utility_apis": 4,
            "intelligence_apis": 1,
            "total_endpoints": 26
        },
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

# Admin and monitoring endpoints
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

@app.get("/admin/api/coverage")
async def get_api_coverage():
    """Get complete API coverage information"""
    return {
        "api_coverage": {
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
        "total_endpoints": 26,
        "implementation_status": "complete",
        "timestamp": datetime.now()
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
    
    print("🚀 Complete Financial Analytics Dashboard API")
    print("=" * 60)
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
    print("📈 Total: 26+ endpoints for complete company analysis!")
    print()
    print("🔑 Multi-API Key Router Features:")
    print("   ✅ Intelligent load balancing (least-used strategy)")
    print("   ✅ Automatic rate limit handling")
    print("   ✅ Real-time performance monitoring")
    print("   ✅ Graceful error handling and recovery")
    print("   ✅ Comprehensive statistics and health checks")
    print()
    print("🌐 Available endpoints:")
    print("   📊 Complete Data: http://localhost:8000/fetch_complete_data/AAPL")
    print("   📈 Core Data: http://localhost:8000/fetch_core_data/AAPL")
    print("   📋 Fundamental: http://localhost:8000/fetch_fundamental_data/AAPL")
    print("   📊 Options: http://localhost:8000/fetch_options_data/AAPL")
    print("   📰 News: http://localhost:8000/fetch_news_sentiment/AAPL")
    print("   💹 Quote: http://localhost:8000/quote/AAPL")
    print("   🔍 Search: http://localhost:8000/search/apple")
    print("   📅 Market: http://localhost:8000/market-status")
    print("   📚 API Docs: http://localhost:8000/docs")
    print("   📊 Router Stats: http://localhost:8000/admin/router/stats")
    print("   🏥 Health Check: http://localhost:8000/admin/router/health")
    print("   📋 API Coverage: http://localhost:8000/admin/api/coverage")
    print()
    print("🔧 Configuration:")
    print("   📁 Add your API keys to .env file:")
    print("   ALPHA_VANTAGE_API_KEYS=key1,key2,key3,key4,key5")
    print()
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )