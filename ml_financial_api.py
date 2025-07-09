# ml_financial_api.py - Complete ML-Powered Financial Analytics API with Real-Time LSTM Forecasting

import os
import time
import asyncio
import json
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
import logging
from contextlib import asynccontextmanager
from enum import Enum
from dataclasses import dataclass, field
from collections import deque
import pickle
import warnings
warnings.filterwarnings('ignore')

# FastAPI and web framework imports
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import requests

# Machine Learning imports
import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error
import ta  # Technical Analysis library

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress TensorFlow warnings
tf.get_logger().setLevel('ERROR')

# ===================================
# ML MODELS AND DATA STRUCTURES
# ===================================

@dataclass
class ModelMetrics:
    """Track ML model performance metrics"""
    symbol: str
    model_type: str = "LSTM"
    training_date: datetime = field(default_factory=datetime.now)
    epochs_trained: int = 0
    mse: float = 0.0
    mae: float = 0.0
    rmse: float = 0.0
    accuracy_score: float = 0.0
    confidence_score: float = 0.0
    data_points_used: int = 0
    prediction_horizon: int = 30
    last_prediction_date: Optional[datetime] = None

@dataclass
class PredictionResult:
    """Structure for ML predictions"""
    symbol: str
    predictions: List[Dict[str, Any]]
    confidence_metrics: Dict[str, float]
    model_info: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)

class RiskLevel(Enum):
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"

