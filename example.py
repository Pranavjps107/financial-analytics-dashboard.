
# ===================================
# examples.py - Usage Examples
# ===================================

import asyncio
import requests
import json
from datetime import datetime

# Example 1: Basic API Usage
def example_basic_usage():
    """Basic example of using the API"""
    base_url = "http://localhost:8000"
    
    print("🔍 Testing API Health Check")
    response = requests.get(f"{base_url}/")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    print()
    
    print("📈 Getting Quick Quote for AAPL")
    response = requests.get(f"{base_url}/quote/AAPL")
    if response.status_code == 200:
        data = response.json()
        print(f"Symbol: {data['symbol']}")
        print(f"Quote Data: {json.dumps(data['quote'], indent=2)}")
    else:
        print(f"Error: {response.status_code} - {response.text}")
    print()
    
    print("🔍 Searching for 'apple' symbols")
    response = requests.get(f"{base_url}/search/apple")
    if response.status_code == 200:
        data = response.json()
        print(f"Search Results: {json.dumps(data['results'], indent=2)}")
    print()

# Example 2: Comprehensive Data Fetch
def example_comprehensive_fetch():
    """Example of fetching comprehensive data"""
    base_url = "http://localhost:8000"
    symbol = "MSFT"
    
    print(f"📊 Fetching comprehensive data for {symbol}")
    print("This may take a few minutes due to rate limiting...")
    
    response = requests.get(f"{base_url}/fetch_company_data/{symbol}")
    
    if response.status_code == 200:
        data = response.json()
        
        print(f"\n✅ Data fetch completed for {data['symbol']}")
        print(f"📅 Timestamp: {data['timestamp']}")
        print(f"📈 Success Rate: {data['success_count']}/{data['total_endpoints']}")
        
        if data['errors']:
            print(f"⚠️  Errors encountered: {len(data['errors'])}")
            for error in data['errors']:
                print(f"   - {error}")
        
        # Display core stock data summary
        print(f"\n📊 Core Stock Data ({len(data['core_stock_data'])} endpoints):")
        for endpoint, result in data['core_stock_data'].items():
            status = "✅" if result else "❌"
            print(f"   {status} {endpoint}")
        
        # Display fundamental data summary
        print(f"\n📋 Fundamental Data ({len(data['fundamental_data'])} endpoints):")
        for endpoint, result in data['fundamental_data'].items():
            status = "✅" if result else "❌"
            print(f"   {status} {endpoint}")
        
        # Display utility data summary
        print(f"\n🔧 Utility Data ({len(data['utility_data'])} endpoints):")
        for endpoint, result in data['utility_data'].items():
            status = "✅" if result else "❌"
            print(f"   {status} {endpoint}")
            
    else:
        print(f"❌ Error: {response.status_code}")
        print(f"Response: {response.text}")

# Example 3: Data Processing and Analysis
def example_data_processing():
    """Example of processing the fetched data"""
    import pandas as pd
    
    base_url = "http://localhost:8000"
    symbol = "AAPL"
    
    # Fetch comprehensive data
    response = requests.get(f"{base_url}/fetch_company_data/{symbol}")
    
    if response.status_code == 200:
        data = response.json()
        
        # Extract quote data
        if 'quote' in data['core_stock_data']:
            quote_data = data['core_stock_data']['quote']
            if 'Global Quote' in quote_data:
                quote = quote_data['Global Quote']
                print(f"📈 Current Price: ${quote.get('05. price', 'N/A')}")
                print(f"📊 Volume: {quote.get('06. volume', 'N/A')}")
                print(f"📈 Change: {quote.get('09. change', 'N/A')} ({quote.get('10. change percent', 'N/A')})")
        
        # Extract company overview
        if 'overview' in data['fundamental_data']:
            overview = data['fundamental_data']['overview']
            print(f"\n🏢 Company: {overview.get('Name', 'N/A')}")
            print(f"🏭 Sector: {overview.get('Sector', 'N/A')}")
            print(f"🏭 Industry: {overview.get('Industry', 'N/A')}")
            print(f"💰 Market Cap: ${overview.get('MarketCapitalization', 'N/A')}")
            print(f"📊 P/E Ratio: {overview.get('PERatio', 'N/A')}")
        
        # Process daily data for analysis
        if 'daily' in data['core_stock_data']:
            daily_data = data['core_stock_data']['daily']
            if 'Time Series (Daily)' in daily_data:
                time_series = daily_data['Time Series (Daily)']
                
                # Convert to DataFrame for analysis
                df = pd.DataFrame.from_dict(time_series, orient='index')
                df.index = pd.to_datetime(df.index)
                df = df.astype(float)
                
                print(f"\n📅 Daily Data Analysis (Last 5 days):")
                print(df.head())
                
                # Calculate simple moving average
                df['SMA_5'] = df['4. close'].rolling(window=5).mean()
                print(f"\n📈 5-Day Moving Average: ${df['SMA_5'].iloc[0]:.2f}")

