"""
Data Fetcher
Fetches candle data from Yahoo Finance as backup when TradingView data is insufficient.
Provides unified data access for the MTF analyzer.
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from collections import deque
import time
import warnings
import ssl
import os

# Suppress yfinance FutureWarnings
warnings.filterwarnings('ignore', category=FutureWarning, module='yfinance')

# Try to fix SSL certificate issues on macOS
try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
except ImportError:
    pass


class DataFetcher:
    """
    Fetches multi-timeframe candle data from Yahoo Finance
    Used as backup when TradingView webhook data is insufficient
    """
    
    # Ticker mappings - Micro futures often have data issues, use main contracts as proxy
    # The price action is nearly identical, just different tick values
    TICKER_MAP = {
        # Micro futures -> Use main contract (same price action)
        'MNQ': 'NQ=F',      # Micro Nasdaq -> Nasdaq
        'MNQ=F': 'NQ=F',
        'MES': 'ES=F',      # Micro S&P -> S&P
        'MES=F': 'ES=F',
        'MGC': 'GC=F',      # Micro Gold -> Gold
        'MGC=F': 'GC=F',
        'MCL': 'CL=F',      # Micro Crude -> Crude
        'MCL=F': 'CL=F',
        'M2K': 'RTY=F',     # Micro Russell -> Russell
        'M2K=F': 'RTY=F',
        # Main contracts
        'NQ': 'NQ=F',
        'ES': 'ES=F',
        'GC': 'GC=F',
        'CL': 'CL=F',
        'RTY': 'RTY=F',
    }
    
    # Display names for logging
    DISPLAY_NAMES = {
        'NQ=F': 'NQ (Nasdaq)',
        'ES=F': 'ES (S&P 500)',
        'GC=F': 'GC (Gold)',
        'CL=F': 'CL (Crude Oil)',
        'RTY=F': 'RTY (Russell)',
    }
    
    def __init__(self):
        self.cache = {}  # ticker -> {timeframe -> candles}
        self.last_fetch = {}  # ticker -> timestamp
        self.cache_duration = 30  # seconds before refetching
    
    def normalize_ticker(self, ticker):
        """Normalize ticker to Yahoo Finance format"""
        # Remove any exchange prefix (CME:MNQ -> MNQ)
        base = ticker.split(':')[-1] if ':' in ticker else ticker
        
        # Remove =F suffix if present for processing
        base = base.replace('=F', '')
        
        # Extract root symbol from contract month format
        # Examples: MESZ2025 -> MES, MNQH2026 -> MNQ, GCGZ2025 -> GC
        # Contract months are single letters: F,G,H,J,K,M,N,Q,U,V,X,Z followed by year
        import re
        match = re.match(r'^([A-Z]{2,3})([FGHJKMNQUVXZ])(\d{4}|\d{2})?$', base.upper())
        if match:
            base_clean = match.group(1)  # Get the root symbol (MES, MNQ, etc.)
        else:
            # Fallback: just get alphabetic prefix
            base_clean = ''.join(c for c in base if c.isalpha())
        
        # Check mapping - first try exact, then cleaned
        if base in self.TICKER_MAP:
            return self.TICKER_MAP[base]
        elif base_clean in self.TICKER_MAP:
            return self.TICKER_MAP[base_clean]
        elif base_clean + '=F' in self.TICKER_MAP:
            return self.TICKER_MAP[base_clean + '=F']
        
        # Default: add =F if not present
        return f"{base_clean}=F" if base_clean else f"{base}=F"
    
    def fetch_candles(self, ticker, timeframe='1m', count=100):
        """
        Fetch candles from Yahoo Finance
        
        Args:
            ticker: Symbol (e.g., 'MNQ', 'MNQ=F', 'CME:MNQ')
            timeframe: '1m', '5m', '15m', '1h', '1d'
            count: Number of candles to fetch
            
        Returns:
            List of candle dicts: [{time, open, high, low, close, volume}, ...]
        """
        yf_ticker = self.normalize_ticker(ticker)
        
        # Determine period based on timeframe and count
        period_map = {
            '1m': '1d',    # 1m data only available for last 7 days, use 1d
            '5m': '5d',
            '15m': '5d',
            '1h': '1mo',
            '1d': '3mo'
        }
        
        period = period_map.get(timeframe, '5d')
        
        try:
            # Fetch data using Ticker object (more reliable)
            ticker_obj = yf.Ticker(yf_ticker)
            data = ticker_obj.history(period=period, interval=timeframe)
            
            if data.empty:
                print(f"⚠️  No data returned for {yf_ticker} ({timeframe})")
                return []
            
            # Convert to list of dicts
            candles = []
            for idx, row in data.tail(count).iterrows():
                candles.append({
                    'time': idx.strftime('%Y-%m-%d %H:%M:%S'),
                    'open': float(row['Open']) if pd.notna(row['Open']) else 0,
                    'high': float(row['High']) if pd.notna(row['High']) else 0,
                    'low': float(row['Low']) if pd.notna(row['Low']) else 0,
                    'close': float(row['Close']) if pd.notna(row['Close']) else 0,
                    'volume': int(row['Volume']) if pd.notna(row['Volume']) else 0
                })
            
            return candles
            
        except Exception as e:
            print(f"⚠️  Error fetching {yf_ticker} ({timeframe}): {e}")
            return []
    
    def fetch_all_timeframes(self, ticker):
        """
        Fetch 15m, 5m, and 1m data for a ticker
        
        Returns:
            dict: {'15m': [...], '5m': [...], '1m': [...]}
        """
        yf_ticker = self.normalize_ticker(ticker)
        cache_key = yf_ticker
        
        # Check cache
        if cache_key in self.cache:
            last = self.last_fetch.get(cache_key, 0)
            if time.time() - last < self.cache_duration:
                print(f"📦 Using cached data for {ticker} -> {yf_ticker}")
                return self.cache[cache_key]
        
        display_name = self.DISPLAY_NAMES.get(yf_ticker, yf_ticker)
        print(f"📡 Fetching Yahoo Finance: {ticker} -> {display_name}")
        
        result = {
            '15m': self.fetch_candles(ticker, '15m', 30),
            '5m': self.fetch_candles(ticker, '5m', 50),
            '1m': self.fetch_candles(ticker, '1m', 100)
        }
        
        # Cache results
        self.cache[cache_key] = result
        self.last_fetch[cache_key] = time.time()
        
        print(f"   ✅ Got {len(result['15m'])} x 15m, {len(result['5m'])} x 5m, {len(result['1m'])} x 1m candles")
        
        return result
    
    def get_current_price(self, ticker):
        """Get current price for a ticker"""
        yf_ticker = self.normalize_ticker(ticker)
        
        try:
            data = yf.download(yf_ticker, period='1d', interval='1m', progress=False, timeout=5)
            if not data.empty:
                return float(data['Close'].iloc[-1])
        except Exception as e:
            print(f"⚠️  Error getting price for {yf_ticker}: {e}")
        
        return None
    
    def merge_with_webhook_data(self, webhook_candles, yf_candles, max_candles=100):
        """
        Merge webhook candles with Yahoo Finance candles
        Webhook data takes priority (more recent), YF fills gaps
        
        Args:
            webhook_candles: Candles from TradingView webhooks
            yf_candles: Candles from Yahoo Finance
            max_candles: Maximum candles to return
            
        Returns:
            Merged list of candles
        """
        if not yf_candles:
            return list(webhook_candles)[-max_candles:]
        
        if not webhook_candles:
            return yf_candles[-max_candles:]
        
        # Convert webhook candles to list if deque
        wh_list = list(webhook_candles)
        
        # Get the earliest webhook timestamp
        if wh_list and wh_list[0].get('time'):
            earliest_webhook = wh_list[0]['time']
            
            # Get YF candles before the webhook data starts
            yf_before = [c for c in yf_candles if c.get('time', '') < earliest_webhook]
            
            # Combine: YF historical + webhook recent
            merged = yf_before + wh_list
        else:
            merged = yf_candles + wh_list
        
        return merged[-max_candles:]


# Singleton instance
data_fetcher = DataFetcher()


def fetch_backup_data(ticker):
    """Convenience function to fetch all timeframes"""
    return data_fetcher.fetch_all_timeframes(ticker)


def get_price(ticker):
    """Convenience function to get current price"""
    return data_fetcher.get_current_price(ticker)


def merge_candles(webhook_candles, ticker, timeframe):
    """Merge webhook data with YF backup"""
    yf_data = data_fetcher.fetch_candles(ticker, timeframe, 100)
    return data_fetcher.merge_with_webhook_data(webhook_candles, yf_data)


print("✅ Data Fetcher loaded (Yahoo Finance backup)")

