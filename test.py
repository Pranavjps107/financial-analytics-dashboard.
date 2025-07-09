
# test_main.py - Comprehensive Test Suite
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from datetime import datetime
import json

from main import app, alpha_vantage_client, data_service

client = TestClient(app)

# Mock data for testing
MOCK_QUOTE_RESPONSE = {
    "Global Quote": {
        "01. symbol": "AAPL",
        "05. price": "150.25",
        "09. change": "2.50",
        "10. change percent": "+1.69%",
        "06. volume": "50000000"
    }
}

MOCK_OVERVIEW_RESPONSE = {
    "Symbol": "AAPL",
    "Name": "Apple Inc",
    "Description": "Apple Inc. designs, manufactures, and markets smartphones...",
    "Exchange": "NASDAQ",
    "Currency": "USD",
    "Country": "USA",
    "Sector": "Technology",
    "Industry": "Consumer Electronics",
    "MarketCapitalization": "2500000000000",
    "PERatio": "25.5",
    "DividendYield": "0.50"
}

class TestAPI:
    """Test suite for the main API endpoints"""
    
    def test_root_endpoint(self):
        """Test the root health check endpoint"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Financial Analytics Dashboard API"
        assert data["status"] == "healthy"
        assert "timestamp" in data
    
    @patch('main.alpha_vantage_client.get_quote')
    def test_quick_quote_success(self, mock_get_quote):
        """Test successful quote fetch"""
        mock_get_quote.return_value = asyncio.create_task(
            asyncio.coroutine(lambda: MOCK_QUOTE_RESPONSE)()
        )
        
        response = client.get("/quote/AAPL")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert "quote" in data
        assert "timestamp" in data
    
    def test_quick_quote_invalid_symbol(self):
        """Test quote fetch with invalid symbol"""
        response = client.get("/quote/")
        assert response.status_code == 404  # Not found due to empty symbol
    
    @patch('main.alpha_vantage_client.search_symbol')
    def test_search_symbols(self, mock_search):
        """Test symbol search functionality"""
        mock_search.return_value = asyncio.create_task(
            asyncio.coroutine(lambda: {"bestMatches": []})()
        )
        
        response = client.get("/search/apple")
        assert response.status_code == 200
        data = response.json()
        assert data["keywords"] == "apple"
        assert "results" in data
    
    @patch('main.alpha_vantage_client.get_market_status')
    def test_market_status(self, mock_market_status):
        """Test market status endpoint"""
        mock_market_status.return_value = asyncio.create_task(
            asyncio.coroutine(lambda: {"markets": []})()
        )
        
        response = client.get("/market-status")
        assert response.status_code == 200
        data = response.json()
        assert "market_status" in data
        assert "timestamp" in data

class TestAlphaVantageClient:
    """Test suite for Alpha Vantage client"""
    
    @pytest.fixture
    def mock_session(self):
        """Mock requests session"""
        with patch.object(alpha_vantage_client, 'session') as mock:
            mock_response = Mock()
            mock_response.json.return_value = MOCK_QUOTE_RESPONSE
            mock_response.raise_for_status.return_value = None
            mock.get.return_value = mock_response
            yield mock
    
    @pytest.mark.asyncio
    async def test_get_quote(self, mock_session):
        """Test quote data fetching"""
        result = await alpha_vantage_client.get_quote("AAPL")
        assert result == MOCK_QUOTE_RESPONSE
        mock_session.get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_api_error_handling(self):
        """Test API error handling"""
        with patch.object(alpha_vantage_client.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"Error Message": "Invalid API call"}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            
            with pytest.raises(ValueError, match="API Error"):
                await alpha_vantage_client.get_quote("INVALID")

class TestDataService:
    """Test suite for data service"""
    
    @pytest.mark.asyncio
    async def test_comprehensive_data_fetch(self):
        """Test comprehensive data fetching"""
        with patch.multiple(
            alpha_vantage_client,
            get_quote=AsyncMock(return_value=MOCK_QUOTE_RESPONSE),
            get_company_overview=AsyncMock(return_value=MOCK_OVERVIEW_RESPONSE),
            get_daily=AsyncMock(return_value={"Time Series (Daily)": {}}),
            get_intraday=AsyncMock(return_value={"Time Series (5min)": {}}),
            get_weekly=AsyncMock(return_value={"Weekly Time Series": {}}),
            get_monthly=AsyncMock(return_value={"Monthly Time Series": {}}),
            get_daily_adjusted=AsyncMock(return_value={"Time Series (Daily)": {}}),
            get_weekly_adjusted=AsyncMock(return_value={"Weekly Adjusted Time Series": {}}),
            get_monthly_adjusted=AsyncMock(return_value={"Monthly Adjusted Time Series": {}}),
            get_dividends=AsyncMock(return_value={"data": []}),
            get_splits=AsyncMock(return_value={"data": []}),
            get_income_statement=AsyncMock(return_value={"annualReports": []}),
            get_balance_sheet=AsyncMock(return_value={"annualReports": []}),
            get_cash_flow=AsyncMock(return_value={"annualReports": []}),
            get_earnings=AsyncMock(return_value={"annualEarnings": []}),
            search_symbol=AsyncMock(return_value={"bestMatches": []}),
            get_market_status=AsyncMock(return_value={"markets": []})
        ):
            result = await data_service.fetch_comprehensive_data("AAPL")
            
            assert result.symbol == "AAPL"
            assert result.success_count > 0
            assert len(result.errors) == 0
            assert result.total_endpoints > 0
