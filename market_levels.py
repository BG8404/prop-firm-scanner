"""
SignalCrawler v2.0 - Market Levels Tracker
Tracks key levels for better trade filtering:

1. ORB (Opening Range Breakout)
   - First 30 minutes of regular session (9:30-10:00 AM EST)
   - Determines daily bias: LONG ONLY / SHORT ONLY / NEUTRAL

2. PDH/PDL (Previous Day High/Low)
   - Major support/resistance levels
   - Filter out trades too close to these levels

Usage:
    from market_levels import MarketLevels
    levels = MarketLevels()
    
    # Update with candle data
    levels.update_from_candles(ticker, candles)
    
    # Get daily bias
    bias = levels.get_daily_bias(ticker)
    
    # Check if entry is safe
    is_safe, reason = levels.check_entry_safety(ticker, entry_price, direction)
"""

from datetime import datetime, time, timedelta
from collections import defaultdict
import pytz

# EST timezone for market hours
EST = pytz.timezone('America/New_York')

# Market hours (EST)
MARKET_OPEN = time(9, 30)
ORB_END = time(10, 0)  # Opening range ends at 10:00 AM
MARKET_CLOSE = time(16, 0)

# Default buffer from PDH/PDL (in points)
DEFAULT_PDH_PDL_BUFFER = 15