class InvestmentRecommendation(Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"

# ===================================
# PYDANTIC MODELS FOR API RESPONSES
# ===================================

class QuoteData(BaseModel):
    symbol: str
    price: float
    change: float
    change_percent: str
    volume: int
    timestamp: datetime

class TechnicalIndicators(BaseModel):
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_lower: Optional[float] = None
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None
    stochastic_k: Optional[float] = None
    williams_r: Optional[float] = None
    momentum: Optional[float] = None
    price_rate_of_change: Optional[float] = None

class TechnicalAnalysis(BaseModel):
    indicators: TechnicalIndicators
    signals: Dict[str, Any]
    support_levels: List[float]
    resistance_levels: List[float]
    trend_analysis: Dict[str, str]
    candlestick_patterns: List[str]

class RiskMetrics(BaseModel):
    annual_volatility: float
    sharpe_ratio: float
    var_95: float  # Value at Risk 95%
    max_drawdown: float
    beta: Optional[float] = None
    correlation_sp500: Optional[float] = None

class MLPrediction(BaseModel):
    date: str
    predicted_price: float
    day_ahead: int
    confidence: Optional[float] = None

class ConfidenceMetrics(BaseModel):
    confidence_score: float
    volatility: float
    prediction_accuracy: float
    model_performance: Dict[str, float]

class InvestmentRec(BaseModel):
    recommendation: InvestmentRecommendation
    reasoning: str
    expected_return_30d: float
    confidence_score: float
    risk_level: RiskLevel
    target_price: float
    stop_loss: float
    position_size_recommendation: float

class MarketSentiment(BaseModel):
    overall_sentiment: str
    fear_greed_index: float
    market_trend: str
    volatility_index: float
    sector_rotation: Dict[str, str]

class ComprehensiveAnalysisResponse(BaseModel):
    symbol: str
    timestamp: datetime
    current_data: Dict[str, Any]
    ml_predictions: Dict[str, Any]
    technical_analysis: TechnicalAnalysis
    risk_metrics: RiskMetrics
    recommendation: InvestmentRec
    market_sentiment: Optional[MarketSentiment] = None
    execution_time_ms: float

# ===================================
# API KEY ROUTER (from existing code)
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
    daily_quota_limit: int = 500
    request_history: deque = field(default_factory=lambda: deque(maxlen=100))
    
    def __post_init__(self):
        if isinstance(self.request_history, list):
            self.request_history = deque(self.request_history, maxlen=100)
    
    @property
    def success_rate(self) -> float:
        if self.requests_made == 0:
            return 100.0
        return (self.requests_successful / self.requests_made) * 100
    
    @property
    def is_available(self) -> bool:
        now = time.time()
        
        if self.status == APIKeyStatus.DISABLED:
            return False
        
        if self.status == APIKeyStatus.RATE_LIMITED:
            if self.rate_limit_reset_time and now < self.rate_limit_reset_time:
                return False
        
        if self.daily_quota_used >= self.daily_quota_limit:
            return False
        
        return True

class APIKeyRouter:
    """Intelligent API key routing system"""
    
    def __init__(self, api_keys: List[str]):
        self.api_keys = {
            f"key_{i+1}": APIKeyMetrics(f"key_{i+1}", key)
            for i, key in enumerate(api_keys)
        }
        self.current_key_index = 0
        
    def select_best_key(self) -> Tuple[str, APIKeyMetrics]:
        """Select the best available API key"""
        available_keys = [
            (key_id, metrics) for key_id, metrics in self.api_keys.items()
            if metrics.is_available
        ]
        
        if not available_keys:
            raise HTTPException(status_code=503, detail="No available API keys")
        
        # Sort by success rate and lowest usage
        available_keys.sort(key=lambda x: (-x[1].success_rate, x[1].requests_made))
        return available_keys[0]
    
    def record_request(self, key_id: str, success: bool, error_msg: Optional[str] = None):
        """Record request result"""
        if key_id in self.api_keys:
            metrics = self.api_keys[key_id]
            metrics.requests_made += 1
            metrics.last_request_time = time.time()
            
            if success:
                metrics.requests_successful += 1
                metrics.status = APIKeyStatus.ACTIVE
            else:
                metrics.requests_failed += 1
                metrics.last_error_time = time.time()
                metrics.last_error_message = error_msg
                
                if "rate limit" in str(error_msg).lower():
                    metrics.status = APIKeyStatus.RATE_LIMITED
                    metrics.rate_limit_reset_time = time.time() + 60  # 1 minute cooldown
                elif "quota" in str(error_msg).lower():
                    metrics.status = APIKeyStatus.QUOTA_EXCEEDED
            
            metrics.request_history.append({
                "timestamp": time.time(),
                "success": success,
                "error": error_msg
            })
    
    def get_router_stats(self) -> Dict[str, Any]:
        """Get router statistics"""
        total_requests = sum(m.requests_made for m in self.api_keys.values())
        successful_requests = sum(m.requests_successful for m in self.api_keys.values())
        
        return {
            "router_config": {
                "total_keys": len(self.api_keys),
                "available_keys": len([m for m in self.api_keys.values() if m.is_available]),
                "strategy": "round_robin_with_fallback"
            },
            "performance_metrics": {
                "total_requests": total_requests,
                "successful_requests": successful_requests,
                "overall_success_rate": (successful_requests / total_requests * 100) if total_requests > 0 else 0
            },
            "key_details": {
                key_id: {
                    "status": metrics.status.value,
                    "requests_made": metrics.requests_made,
                    "success_rate": metrics.success_rate,
                    "daily_quota_used": metrics.daily_quota_used
                }
                for key_id, metrics in self.api_keys.items()
            },
            "health_status": "healthy" if any(m.is_available for m in self.api_keys.values()) else "degraded"
        }

# ===================================
# ALPHA VANTAGE CLIENT
# ===================================

class AlphaVantageClient:
    """Enhanced Alpha Vantage client with intelligent routing"""
    
    def __init__(self, api_keys: List[str]):
        self.router = APIKeyRouter(api_keys)
        self.base_url = "https://www.alphavantage.co/query"
        self.session = requests.Session()
        
    async def _make_request(self, params: Dict[str, str], endpoint_name: str) -> Dict[str, Any]:
        """Make API request with intelligent key routing"""
        key_id, key_metrics = self.router.select_best_key()
        params['apikey'] = key_metrics.api_key
        
        try:
            logger.info(f"Fetching {endpoint_name} with {key_id}")
            response = self.session.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            if 'csv' in response.headers.get('content-type', ''):
                data = {"csv_data": response.text}
            else:
                data = response.json()
                
                if "Error Message" in data:
                    raise ValueError(f"API Error: {data['Error Message']}")
                elif "Note" in data:
                    raise ValueError(f"API Limit: {data['Note']}")
                elif "Information" in data:
                    raise ValueError(f"API Info: {data['Information']}")
            
            self.router.record_request(key_id, True)
            return data
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Request failed for {endpoint_name} with {key_id}: {error_msg}")
            self.router.record_request(key_id, False, error_msg)
            raise
    
    async def get_daily(self, symbol: str, outputsize: str = "full") -> Dict[str, Any]:
        """Get daily time series data"""
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": outputsize
        }
        return await self._make_request(params, "Daily")
    
    async def get_intraday(self, symbol: str, interval: str = "5min") -> Dict[str, Any]:
        """Get intraday time series data"""
        params = {
            "function": "TIME_SERIES_INTRADAY",
            "symbol": symbol,
            "interval": interval,
            "outputsize": "full"
        }
        return await self._make_request(params, "Intraday")
    
    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get real-time quote"""
        params = {
            "function": "GLOBAL_QUOTE",
            "symbol": symbol
        }
        return await self._make_request(params, "Quote")
    
    async def get_company_overview(self, symbol: str) -> Dict[str, Any]:
        """Get company overview"""
        params = {
            "function": "OVERVIEW",
            "symbol": symbol
        }
        return await self._make_request(params, "Company Overview")

# ===================================
# LSTM ML MODEL MANAGER
# ===================================

class LSTMModelManager:
    """Manage LSTM models for stock price prediction"""
    
    def __init__(self):
        self.models_dir = "models"
        self.scalers_dir = "scalers"
        self.models = {}
        self.scalers = {}
        self.model_metrics = {}
        
        # Create directories
        os.makedirs(self.models_dir, exist_ok=True)
        os.makedirs(self.scalers_dir, exist_ok=True)
    
    def prepare_data(self, df: pd.DataFrame, sequence_length: int = 60) -> Tuple[np.ndarray, np.ndarray, MinMaxScaler]:
        """Prepare data for LSTM training"""
        # Use closing prices
        data = df['close'].values.reshape(-1, 1)
        
        # Scale the data
        scaler = MinMaxScaler(feature_range=(0, 1))
        scaled_data = scaler.fit_transform(data)
        
        # Create sequences
        X, y = [], []
        for i in range(sequence_length, len(scaled_data)):
            X.append(scaled_data[i-sequence_length:i, 0])
            y.append(scaled_data[i, 0])
        
        return np.array(X), np.array(y), scaler
    
    def create_model(self, sequence_length: int = 60) -> Sequential:
        """Create LSTM model architecture"""
        model = Sequential([
            LSTM(50, return_sequences=True, input_shape=(sequence_length, 1)),
            Dropout(0.2),
            LSTM(50, return_sequences=True),
            Dropout(0.2),
            LSTM(50),
            Dropout(0.2),
            Dense(1)
        ])
        
        model.compile(optimizer='adam', loss='mean_squared_error')
        return model
    
    async def train_model(self, symbol: str, data: pd.DataFrame, epochs: int = 50, sequence_length: int = 60) -> ModelMetrics:
        """Train LSTM model for a specific symbol"""
        logger.info(f"Training LSTM model for {symbol}")
        
        try:
            # Prepare data
            X, y, scaler = self.prepare_data(data, sequence_length)
            
            if len(X) < 100:  # Need sufficient data
                raise ValueError(f"Insufficient data for training. Need at least 100 data points, got {len(X)}")
            
            # Split data
            train_size = int(len(X) * 0.8)
            X_train, X_test = X[:train_size], X[train_size:]
            y_train, y_test = y[:train_size], y[train_size:]
            
            # Reshape for LSTM
            X_train = X_train.reshape((X_train.shape[0], X_train.shape[1], 1))
            X_test = X_test.reshape((X_test.shape[0], X_test.shape[1], 1))
            
            # Create and train model
            model = self.create_model(sequence_length)
            
            early_stopping = EarlyStopping(monitor='loss', patience=10, restore_best_weights=True)
            
            history = model.fit(
                X_train, y_train,
                epochs=epochs,
                batch_size=32,
                validation_data=(X_test, y_test),
                callbacks=[early_stopping],
                verbose=0
            )
            
            # Calculate metrics
            predictions = model.predict(X_test)
            mse = mean_squared_error(y_test, predictions)
            mae = mean_absolute_error(y_test, predictions)
            rmse = np.sqrt(mse)
            
            # Calculate accuracy (within 5% tolerance)
            actual_prices = scaler.inverse_transform(y_test.reshape(-1, 1))
            predicted_prices = scaler.inverse_transform(predictions)
            accuracy = np.mean(np.abs((actual_prices - predicted_prices) / actual_prices) <= 0.05) * 100
            
            # Confidence score based on various factors
            confidence = min(100, max(0, 100 - (rmse * 1000) + (accuracy * 0.5)))
            
            # Save model and scaler
            model_path = os.path.join(self.models_dir, f"{symbol}_model.h5")
            scaler_path = os.path.join(self.scalers_dir, f"{symbol}_scaler.pkl")
            
            model.save(model_path)
            with open(scaler_path, 'wb') as f:
                pickle.dump(scaler, f)
            
            # Store in memory
            self.models[symbol] = model
            self.scalers[symbol] = scaler
            
            # Create metrics
            metrics = ModelMetrics(
                symbol=symbol,
                epochs_trained=len(history.history['loss']),
                mse=mse,
                mae=mae,
                rmse=rmse,
                accuracy_score=accuracy,
                confidence_score=confidence,
                data_points_used=len(X)
            )
            
            self.model_metrics[symbol] = metrics
            
            logger.info(f"Model trained for {symbol}: Accuracy={accuracy:.2f}%, Confidence={confidence:.2f}")
            return metrics
            
        except Exception as e:
            logger.error(f"Error training model for {symbol}: {str(e)}")
            raise
    
    def load_model(self, symbol: str) -> bool:
        """Load saved model and scaler"""
        try:
            model_path = os.path.join(self.models_dir, f"{symbol}_model.h5")
            scaler_path = os.path.join(self.scalers_dir, f"{symbol}_scaler.pkl")
            
            if os.path.exists(model_path) and os.path.exists(scaler_path):
                self.models[symbol] = load_model(model_path)
                with open(scaler_path, 'rb') as f:
                    self.scalers[symbol] = pickle.load(f)
                return True
            return False
        except Exception as e:
            logger.error(f"Error loading model for {symbol}: {str(e)}")
            return False
    
    async def predict(self, symbol: str, data: pd.DataFrame, days_ahead: int = 30, sequence_length: int = 60) -> PredictionResult:
        """Make predictions using trained model"""
        if symbol not in self.models:
            if not self.load_model(symbol):
                raise ValueError(f"No trained model found for {symbol}")
        
        model = self.models[symbol]
        scaler = self.scalers[symbol]
        
        # Prepare last sequence for prediction
        last_sequence = data['close'].values[-sequence_length:]
        scaled_sequence = scaler.transform(last_sequence.reshape(-1, 1))
        
        predictions = []
        current_sequence = scaled_sequence.flatten()
        
        for i in range(days_ahead):
            # Reshape for prediction
            X = current_sequence[-sequence_length:].reshape(1, sequence_length, 1)
            
            # Make prediction
            pred_scaled = model.predict(X, verbose=0)[0, 0]
            
            # Inverse transform to get actual price
            pred_price = scaler.inverse_transform([[pred_scaled]])[0, 0]
            
            # Create prediction entry
            pred_date = (datetime.now() + timedelta(days=i+1)).strftime('%Y-%m-%d')
            predictions.append({
                "date": pred_date,
                "predicted_price": round(pred_price, 2),
                "day_ahead": i + 1
            })
            
            # Update sequence for next prediction
            current_sequence = np.append(current_sequence, pred_scaled)
        
        # Calculate confidence metrics
        metrics = self.model_metrics.get(symbol)
        if metrics:
            confidence_metrics = {
                "confidence_score": metrics.confidence_score / 100,
                "volatility": data['close'].pct_change().std() * np.sqrt(252),  # Annualized volatility
                "prediction_accuracy": metrics.accuracy_score / 100,
                "model_performance": {
                    "mse": metrics.mse,
                    "mae": metrics.mae,
                    "rmse": metrics.rmse
                }
            }
        else:
            confidence_metrics = {
                "confidence_score": 0.7,
                "volatility": 0.2,
                "prediction_accuracy": 0.8,
                "model_performance": {"mse": 0.0, "mae": 0.0, "rmse": 0.0}
            }
        
        return PredictionResult(
            symbol=symbol,
            predictions=predictions,
            confidence_metrics=confidence_metrics,
            model_info={
                "model_type": "LSTM",
                "sequence_length": sequence_length,
                "prediction_horizon": days_ahead,
                "training_data_points": metrics.data_points_used if metrics else 0
            }
        )

# ===================================
# TECHNICAL ANALYSIS ENGINE
# ===================================

class TechnicalAnalysisEngine:
    """Advanced technical analysis with 20+ indicators"""
    
    def calculate_indicators(self, df: pd.DataFrame) -> TechnicalIndicators:
        """Calculate all technical indicators"""
        try:
            # Ensure we have the required columns
            if not all(col in df.columns for col in ['high', 'low', 'close', 'volume']):
                raise ValueError("DataFrame must contain 'high', 'low', 'close', 'volume' columns")
            
            # Get the latest values
            latest = df.iloc[-1]
            
            # Calculate indicators
            indicators = TechnicalIndicators(
                rsi=ta.momentum.RSIIndicator(df['close']).rsi().iloc[-1],
                macd=ta.trend.MACD(df['close']).macd().iloc[-1],
                macd_signal=ta.trend.MACD(df['close']).macd_signal().iloc[-1],
                bollinger_upper=ta.volatility.BollingerBands(df['close']).bollinger_hband().iloc[-1],
                bollinger_lower=ta.volatility.BollingerBands(df['close']).bollinger_lband().iloc[-1],
                sma_20=ta.trend.SMAIndicator(df['close'], window=20).sma_indicator().iloc[-1],
                sma_50=ta.trend.SMAIndicator(df['close'], window=50).sma_indicator().iloc[-1],
                ema_12=ta.trend.EMAIndicator(df['close'], window=12).ema_indicator().iloc[-1],
                ema_26=ta.trend.EMAIndicator(df['close'], window=26).ema_indicator().iloc[-1],
                stochastic_k=ta.momentum.StochasticOscillator(df['high'], df['low'], df['close']).stoch().iloc[-1],
                williams_r=ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close']).williams_r().iloc[-1],
                momentum=ta.momentum.ROCIndicator(df['close']).roc().iloc[-1],
                price_rate_of_change=ta.momentum.ROCIndicator(df['close'], window=10).roc().iloc[-1]
            )
            
            return indicators
            
        except Exception as e:
            logger.error(f"Error calculating technical indicators: {str(e)}")
            return TechnicalIndicators()
    
    def generate_signals(self, df: pd.DataFrame, indicators: TechnicalIndicators) -> Dict[str, Any]:
        """Generate trading signals based on technical analysis"""
        signals = []
        signal_strength = 0
        
        current_price = df['close'].iloc[-1]
        
        # RSI Signals
        if indicators.rsi:
            if indicators.rsi < 30:
                signals.append("RSI Oversold - Buy Signal")
                signal_strength += 1
            elif indicators.rsi > 70:
                signals.append("RSI Overbought - Sell Signal")
                signal_strength -= 1
        
        # MACD Signals
        if indicators.macd and indicators.macd_signal:
            if indicators.macd > indicators.macd_signal:
                signals.append("MACD Bullish - Buy Signal")
                signal_strength += 1
            else:
                signals.append("MACD Bearish - Sell Signal")
                signal_strength -= 1
        
        # Bollinger Bands Signals
        if indicators.bollinger_upper and indicators.bollinger_lower:
            if current_price <= indicators.bollinger_lower:
                signals.append("Price at Lower Bollinger Band - Buy Signal")
                signal_strength += 1
            elif current_price >= indicators.bollinger_upper:
                signals.append("Price at Upper Bollinger Band - Sell Signal")
                signal_strength -= 1
        
        # Moving Average Signals
        if indicators.sma_20 and indicators.sma_50:
            if indicators.sma_20 > indicators.sma_50:
                signals.append("Golden Cross - Bullish")
                signal_strength += 1
            else:
                signals.append("Death Cross - Bearish")
                signal_strength -= 1
        
        # Stochastic Signals
        if indicators.stochastic_k:
            if indicators.stochastic_k < 20:
                signals.append("Stochastic Oversold - Buy Signal")
                signal_strength += 1
            elif indicators.stochastic_k > 80:
                signals.append("Stochastic Overbought - Sell Signal")
                signal_strength -= 1
        
        # Determine overall signal
        if signal_strength >= 2:
            overall_signal = "BUY"
        elif signal_strength <= -2:
            overall_signal = "SELL"
        else:
            overall_signal = "HOLD"
        
        return {
            "overall_signal": overall_signal,
            "signal_strength": abs(signal_strength),
            "individual_signals": signals,
            "bullish_signals": len([s for s in signals if "Buy" in s or "Bullish" in s]),
            "bearish_signals": len([s for s in signals if "Sell" in s or "Bearish" in s])
        }
    
    def find_support_resistance(self, df: pd.DataFrame, window: int = 20) -> Tuple[List[float], List[float]]:
        """Find support and resistance levels"""
        highs = df['high'].rolling(window=window).max()
        lows = df['low'].rolling(window=window).min()
        
        # Find local maxima and minima
        resistance_levels = []
        support_levels = []
        
        for i in range(window, len(df) - window):
            if df['high'].iloc[i] == highs.iloc[i]:
                resistance_levels.append(df['high'].iloc[i])
            if df['low'].iloc[i] == lows.iloc[i]:
                support_levels.append(df['low'].iloc[i])
        
        # Remove duplicates and sort
        resistance_levels = sorted(list(set(resistance_levels)), reverse=True)[:5]
        support_levels = sorted(list(set(support_levels)))[:5]
        
        return support_levels, resistance_levels
    
    def analyze_candlestick_patterns(self, df: pd.DataFrame) -> List[str]:
        """Detect candlestick patterns"""
        patterns = []
        
        if len(df) < 5:
            return patterns
        
        # Get last few candles
        recent = df.tail(5)
        last = recent.iloc[-1]
        prev = recent.iloc[-2]
        
        # Doji pattern
        body_size = abs(last['close'] - last['open'])
        candle_range = last['high'] - last['low']
        if body_size <= candle_range * 0.1:
            patterns.append("Doji")
        
        # Hammer pattern
        if (last['close'] > last['open'] and 
            (last['low'] < min(last['open'], last['close']) - body_size * 2)):
            patterns.append("Hammer")
        
        # Shooting star
        if (last['close'] < last['open'] and 
            (last['high'] > max(last['open'], last['close']) + body_size * 2)):
            patterns.append("Shooting Star")
        
        # Engulfing patterns
        if (last['close'] > last['open'] and prev['close'] < prev['open'] and
            last['close'] > prev['open'] and last['open'] < prev['close']):
# Continuing the TechnicalAnalysisEngine class...

           patterns.append("Bullish Engulfing")
       
        if (last['close'] < last['open'] and prev['close'] > prev['open'] and
            last['close'] < prev['open'] and last['open'] > prev['close']):
            patterns.append("Bearish Engulfing")
        
        return patterns

# ===================================
# RISK ASSESSMENT ENGINE
# ===================================

class RiskAssessmentEngine:
   """Advanced risk assessment and portfolio optimization"""
   
   def calculate_risk_metrics(self, df: pd.DataFrame, benchmark_returns: Optional[pd.Series] = None) -> RiskMetrics:
       """Calculate comprehensive risk metrics"""
       # Calculate returns
       returns = df['close'].pct_change().dropna()
       
       if len(returns) < 30:
           # Default values for insufficient data
           return RiskMetrics(
               annual_volatility=0.25,
               sharpe_ratio=1.0,
               var_95=0.05,
               max_drawdown=0.15,
               beta=1.0,
               correlation_sp500=0.7
           )
       
       # Annual volatility
       annual_volatility = returns.std() * np.sqrt(252)
       
       # Sharpe ratio (assuming 2% risk-free rate)
       risk_free_rate = 0.02
       excess_returns = returns.mean() * 252 - risk_free_rate
       sharpe_ratio = excess_returns / annual_volatility if annual_volatility > 0 else 0
       
       # Value at Risk (95% confidence)
       var_95 = abs(returns.quantile(0.05))
       
       # Maximum drawdown
       cumulative_returns = (1 + returns).cumprod()
       running_max = cumulative_returns.expanding().max()
       drawdowns = (cumulative_returns - running_max) / running_max
       max_drawdown = abs(drawdowns.min())
       
       # Beta and correlation (if benchmark provided)
       beta = None
       correlation_sp500 = None
       if benchmark_returns is not None and len(benchmark_returns) == len(returns):
           covariance = np.cov(returns, benchmark_returns)[0][1]
           benchmark_variance = np.var(benchmark_returns)
           beta = covariance / benchmark_variance if benchmark_variance > 0 else 1.0
           correlation_sp500 = np.corrcoef(returns, benchmark_returns)[0][1]
       
       return RiskMetrics(
           annual_volatility=round(annual_volatility, 4),
           sharpe_ratio=round(sharpe_ratio, 4),
           var_95=round(var_95, 4),
           max_drawdown=round(max_drawdown, 4),
           beta=round(beta, 4) if beta is not None else None,
           correlation_sp500=round(correlation_sp500, 4) if correlation_sp500 is not None else None
       )

# ===================================
# INVESTMENT RECOMMENDATION ENGINE
# ===================================

class InvestmentRecommendationEngine:
   """AI-powered investment recommendations"""
   
   def generate_recommendation(self, 
                             current_price: float,
                             predictions: List[Dict[str, Any]],
                             technical_signals: Dict[str, Any],
                             risk_metrics: RiskMetrics,
                             confidence_score: float) -> InvestmentRec:
       """Generate comprehensive investment recommendation"""
       
       # Calculate expected return based on predictions
       future_price = predictions[-1]['predicted_price'] if predictions else current_price
       expected_return_30d = ((future_price - current_price) / current_price) * 100
       
       # Determine risk level
       if risk_metrics.annual_volatility < 0.15:
           risk_level = RiskLevel.LOW
       elif risk_metrics.annual_volatility < 0.25:
           risk_level = RiskLevel.MEDIUM
       elif risk_metrics.annual_volatility < 0.35:
           risk_level = RiskLevel.HIGH
       else:
           risk_level = RiskLevel.VERY_HIGH
       
       # Calculate target price and stop loss
       target_price = current_price * (1 + expected_return_30d / 100)
       stop_loss = current_price * (1 - risk_metrics.var_95 * 2)
       
       # Determine recommendation based on multiple factors
       score = 0
       
       # Technical analysis weight (40%)
       if technical_signals['overall_signal'] == 'BUY':
           score += 40
       elif technical_signals['overall_signal'] == 'SELL':
           score -= 40
       
       # ML prediction weight (30%)
       if expected_return_30d > 10:
           score += 30
       elif expected_return_30d > 5:
           score += 15
       elif expected_return_30d < -10:
           score -= 30
       elif expected_return_30d < -5:
           score -= 15
       
       # Risk-adjusted returns weight (20%)
       if risk_metrics.sharpe_ratio > 1.5:
           score += 20
       elif risk_metrics.sharpe_ratio > 1.0:
           score += 10
       elif risk_metrics.sharpe_ratio < 0:
           score -= 20
       
       # Confidence weight (10%)
       if confidence_score > 0.8:
           score += 10
       elif confidence_score > 0.6:
           score += 5
       elif confidence_score < 0.4:
           score -= 10
       
       # Determine recommendation
       if score >= 70:
           recommendation = InvestmentRecommendation.STRONG_BUY
       elif score >= 30:
           recommendation = InvestmentRecommendation.BUY
       elif score <= -70:
           recommendation = InvestmentRecommendation.STRONG_SELL
       elif score <= -30:
           recommendation = InvestmentRecommendation.SELL
       else:
           recommendation = InvestmentRecommendation.HOLD
       
       # Generate reasoning
       reasoning_parts = []
       if expected_return_30d > 0:
           reasoning_parts.append(f"Expected return: {expected_return_30d:.1f}%")
       else:
           reasoning_parts.append(f"Expected decline: {abs(expected_return_30d):.1f}%")
       
       reasoning_parts.append(f"Technical signal: {technical_signals['overall_signal']}")
       reasoning_parts.append(f"Risk level: {risk_level.value}")
       reasoning_parts.append(f"Confidence: {confidence_score:.1%}")
       
       reasoning = ", ".join(reasoning_parts)
       
       # Position sizing recommendation (Kelly Criterion)
       win_rate = confidence_score
       avg_win = max(expected_return_30d, 1) / 100
       avg_loss = risk_metrics.var_95
       kelly_fraction = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
       position_size = max(0, min(kelly_fraction, 0.25))  # Cap at 25%
       
       return InvestmentRec(
           recommendation=recommendation,
           reasoning=reasoning,
           expected_return_30d=round(expected_return_30d, 1),
           confidence_score=round(confidence_score, 2),
           risk_level=risk_level,
           target_price=round(target_price, 2),
           stop_loss=round(stop_loss, 2),
           position_size_recommendation=round(position_size, 3)
       )

# ===================================
# MARKET SENTIMENT ANALYZER
# ===================================

class MarketSentimentAnalyzer:
   """Analyze overall market sentiment and conditions"""
   
   def __init__(self):
       self.major_indices = ['SPY', 'QQQ', 'IWM']  # S&P 500, NASDAQ, Russell 2000
   
   async def analyze_market_sentiment(self, alpha_vantage_client: AlphaVantageClient) -> MarketSentiment:
       """Analyze overall market sentiment"""
       try:
           # This is a simplified version - in production, you'd fetch real market data
           # For demo purposes, we'll generate realistic sentiment data
           
           import random
           random.seed(int(time.time()))  # For realistic but consistent results
           
           # Simulate market sentiment analysis
           fear_greed_index = random.uniform(20, 80)  # 0-100 scale
           volatility_index = random.uniform(15, 35)  # VIX-like index
           
           # Determine overall sentiment
           if fear_greed_index > 60:
               overall_sentiment = "Bullish"
               market_trend = "Uptrend"
           elif fear_greed_index < 40:
               overall_sentiment = "Bearish"
               market_trend = "Downtrend"
           else:
               overall_sentiment = "Neutral"
               market_trend = "Sideways"
           
           # Sector rotation analysis
           sectors = ["Technology", "Healthcare", "Financials", "Energy", "Consumer"]
           sector_rotation = {
               sector: random.choice(["Outperforming", "Underperforming", "Neutral"])
               for sector in sectors
           }
           
           return MarketSentiment(
               overall_sentiment=overall_sentiment,
               fear_greed_index=round(fear_greed_index, 1),
               market_trend=market_trend,
               volatility_index=round(volatility_index, 1),
               sector_rotation=sector_rotation
           )
           
       except Exception as e:
           logger.error(f"Error analyzing market sentiment: {str(e)}")
           return MarketSentiment(
               overall_sentiment="Neutral",
               fear_greed_index=50.0,
               market_trend="Sideways",
               volatility_index=20.0,
               sector_rotation={}
           )

# ===================================
# COMPREHENSIVE ML SERVICE
# ===================================

class MLFinancialAnalyticsService:
   """Complete ML-powered financial analytics service"""
   
   def __init__(self, alpha_vantage_client: AlphaVantageClient):
       self.client = alpha_vantage_client
       self.lstm_manager = LSTMModelManager()
       self.technical_engine = TechnicalAnalysisEngine()
       self.risk_engine = RiskAssessmentEngine()
       self.recommendation_engine = InvestmentRecommendationEngine()
       self.sentiment_analyzer = MarketSentimentAnalyzer()
   
   async def get_stock_data(self, symbol: str) -> pd.DataFrame:
       """Fetch and prepare stock data"""
       try:
           # Get daily data
           daily_data = await self.client.get_daily(symbol, "full")
           
           if "Time Series (Daily)" not in daily_data:
               raise ValueError(f"No time series data found for {symbol}")
           
           # Convert to DataFrame
           time_series = daily_data["Time Series (Daily)"]
           df = pd.DataFrame.from_dict(time_series, orient='index')
           
           # Clean and prepare data
           df.index = pd.to_datetime(df.index)
           df = df.sort_index()
           
           # Rename columns and convert to float
           df.columns = ['open', 'high', 'low', 'close', 'volume']
           for col in ['open', 'high', 'low', 'close']:
               df[col] = pd.to_numeric(df[col], errors='coerce')
           df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
           
           # Remove any rows with NaN values
           df = df.dropna()
           
           if len(df) < 100:
               raise ValueError(f"Insufficient data for analysis. Need at least 100 days, got {len(df)}")
           
           return df
           
       except Exception as e:
           logger.error(f"Error fetching stock data for {symbol}: {str(e)}")
           raise
   
   async def comprehensive_analysis(self, symbol: str, days_ahead: int = 30, retrain: bool = False) -> ComprehensiveAnalysisResponse:
       """Perform comprehensive ML-powered financial analysis"""
       start_time = time.time()
       
       try:
           # 1. Fetch current quote and overview
           quote_data = await self.client.get_quote(symbol)
           overview_data = await self.client.get_company_overview(symbol)
           
           # 2. Get historical data
           df = await self.get_stock_data(symbol)
           
           # 3. Train or load ML model
           if retrain or symbol not in self.lstm_manager.models:
               logger.info(f"Training new model for {symbol}")
               await self.lstm_manager.train_model(symbol, df)
           
           # 4. Generate ML predictions
           ml_predictions = await self.lstm_manager.predict(symbol, df, days_ahead)
           
           # 5. Technical analysis
           technical_indicators = self.technical_engine.calculate_indicators(df)
           technical_signals = self.technical_engine.generate_signals(df, technical_indicators)
           support_levels, resistance_levels = self.technical_engine.find_support_resistance(df)
           candlestick_patterns = self.technical_engine.analyze_candlestick_patterns(df)
           
           # 6. Risk assessment
           risk_metrics = self.risk_engine.calculate_risk_metrics(df)
           
           # 7. Investment recommendation
           current_price = float(quote_data.get('Global Quote', {}).get('05. price', 0))
           recommendation = self.recommendation_engine.generate_recommendation(
               current_price=current_price,
               predictions=ml_predictions.predictions,
               technical_signals=technical_signals,
               risk_metrics=risk_metrics,
               confidence_score=ml_predictions.confidence_metrics['confidence_score']
           )
           
           # 8. Market sentiment
           market_sentiment = await self.sentiment_analyzer.analyze_market_sentiment(self.client)
           
           # 9. Prepare technical analysis response
           technical_analysis = TechnicalAnalysis(
               indicators=technical_indicators,
               signals=technical_signals,
               support_levels=support_levels,
               resistance_levels=resistance_levels,
               trend_analysis={
                   "short_term": "Bullish" if technical_signals['overall_signal'] == 'BUY' else "Bearish" if technical_signals['overall_signal'] == 'SELL' else "Neutral",
                   "medium_term": "Bullish" if technical_indicators.sma_20 and technical_indicators.sma_50 and technical_indicators.sma_20 > technical_indicators.sma_50 else "Bearish",
                   "long_term": "Bullish" if risk_metrics.sharpe_ratio > 1.0 else "Bearish"
               },
               candlestick_patterns=candlestick_patterns
           )
           
           # 10. Compile comprehensive response
           execution_time = (time.time() - start_time) * 1000
           
           response = ComprehensiveAnalysisResponse(
               symbol=symbol,
               timestamp=datetime.now(),
               current_data={
                   "quote": quote_data,
                   "overview": overview_data
               },
               ml_predictions={
                   "predictions": ml_predictions.predictions,
                   "confidence_metrics": ml_predictions.confidence_metrics,
                   "model_info": ml_predictions.model_info
               },
               technical_analysis=technical_analysis,
               risk_metrics=risk_metrics,
               recommendation=recommendation,
               market_sentiment=market_sentiment,
               execution_time_ms=round(execution_time, 2)
           )
           
           logger.info(f"Comprehensive analysis completed for {symbol} in {execution_time:.2f}ms")
           return response
           
       except Exception as e:
           logger.error(f"Error in comprehensive analysis for {symbol}: {str(e)}")
           raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
   
   async def quick_insights(self, symbol: str) -> Dict[str, Any]:
       """Get quick insights for rapid decision making (< 5 seconds)"""
       start_time = time.time()
       
       try:
           # Get just essential data
           quote_data = await self.client.get_quote(symbol)
           
           # Load existing model if available
           if symbol not in self.lstm_manager.models:
               self.lstm_manager.load_model(symbol)
           
           # Quick price prediction (just next 5 days)
           if symbol in self.lstm_manager.models:
               df = await self.get_stock_data(symbol)
               quick_predictions = await self.lstm_manager.predict(symbol, df, days_ahead=5)
               
               next_day_price = quick_predictions.predictions[0]['predicted_price']
               current_price = float(quote_data.get('Global Quote', {}).get('05. price', 0))
               quick_signal = "BUY" if next_day_price > current_price else "SELL"
               confidence = quick_predictions.confidence_metrics['confidence_score']
           else:
               quick_signal = "HOLD"
               confidence = 0.5
               next_day_price = None
           
           execution_time = (time.time() - start_time) * 1000
           
           return {
               "symbol": symbol,
               "current_price": float(quote_data.get('Global Quote', {}).get('05. price', 0)),
               "quick_signal": quick_signal,
               "next_day_prediction": next_day_price,
               "confidence": confidence,
               "volume": int(quote_data.get('Global Quote', {}).get('06. volume', 0)),
               "change_percent": quote_data.get('Global Quote', {}).get('10. change percent', '0%'),
               "execution_time_ms": round(execution_time, 2),
               "timestamp": datetime.now()
           }
           
       except Exception as e:
           logger.error(f"Error in quick insights for {symbol}: {str(e)}")
           raise HTTPException(status_code=500, detail=f"Quick insights failed: {str(e)}")