# Example 4: Async Client Usage
async def example_async_usage():
    """Example of using the API asynchronously"""
    import aiohttp
    
    base_url = "http://localhost:8000"
    symbols = ["AAPL", "MSFT", "GOOGL"]
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        
        for symbol in symbols:
            async def fetch_quote(sym):
                url = f"{base_url}/quote/{sym}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return sym, data
                    return sym, None
            
            tasks.append(fetch_quote(symbol))
        
        results = await asyncio.gather(*tasks)
        
        print("📊 Multiple Symbol Quotes:")
        for symbol, data in results:
            if data:
                quote = data.get('quote', {}).get('Global Quote', {})
                price = quote.get('05. price', 'N/A')
                change = quote.get('10. change percent', 'N/A')
                print(f"   {symbol}: ${price} ({change})")
            else:
                print(f"   {symbol}: Failed to fetch")

# Example 5: Error Handling and Retry Logic
def example_error_handling():
    """Example of proper error handling"""
    import time
    
    base_url = "http://localhost:8000"
    
    def fetch_with_retry(url, max_retries=3, delay=1):
        """Fetch data with retry logic"""
        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=30)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:  # Rate limited
                    print(f"Rate limited. Waiting {delay * (attempt + 1)} seconds...")
                    time.sleep(delay * (attempt + 1))
                    continue
                else:
                    print(f"HTTP Error {response.status_code}: {response.text}")
                    return None
                    
            except requests.exceptions.Timeout:
                print(f"Timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
                    
            except requests.exceptions.ConnectionError:
                print(f"Connection error on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
        
        return None
    
    # Test with retry logic
    print("🔄 Testing with retry logic")
    data = fetch_with_retry(f"{base_url}/quote/AAPL")
    
    if data:
        print("✅ Successfully fetched data")
        print(f"Quote: {json.dumps(data, indent=2)}")
    else:
        print("❌ Failed to fetch data after retries")

# Main execution
if __name__ == "__main__":
    print("🚀 Financial Analytics Dashboard - Usage Examples")
    print("=" * 60)
    
    print("\n1. Basic Usage Example")
    try:
        example_basic_usage()
    except Exception as e:
        print(f"Error in basic usage: {e}")
    
    print("\n2. Comprehensive Data Fetch Example")
    try:
        example_comprehensive_fetch()
    except Exception as e:
        print(f"Error in comprehensive fetch: {e}")
    
    print("\n3. Data Processing Example")
    try:
        example_data_processing()
    except Exception as e:
        print(f"Error in data processing: {e}")
    
    print("\n4. Async Usage Example")
    try:
        asyncio.run(example_async_usage())
    except Exception as e:
        print(f"Error in async usage: {e}")
    
    print("\n5. Error Handling Example")
    try:
        example_error_handling()
    except Exception as e:
        print(f"Error in error handling example: {e}")