class MarketLevels:
    """
    Tracks market levels for all tickers:
    - ORB (Opening Range)
    - PDH/PDL (Previous Day High/Low)
    """
    
    def __init__(self, pdh_pdl_buffer=DEFAULT_PDH_PDL_BUFFER):
        self.pdh_pdl_buffer = pdh_pdl_buffer
        
        # Storage for each ticker
        # Format: {ticker: {date: {'orb_high': x, 'orb_low': x, 'pdh': x, 'pdl': x}}}
        self.levels = defaultdict(dict)
        
        # Track ORB completion status
        self.orb_complete = defaultdict(dict)  # {ticker: {date: bool}}
        
        # Cache daily bias
        self.daily_bias = defaultdict(dict)  # {ticker: {date: 'LONG'/'SHORT'/'NEUTRAL'}}
        
    def _get_current_date(self):
        """Get current date in EST"""
        return datetime.now(EST).date()
    
    def _get_current_time(self):
        """Get current time in EST"""
        return datetime.now(EST).time()
    
    def _normalize_ticker(self, ticker):
        """Normalize ticker symbol"""
        import re
        base = re.sub(r'[FGHJKMNQUVXZ]\d{4}$', '', ticker)
        base = base.replace('=F', '')
        return base.upper()
    
    def update_from_candles(self, ticker, candles):
        """
        Update levels from candle data.
        Expects candles to be sorted by timestamp (oldest first).
        """
        ticker = self._normalize_ticker(ticker)
        today = self._get_current_date()
        current_time = self._get_current_time()
        
        if not candles:
            return
        
        # Initialize today's levels if not exist
        if today not in self.levels[ticker]:
            self.levels[ticker][today] = {
                'orb_high': None,
                'orb_low': None,
                'orb_candles': [],
                'pdh': None,
                'pdl': None,
                'session_high': None,
                'session_low': None
            }
        
        levels = self.levels[ticker][today]
        
        # Process candles
        for candle in candles:
            candle_time = candle.get('timestamp')
            if isinstance(candle_time, str):
                try:
                    candle_time = datetime.fromisoformat(candle_time.replace('Z', '+00:00'))
                    if candle_time.tzinfo is None:
                        candle_time = EST.localize(candle_time)
                    else:
                        candle_time = candle_time.astimezone(EST)
                except:
                    continue
            
            candle_date = candle_time.date() if candle_time else today
            candle_hour_min = candle_time.time() if candle_time else current_time
            
            high = candle.get('high', 0)
            low = candle.get('low', 0)
            
            # Check if this is an ORB candle (9:30-10:00 AM)
            if candle_date == today and MARKET_OPEN <= candle_hour_min < ORB_END:
                levels['orb_candles'].append(candle)
                
                if levels['orb_high'] is None or high > levels['orb_high']:
                    levels['orb_high'] = high
                if levels['orb_low'] is None or low < levels['orb_low']:
                    levels['orb_low'] = low
            
            # Track session high/low for today
            if candle_date == today and candle_hour_min >= MARKET_OPEN:
                if levels['session_high'] is None or high > levels['session_high']:
                    levels['session_high'] = high
                if levels['session_low'] is None or low < levels['session_low']:
                    levels['session_low'] = low
            
            # Track previous day for PDH/PDL
            yesterday = today - timedelta(days=1)
            if candle_date == yesterday:
                if yesterday not in self.levels[ticker]:
                    self.levels[ticker][yesterday] = {
                        'session_high': high,
                        'session_low': low
                    }
                else:
                    if high > self.levels[ticker][yesterday].get('session_high', 0):
                        self.levels[ticker][yesterday]['session_high'] = high
                    if self.levels[ticker][yesterday].get('session_low') is None or low < self.levels[ticker][yesterday]['session_low']:
                        self.levels[ticker][yesterday]['session_low'] = low
        
        # Set PDH/PDL from yesterday's session
        yesterday = today - timedelta(days=1)
        if yesterday in self.levels[ticker]:
            levels['pdh'] = self.levels[ticker][yesterday].get('session_high')
            levels['pdl'] = self.levels[ticker][yesterday].get('session_low')
        
        # Check if ORB is complete
        if current_time >= ORB_END:
            self.orb_complete[ticker][today] = True
            self._calculate_daily_bias(ticker, today)
    
    def set_pdh_pdl(self, ticker, pdh, pdl):
        """Manually set PDH/PDL values"""
        ticker = self._normalize_ticker(ticker)
        today = self._get_current_date()
        
        if today not in self.levels[ticker]:
            self.levels[ticker][today] = {}
        
        self.levels[ticker][today]['pdh'] = pdh
        self.levels[ticker][today]['pdl'] = pdl
        print(f"📊 Set {ticker} PDH: {pdh}, PDL: {pdl}")
    
    def _calculate_daily_bias(self, ticker, date):
        """
        Calculate daily bias based on ORB breakout:
        - Price above ORB high = LONG ONLY
        - Price below ORB low = SHORT ONLY
        - Inside ORB range = NEUTRAL (wait for breakout)
        """
        levels = self.levels[ticker].get(date, {})
        orb_high = levels.get('orb_high')
        orb_low = levels.get('orb_low')
        current_price = levels.get('session_high')  # Use latest price if available
        
        if not orb_high or not orb_low:
            self.daily_bias[ticker][date] = 'NEUTRAL'
            return
        
        # If we have session data, use the latest close
        session_high = levels.get('session_high', orb_high)
        session_low = levels.get('session_low', orb_low)
        
        # Determine bias based on where price is relative to ORB
        orb_range = orb_high - orb_low
        buffer = orb_range * 0.1  # 10% buffer for confirmation
        
        if session_high > orb_high + buffer:
            self.daily_bias[ticker][date] = 'LONG'
        elif session_low < orb_low - buffer:
            self.daily_bias[ticker][date] = 'SHORT'
        else:
            self.daily_bias[ticker][date] = 'NEUTRAL'
    
    def get_daily_bias(self, ticker, current_price=None):
        """
        Get the daily bias for a ticker.
        Returns: 'LONG', 'SHORT', or 'NEUTRAL'
        """
        ticker = self._normalize_ticker(ticker)
        today = self._get_current_date()
        current_time = self._get_current_time()
        
        # If before ORB completion, return NEUTRAL (wait)
        if current_time < ORB_END:
            return {
                'bias': 'WAITING',
                'reason': f'ORB not complete until {ORB_END.strftime("%H:%M")} EST',
                'orb_high': None,
                'orb_low': None,
                'can_trade': False
            }
        
        levels = self.levels[ticker].get(today, {})
        orb_high = levels.get('orb_high')
        orb_low = levels.get('orb_low')
        
        if not orb_high or not orb_low:
            return {
                'bias': 'UNKNOWN',
                'reason': 'No ORB data available',
                'orb_high': None,
                'orb_low': None,
                'can_trade': True  # Allow trading but no bias filter
            }
        
        # If current price provided, calculate real-time bias
        if current_price:
            orb_range = orb_high - orb_low
            buffer = orb_range * 0.05  # 5% buffer
            
            if current_price > orb_high + buffer:
                bias = 'LONG'
                reason = f'Price {current_price:.2f} above ORB high {orb_high:.2f}'
            elif current_price < orb_low - buffer:
                bias = 'SHORT'
                reason = f'Price {current_price:.2f} below ORB low {orb_low:.2f}'
            else:
                bias = 'NEUTRAL'
                reason = f'Price {current_price:.2f} inside ORB range ({orb_low:.2f} - {orb_high:.2f})'
        else:
            bias = self.daily_bias[ticker].get(today, 'NEUTRAL')
            reason = f'ORB range: {orb_low:.2f} - {orb_high:.2f}'
        
        return {
            'bias': bias,
            'reason': reason,
            'orb_high': orb_high,
            'orb_low': orb_low,
            'orb_range': orb_high - orb_low if orb_high and orb_low else 0,
            'can_trade': True
        }
    
    def get_pdh_pdl(self, ticker):
        """Get PDH/PDL for a ticker"""
        ticker = self._normalize_ticker(ticker)
        today = self._get_current_date()
        levels = self.levels[ticker].get(today, {})
        
        return {
            'pdh': levels.get('pdh'),
            'pdl': levels.get('pdl')
        }
    
    def check_entry_safety(self, ticker, entry_price, direction):
        """
        Check if an entry is safe from PDH/PDL levels.
        
        Returns: (is_safe, reason)
        """
        ticker = self._normalize_ticker(ticker)
        today = self._get_current_date()
        levels = self.levels[ticker].get(today, {})
        
        pdh = levels.get('pdh')
        pdl = levels.get('pdl')
        
        if not pdh or not pdl:
            return True, "No PDH/PDL data - entry allowed"
        
        # Calculate distance from levels
        dist_to_pdh = abs(entry_price - pdh)
        dist_to_pdl = abs(entry_price - pdl)
        
        # Check if too close to levels
        if direction.upper() == 'LONG':
            # For longs, PDH is resistance - don't enter too close to it
            if dist_to_pdh < self.pdh_pdl_buffer:
                return False, f"❌ Entry {entry_price:.2f} too close to PDH {pdh:.2f} ({dist_to_pdh:.1f} pts < {self.pdh_pdl_buffer} buffer)"
            # PDL should be support - entry above PDL is good
            return True, f"✅ Safe from PDH ({dist_to_pdh:.1f} pts away)"
        else:  # SHORT
            # For shorts, PDL is support - don't short too close to it
            if dist_to_pdl < self.pdh_pdl_buffer:
                return False, f"❌ Entry {entry_price:.2f} too close to PDL {pdl:.2f} ({dist_to_pdl:.1f} pts < {self.pdh_pdl_buffer} buffer)"
            return True, f"✅ Safe from PDL ({dist_to_pdl:.1f} pts away)"
    
    def check_bias_alignment(self, ticker, signal_direction, current_price=None):
        """
        Check if signal direction aligns with ORB daily bias.
        
        Returns: (is_aligned, reason)
        """
        bias_info = self.get_daily_bias(ticker, current_price)
        bias = bias_info['bias']
        
        if bias == 'WAITING':
            return False, bias_info['reason']
        
        if bias == 'UNKNOWN':
            return True, "No ORB data - allowing trade"
        
        if bias == 'NEUTRAL':
            return True, f"ORB neutral - {signal_direction} allowed with caution"
        
        signal_dir = signal_direction.upper()
        
        if (bias == 'LONG' and signal_dir == 'LONG') or (bias == 'SHORT' and signal_dir == 'SHORT'):
            return True, f"✅ {signal_dir} aligns with ORB bias ({bias})"
        else:
            return False, f"❌ {signal_dir} against ORB bias ({bias})"
    
    def get_all_levels(self, ticker, current_price=None):
        """
        Get all levels for a ticker in a formatted dict.
        """
        ticker = self._normalize_ticker(ticker)
        today = self._get_current_date()
        levels = self.levels[ticker].get(today, {})
        bias_info = self.get_daily_bias(ticker, current_price)
        
        return {
            'ticker': ticker,
            'date': today.isoformat(),
            'orb': {
                'high': levels.get('orb_high'),
                'low': levels.get('orb_low'),
                'range': (levels.get('orb_high', 0) or 0) - (levels.get('orb_low', 0) or 0),
                'complete': self.orb_complete[ticker].get(today, False)
            },
            'pdh_pdl': {
                'pdh': levels.get('pdh'),
                'pdl': levels.get('pdl'),
                'range': (levels.get('pdh', 0) or 0) - (levels.get('pdl', 0) or 0)
            },
            'session': {
                'high': levels.get('session_high'),
                'low': levels.get('session_low')
            },
            'bias': bias_info
        }
    
    def format_levels_for_alert(self, ticker, current_price=None):
        """
        Format levels for Discord/display alert.
        """
        all_levels = self.get_all_levels(ticker, current_price)
        
        lines = []
        lines.append(f"📊 **Key Levels - {ticker}**")
        
        # ORB
        orb = all_levels['orb']
        if orb['high'] and orb['low']:
            lines.append(f"🎯 ORB: {orb['low']:.2f} - {orb['high']:.2f} (range: {orb['range']:.1f})")
        else:
            lines.append("🎯 ORB: Not available")
        
        # PDH/PDL
        pdh_pdl = all_levels['pdh_pdl']
        if pdh_pdl['pdh'] and pdh_pdl['pdl']:
            lines.append(f"📈 PDH: {pdh_pdl['pdh']:.2f}")
            lines.append(f"📉 PDL: {pdh_pdl['pdl']:.2f}")
        else:
            lines.append("📈 PDH/PDL: Not available")
        
        # Bias
        bias = all_levels['bias']
        bias_emoji = '🟢' if bias['bias'] == 'LONG' else '🔴' if bias['bias'] == 'SHORT' else '⚪'
        lines.append(f"{bias_emoji} Daily Bias: **{bias['bias']}**")
        lines.append(f"   {bias['reason']}")
        
        return '\n'.join(lines)


