"""
Market Regime Detector
Detects market conditions (trending, ranging, volatile) and suggests
regime-specific strategy adjustments.
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from collections import deque
import statistics

# Database path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_journal.db')
REGIME_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'market_regime.json')


def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# Regime definitions
class MarketRegime:
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    CHOPPY = "choppy"
    UNKNOWN = "unknown"


def load_regime_state():
    """Load current regime state"""
    default = {
        'current_regime': MarketRegime.UNKNOWN,
        'regime_history': [],
        'performance_by_regime': {},
        'last_updated': None
    }
    try:
        if os.path.exists(REGIME_STATE_FILE):
            with open(REGIME_STATE_FILE, 'r') as f:
                state = json.load(f)
                for key in default:
                    if key not in state:
                        state[key] = default[key]
                return state
    except:
        pass
    return default


def save_regime_state(state):
    """Save regime state"""
    try:
        state['last_updated'] = datetime.now().isoformat()
        with open(REGIME_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠️  Error saving regime state: {e}")


def calculate_atr(candles, period=14):
    """
    Calculate Average True Range from candle data
    
    candles: list of dicts with high, low, close keys
    """
    if len(candles) < period + 1:
        return None
    
    true_ranges = []
    for i in range(1, len(candles)):
        high = candles[i].get('high', 0)
        low = candles[i].get('low', 0)
        prev_close = candles[i-1].get('close', 0)
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)
    
    if len(true_ranges) < period:
        return None
    
    return statistics.mean(true_ranges[-period:])


def calculate_trend_strength(candles, period=20):
    """
    Calculate trend strength using linear regression slope
    Returns value between -1 (strong downtrend) and 1 (strong uptrend)
    """
    if len(candles) < period:
        return 0
    
    closes = [c.get('close', 0) for c in candles[-period:]]
    
    # Simple linear regression
    n = len(closes)
    x_sum = sum(range(n))
    y_sum = sum(closes)
    xy_sum = sum(i * closes[i] for i in range(n))
    x2_sum = sum(i * i for i in range(n))
    
    denom = n * x2_sum - x_sum * x_sum
    if denom == 0:
        return 0
    
    slope = (n * xy_sum - x_sum * y_sum) / denom
    
    # Normalize by price range
    price_range = max(closes) - min(closes)
    if price_range == 0:
        return 0
    
    normalized = slope * n / price_range
    return max(-1, min(1, normalized))


def calculate_choppiness(candles, period=14):
    """
    Calculate Choppiness Index (0-100)
    High values (>61.8) indicate ranging/choppy
    Low values (<38.2) indicate trending
    """
    if len(candles) < period + 1:
        return 50
    
    recent = candles[-period:]
    
    # Sum of true ranges
    tr_sum = 0
    for i in range(1, len(recent)):
        high = recent[i].get('high', 0)
        low = recent[i].get('low', 0)
        prev_close = recent[i-1].get('close', 0)
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        tr_sum += tr
    
    # Highest high and lowest low
    highest = max(c.get('high', 0) for c in recent)
    lowest = min(c.get('low', 0) for c in recent)
    
    hl_range = highest - lowest
    if hl_range == 0:
        return 50
    
    import math
    chop = 100 * math.log10(tr_sum / hl_range) / math.log10(period)
    
    return max(0, min(100, chop))


def detect_regime_from_candles(candles):
    """
    Detect market regime from candle data
    
    Returns regime string and confidence
    """
    if not candles or len(candles) < 20:
        return MarketRegime.UNKNOWN, 0
    
    # Calculate indicators
    atr = calculate_atr(candles)
    trend = calculate_trend_strength(candles)
    chop = calculate_choppiness(candles)
    
    # Calculate volatility percentile
    if atr:
        # Compare to recent ATR average
        recent_atrs = []
        for i in range(14, len(candles)):
            recent_atrs.append(calculate_atr(candles[:i+1]))
        recent_atrs = [a for a in recent_atrs if a]
        
        if recent_atrs:
            atr_mean = statistics.mean(recent_atrs)
            atr_std = statistics.stdev(recent_atrs) if len(recent_atrs) > 1 else atr_mean * 0.2
            volatility_z = (atr - atr_mean) / atr_std if atr_std > 0 else 0
        else:
            volatility_z = 0
    else:
        volatility_z = 0
    
    # Determine regime
    confidence = 0.5
    
    # High volatility check
    if volatility_z > 1.5:
        confidence = min(0.9, 0.5 + volatility_z * 0.2)
        return MarketRegime.HIGH_VOLATILITY, confidence
    
    # Low volatility check
    if volatility_z < -1.5:
        confidence = min(0.9, 0.5 + abs(volatility_z) * 0.2)
        return MarketRegime.LOW_VOLATILITY, confidence
    
    # Choppy market check
    if chop > 61.8:
        confidence = min(0.85, 0.4 + (chop - 50) / 50)
        return MarketRegime.CHOPPY, confidence
    
    # Trending check
    if abs(trend) > 0.3 and chop < 50:
        confidence = min(0.9, 0.4 + abs(trend) * 0.5)
        if trend > 0:
            return MarketRegime.TRENDING_UP, confidence
        else:
            return MarketRegime.TRENDING_DOWN, confidence
    
    # Ranging
    if chop > 45 and abs(trend) < 0.2:
        confidence = 0.6
        return MarketRegime.RANGING, confidence
    
    return MarketRegime.UNKNOWN, 0.3


def update_regime(candles, ticker="MARKET"):
    """
    Update market regime based on new candle data
    """
    regime, confidence = detect_regime_from_candles(candles)
    
    state = load_regime_state()
    
    # Log regime change if different
    current = state.get('current_regime')
    if regime != current:
        state['regime_history'].append({
            'from': current,
            'to': regime,
            'confidence': confidence,
            'ticker': ticker,
            'timestamp': datetime.now().isoformat()
        })
        
        # Keep last 100 changes
        state['regime_history'] = state['regime_history'][-100:]
    
    state['current_regime'] = regime
    state['current_confidence'] = confidence
    
    save_regime_state(state)
    
    return regime, confidence


def get_performance_by_regime():
    """
    Analyze trading performance by market regime
    """
    state = load_regime_state()
    
    # This requires regime tagging on trades
    # For now, return stored performance data
    return state.get('performance_by_regime', {})


def analyze_regime_performance():
    """
    Analyze how trades performed in different regimes
    
    This requires trades to be tagged with regime at time of signal
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check if regime column exists
    cursor.execute("PRAGMA table_info(signals)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'market_regime' not in columns:
        # Add column if doesn't exist
        try:
            cursor.execute('ALTER TABLE signals ADD COLUMN market_regime TEXT')
            conn.commit()
        except:
            pass
    
    cursor.execute('''
        SELECT 
            market_regime,
            COUNT(*) as total,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(COALESCE(pnl_ticks, 0)) as total_pnl
        FROM signals
        WHERE outcome IN ('win', 'loss') 
        AND market_regime IS NOT NULL
        GROUP BY market_regime
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    results = {}
    for row in rows:
        regime = row['market_regime']
        total = row['total']
        wins = row['wins']
        
        results[regime] = {
            'total_trades': total,
            'wins': wins,
            'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
            'total_pnl': round(row['total_pnl'] or 0, 2)
        }
    
    # Update state
    state = load_regime_state()
    state['performance_by_regime'] = results
    save_regime_state(state)
    
    return results


def get_regime_suggestions():
    """
    Generate suggestions based on regime analysis
    """
    suggestions = []
    
    perf = analyze_regime_performance()
    
    if not perf:
        return suggestions
    
    # Find underperforming regimes
    overall_wins = sum(p['wins'] for p in perf.values())
    overall_total = sum(p['total_trades'] for p in perf.values())
    overall_rate = overall_wins / overall_total * 100 if overall_total > 0 else 50
    
    for regime, stats in perf.items():
        if stats['total_trades'] < 10:
            continue
        
        diff = stats['win_rate'] - overall_rate
        
        if diff <= -15:
            suggestions.append({
                'type': 'regime',
                'category': 'avoid_regime',
                'title': f'Reduce Trading in {regime.replace("_", " ").title()} Conditions',
                'explanation': f'Your trades in {regime.replace("_", " ")} conditions have a {stats["win_rate"]:.0f}% win rate vs {overall_rate:.0f}% overall. Consider being more selective or avoiding trades in this regime.',
                'action': f'Increase confidence threshold to 90%+ when market is in {regime} regime',
                'projected_impact': f'Could improve overall win rate by filtering weak regime',
                'confidence': min(stats['total_trades'] / 25, 1.0),
                'sample_size': stats['total_trades'],
                'data': {
                    'regime': regime,
                    'regime_win_rate': stats['win_rate'],
                    'overall_win_rate': overall_rate
                }
            })
        
        elif diff >= 15:
            suggestions.append({
                'type': 'regime',
                'category': 'prefer_regime',
                'title': f'Capitalize on {regime.replace("_", " ").title()} Conditions',
                'explanation': f'Your trades in {regime.replace("_", " ")} conditions have a {stats["win_rate"]:.0f}% win rate vs {overall_rate:.0f}% overall. This regime suits your strategy well.',
                'action': f'Consider lowering confidence threshold to 75% when market is in {regime} regime',
                'projected_impact': f'Could increase profitable trade frequency',
                'confidence': min(stats['total_trades'] / 25, 1.0),
                'sample_size': stats['total_trades'],
                'data': {
                    'regime': regime,
                    'regime_win_rate': stats['win_rate'],
                    'overall_win_rate': overall_rate
                }
            })
    
    return suggestions


def get_current_regime():
    """Get current market regime and confidence"""
    state = load_regime_state()
    return {
        'regime': state.get('current_regime', MarketRegime.UNKNOWN),
        'confidence': state.get('current_confidence', 0),
        'last_updated': state.get('last_updated'),
        'description': get_regime_description(state.get('current_regime'))
    }


def get_regime_description(regime):
    """Get human-readable description of regime"""
    descriptions = {
        MarketRegime.TRENDING_UP: "Strong upward trend - momentum favors longs",
        MarketRegime.TRENDING_DOWN: "Strong downward trend - momentum favors shorts",
        MarketRegime.RANGING: "Range-bound market - watch for breakouts",
        MarketRegime.HIGH_VOLATILITY: "High volatility - use wider stops, smaller size",
        MarketRegime.LOW_VOLATILITY: "Low volatility - watch for breakout setups",
        MarketRegime.CHOPPY: "Choppy/indecisive - be very selective",
        MarketRegime.UNKNOWN: "Insufficient data to determine regime"
    }
    return descriptions.get(regime, "Unknown regime")


def get_regime_trading_guidance(regime):
    """Get trading guidance for current regime"""
    guidance = {
        MarketRegime.TRENDING_UP: {
            'bias': 'long',
            'confidence_adjust': -5,  # Can be less strict
            'size_adjust': 0,
            'notes': ['Look for pullback entries', 'Avoid counter-trend shorts']
        },
        MarketRegime.TRENDING_DOWN: {
            'bias': 'short',
            'confidence_adjust': -5,
            'size_adjust': 0,
            'notes': ['Look for pullback entries', 'Avoid counter-trend longs']
        },
        MarketRegime.RANGING: {
            'bias': 'neutral',
            'confidence_adjust': 5,  # Be more strict
            'size_adjust': -10,  # Smaller size
            'notes': ['Trade range extremes', 'Quick targets']
        },
        MarketRegime.HIGH_VOLATILITY: {
            'bias': 'neutral',
            'confidence_adjust': 10,  # Much more strict
            'size_adjust': -25,  # Much smaller size
            'notes': ['Wider stops needed', 'Reduce position size']
        },
        MarketRegime.LOW_VOLATILITY: {
            'bias': 'neutral',
            'confidence_adjust': 0,
            'size_adjust': 0,
            'notes': ['Watch for breakout setups', 'Tighter stops possible']
        },
        MarketRegime.CHOPPY: {
            'bias': 'neutral',
            'confidence_adjust': 15,  # Very strict
            'size_adjust': -30,
            'notes': ['Very selective', 'Consider sitting out']
        }
    }
    
    return guidance.get(regime, {
        'bias': 'neutral',
        'confidence_adjust': 0,
        'size_adjust': 0,
        'notes': ['Proceed with normal caution']
    })


print("✅ Market Regime Detector loaded")

