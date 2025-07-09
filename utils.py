
# ===================================
# utils.py - Utility Functions
# ===================================

import json
import pandas as pd
from datetime import datetime
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def sanitize_symbol(symbol: str) -> str:
    """Sanitize and validate stock symbol"""
    if not symbol:
        raise ValueError("Symbol cannot be empty")
    
    # Remove whitespace and convert to uppercase
    clean_symbol = symbol.strip().upper()
    
    # Basic validation (alphanumeric and dots allowed)
    if not clean_symbol.replace('.', '').isalnum():
        raise ValueError(f"Invalid symbol format: {symbol}")
    
    return clean_symbol

def extract_quote_data(api_response: Dict[str, Any]) -> Optional[QuoteData]:
    """Extract quote data from Alpha Vantage response"""
    try:
        if "Global Quote" in api_response:
            quote = api_response["Global Quote"]
            return QuoteData(
                symbol=quote.get("01. symbol", ""),
                price=float(quote.get("05. price", 0)),
                change=float(quote.get("09. change", 0)),
                change_percent=quote.get("10. change percent", ""),
                volume=int(quote.get("06. volume", 0)),
                timestamp=datetime.now()
            )
    except (KeyError, ValueError, TypeError) as e:
        logger.error(f"Error extracting quote data: {e}")
    return None

def extract_company_overview(api_response: Dict[str, Any]) -> Optional[CompanyOverview]:
    """Extract company overview from Alpha Vantage response"""
    try:
        return CompanyOverview(
            symbol=api_response.get("Symbol", ""),
            name=api_response.get("Name", ""),
            description=api_response.get("Description", ""),
            exchange=api_response.get("Exchange", ""),
            currency=api_response.get("Currency", ""),
            country=api_response.get("Country", ""),
            sector=api_response.get("Sector", ""),
            industry=api_response.get("Industry", ""),
            market_cap=api_response.get("MarketCapitalization", ""),
            pe_ratio=api_response.get("PERatio", ""),
            dividend_yield=api_response.get("DividendYield", "")
        )
    except (KeyError, TypeError) as e:
        logger.error(f"Error extracting company overview: {e}")
    return None

def save_to_csv(data: Dict[str, Any], filename: str) -> bool:
    """Save data to CSV file"""
    try:
        # Convert nested dict to flattened structure for CSV
        flattened_data = {}
        
        def flatten_dict(d: Dict[str, Any], prefix: str = "") -> None:
            for key, value in d.items():
                new_key = f"{prefix}_{key}" if prefix else key
                if isinstance(value, dict):
                    flatten_dict(value, new_key)
                else:
                    flattened_data[new_key] = value
        
        flatten_dict(data)
        
        # Create DataFrame and save
        df = pd.DataFrame([flattened_data])
        df.to_csv(filename, index=False)
        logger.info(f"Data saved to {filename}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving to CSV: {e}")
        return False

def format_currency(amount: str) -> Optional[float]:
    """Format currency string to float"""
    try:
        if not amount or amount == "None":
            return None
        # Remove currency symbols and commas
        clean_amount = amount.replace("$", "").replace(",", "")
        return float(clean_amount)
    except (ValueError, AttributeError):
        return None
