
# ===================================
# models.py - Enhanced Pydantic Models
# ===================================

from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from enum import Enum

class DataFetchStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"

class QuoteData(BaseModel):
    symbol: str
    price: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[str] = None
    volume: Optional[int] = None
    timestamp: datetime

class CompanyOverview(BaseModel):
    symbol: str
    name: Optional[str] = None
    description: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    country: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[str] = None
    pe_ratio: Optional[str] = None
    dividend_yield: Optional[str] = None

class APIEndpointResult(BaseModel):
    endpoint_name: str
    status: DataFetchStatus
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    response_time_ms: Optional[float] = None

class EnhancedCompanyDataResponse(BaseModel):
    symbol: str
    timestamp: datetime
    overall_status: DataFetchStatus
    
    # Categorized results
    core_stock_data: List[APIEndpointResult] = Field(default_factory=list)
    fundamental_data: List[APIEndpointResult] = Field(default_factory=list)
    utility_data: List[APIEndpointResult] = Field(default_factory=list)
    
    # Summary
    total_endpoints: int = 0
    successful_endpoints: int = 0
    failed_endpoints: int = 0
    total_response_time_ms: float = 0
    
    # Quick access to key data
    current_quote: Optional[QuoteData] = None
    company_overview: Optional[CompanyOverview] = None