# Global instance
market_levels = MarketLevels()


def get_market_levels():
    """Get the global MarketLevels instance"""
    return market_levels


def load_levels_from_database():
    """
    Load PDH/PDL and ORB levels from historical candle data in database.
    Called on app startup to populate levels immediately.
    """
    try:
        import sqlite3
        import os
        
        # Get database path
        if os.path.exists('/app/data'):
            db_path = '/app/data/trade_journal.db'
        else:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_journal.db')
        
        if not os.path.exists(db_path):
            print("⚠️ Database not found - levels will build from live data")
            return
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        today = datetime.now(EST).date()
        yesterday = today - timedelta(days=1)
        current_time = datetime.now(EST).time()
        
        # Also check if it's a weekend, go back to Friday
        while yesterday.weekday() >= 5:  # Saturday=5, Sunday=6
            yesterday = yesterday - timedelta(days=1)
        
        tickers = ['MNQ', 'MES', 'MGC']
        
        print(f"📊 Loading historical levels from database...")
        print(f"   Today: {today}, Looking for previous day: {yesterday}")
        
        for ticker in tickers:
            # ============================================
            # LOAD PDH/PDL (Previous Day High/Low)
            # ============================================
            # Query for yesterday's session high/low (RTH: 9:30 AM - 4:00 PM)
            # Use LIKE to match contract months (MNQ%, MNQZ2025, etc.)
            cursor.execute('''
                SELECT 
                    MAX(high) as pdh, 
                    MIN(low) as pdl,
                    COUNT(*) as candle_count
                FROM candle_history
                WHERE ticker LIKE ? 
                AND date(timestamp) = ?
            ''', (ticker + '%', yesterday.isoformat()))
            
            row = cursor.fetchone()
            
            if row and row['pdh'] and row['pdl'] and row['candle_count'] > 0:
                pdh = row['pdh']
                pdl = row['pdl']
                
                # Set PDH/PDL in the market levels tracker
                if today not in market_levels.levels[ticker]:
                    market_levels.levels[ticker][today] = {
                        'orb_high': None, 'orb_low': None, 'orb_candles': [],
                        'pdh': None, 'pdl': None,
                        'session_high': None, 'session_low': None
                    }
                
                market_levels.levels[ticker][today]['pdh'] = pdh
                market_levels.levels[ticker][today]['pdl'] = pdl
                
                print(f"   ✅ {ticker} PDH: {pdh:.2f}, PDL: {pdl:.2f} (from {row['candle_count']} candles)")
            else:
                print(f"   ⚠️ {ticker} No previous day data found")
            
            # ============================================
            # LOAD ORB (Opening Range 9:30-10:00 AM)
            # ============================================
            # Only load if after 10:00 AM (ORB complete)
            if current_time >= ORB_END:
                cursor.execute('''
                    SELECT 
                        MAX(high) as orb_high, 
                        MIN(low) as orb_low,
                        COUNT(*) as candle_count
                    FROM candle_history
                    WHERE ticker LIKE ?
                    AND date(timestamp) = ?
                    AND time(timestamp) >= '09:30:00'
                    AND time(timestamp) < '10:00:00'
                ''', (ticker + '%', today.isoformat()))
                
                orb_row = cursor.fetchone()
                
                if orb_row and orb_row['orb_high'] and orb_row['orb_low'] and orb_row['candle_count'] > 0:
                    orb_high = orb_row['orb_high']
                    orb_low = orb_row['orb_low']
                    
                    if today not in market_levels.levels[ticker]:
                        market_levels.levels[ticker][today] = {
                            'orb_high': None, 'orb_low': None, 'orb_candles': [],
                            'pdh': None, 'pdl': None,
                            'session_high': None, 'session_low': None
                        }
                    
                    market_levels.levels[ticker][today]['orb_high'] = orb_high
                    market_levels.levels[ticker][today]['orb_low'] = orb_low
                    market_levels.orb_complete[ticker][today] = True
                    
                    # Calculate bias
                    market_levels._calculate_daily_bias(ticker, today)
                    bias = market_levels.daily_bias[ticker].get(today, 'NEUTRAL')
                    
                    print(f"   ✅ {ticker} ORB: {orb_low:.2f} - {orb_high:.2f}, Bias: {bias}")
                else:
                    print(f"   ⚠️ {ticker} No ORB data for today yet")
            else:
                print(f"   ⏳ {ticker} ORB not complete yet (before 10:00 AM)")
            
            # ============================================
            # LOAD TODAY'S SESSION HIGH/LOW
            # ============================================
            cursor.execute('''
                SELECT 
                    MAX(high) as session_high, 
                    MIN(low) as session_low
                FROM candle_history
                WHERE ticker LIKE ?
                AND date(timestamp) = ?
                AND time(timestamp) >= '09:30:00'
            ''', (ticker + '%', today.isoformat()))
            
            session_row = cursor.fetchone()
            
            if session_row and session_row['session_high']:
                if today in market_levels.levels[ticker]:
                    market_levels.levels[ticker][today]['session_high'] = session_row['session_high']
                    market_levels.levels[ticker][today]['session_low'] = session_row['session_low']
        
        conn.close()
        
        print("✅ Historical levels loaded from database")
        
        # Print summary
        for ticker in tickers:
            levels = market_levels.levels[ticker].get(today, {})
            pdh = levels.get('pdh')
            pdl = levels.get('pdl')
            orb_high = levels.get('orb_high')
            orb_low = levels.get('orb_low')
            
            print(f"   📍 {ticker}: PDH={pdh or 'N/A'}, PDL={pdl or 'N/A'}, ORB={orb_low or 'N/A'}-{orb_high or 'N/A'}")
        
    except Exception as e:
        print(f"⚠️ Error loading levels from database: {e}")
        import traceback
        traceback.print_exc()


# Auto-load on import
print("✅ Market Levels tracker loaded (ORB + PDH/PDL)")
load_levels_from_database()

