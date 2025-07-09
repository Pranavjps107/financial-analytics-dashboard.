
# ===================================
# enhanced_main.py - Enhanced Main with Caching and Database
# ===================================

# Add these imports to your main.py
from supabase_client import supabase_client
from cache import cache_client

# Enhanced endpoint with caching and database storage
@app.get("/fetch_company_data/{symbol}", response_model=CompanyDataResponse)
async def enhanced_fetch_company_data(
    symbol: str,
    background_tasks: BackgroundTasks,
    use_cache: bool = True,
    force_refresh: bool = False
) -> CompanyDataResponse:
    """
    Enhanced endpoint with caching and database storage
    
    Args:
        symbol: Stock symbol
        use_cache: Whether to use cached data
        force_refresh: Force refresh even if cached data exists
    """
    try:
        symbol = symbol.upper().strip()
        
        # Check cache first (if enabled and not forcing refresh)
        if use_cache and not force_refresh:
            cache_key = f"company_data:{symbol}"
            cached_data = cache_client.get(cache_key)
            
            if cached_data:
                logger.info(f"Returning cached data for {symbol}")
                return CompanyDataResponse(**cached_data)
        
        # Check database for recent data
        if not force_refresh:
            db_data = await supabase_client.get_company_data(symbol, hours_old=6)
            if db_data:
                logger.info(f"Returning database data for {symbol}")
                # Cache the database data
                if use_cache:
                    cache_client.set(f"company_data:{symbol}", db_data, ttl=1800)  # 30 min
                return CompanyDataResponse(**db_data)
        
        # Fetch fresh data
        logger.info(f"Fetching fresh data for {symbol}")
        response = await data_service.fetch_comprehensive_data(symbol)
        
        # Store in database
        background_tasks.add_task(
            supabase_client.save_company_data, 
            symbol, 
            response.dict()
        )
        
        # Cache the response
        if use_cache:
            cache_client.set(
                f"company_data:{symbol}", 
                response.dict(), 
                ttl=1800  # 30 minutes
            )
        
        return response
        
    except Exception as e:
        logger.error(f"Error in enhanced fetch for {symbol}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Analytics endpoint
@app.get("/analytics/symbol/{symbol}")
async def get_symbol_analytics(symbol: str):
    """Get analytics for a specific symbol"""
    # This would query your database for historical request patterns
    # Return insights like request frequency, success rates, etc.
    pass

@app.get("/analytics/performance")
async def get_performance_analytics():
    """Get overall API performance analytics"""
    from performance_monitor import performance_monitor
    return performance_monitor.get_stats()
