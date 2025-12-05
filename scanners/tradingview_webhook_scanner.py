"""
TradingView Webhook Futures Scanner
Real-time signal detection with AI validation

Port: 5055
"""

import json
import datetime as dt
import os
import sys
import requests as http_requests
from flask import Flask, request, jsonify, render_template
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from collections import deque
import webbrowser
import threading
import time

# EST timezone helper using pytz for proper timezone handling
import pytz
EST = pytz.timezone('America/New_York')

def est_now():
    """Get current time in EST"""
    return dt.datetime.now(EST)

def est_time_str(fmt="%H:%M:%S"):
    """Get EST time as formatted string"""
    return est_now().strftime(fmt)

def convert_to_est(timestamp_str):
    """
    Convert a timestamp string to EST.
    Handles various formats from TradingView.
    Returns EST datetime string in format: YYYY-MM-DD HH:MM:SS
    """
    if not timestamp_str:
        return est_now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        # Try parsing ISO format with timezone
        if 'T' in str(timestamp_str):
            # ISO format: 2025-12-05T17:18:00Z or 2025-12-05T17:18:00+00:00
            ts = str(timestamp_str).replace('Z', '+00:00')
            parsed = dt.datetime.fromisoformat(ts)
            if parsed.tzinfo is None:
                # Assume UTC if no timezone
                parsed = pytz.UTC.localize(parsed)
            est_time = parsed.astimezone(EST)
            return est_time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Try parsing just time (HH:MM:SS) - assume it's from today
        if len(str(timestamp_str)) <= 8 and ':' in str(timestamp_str):
            today = est_now().date()
            time_parts = str(timestamp_str).split(':')
            hour = int(time_parts[0])
            minute = int(time_parts[1]) if len(time_parts) > 1 else 0
            second = int(time_parts[2]) if len(time_parts) > 2 else 0
            return f"{today} {hour:02d}:{minute:02d}:{second:02d}"
        
        # Already in correct format or other format - return as-is
        return str(timestamp_str)
        
    except Exception as e:
        print(f"⚠️ Time conversion error: {e}, using current EST time")
        return est_now().strftime("%Y-%m-%d %H:%M:%S")

# Auto ngrok tunnel
try:
    from pyngrok import ngrok
    NGROK_AVAILABLE = True
except ImportError:
    NGROK_AVAILABLE = False
    print("⚠️  pyngrok not installed - run: pip install pyngrok")

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import (
    save_signal, get_recent_signals, get_performance_stats, init_database,
    get_ticker_list, get_ticker_settings, TICKERS,
    save_candle as db_save_candle, save_candles_batch, load_candles,
    load_all_candles, get_candle_counts, clear_old_candles
)
from outcome_tracker import set_candle_storage, check_all_pending_outcomes
from apex_rules import (
    get_apex_status, update_apex_config, reset_apex_state,
    record_trade_result, should_block_trading, check_all_rules
)
from analytics import (
    get_full_analytics, get_win_rate_chart_data, get_pnl_chart_data,
    get_ticker_performance, get_hourly_distribution, get_confidence_performance
)
from ai_tuning import (
    get_optimization_summary, auto_tune, get_tuning_history, get_performance_trend
)
from market_levels import get_market_levels, MarketLevels
from news_filter import check_news_blackout, get_news_status, get_upcoming_events
from strategy_coach import run_analysis as run_coach_analysis, get_insights as get_coach_insights
from suggestion_manager import (
    add_suggestions, get_pending_suggestions, approve_suggestion,
    reject_suggestion, get_history as get_suggestion_history,
    get_stats as get_suggestion_stats, undo_suggestion, measure_suggestion_impact
)
from prompt_evolver import get_current_prompt, get_prompt_status, reset_prompt
from market_regime import get_current_regime, get_regime_suggestions, get_regime_trading_guidance
from mtf_analyzer import analyze_ticker as mtf_analyze, MTFAnalyzer
from data_fetcher import fetch_backup_data, merge_candles, data_fetcher

# ========= OPENAI CONFIG =========
# TODO: Move to environment variables for security
# Get API key from local config (dev) or environment variable (production)
try:
    from config_local import OPENAI_API_KEY
    print("✅ Loaded API key from config_local.py")
except ImportError:
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    if OPENAI_API_KEY:
        print("✅ Loaded API key from environment variable")
    else:
        print("⚠️  No OPENAI_API_KEY found - AI analysis will not work")
MODEL_NAME = "gpt-4o-mini"
client = OpenAI(api_key=OPENAI_API_KEY)
# =================================

# ========= EMAIL CONFIG =========
# TODO: Move to environment variables for security
ENABLE_EMAIL_ALERTS = True
EMAIL_FROM = os.environ.get("EMAIL_USER", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "williamgrello@icloud.com")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_USER = os.environ.get("EMAIL_USER", "")
EMAIL_PASS = os.environ.get("EMAIL_PASS", "")
# ================================

# ========= DISCORD CONFIG =========
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
# ==================================


def send_discord_alert(ticker, signal, analysis_details=None):
    """
    Send trade signal alert to Discord - SignalCrawler v2.0
    Enhanced format with written MTF analysis and multiple profit targets
    """
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ Discord webhook not configured")
        return False
    
    try:
        direction = (signal.get('direction', 'NO_TRADE') or '').upper()
        confidence = signal.get('confidence', 0)
        entry = signal.get('entry', 0)
        stop = signal.get('stop', 0)
        target = signal.get('takeProfit', 0)
        
        print(f"📱 Sending Discord alert: {ticker} {direction} {confidence}%")
        
        # Get market levels for context
        market_lvls = get_market_levels()
        levels_info = market_lvls.get_all_levels(ticker, entry)
        bias_info = levels_info.get('bias', {})
        
        # Calculate stop distance for pips display
        stop_pips = abs(entry - stop) if entry and stop else 0
        
        # Emoji based on direction
        if direction == 'LONG':
            emoji = "🟢"
            color = 0x1a472a  # Dark green (like screenshot)
        elif direction == 'SHORT':
            emoji = "🔴"
            color = 0x8b0000  # Dark red
        else:
            emoji = "⚪"
            color = 0x2f3136  # Discord dark
        
        # Get analysis data
        mtf_analysis = {}
        target1 = None
        target2 = None
        target1_pips = 0
        target2_pips = 0
        
        if analysis_details:
            mtf_analysis = analysis_details.get('mtf_analysis', {})
            target1 = analysis_details.get('target1')
            target2 = analysis_details.get('target2')
            target1_pips = analysis_details.get('target1_pips', 0)
            target2_pips = analysis_details.get('target2_pips', 0)
        
        # Build the TRADE SETUP section
        trade_setup = f"**Direction:** {direction}\n"
        trade_setup += f"**Confidence Level:** {confidence}%"
        
        # Build Entry Strategy section
        entry_strategy = f"• **Entry Price:** {entry:.2f}\n"
        entry_strategy += f"• **Stop Loss:** {stop:.2f} ({stop_pips:.1f} pts away)"
        
        # Build Profit Targets section
        profit_targets = ""
        if target1:
            profit_targets += f"• **Target 1:** {target1:.2f} ({target1_pips:.1f} pts, 1:1.50 R:R)\n"
        if target2:
            profit_targets += f"• **Target 2:** {target2:.2f} ({target2_pips:.1f} pts, 1:2.00 R:R)"
        else:
            profit_targets = f"• **Target:** {target:.2f} (2:1 R:R)"
        
        # Build MTF Analysis section (written text like the screenshot)
        mtf_text = ""
        if mtf_analysis:
            if mtf_analysis.get('15m'):
                mtf_text += f"**15m Chart:** {mtf_analysis['15m']}\n\n"
            if mtf_analysis.get('5m'):
                mtf_text += f"**5m Chart:** {mtf_analysis['5m']}\n\n"
            if mtf_analysis.get('1m'):
                mtf_text += f"**1m Chart:** {mtf_analysis['1m']}"
        else:
            mtf_text = "Analysis data not available"
        
        # Truncate MTF text if too long (Discord limit)
        if len(mtf_text) > 1000:
            mtf_text = mtf_text[:997] + "..."
        
        # Build Discord embed with new format (like screenshot)
        embed = {
            "title": f"{emoji} TRADE SETUP - {ticker}",
            "color": color,
            "fields": [
                # Trade Setup
                {"name": "📋 TRADE SETUP", "value": trade_setup, "inline": False},
                
                # Entry Strategy
                {"name": "🎯 Entry Strategy", "value": entry_strategy, "inline": False},
                
                # Profit Targets
                {"name": "💰 Profit Targets", "value": profit_targets, "inline": False},
                
                # Multi-Timeframe Analysis (written text)
                {"name": "📊 Multi-Timeframe Analysis", "value": mtf_text, "inline": False},
            ],
            "footer": {"text": f"SignalCrawler v2.0 • {confidence}% Confidence • $250 Risk"},
            "timestamp": dt.datetime.now().isoformat()
        }
        
        # Add position sizing if available
        if analysis_details:
            position = analysis_details.get('position_size', {})
            if position:
                contracts = position.get('contracts', 1)
                actual_risk = position.get('actual_risk', 250)
                potential_profit = position.get('potential_profit', 500)
                embed["fields"].append({
                    "name": "📊 Position Size",
                    "value": f"**{contracts} contract(s)** @ $250 risk\nPotential Profit: ${potential_profit:.0f}",
                    "inline": False
                })
        
        # Send to Discord
        payload = {
            "username": "SignalCrawler v2.0",
            "embeds": [embed]
        }
        
        response = http_requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        
        if response.status_code in [200, 204]:
            print(f"📱 Discord alert sent for {ticker}")
            return True
        else:
            print(f"⚠️ Discord error: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"⚠️ Discord alert failed: {e}")
        return False

# ========= QUALITY FILTERS (v2.0) =========
MIN_CONFIDENCE = 80  # Only 80%+ signals now
MIN_DISCORD_CONFIDENCE = 80  # Discord alert threshold
MAX_PRICE_DRIFT_TICKS = 15
REQUIRE_MOMENTUM_ALIGNMENT = True
MIN_RISK_REWARD = 2.0  # Exact 2:1 R:R required
ANALYSIS_INTERVAL_MINUTES = 5  # Only auto-analyze every N minutes
PDH_PDL_BUFFER = 15  # Must be 15+ pts from PDH/PDL
# ==========================================

# Track last analysis time per ticker
last_analysis_time = {}

# ========= SMART ALERT COOLDOWN =========
# Only send alerts when something ACTUALLY changes, not every 5 minutes
last_alert_info = {}  # {ticker: {'direction': 'LONG', 'entry': 25800, 'confidence': 92, 'time': datetime}}

# Thresholds for new alert (per ticker type)
ALERT_PRICE_THRESHOLD = {
    'MNQ': 50,   # 50 points (~$25 move)
    'MES': 10,   # 10 points (~$12.50 move)
    'MGC': 5,    # 5 points (~$5 move)
    'DEFAULT': 20
}
ALERT_CONFIDENCE_THRESHOLD = 10  # Alert if confidence increased by 10%+
ALERT_MIN_COOLDOWN_MINUTES = 15  # Minimum time between alerts for same setup

def should_send_alert(ticker, direction, entry, confidence):
    """
    Smart cooldown - only send alert if:
    1. Direction changed (LONG → SHORT or vice versa)
    2. Price moved significantly from last alert
    3. Confidence increased significantly
    4. OR minimum cooldown passed with same direction
    
    Returns: (should_send: bool, reason: str)
    """
    import re
    # Normalize ticker
    base_ticker = re.sub(r'[FGHJKMNQUVXZ]\d{4}$', '', ticker).replace('=F', '').upper()
    
    last = last_alert_info.get(base_ticker)
    
    if not last:
        return True, "First alert for this ticker"
    
    last_dir = last.get('direction')
    last_entry = last.get('entry', 0)
    last_conf = last.get('confidence', 0)
    last_time = last.get('time')
    
    # 1. Direction changed - ALWAYS alert
    if direction != last_dir:
        return True, f"Direction changed: {last_dir} → {direction}"
    
    # 2. Price moved significantly
    price_threshold = ALERT_PRICE_THRESHOLD.get(base_ticker, ALERT_PRICE_THRESHOLD['DEFAULT'])
    price_diff = abs(entry - last_entry) if entry and last_entry else 0
    if price_diff >= price_threshold:
        return True, f"Price moved {price_diff:.1f} pts (threshold: {price_threshold})"
    
    # 3. Confidence increased significantly
    conf_diff = confidence - last_conf
    if conf_diff >= ALERT_CONFIDENCE_THRESHOLD:
        return True, f"Confidence increased +{conf_diff}% (was {last_conf}%)"
    
    # 4. Minimum cooldown passed
    if last_time:
        minutes_since = (dt.datetime.now() - last_time).total_seconds() / 60
        if minutes_since >= ALERT_MIN_COOLDOWN_MINUTES:
            return True, f"Cooldown passed ({minutes_since:.0f} min since last)"
    
    # Same setup, no significant change
    return False, f"Same setup (dir={direction}, price diff={price_diff:.1f}, cooldown not met)"

def record_alert_sent(ticker, direction, entry, confidence):
    """Record that we sent an alert for this ticker"""
    import re
    base_ticker = re.sub(r'[FGHJKMNQUVXZ]\d{4}$', '', ticker).replace('=F', '').upper()
    last_alert_info[base_ticker] = {
        'direction': direction,
        'entry': entry,
        'confidence': confidence,
        'time': dt.datetime.now()
    }
    print(f"📝 Recorded alert: {base_ticker} {direction} @ {entry} ({confidence}%)")

# ========= PRODUCT SETTINGS =========
TICK_SIZES = {
    "MNQ": 0.25, "MNQ=F": 0.25,
    "MES": 0.25, "MES=F": 0.25,
    "MGC": 0.10, "MGC=F": 0.10,
    "NQ": 0.25, "ES": 0.25, "GC": 0.10,
}

MAX_TICKS = {
    "MNQ": 30, "MNQ=F": 30,
    "MES": 20, "MES=F": 20,
    "MGC": 40, "MGC=F": 40,
}
# ====================================

# ========= DATA STORAGE =========
# Store recent candles in memory - INCREASED for longer-term analysis
# 1m: 300 candles = 5 hours (full RTH session)
# 5m: 100 candles = 8+ hours (full trading day)
# 15m: 60 candles = 15 hours (day + overnight)
candle_storage = {
    "1m": {},   # ticker -> deque of candles
    "5m": {},
    "15m": {}
}

# Storage limits per timeframe
CANDLE_LIMITS = {
    "1m": 300,
    "5m": 100,
    "15m": 60
}

# File for persisting candle history
CANDLE_HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'candle_history.json')

def save_candle_history():
    """Save candle history to file for persistence between restarts"""
    try:
        data = {}
        for tf in ["1m", "5m", "15m"]:
            data[tf] = {}
            for ticker, candles in candle_storage[tf].items():
                data[tf][ticker] = list(candles)
        
        with open(CANDLE_HISTORY_FILE, 'w') as f:
            json.dump(data, f)
        
        total = sum(len(candles) for tf_data in data.values() for candles in tf_data.values())
        print(f"💾 Saved {total} candles to history file")
    except Exception as e:
        print(f"⚠️  Error saving candle history: {e}")

def normalize_ticker(ticker):
    """Normalize ticker symbol - strip contract months like Z2025, G2026, etc."""
    import re
    # Remove contract month/year suffixes like Z2025, G2026, H2025, etc.
    base = re.sub(r'[FGHJKMNQUVXZ]\d{4}$', '', ticker)
    # Also remove =F suffix
    base = base.replace('=F', '')
    return base.upper()


def load_candle_history():
    """Load candle history from DATABASE on startup"""
    global candle_storage
    
    try:
        # Load from database
        db_candles = load_all_candles()
        
        if not db_candles:
            print("📂 No candle history in database - starting fresh")
            return False
        
        total_loaded = 0
        
        for ticker, timeframes in db_candles.items():
            # Normalize the ticker (MNQZ2025 -> MNQ)
            base_ticker = normalize_ticker(ticker)
            
        for tf in ["1m", "5m", "15m"]:
                candles = timeframes.get(tf, [])
                if candles:
                    maxlen = CANDLE_LIMITS[tf]
                    
                    # Merge with existing if base ticker already has candles
                    if base_ticker in candle_storage[tf]:
                        existing = list(candle_storage[tf][base_ticker])
                        combined = existing + candles
                        candle_storage[tf][base_ticker] = deque(combined[-maxlen:], maxlen=maxlen)
                    else:
                        candle_storage[tf][base_ticker] = deque(candles, maxlen=maxlen)
                    
                    total_loaded += len(candles)
        
        if total_loaded > 0:
            print(f"✅ Loaded {total_loaded} candles from database!")
            # Print summary per ticker
            printed_tickers = set()
            for ticker in db_candles.keys():
                if ticker not in printed_tickers:
                    c1m = len(candle_storage['1m'].get(ticker, []))
                    c5m = len(candle_storage['5m'].get(ticker, []))
                    c15m = len(candle_storage['15m'].get(ticker, []))
                    if c1m > 0 or c5m > 0 or c15m > 0:
                        print(f"   {ticker}: {c1m} x 1m, {c5m} x 5m, {c15m} x 15m")
                        printed_tickers.add(ticker)
            return True
        
    except Exception as e:
        print(f"⚠️  Error loading candle history from database: {e}")
    
    return False

# Initialize storage for each ticker with new limits
for ticker in ["MNQ", "MES", "MGC"]:
    candle_storage["1m"][ticker] = deque(maxlen=CANDLE_LIMITS["1m"])  # 300 candles
    candle_storage["5m"][ticker] = deque(maxlen=CANDLE_LIMITS["5m"])  # 100 candles
    candle_storage["15m"][ticker] = deque(maxlen=CANDLE_LIMITS["15m"])  # 60 candles

# Load history from previous session
load_candle_history()

# Pass candle storage to outcome tracker for price lookups
set_candle_storage(candle_storage)

# Dashboard stats
dashboard_stats = {
    "webhook_count": 0,
    "signal_count": 0,
    "recent_signals": deque(maxlen=50),
    "recent_logs": deque(maxlen=100)
}

def add_log(message, log_type="info"):
    """Add log entry for dashboard"""
    dashboard_stats["recent_logs"].appendleft({
        "time": dt.datetime.now().strftime("%H:%M:%S"),
        "message": message,
        "type": log_type
    })
# ================================


# ========= AI PROMPT =========
SYSTEM_PROMPT = """
You are an advanced futures trading assistant specializing in MICRO futures contracts.
Analyze the provided multi-timeframe data and return ONE clear trade idea.

CRITICAL PRICE ACTION RULES:
- Only suggest trades when ALL timeframes align
- 15m must show clear trend direction (not choppy)
- 5m must show BOS + displacement in that direction
- 1m must show clean retracement (not continued opposite momentum)
- Recent 1m candles (last 3-5) should support the direction
- For LONG: Last 3 candles should NOT all be bearish
- For SHORT: Last 3 candles should NOT all be bullish

WHEN TO SAY NO_TRADE:
- Choppy, overlapping candles
- Mixed signals across timeframes
- Price in middle of range
- Recent strong momentum AGAINST proposed direction
- Risk:Reward less than 2:1

BE CONSERVATIVE. Better to skip 10 mediocre setups than take 1 bad trade.

ENTRY TIMING:
- "IMMEDIATE" - Price at ideal entry zone NOW
- "WAIT_FOR_PULLBACK" - Specify exact pullback level
- "WAIT_FOR_BREAKOUT" - Waiting for break + retest

OUTPUT FORMAT (STRICT JSON):
{
  "direction": "long" | "short" | "no_trade",
  "confidence": 0-100,
  "entryType": "IMMEDIATE" | "WAIT_FOR_PULLBACK" | "WAIT_FOR_BREAKOUT",
  "entry": number,
  "currentPrice": number,
  "stop": number,
  "takeProfit": number,
  "rationale": "Explain timeframe alignment and structure",
  "entryInstructions": "Detailed entry guidance with specific levels",
  "recentMomentum": "bullish" | "bearish" | "neutral"
}
"""
# ============================


# ========= FLASK APP =========
# Set template folder relative to this file's location
template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)


def get_tick_size(ticker):
    """Get tick size for ticker"""
    base_ticker = ticker.split(":")[0] if ":" in ticker else ticker
    return TICK_SIZES.get(base_ticker, 0.25)


def get_max_ticks(ticker):
    """Get max stop ticks for ticker"""
    base_ticker = ticker.split(":")[0] if ":" in ticker else ticker
    return MAX_TICKS.get(base_ticker, 30)


def store_candle(ticker, timeframe, candle_data):
    """Store candle in memory AND database"""
    # Normalize ticker (MNQZ2025 -> MNQ, CBOT:MES=F -> MES)
    base_ticker = ticker.split(":")[0] if ":" in ticker else ticker
    base_ticker = normalize_ticker(base_ticker)
    
    # Ensure ticker exists in storage
    if base_ticker not in candle_storage[timeframe]:
        candle_storage[timeframe][base_ticker] = deque(maxlen=CANDLE_LIMITS[timeframe])
    
    candle_storage[timeframe][base_ticker].append(candle_data)
    print(f"  📊 Stored {timeframe} candle for {base_ticker} (total: {len(candle_storage[timeframe][base_ticker])})")
    
    # Save to database for persistence
    db_save_candle(base_ticker, timeframe, candle_data)
    
    # Auto-aggregate 1m candles into 5m and 15m
    if timeframe == "1m":
        aggregate_candles(base_ticker)
        
        # Auto-save JSON backup every 5 candles (5 minutes) - keeping as backup
        if len(candle_storage["1m"][base_ticker]) % 5 == 0:
            save_candle_history()


def aggregate_candles(ticker):
    """
    Aggregate 1m candles into 5m and 15m candles
    Called automatically after each 1m candle is stored
    """
    candles_1m = list(candle_storage["1m"].get(ticker, []))
    
    if len(candles_1m) < 5:
        return  # Not enough data yet
    
    # Build 5m candles (every 5 x 1m candles)
    build_aggregated_candles(ticker, candles_1m, 5, "5m")
    
    # Build 15m candles (every 15 x 1m candles)  
    build_aggregated_candles(ticker, candles_1m, 15, "15m")


def build_aggregated_candles(ticker, candles_1m, period, target_tf):
    """
    Build aggregated candles from 1m data
    
    Args:
        ticker: Symbol
        candles_1m: List of 1m candles
        period: Number of 1m candles per aggregated candle (5 or 15)
        target_tf: Target timeframe ('5m' or '15m')
    """
    # Ensure storage exists
    if ticker not in candle_storage[target_tf]:
        candle_storage[target_tf][ticker] = deque(maxlen=CANDLE_LIMITS[target_tf])
    
    # Calculate how many complete periods we can build
    num_complete = len(candles_1m) // period
    
    if num_complete == 0:
        return
    
    # Current count of aggregated candles
    current_count = len(candle_storage[target_tf][ticker])
    
    # Only build if we have new complete periods
    # (avoid rebuilding the same candles)
    expected_count = num_complete
    
    if current_count >= expected_count:
        return  # Already up to date
    
    # Clear and rebuild (simpler than incremental updates)
    candle_storage[target_tf][ticker].clear()
    
    for i in range(num_complete):
        start_idx = i * period
        end_idx = start_idx + period
        chunk = candles_1m[start_idx:end_idx]
        
        if len(chunk) == period:
            aggregated = {
                'time': chunk[0].get('time', ''),  # Time of first candle
                'open': chunk[0].get('open', 0),   # Open of first candle
                'high': max(c.get('high', 0) for c in chunk),  # Highest high
                'low': min(c.get('low', float('inf')) for c in chunk),  # Lowest low
                'close': chunk[-1].get('close', 0),  # Close of last candle
                'volume': sum(c.get('volume', 0) for c in chunk)  # Sum of volume
            }
            candle_storage[target_tf][ticker].append(aggregated)
    
    new_count = len(candle_storage[target_tf][ticker])
    if new_count > current_count:
        print(f"  📈 Auto-built {new_count} x {target_tf} candles for {ticker} (from {len(candles_1m)} x 1m)")


def format_data_for_ai(ticker):
    """Format stored candles for AI analysis"""
    base_ticker = ticker.split(":")[0] if ":" in ticker else ticker
    tick_size = get_tick_size(base_ticker)
    max_ticks = get_max_ticks(base_ticker)
    
    output = f"TICKER: {base_ticker}\n"
    output += f"TICK_SIZE: {tick_size}\n"
    output += f"MAX_STOP_TICKS: {max_ticks}\n\n"
    
    for timeframe in ["15m", "5m", "1m"]:
        candles = candle_storage[timeframe].get(base_ticker, [])
        
        if not candles:
            output += f"=== {timeframe.upper()} DATA ===\nNo data available yet\n\n"
            continue
        
        output += f"=== {timeframe.upper()} DATA (last {min(10, len(candles))} candles) ===\n"
        
        # Get last 10 candles
        recent = list(candles)[-10:]
        
        for candle in recent:
            timestamp = candle.get('time', 'unknown')
            o = candle.get('open', 0)
            h = candle.get('high', 0)
            l = candle.get('low', 0)
            c = candle.get('close', 0)
            v = candle.get('volume', 0)
            
            output += f"{timestamp} | O:{o:.2f} H:{h:.2f} L:{l:.2f} C:{c:.2f} V:{int(v)}\n"
        
        output += "\n"
    
    return output


def check_momentum_alignment(ticker, direction):
    """Check if recent 1m candles support the trade direction"""
    base_ticker = ticker.split(":")[0] if ":" in ticker else ticker
    candles = candle_storage["1m"].get(base_ticker, [])
    
    if len(candles) < 3:
        return False, "insufficient_data"
    
    recent = list(candles)[-3:]
    bullish_count = sum(1 for c in recent if c.get('close', 0) > c.get('open', 0))
    bearish_count = sum(1 for c in recent if c.get('close', 0) < c.get('open', 0))
    
    if direction == "long":
        if bearish_count == 3:
            return False, "strong_bearish_momentum"
        elif bearish_count == 2:
            return False, "weak_bearish_momentum"
    elif direction == "short":
        if bullish_count == 3:
            return False, "strong_bullish_momentum"
        elif bullish_count == 2:
            return False, "weak_bullish_momentum"
    
    return True, "aligned"


def calculate_risk_reward(entry, stop, target):
    """Calculate R:R ratio"""
    try:
        risk = abs(float(entry) - float(stop))
        reward = abs(float(target) - float(entry))
        return reward / risk if risk > 0 else 0
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


def validate_signal(signal, ticker):
    """
    Run quality checks on AI signal - SignalCrawler v2.0
    
    ALL criteria must be met:
    1. No active news blackout
    2. Confidence >= 80%
    3. Valid direction
    4. Required price levels
    5. R:R >= 2.0
    6. Price drift acceptable
    7. ORB bias alignment (LONG/SHORT must match daily bias)
    8. PDH/PDL safety (not too close to major levels)
    """
    reasons = []
    
    direction = signal.get('direction', 'no_trade')
    confidence = signal.get('confidence', 0)
    entry = signal.get('entry')
    stop = signal.get('stop')
    target = signal.get('takeProfit')
    current_price = signal.get('currentPrice')
    
    # Check 0: News blackout (NEW - blocks all trading during major news)
    is_blackout, news_event = check_news_blackout()
    if is_blackout:
        reasons.append(f"🚫 NEWS BLACKOUT: {news_event['event']} - Clear in {news_event['minutes_until_clear']} min")
        return False, reasons
    
    # Get market levels for bias and level checks
    market_lvls = get_market_levels()
    
    # Check 1: Confidence (80%+ required)
    if confidence < MIN_CONFIDENCE:
        reasons.append(f"❌ Confidence {confidence}% below threshold {MIN_CONFIDENCE}%")
        return False, reasons
    
    # Check 2: Direction
    if direction == "no_trade" or direction == "STAY_AWAY":
        reasons.append("⚠️  AI suggests no trade")
        return False, reasons
    
    # Check 3: Required fields
    if entry is None or stop is None or target is None or current_price is None:
        reasons.append("❌ Missing required price levels")
        return False, reasons
    
    # Check 4: R:R (2:1 minimum)
    rr = calculate_risk_reward(entry, stop, target)
    if rr < MIN_RISK_REWARD:
        reasons.append(f"❌ R:R {rr:.2f} below minimum {MIN_RISK_REWARD}")
        return False, reasons
    
    # Check 5: Price drift
    tick_size = get_tick_size(ticker)
    drift = abs(float(current_price) - float(entry))
    drift_ticks = drift / tick_size
    
    if drift_ticks > MAX_PRICE_DRIFT_TICKS:
        reasons.append(f"❌ Price drifted {drift_ticks:.1f} ticks from entry")
        return False, reasons
    
    # Check 6: ORB Bias Alignment (NEW in v2.0)
    bias_aligned, bias_reason = market_lvls.check_bias_alignment(ticker, direction, current_price)
    if not bias_aligned:
        reasons.append(f"❌ {bias_reason}")
        return False, reasons
    reasons.append(f"✓ {bias_reason}")
    
    # Check 7: PDH/PDL Safety (NEW in v2.0)
    level_safe, level_reason = market_lvls.check_entry_safety(ticker, entry, direction)
    if not level_safe:
        reasons.append(f"❌ {level_reason}")
        return False, reasons
    reasons.append(f"✓ {level_reason}")
    
    # All checks passed
    reasons.append("✓ MTF alignment confirmed")
    reasons.append(f"✓ Confidence: {confidence}%")
    reasons.append(f"✓ R:R: {rr:.2f}")
    reasons.append(f"✓ Price drift: {drift_ticks:.1f} ticks")
    
    return True, reasons


def analyze_with_ai(data_text):
    """Send data to OpenAI for analysis"""
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": data_text}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"❌ AI Error: {e}")
        return None


def send_email_alert(ticker, signal, reasons):
    """Send email alert"""
    if not ENABLE_EMAIL_ALERTS:
        return
    
    try:
        direction = signal['direction'].upper()
        confidence = signal['confidence']
        entry_type = signal.get('entryType', 'UNKNOWN')
        current_price = signal.get('currentPrice', 'N/A')
        entry = signal.get('entry', 'N/A')
        stop = signal.get('stop', 'N/A')
        tp = signal.get('takeProfit', 'N/A')
        rationale = signal.get('rationale', '')
        entry_instructions = signal.get('entryInstructions', 'No instructions')
        
        # Calculate R:R
        rr_text = ""
        if entry != 'N/A' and stop != 'N/A' and tp != 'N/A':
            rr = calculate_risk_reward(entry, stop, tp)
            rr_text = f"\n💰 Risk:Reward: 1:{rr:.2f}"
        
        validation_text = "\n".join(reasons)
        
        subject = f"🚨 {ticker} {direction} ({confidence}% • {entry_type})"
        
        body = f"""
🎯 REAL-TIME FUTURES ALERT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 SETUP DETAILS
Ticker: {ticker}
Direction: {direction}
Confidence: {confidence}%
Entry Type: {entry_type}

💵 PRICE LEVELS
Current Price: {current_price}
Entry Price: {entry}
Stop Loss: {stop}
Take Profit: {tp}{rr_text}

📍 ENTRY INSTRUCTIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{entry_instructions}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 ANALYSIS:
{rationale}

✅ QUALITY CHECKS:
{validation_text}

⏰ Time: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        
        print(f"📧 Email sent for {ticker}")
        
    except Exception as e:
        print(f"❌ Email error: {e}")


# ========= WEBHOOK ENDPOINTS =========

@app.route('/')
def home():
    """Serve the dashboard"""
    return render_template('dashboard.html')


@app.route('/api/status')
def api_status():
    """API endpoint for dashboard data"""
    # Get public URL - check Railway first, then ngrok
    public_url = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
    if public_url:
        public_url = f"https://{public_url}"
    else:
        # Try ngrok for local development
        try:
            ngrok_response = http_requests.get('http://localhost:4040/api/tunnels', timeout=1)
            tunnels = ngrok_response.json().get('tunnels', [])
            for tunnel in tunnels:
                if tunnel.get('proto') == 'https':
                    public_url = tunnel.get('public_url')
                    break
            if not public_url and tunnels:
                public_url = tunnels[0].get('public_url')
        except Exception:
            public_url = None
    
    return jsonify({
        "status": "running",
        "scanner": "TradingView Webhook Futures Scanner",
        "port": 5055,
        "tickers": list(candle_storage["1m"].keys()),
        "candles_stored": {
            "1m": sum(len(v) for v in candle_storage["1m"].values()),
            "5m": sum(len(v) for v in candle_storage["5m"].values()),
            "15m": sum(len(v) for v in candle_storage["15m"].values())
        },
        "webhook_count": dashboard_stats["webhook_count"],
        "signal_count": dashboard_stats["signal_count"],
        "recent_signals": list(dashboard_stats["recent_signals"]),
        "recent_logs": list(dashboard_stats["recent_logs"])[:10],
        "ngrok_url": public_url
    })


@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "running",
        "port": 5055
    })


# ========= SETTINGS STORAGE =========
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'settings.json')

def load_settings_from_file():
    """Load settings from JSON file"""
    default_settings = {
        "scan_interval": 1,
        "min_confidence": MIN_CONFIDENCE,
        "min_risk_reward": MIN_RISK_REWARD,
        "tickers": ["MNQ=F", "MES=F", "MGC=F"]
    }
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return default_settings

def save_settings_to_file(settings):
    """Save settings to JSON file"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Error saving settings: {e}")

scanner_settings = load_settings_from_file()


@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get current scanner settings"""
    return jsonify(scanner_settings)


@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Update scanner settings"""
    global MIN_CONFIDENCE, MIN_RISK_REWARD, scanner_settings
    
    try:
        data = request.get_json(force=True, silent=True)
        
        if data.get('scan_interval'):
            scanner_settings['scan_interval'] = int(data['scan_interval'])
        
        if data.get('min_confidence'):
            scanner_settings['min_confidence'] = int(data['min_confidence'])
            MIN_CONFIDENCE = int(data['min_confidence'])
        
        if data.get('min_risk_reward'):
            scanner_settings['min_risk_reward'] = float(data['min_risk_reward'])
            MIN_RISK_REWARD = float(data['min_risk_reward'])
        
        if data.get('tickers'):
            scanner_settings['tickers'] = data['tickers']
        
        # Save to file so futures scanner can read it
        save_settings_to_file(scanner_settings)
        
        add_log(f"Settings updated: interval={scanner_settings['scan_interval']}min, confidence={scanner_settings['min_confidence']}%", "success")
        
        return jsonify({"status": "success", "settings": scanner_settings})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/trades')
def get_trades():
    """Get trade history from database"""
    try:
        limit = request.args.get('limit', 15, type=int)  # Default 15, max 100
        limit = min(limit, 100)  # Cap at 100
        trades = get_recent_signals(limit=limit)
        return jsonify(trades)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========= TICKER API (Hardcoded: MNQ, MES, MGC) =========

@app.route('/api/analyze', methods=['POST', 'GET'])
@app.route('/api/analyze/<ticker_symbol>', methods=['POST', 'GET'])
def analyze_on_demand(ticker_symbol=None):
    """On-demand analysis API - returns JSON"""
    results = run_analysis(ticker_symbol)
    return jsonify({
        "status": "success",
        "analyzed_at": dt.datetime.now().isoformat(),
        "results": results
    })


@app.route('/analyze', methods=['GET'])
@app.route('/analyze/<ticker_symbol>', methods=['GET'])
def analyze_mobile(ticker_symbol=None):
    """
    Mobile-friendly analysis page
    GET /analyze - Analyze all tickers (nice HTML page)
    GET /analyze/MNQ - Analyze specific ticker
    """
    results = run_analysis(ticker_symbol, send_alerts=True)
    
    # Build mobile-friendly HTML
    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>SignalCrawler Analysis</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #0a0a0f;
                color: #e0e0e0;
                padding: 20px;
                min-height: 100vh;
            }}
            h1 {{ 
                text-align: center; 
                margin-bottom: 20px;
                font-size: 1.5rem;
                color: #fff;
            }}
            .time {{ 
                text-align: center; 
                color: #888; 
                font-size: 0.8rem;
                margin-bottom: 20px;
            }}
            .card {{
                background: #1a1a24;
                border-radius: 12px;
                padding: 16px;
                margin-bottom: 16px;
                border: 1px solid #2a2a3a;
            }}
            .ticker {{ 
                font-size: 1.4rem; 
                font-weight: bold;
                margin-bottom: 8px;
            }}
            .direction {{
                display: inline-block;
                padding: 6px 16px;
                border-radius: 20px;
                font-weight: bold;
                font-size: 1rem;
                margin-bottom: 12px;
            }}
            .long {{ background: #00c853; color: #000; }}
            .short {{ background: #ff1744; color: #fff; }}
            .stay_away {{ background: #666; color: #fff; }}
            .insufficient {{ background: #333; color: #888; }}
            .confidence {{
                font-size: 2rem;
                font-weight: bold;
                margin: 8px 0;
            }}
            .conf-high {{ color: #00c853; }}
            .conf-med {{ color: #ffc107; }}
            .conf-low {{ color: #ff1744; }}
            .prices {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 8px;
                margin-top: 12px;
            }}
            .price-box {{
                background: #0a0a0f;
                padding: 8px;
                border-radius: 8px;
                text-align: center;
            }}
            .price-label {{ font-size: 0.7rem; color: #888; }}
            .price-value {{ font-size: 1rem; font-weight: bold; }}
            .warning {{
                background: #332200;
                border: 1px solid #664400;
                padding: 8px;
                border-radius: 8px;
                margin-top: 8px;
                font-size: 0.85rem;
                color: #ffaa00;
            }}
            .btn {{
                display: block;
                width: 100%;
                padding: 16px;
                background: #4488ff;
                color: #fff;
                border: none;
                border-radius: 12px;
                font-size: 1.1rem;
                font-weight: bold;
                cursor: pointer;
                margin-top: 20px;
                text-decoration: none;
                text-align: center;
            }}
            .btn:active {{ background: #3366cc; }}
        </style>
    </head>
    <body>
        <h1>🕷️ SignalCrawler v2.0</h1>
        <div class="time">Analyzed: {est_time_str("%I:%M:%S %p")} EST</div>
    '''
    
    # Check for news blackout and show banner
    is_news_blackout, news_event = check_news_blackout()
    if is_news_blackout:
        html += f'''
        <div style="background:#4a1a1a;border:2px solid #ff4444;padding:12px;border-radius:8px;margin:12px 0;text-align:center;">
            <div style="font-size:1.1rem;font-weight:bold;color:#ff4444;">🚫 NEWS BLACKOUT ACTIVE</div>
            <div style="font-size:0.9rem;color:#ffaaaa;margin-top:4px;">📰 {news_event['event']}</div>
            <div style="font-size:0.85rem;color:#888;margin-top:4px;">Clear in {news_event['minutes_until_clear']} min</div>
        </div>
        '''
    else:
        # Show upcoming events if any
        upcoming = get_upcoming_events(days_ahead=2)
        if upcoming:
            next_event = upcoming[0]
            html += f'''
            <div style="background:#1a2a3a;border:1px solid #2a4a6a;padding:8px;border-radius:8px;margin:12px 0;text-align:center;">
                <div style="font-size:0.8rem;color:#888;">📅 Next Event: {next_event['date']} {next_event['time']}</div>
                <div style="font-size:0.85rem;color:#aaddff;">{next_event['event']}</div>
            </div>
            '''
    
    for r in results:
        ticker = r.get('ticker', 'UNKNOWN')
        status = r.get('status', '')
        direction = r.get('direction', 'STAY_AWAY')
        confidence = r.get('confidence', 0)
        entry = r.get('entry')
        stop = r.get('stop')
        target = r.get('target')
        rr = r.get('risk_reward', 0)
        warnings = r.get('warnings', [])
        stay_reason = r.get('stay_away_reason', '')
        message = r.get('message', '')
        
        # v2.0 additions
        daily_bias = r.get('daily_bias', 'UNKNOWN')
        orb_high = r.get('orb_high')
        orb_low = r.get('orb_low')
        pdh = r.get('pdh')
        pdl = r.get('pdl')
        all_criteria_met = r.get('all_criteria_met', False)
        criteria_met = r.get('criteria_met', [])
        criteria_failed = r.get('criteria_failed', [])
        
        # Direction styling
        if status == 'insufficient_data':
            dir_class = 'insufficient'
            dir_text = '⏳ LOADING'
        elif direction == 'LONG':
            dir_class = 'long'
            dir_text = '🟢 LONG'
        elif direction == 'SHORT':
            dir_class = 'short'
            dir_text = '🔴 SHORT'
        else:
            dir_class = 'stay_away'
            dir_text = '⚪ STAY AWAY'
        
        # Confidence styling
        conf_class = 'conf-high' if confidence >= 80 else 'conf-med' if confidence >= 70 else 'conf-low'
        
        # Bias styling
        bias_emoji = '🟢' if daily_bias == 'LONG' else '🔴' if daily_bias == 'SHORT' else '⚪'
        
        html += f'''
        <div class="card">
            <div class="ticker">{ticker}</div>
            <span class="direction {dir_class}">{dir_text}</span>
        '''
        
        if status != 'insufficient_data':
            html += f'''
            <div class="confidence {conf_class}">{confidence}%</div>
            '''
            
            # Daily Bias Box (NEW in v2.0)
            html += f'''
            <div style="background:#1a1a2a;border:1px solid #3a3a5a;padding:10px;border-radius:8px;margin:12px 0;text-align:center;">
                <div style="font-size:0.75rem;color:#888;margin-bottom:4px;">DAILY BIAS (ORB)</div>
                <div style="font-size:1.3rem;font-weight:bold;">{bias_emoji} {daily_bias}</div>
            </div>
            '''
            
            # Timeframe Trends (15m, 5m, 1m)
            tf15_trend = r.get('tf15_trend', '?')
            tf15_str = r.get('tf15_strength', '?')
            tf5_trend = r.get('tf5_trend', '?')
            tf5_str = r.get('tf5_strength', '?')
            tf1_trend = r.get('tf1_trend', '?')
            tf1_str = r.get('tf1_strength', '?')
            
            def trend_color(trend):
                if trend == 'bullish': return '#00ff88'
                if trend == 'bearish': return '#ff4466'
                return '#888888'
            
            def trend_emoji(trend):
                if trend == 'bullish': return '🟢'
                if trend == 'bearish': return '🔴'
                return '⚪'
            
            html += f'''
            <div style="background:#1a1a24;border:1px solid #2a2a3a;padding:10px;border-radius:8px;margin:12px 0;">
                <div style="font-size:0.75rem;color:#888;margin-bottom:8px;text-align:center;">TIMEFRAME TRENDS</div>
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;text-align:center;">
                    <div style="background:#0a0a0f;padding:8px;border-radius:6px;">
                        <div style="font-size:0.7rem;color:#666;">15m</div>
                        <div style="font-size:0.95rem;font-weight:bold;color:{trend_color(tf15_trend)};">{trend_emoji(tf15_trend)} {tf15_trend.upper()}</div>
                        <div style="font-size:0.65rem;color:#888;">{tf15_str}</div>
                    </div>
                    <div style="background:#0a0a0f;padding:8px;border-radius:6px;">
                        <div style="font-size:0.7rem;color:#666;">5m</div>
                        <div style="font-size:0.95rem;font-weight:bold;color:{trend_color(tf5_trend)};">{trend_emoji(tf5_trend)} {tf5_trend.upper()}</div>
                        <div style="font-size:0.65rem;color:#888;">{tf5_str}</div>
                    </div>
                    <div style="background:#0a0a0f;padding:8px;border-radius:6px;">
                        <div style="font-size:0.7rem;color:#666;">1m</div>
                        <div style="font-size:0.95rem;font-weight:bold;color:{trend_color(tf1_trend)};">{trend_emoji(tf1_trend)} {tf1_trend.upper()}</div>
                        <div style="font-size:0.65rem;color:#888;">{tf1_str}</div>
                    </div>
                </div>
            </div>
            '''
            
            # Key Levels (NEW in v2.0)
            if orb_high or pdh:
                html += '''
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0;">
                '''
                if orb_high and orb_low:
                    html += f'''
                    <div style="background:#1a2a1a;border:1px solid #2a4a2a;padding:8px;border-radius:8px;text-align:center;">
                        <div style="font-size:0.7rem;color:#888;">ORB RANGE</div>
                        <div style="font-size:0.9rem;color:#aaffaa;">{orb_low:.2f} - {orb_high:.2f}</div>
                    </div>
                    '''
                if pdh and pdl:
                    html += f'''
                    <div style="background:#2a1a1a;border:1px solid #4a2a2a;padding:8px;border-radius:8px;text-align:center;">
                        <div style="font-size:0.7rem;color:#888;">PDH / PDL</div>
                        <div style="font-size:0.9rem;color:#ffaaaa;">{pdh:.2f} / {pdl:.2f}</div>
                    </div>
                    '''
                html += '</div>'
            
            if entry and stop and target:
                html += f'''
                <div class="prices">
                    <div class="price-box">
                        <div class="price-label">ENTRY</div>
                        <div class="price-value">{entry:.2f}</div>
                    </div>
                    <div class="price-box">
                        <div class="price-label">STOP</div>
                        <div class="price-value">{stop:.2f}</div>
                    </div>
                    <div class="price-box">
                        <div class="price-label">TARGET</div>
                        <div class="price-value">{target:.2f}</div>
                    </div>
                </div>
                '''
                html += f'<div style="text-align:center;margin-top:8px;color:#888;">R:R 2:1 (Fixed) | $250 Risk</div>'
                
                # Position sizing box
                position = r.get('position_size', {})
                if position:
                    contracts = position.get('contracts', 1)
                    actual_risk = position.get('actual_risk', 250)
                    potential_profit = position.get('potential_profit', 500)
                    html += f'''
                    <div style="background:#1a2a3a;border:1px solid #2a4a6a;padding:12px;border-radius:8px;margin-top:12px;text-align:center;">
                        <div style="font-size:1.5rem;font-weight:bold;color:#00d4ff;">{contracts} contracts</div>
                        <div style="font-size:0.85rem;color:#888;margin-top:4px;">
                            Risk: <span style="color:#ff4466">${actual_risk:.0f}</span> → 
                            Profit: <span style="color:#00ff88">${potential_profit:.0f}</span>
                        </div>
                    </div>
                    '''
            
            # Criteria Status (NEW in v2.0)
            if all_criteria_met:
                html += '''
                <div style="background:#1a3a1a;border:2px solid #00ff88;padding:12px;border-radius:8px;margin-top:12px;text-align:center;">
                    <div style="font-size:1.1rem;font-weight:bold;color:#00ff88;">✅ ALL CRITERIA MET</div>
                    <div style="font-size:0.8rem;color:#aaffaa;margin-top:4px;">Trade Approved</div>
                </div>
                '''
            elif criteria_failed:
                html += '''
                <div style="background:#3a1a1a;border:2px solid #ff4444;padding:12px;border-radius:8px;margin-top:12px;">
                    <div style="font-size:0.9rem;font-weight:bold;color:#ff4444;margin-bottom:8px;">❌ CRITERIA NOT MET</div>
                '''
                for cf in criteria_failed:
                    html += f'<div style="font-size:0.8rem;color:#ffaaaa;">{cf}</div>'
                html += '</div>'
            
            if stay_reason:
                html += f'<div class="warning">🚫 {stay_reason}</div>'
            
            for w in warnings[:2]:
                html += f'<div class="warning">⚠️ {w}</div>'
            
            # Add entry instructions
            entry_instruction = r.get('entry_instruction', '')
            if entry_instruction and direction in ('LONG', 'SHORT') and all_criteria_met:
                html += f'''
                <div style="background:#1a2a1a;border:1px solid #2a4a2a;padding:12px;border-radius:8px;margin-top:12px;">
                    <div style="font-weight:bold;color:#00ff88;margin-bottom:8px;">📝 Entry Instructions</div>
                    <div style="font-size:0.9rem;white-space:pre-line;color:#aaffaa;">{entry_instruction}</div>
                </div>
                '''
        else:
            html += f'<div style="color:#888;margin-top:8px;">{message}</div>'
        
        html += '</div>'
    
    html += '''
        <a href="/analyze" class="btn">🔄 Refresh Analysis</a>
        <a href="/" class="btn" style="background:#333;">📊 Full Dashboard</a>
    </body>
    </html>
    '''
    
    return html


def run_analysis(ticker_symbol=None, send_alerts=False):
    """
    Run analysis and return results - SignalCrawler v2.0
    Now includes ORB bias, PDH/PDL level checking, and news filter
    """
    try:
        from database import TICKERS
        
        results = []
        tickers_to_analyze = [ticker_symbol.upper()] if ticker_symbol else list(TICKERS.keys())
        
        # Check for news blackout first
        is_news_blackout, news_event = check_news_blackout()
        
        # Get market levels tracker
        market_lvls = get_market_levels()
        
        for ticker in tickers_to_analyze:
            base_ticker = normalize_ticker(ticker)
            
            # Get candle data
            candles_1m = list(candle_storage["1m"].get(base_ticker, []))
            candles_5m = list(candle_storage["5m"].get(base_ticker, []))
            candles_15m = list(candle_storage["15m"].get(base_ticker, []))
            
            # Update market levels from candle data
            all_candles = candles_1m + candles_5m + candles_15m
            if all_candles:
                market_lvls.update_from_candles(ticker, all_candles)
            
            if len(candles_1m) < 10:
                results.append({
                    "ticker": ticker,
                    "status": "insufficient_data",
                    "message": f"Need more candles: {len(candles_1m)}/10"
                })
                continue
            
            # Run MTF analysis
            mtf_result = mtf_analyze(candles_15m, candles_5m, candles_1m, ticker=ticker)
            
            direction = mtf_result.get('direction', 'STAY_AWAY')
            confidence = mtf_result.get('confidence', 0)
            entry = mtf_result.get('entry')
            
            # Get market levels info
            levels_info = market_lvls.get_all_levels(ticker, entry)
            bias_info = levels_info.get('bias', {})
            
            # Check bias alignment and level safety
            bias_aligned = True
            level_safe = True
            criteria_met = []
            criteria_failed = []
            
            if direction in ('LONG', 'SHORT') and entry:
                # Check bias
                aligned, bias_reason = market_lvls.check_bias_alignment(ticker, direction, entry)
                if aligned:
                    criteria_met.append(f"✅ Bias: {bias_reason}")
                else:
                    criteria_failed.append(f"❌ Bias: {bias_reason}")
                    bias_aligned = False
                
                # Check level safety
                safe, level_reason = market_lvls.check_entry_safety(ticker, entry, direction)
                if safe:
                    criteria_met.append(f"✅ Levels: {level_reason}")
                else:
                    criteria_failed.append(f"❌ Levels: {level_reason}")
                    level_safe = False
                
                # Check confidence
                if confidence >= MIN_CONFIDENCE:
                    criteria_met.append(f"✅ Confidence: {confidence}% >= {MIN_CONFIDENCE}%")
                else:
                    criteria_failed.append(f"❌ Confidence: {confidence}% < {MIN_CONFIDENCE}%")
                
                # Check R:R
                rr = mtf_result.get('risk_reward', 0)
                if rr >= MIN_RISK_REWARD:
                    criteria_met.append(f"✅ R:R: {rr}:1 >= {MIN_RISK_REWARD}:1")
                else:
                    criteria_failed.append(f"❌ R:R: {rr}:1 < {MIN_RISK_REWARD}:1")
            
            all_criteria_met = len(criteria_failed) == 0 and confidence >= MIN_CONFIDENCE and direction in ('LONG', 'SHORT')
            
            # Get timeframe trends from MTF analysis
            tf_data = mtf_result.get('components', {}).get('timeframe', {})
            tf15 = tf_data.get('tf15', {})
            tf5 = tf_data.get('tf5', {})
            tf1 = tf_data.get('tf1', {})
            
            result = {
                "ticker": ticker,
                "direction": direction,
                "confidence": confidence,
                "entry": entry,
                "stop": mtf_result.get('stop'),
                "target": mtf_result.get('target'),
                "risk_reward": mtf_result.get('risk_reward'),
                "warnings": mtf_result.get('warnings', []),
                "stay_away_reason": mtf_result.get('stay_away_reason'),
                "entry_instruction": mtf_result.get('entry_instruction', ''),
                "position_size": mtf_result.get('position_size', {}),
                # Timeframe trends (15m, 5m, 1m)
                "tf15_trend": tf15.get('direction', '?'),
                "tf15_strength": tf15.get('strength', '?'),
                "tf5_trend": tf5.get('direction', '?'),
                "tf5_strength": tf5.get('strength', '?'),
                "tf1_trend": tf1.get('direction', '?'),
                "tf1_strength": tf1.get('strength', '?'),
                "alignment": tf_data.get('alignment', 'unknown'),
                # v2.0 additions
                "daily_bias": bias_info.get('bias', 'UNKNOWN'),
                "bias_reason": bias_info.get('reason', ''),
                "orb_high": levels_info.get('orb', {}).get('high'),
                "orb_low": levels_info.get('orb', {}).get('low'),
                "pdh": levels_info.get('pdh_pdl', {}).get('pdh'),
                "pdl": levels_info.get('pdh_pdl', {}).get('pdl'),
                "bias_aligned": bias_aligned,
                "level_safe": level_safe,
                "all_criteria_met": all_criteria_met and not is_news_blackout,
                "criteria_met": criteria_met,
                "criteria_failed": criteria_failed,
                # News filter status
                "news_blackout": is_news_blackout,
                "news_event": news_event.get('event') if news_event else None,
                "news_clear_in": news_event.get('minutes_until_clear') if news_event else None
            }
            
            # Add news blackout to criteria if active
            if is_news_blackout:
                result['criteria_failed'].append(f"🚫 News: {news_event['event']} - Clear in {news_event['minutes_until_clear']} min")
                result['all_criteria_met'] = False
            
            results.append(result)
            
            # Send Discord alert ONLY if ALL criteria are met (and no news blackout)
            if send_alerts and all_criteria_met and not is_news_blackout:
                # SMART COOLDOWN: Check if we should actually send this alert
                should_send, cooldown_reason = should_send_alert(ticker, direction, entry, confidence)
                
                if should_send:
                    signal = {
                        'direction': direction,
                        'confidence': confidence,
                        'entry': entry,
                        'stop': mtf_result.get('stop'),
                        'takeProfit': mtf_result.get('target'),
                        'rationale': mtf_result.get('rationale', '')
                    }
                    send_discord_alert(ticker, signal, mtf_result)
                    record_alert_sent(ticker, direction, entry, confidence)
                    add_log(f"📱 v2.0 Alert: {ticker} {direction} {confidence}% - {cooldown_reason}", "success")
                else:
                    add_log(f"🔇 Skipped alert: {ticker} {direction} {confidence}% - {cooldown_reason}", "info")
            elif send_alerts and direction in ('LONG', 'SHORT') and confidence >= MIN_CONFIDENCE:
                # Log why not alerted
                add_log(f"⚠️ {ticker} {direction} {confidence}% - Criteria failed: {', '.join(criteria_failed)}", "warning")
        
        return results
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return [{"error": str(e)}]


@app.route('/api/debug-signals', methods=['GET'])
def debug_signals():
    """Debug endpoint to see signal processing details"""
    recent = list(dashboard_stats.get("recent_signals", []))[:10]
    return jsonify({
        "recent_signals": recent,
        "webhook_count": dashboard_stats.get("webhook_count", 0),
        "signal_count": dashboard_stats.get("signal_count", 0),
        "min_confidence": MIN_CONFIDENCE,
        "min_risk_reward": MIN_RISK_REWARD,
        "discord_configured": bool(DISCORD_WEBHOOK_URL)
    })


@app.route('/api/check-outcomes', methods=['POST', 'GET'])
def api_check_outcomes():
    """Manually trigger outcome check for all pending trades"""
    try:
        from database import get_pending_signals
        from outcome_tracker import get_current_price, normalize_ticker
        
        pending = get_pending_signals()
        
        # Run the check
        updated = check_all_pending_outcomes()
        
        # Get debug info for remaining pending
        debug_info = []
        remaining_pending = get_pending_signals()
        for signal in remaining_pending[:10]:  # Limit to 10 for response
            ticker = signal['ticker']
            base_ticker = normalize_ticker(ticker)
            current_price = get_current_price(ticker)
            
            debug_info.append({
                'id': signal['id'],
                'ticker': ticker,
                'normalized': base_ticker,
                'direction': signal['direction'],
                'entry': signal['entry_price'],
                'stop': signal['stop_price'],
                'target': signal['target_price'],
                'current_price': current_price,
                'price_available': current_price is not None
            })
        
        return jsonify({
            "status": "success",
            "checked": len(pending),
            "updated": len(updated),
            "updates": updated,
            "remaining_pending": len(remaining_pending),
            "debug": debug_info
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/trade/<int:trade_id>/outcome', methods=['POST'])
def mark_trade_outcome(trade_id):
    """Manually mark a trade as WIN or LOSS"""
    try:
        from database import get_connection
        data = request.get_json(force=True, silent=True) or {}
        outcome = data.get('outcome', '').upper()
        
        if outcome not in ['WIN', 'LOSS']:
            return jsonify({"error": "Outcome must be WIN or LOSS"}), 400
        
        conn = get_connection()
        cursor = conn.cursor()
        
        # Get the trade to calculate P&L (column names: entry, stop, target)
        cursor.execute('SELECT entry, stop, target, direction FROM signal_recommendations WHERE id = ?', (trade_id,))
        trade = cursor.fetchone()
        
        if not trade:
            conn.close()
            return jsonify({"error": "Trade not found"}), 404
        
        entry = trade['entry'] or 0
        stop = trade['stop'] or 0
        target = trade['target'] or 0
        direction = (trade['direction'] or '').upper()
        
        # Calculate P&L based on outcome
        if outcome == 'WIN':
            if direction == 'LONG':
                pnl = target - entry
            else:
                pnl = entry - target
            exit_price = target
        else:  # LOSS
            if direction == 'LONG':
                pnl = stop - entry  # Negative
            else:
                pnl = entry - stop  # Negative
            exit_price = stop
        
        # Update the trade
        cursor.execute('''
            UPDATE signal_recommendations 
            SET outcome = ?, exit_price = ?, pnl_ticks = ?, exit_time = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (outcome, exit_price, pnl, trade_id))
        
        # Update strategy version stats
        cursor.execute(f'''
            UPDATE strategy_versions 
            SET {outcome.lower()}s = {outcome.lower()}s + 1,
                win_rate = CASE WHEN (wins + losses) > 0 
                           THEN ROUND(100.0 * wins / (wins + losses), 1) 
                           ELSE NULL END
            WHERE is_active = 1
        ''')
        
        conn.commit()
        conn.close()
        
        add_log(f"Trade #{trade_id} marked as {outcome} (P&L: {pnl:+.2f})", "success" if outcome == 'WIN' else "warning")
        return jsonify({"status": "success", "outcome": outcome, "pnl": pnl})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/trade/<int:trade_id>', methods=['DELETE'])
def delete_trade(trade_id):
    """Delete a trade (user didn't take it)"""
    try:
        from database import get_connection
        
        conn = get_connection()
        cursor = conn.cursor()
        
        # Delete the trade and its features
        cursor.execute('DELETE FROM signal_features WHERE signal_id = ?', (trade_id,))
        cursor.execute('DELETE FROM signal_recommendations WHERE id = ?', (trade_id,))
        
        conn.commit()
        conn.close()
        
        add_log(f"Trade #{trade_id} deleted", "info")
        return jsonify({"status": "success", "message": f"Trade #{trade_id} deleted"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/clear-database', methods=['POST'])
def clear_database():
    """Clear all signals and start fresh"""
    try:
        from database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        
        # Clear signals
        cursor.execute('DELETE FROM signal_recommendations')
        cursor.execute('DELETE FROM signal_features')
        cursor.execute('DELETE FROM daily_stats')
        
        # Reset strategy version stats
        cursor.execute('''
            UPDATE strategy_versions 
            SET signals_generated = 0, wins = 0, losses = 0, win_rate = NULL
        ''')
        
        conn.commit()
        conn.close()
        
        add_log("🗑️ Database cleared - fresh start!", "warning")
        return jsonify({"status": "success", "message": "Database cleared!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/test-discord', methods=['POST', 'GET'])
def test_discord():
    """Send a test Discord alert"""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    
    if not webhook_url:
        return jsonify({
            "error": "DISCORD_WEBHOOK_URL not configured",
            "hint": "Add DISCORD_WEBHOOK_URL to Railway Variables"
        }), 400
    
    # Validate URL format
    if not webhook_url.startswith("https://discord.com/api/webhooks/"):
        return jsonify({
            "error": "Invalid webhook URL format",
            "expected": "https://discord.com/api/webhooks/...",
            "got_prefix": webhook_url[:50] + "..." if len(webhook_url) > 50 else webhook_url
        }), 400
    
    test_signal = {
        'direction': 'LONG',
        'confidence': 85,
        'entry': 21500.25,
        'stop': 21490.00,
        'takeProfit': 21520.00,
        'rationale': '🧪 TEST ALERT - SignalCrawler is connected and working!'
    }
    
    try:
        # Direct test with detailed error
        payload = {
            "username": "SignalCrawler",
            "embeds": [{
                "title": "🧪 TEST - MNQ LONG",
                "description": "SignalCrawler is connected and working!",
                "color": 0x00ff00,
                "fields": [
                    {"name": "📊 Confidence", "value": "85%", "inline": True},
                    {"name": "📈 Entry", "value": "$21,500.25", "inline": True},
                    {"name": "🎯 Target", "value": "$21,520.00", "inline": True},
                ],
                "footer": {"text": "Test Alert from SignalCrawler"}
            }]
        }
        
        response = http_requests.post(webhook_url, json=payload, timeout=10)
        
        if response.status_code in [200, 204]:
            return jsonify({"status": "success", "message": "Test alert sent to Discord! Check your channel."})
        else:
            return jsonify({
                "error": f"Discord returned status {response.status_code}",
                "response": response.text[:200]
            }), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tickers', methods=['GET'])
def api_get_tickers():
    """Get all tickers (hardcoded)"""
    tickers = [
        {"symbol": sym, **data, "is_active": 1}
        for sym, data in TICKERS.items()
    ]
    return jsonify(tickers)


@app.route('/api/performance')
def get_performance():
    """Get performance statistics"""
    try:
        stats = get_performance_stats()
        tracking = get_tracking_status()
        stats['tracking'] = tracking
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========= APEX RULES API =========

@app.route('/api/apex/status')
def apex_status():
    """Get Apex Trader Funding rules status"""
    try:
        status = get_apex_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/apex/config', methods=['GET'])
def get_apex_config():
    """Get Apex configuration"""
    try:
        status = get_apex_status()
        return jsonify(status['config'])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/apex/config', methods=['POST'])
def set_apex_config():
    """Update Apex configuration"""
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        config = update_apex_config(data)
        add_log(f"Apex config updated: account_size=${config.get('account_size')}", "success")
        return jsonify({"status": "success", "config": config})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/apex/reset', methods=['POST'])
def reset_apex():
    """Reset Apex state (start fresh)"""
    try:
        state = reset_apex_state()
        add_log("Apex state reset to initial values", "warning")
        return jsonify({"status": "success", "state": state})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/apex/check')
def apex_check():
    """Quick check if trading is allowed"""
    try:
        blocked, reason = should_block_trading()
        return jsonify({
            "trading_allowed": not blocked,
            "blocked": blocked,
            "reason": reason
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========= NEWS FILTER API =========

@app.route('/api/news/status')
def news_status():
    """Get current news blackout status"""
    try:
        status = get_news_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/news/upcoming')
def news_upcoming():
    """Get upcoming high-impact events"""
    try:
        days = request.args.get('days', 7, type=int)
        events = get_upcoming_events(days_ahead=days)
        return jsonify({"events": events})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========= ANALYTICS API =========

@app.route('/api/analytics')
def get_analytics():
    """Get full analytics data"""
    try:
        analytics = get_full_analytics()
        return jsonify(analytics)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/winrate')
def get_winrate_chart():
    """Get win rate chart data"""
    try:
        days = request.args.get('days', 30, type=int)
        data = get_win_rate_chart_data(days)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/pnl')
def get_pnl_chart():
    """Get P&L chart data"""
    try:
        days = request.args.get('days', 30, type=int)
        data = get_pnl_chart_data(days)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/tickers')
def get_tickers_analytics():
    """Get ticker performance analytics"""
    try:
        data = get_ticker_performance()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/hourly')
def get_hourly_analytics():
    """Get hourly distribution analytics"""
    try:
        data = get_hourly_distribution()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/confidence')
def get_confidence_analytics():
    """Get confidence level performance"""
    try:
        data = get_confidence_performance()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========= AI TUNING API =========

@app.route('/api/tuning/summary')
def tuning_summary():
    """Get AI tuning optimization summary"""
    try:
        summary = get_optimization_summary()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tuning/apply', methods=['POST'])
def apply_tuning():
    """Apply AI tuning recommendations"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        conservative = data.get('conservative', True)
        
        result = auto_tune(apply_changes=True, conservative=conservative)
        
        if result.get('applied_changes'):
            add_log(f"AI Tuning applied: {result['applied_changes']}", "success")
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tuning/preview')
def preview_tuning():
    """Preview AI tuning recommendations without applying"""
    try:
        result = auto_tune(apply_changes=False, conservative=True)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tuning/history')
def tuning_history():
    """Get history of AI tuning actions"""
    try:
        history = get_tuning_history()
        return jsonify(history)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tuning/trend')
def performance_trend():
    """Get recent performance trend"""
    try:
        days = request.args.get('days', 14, type=int)
        trend = get_performance_trend(days)
        return jsonify(trend)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========= MANUAL SCAN API =========

@app.route('/api/scan/<ticker>', methods=['GET'])
def manual_scan(ticker):
    """
    Manually scan a ticker using Yahoo Finance data
    Useful for testing without waiting for TradingView webhooks
    """
    try:
        print(f"\n🔍 Manual scan requested for {ticker}")
        
        # Fetch data from Yahoo Finance
        yf_data = fetch_backup_data(ticker)
        
        candles_15m = yf_data.get('15m', [])
        candles_5m = yf_data.get('5m', [])
        candles_1m = yf_data.get('1m', [])
        
        if len(candles_1m) < 15 or len(candles_5m) < 10 or len(candles_15m) < 10:
            return jsonify({
                "error": "Insufficient data from Yahoo Finance",
                "data": {
                    "15m": len(candles_15m),
                    "5m": len(candles_5m),
                    "1m": len(candles_1m)
                }
            }), 400
        
        # Run MTF analysis
        result = mtf_analyze(candles_15m, candles_5m, candles_1m, ticker=ticker)
        
        # Log the result
        direction = result.get('direction', 'no_trade')
        confidence = result.get('confidence', 0)
        
        if direction != 'no_trade':
            add_log(f"📊 Manual scan: {ticker} {direction.upper()} {confidence}%", "info")
        
        return jsonify(result)
        
    except Exception as e:
        print(f"⚠️  Manual scan error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/candles/status', methods=['GET'])
def candle_status():
    """Get current candle history status"""
    status = {}
    for ticker in set(list(candle_storage["1m"].keys()) + ["MNQ", "MES", "MGC"]):
        status[ticker] = {
            "1m": len(candle_storage["1m"].get(ticker, [])),
            "5m": len(candle_storage["5m"].get(ticker, [])),
            "15m": len(candle_storage["15m"].get(ticker, []))
        }
    
    total_1m = sum(s["1m"] for s in status.values())
    ready = all(s["1m"] >= 50 and s["5m"] >= 3 for s in status.values() if s["1m"] > 0)
    
    return jsonify({
        "tickers": status,
        "total_candles": total_1m,
        "ready_for_analysis": ready,
        "history_file": os.path.exists(CANDLE_HISTORY_FILE)
    })


@app.route('/api/candles/save', methods=['POST'])
def save_candles():
    """Manually save candle history"""
    save_candle_history()
    return jsonify({"status": "saved"})


@app.route('/api/candles/clear', methods=['POST'])
def clear_candles():
    """Clear candle history (start fresh)"""
    from database import clear_all_candles
    
    # Clear memory
    for tf in ["1m", "5m", "15m"]:
        for ticker in candle_storage[tf]:
            candle_storage[tf][ticker].clear()
    
    # Clear JSON file
    if os.path.exists(CANDLE_HISTORY_FILE):
        os.remove(CANDLE_HISTORY_FILE)
    
    # Clear database
    clear_all_candles()
    
    add_log("Cleared all candle history", "warning")
    return jsonify({"status": "cleared"})


@app.route('/api/candles/db-status', methods=['GET'])
def candle_db_status():
    """Get candle database statistics"""
    try:
        counts = get_candle_counts()
        total = sum(sum(tf.values()) for tf in counts.values())
        return jsonify({
            "total_candles": total,
            "by_ticker": counts,
            "storage": "SQLite database"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/scan/all', methods=['GET'])
def scan_all_tickers():
    """Scan all tickers that have stored candle data"""
    try:
        results = []
        
        # Get all tickers that actually have data stored (from TradingView webhooks)
        stored_tickers = set()
        for tf in ["1m", "5m", "15m"]:
            for ticker in candle_storage[tf].keys():
                if len(candle_storage["1m"].get(ticker, [])) > 0:
                    stored_tickers.add(ticker)
        
        if not stored_tickers:
            return jsonify({"error": "No candle data stored yet", "results": []})
        
        for ticker in stored_tickers:
            print(f"\n🔍 Scanning {ticker}...")
            
            # Get stored candle data
            candles_1m = list(candle_storage["1m"].get(ticker, []))
            candles_5m = list(candle_storage["5m"].get(ticker, []))
            candles_15m = list(candle_storage["15m"].get(ticker, []))
            
            print(f"   Data: {len(candles_1m)} x 1m, {len(candles_5m)} x 5m, {len(candles_15m)} x 15m")
            
            if len(candles_1m) < 15 or len(candles_5m) < 3 or len(candles_15m) < 2:
                results.append({
                    "ticker": ticker,
                    "error": f"Insufficient data: {len(candles_1m)}x1m, {len(candles_5m)}x5m, {len(candles_15m)}x15m",
                    "direction": "no_trade",
                    "htf_bias": "NEUTRAL"
                })
                continue
            
            # Run MTF analysis
            result = mtf_analyze(candles_15m, candles_5m, candles_1m, ticker)
            results.append(result)
            
            # Log result
            direction = result.get('direction', 'no_trade')
            confidence = result.get('confidence', 0)
            htf_bias = result.get('htf_bias', 'NEUTRAL')
            print(f"   Result: {htf_bias} bias, {direction} @ {confidence}%")
            
            if direction != 'no_trade':
                add_log(f"📊 Scan: {ticker} {direction.upper()} {confidence}%", "success")
        
        return jsonify({
            "timestamp": dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "results": results,
            "signals": [r for r in results if r.get('direction') != 'no_trade']
        })
        
    except Exception as e:
        print(f"⚠️  Scan all error: {e}")
        return jsonify({"error": str(e)}), 500


# ========= TEST EMAIL =========

@app.route('/api/test-email', methods=['GET'])
def test_email():
    """Send a test email to verify email configuration"""
    if not EMAIL_USER or not EMAIL_PASS:
        return jsonify({"error": "Email not configured. Set EMAIL_USER and EMAIL_PASS environment variables."}), 400
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        
        msg = MIMEText(f"""
🎯 Prop Firm Scanner - Test Email

This is a test email to verify your alert system is working!

If you received this, your email alerts are configured correctly.

Scanner URL: https://web-production-23cc7.up.railway.app
Time: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

You will receive alerts like this when the scanner finds valid trade signals.
        """)
        msg['Subject'] = "🎯 Test Alert - Prop Firm Scanner"
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_TO
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        
        return jsonify({"status": "success", "message": f"Test email sent to {EMAIL_TO}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========= AI COACH API =========

@app.route('/api/coach/analyze', methods=['POST'])
def coach_analyze():
    """Run full AI coach analysis"""
    try:
        result = run_coach_analysis()
        
        # Auto-add suggestions to pending queue
        if result.get('status') == 'success' and result.get('suggestions'):
            added = add_suggestions(result['suggestions'])
            result['suggestions_added'] = added
            add_log(f"Coach analyzed: {len(result['suggestions'])} suggestions, {added} new", "info")
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/coach/suggestions')
def coach_suggestions():
    """Get pending suggestions"""
    try:
        suggestions = get_pending_suggestions()
        stats = get_suggestion_stats()
        return jsonify({
            "suggestions": suggestions,
            "stats": stats
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/coach/approve/<suggestion_id>', methods=['POST'])
def coach_approve(suggestion_id):
    """Approve a suggestion"""
    try:
        result = approve_suggestion(suggestion_id, apply_change=True)
        
        if result.get('status') == 'success':
            suggestion = result.get('suggestion', {})
            add_log(f"✅ Approved: {suggestion.get('title', 'Unknown')}", "success")
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/coach/reject/<suggestion_id>', methods=['POST'])
def coach_reject(suggestion_id):
    """Reject a suggestion"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        reason = data.get('reason')
        
        result = reject_suggestion(suggestion_id, reason)
        
        if result.get('status') == 'success':
            suggestion = result.get('suggestion', {})
            add_log(f"❌ Rejected: {suggestion.get('title', 'Unknown')}", "warning")
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/coach/undo/<suggestion_id>', methods=['POST'])
def coach_undo(suggestion_id):
    """Undo an approved suggestion"""
    try:
        result = undo_suggestion(suggestion_id)
        
        if result.get('status') == 'success':
            add_log(f"↩️ Undone suggestion changes", "warning")
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/coach/history')
def coach_history():
    """Get suggestion history"""
    try:
        limit = request.args.get('limit', 50, type=int)
        history = get_suggestion_history(limit)
        return jsonify(history)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/coach/insights')
def coach_insights():
    """Get quick insights"""
    try:
        insights = get_coach_insights()
        return jsonify(insights)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/coach/impact/<suggestion_id>')
def coach_impact(suggestion_id):
    """Measure impact of an approved suggestion"""
    try:
        result = measure_suggestion_impact(suggestion_id)
        return jsonify(result if result else {"status": "not_found"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/coach/prompt')
def coach_prompt():
    """Get current evolved prompt status"""
    try:
        status = get_prompt_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/coach/prompt/reset', methods=['POST'])
def coach_prompt_reset():
    """Reset prompt to base version"""
    try:
        reset_prompt()
        add_log("🔄 AI prompt reset to base version", "warning")
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/coach/regime')
def coach_regime():
    """Get current market regime"""
    try:
        regime = get_current_regime()
        guidance = get_regime_trading_guidance(regime.get('regime'))
        regime['guidance'] = guidance
        return jsonify(regime)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Main webhook endpoint for TradingView alerts
    
    Expected JSON from TradingView:
    {
        "ticker": "MNQ",
        "timeframe": "1m",
        "time": "2025-12-01 12:30:00",
        "open": 21450.25,
        "high": 21452.50,
        "low": 21448.00,
        "close": 21451.75,
        "volume": 1523
    }
    """
    try:
        # Force JSON parsing even without Content-Type header (TradingView doesn't send it)
        data = request.get_json(force=True, silent=True)
        
        if not data:
            return jsonify({"error": "No data received"}), 400
        
        ticker = data.get("ticker", "UNKNOWN")
        timeframe = data.get("timeframe", "1m")
        
        # Update dashboard stats
        dashboard_stats["webhook_count"] += 1
        add_log(f"Webhook received: {ticker} {timeframe}", "info")
        
        print(f"\n{'='*60}")
        print(f"🔔 WEBHOOK RECEIVED: {ticker} {timeframe}")
        print(f"{'='*60}")
        print(f"Data: {json.dumps(data, indent=2)}")
        
        # Store the candle - CONVERT TIME TO EST
        raw_time = data.get("time")
        est_timestamp = convert_to_est(raw_time)
        
        candle_data = {
            "time": est_timestamp,  # Now in EST!
            "open": float(data.get("open", 0)),
            "high": float(data.get("high", 0)),
            "low": float(data.get("low", 0)),
            "close": float(data.get("close", 0)),
            "volume": int(data.get("volume", 0))
        }
        
        print(f"   ⏰ Time: {raw_time} → EST: {est_timestamp}")
        
        store_candle(ticker, timeframe, candle_data)
        
        # Only analyze on 1m candle closes
        if timeframe == "1m":
            # Normalize ticker for consistent key lookup (MESZ2025 -> MES)
            raw_ticker = ticker.split(":")[0] if ":" in ticker else ticker
            base_ticker = normalize_ticker(raw_ticker)
            
            # Get TradingView webhook data
            candles_1m = list(candle_storage["1m"].get(base_ticker, []))
            candles_5m = list(candle_storage["5m"].get(base_ticker, []))
            candles_15m = list(candle_storage["15m"].get(base_ticker, []))
            
            # Show current data status (5m/15m are auto-aggregated from 1m)
            print(f"   📊 Data: {len(candles_1m)} x 1m → {len(candles_5m)} x 5m (auto), {len(candles_15m)} x 15m (auto)")
            
            # Final check - do we have enough data?
            # Need: 15 x 1m, 10 x 5m (50 x 1m), 10 x 15m (150 x 1m)
            # With aggregation: need ~150 x 1m candles for full MTF analysis
            
            min_1m_for_analysis = 50  # Minimum to start (10 x 5m candles)
            
            if len(candles_1m) < min_1m_for_analysis:
                remaining = min_1m_for_analysis - len(candles_1m)
                print(f"⏳ Building history... {len(candles_1m)}/{min_1m_for_analysis} candles (~{remaining} min remaining)")
                return jsonify({"status": "stored", "message": f"Building history: {len(candles_1m)}/{min_1m_for_analysis}"}), 200
            
            if len(candles_5m) < 3:
                print(f"⏳ Building 5m candles... ({len(candles_5m)} available, need 3)")
                return jsonify({"status": "stored", "message": "Aggregating 5m candles..."}), 200
            
            if len(candles_15m) < 2:
                print(f"⏳ Building 15m candles... ({len(candles_15m)} available, need 2)")
                return jsonify({"status": "stored", "message": "Aggregating 15m candles..."}), 200
            
            # Check if we should analyze (every N minutes, not every candle)
            now = dt.datetime.now()
            last_time = last_analysis_time.get(base_ticker)
            
            if last_time:
                elapsed = (now - last_time).total_seconds() / 60
                print(f"⏱️ {base_ticker}: Last analysis {elapsed:.1f} min ago (interval: {ANALYSIS_INTERVAL_MINUTES} min)")
                if elapsed < ANALYSIS_INTERVAL_MINUTES:
                    remaining = ANALYSIS_INTERVAL_MINUTES - elapsed
                    print(f"⏳ Skipping {base_ticker} - next analysis in {remaining:.1f} min")
                    return jsonify({"status": "stored", "message": f"Candle stored. Analysis in {remaining:.1f} min"}), 200
            else:
                print(f"⏱️ {base_ticker}: First analysis (no previous time)")
            
            # Update last analysis time
            last_analysis_time[base_ticker] = now
            print(f"⏱️ {base_ticker}: Analysis time set to {now.strftime('%H:%M:%S')}")
            
            print(f"\n📊 Running MTF Analysis on {ticker}...")
            print(f"   Data: {len(candles_15m)} x 15m, {len(candles_5m)} x 5m, {len(candles_1m)} x 1m")
            
            # Run rule-based MTF analysis
            mtf_result = mtf_analyze(candles_15m, candles_5m, candles_1m, ticker=ticker)
            
            direction = mtf_result.get('direction', 'no_trade')
            confidence = mtf_result.get('confidence', 0)
            htf_bias = mtf_result.get('htf_bias', 'NEUTRAL')
            
            print(f"\n📊 MTF Analysis Result:")
            print(f"   15m Bias: {htf_bias}")
            print(f"   Direction: {direction.upper()}")
            print(f"   Confidence: {confidence}%")
            print(f"   Setup Valid: {mtf_result.get('setup_valid')}")
            print(f"   Entry Valid: {mtf_result.get('entry_valid')}")
            if mtf_result.get('entry_type'):
                print(f"   Entry Type: {mtf_result.get('entry_type')}")
            
            # Convert MTF result to signal format
            entry_price = mtf_result.get('entry') or mtf_result.get('suggested_entry')
            stop_price = mtf_result.get('stop') or mtf_result.get('suggested_stop')
            target_price = mtf_result.get('target') or mtf_result.get('suggested_target')
            current_price = mtf_result.get('current_price') or entry_price
            
            signal = {
                'direction': direction,
                'confidence': confidence,
                'entry': entry_price,
                'stop': stop_price,
                'takeProfit': target_price,
                'currentPrice': current_price,
                'entryType': mtf_result.get('entry_type', 'MTF_CONFLUENCE'),
                'rationale': mtf_result.get('rationale', ''),
                'recentMomentum': 'bullish' if direction == 'long' else 'bearish' if direction == 'short' else 'neutral'
            }
            
            # Debug log
            print(f"   Entry: {entry_price}, Stop: {stop_price}, Target: {target_price}")
            
            # Store signal for dashboard
            signal_entry = {
                "time": est_time_str("%H:%M:%S"),
                "ticker": ticker,
                "direction": direction,
                "confidence": confidence,
                "entry": signal.get('entry'),
                "stop": signal.get('stop'),
                "target": signal.get('takeProfit'),
                "valid": False
            }
            
            if direction != "no_trade":
                # Update market levels from candle data (v2.0)
                market_lvls = get_market_levels()
                all_candles = candles_1m + candles_5m + candles_15m
                if all_candles:
                    market_lvls.update_from_candles(ticker, all_candles)
                
                # Validate signal with v2.0 criteria (includes bias + level checks)
                is_valid, reasons = validate_signal(signal, ticker)
                signal_entry["valid"] = is_valid
                
                print(f"\n🔍 SignalCrawler v2.0 Quality Check:")
                for reason in reasons:
                    print(f"   {reason}")
                
                # v2.0: Only alert when ALL criteria are met
                if is_valid and confidence >= MIN_CONFIDENCE:
                    print(f"\n✅ ALL CRITERIA MET: {ticker} {direction.upper()} {confidence}%")
                    
                    entry_price = signal.get('entry') or signal.get('currentPrice') or 0
                    
                    # SMART COOLDOWN: Check if we should actually send this alert
                    should_send, cooldown_reason = should_send_alert(ticker, direction.upper(), entry_price, confidence)
                    
                    if should_send:
                        # Send Discord alert for valid signals only
                        discord_signal = {
                            'direction': direction.upper(),
                            'confidence': confidence,
                            'entry': entry_price,
                            'stop': signal.get('stop') or 0,
                            'takeProfit': signal.get('takeProfit') or 0,
                            'rationale': signal.get('rationale', '')
                        }
                        
                        try:
                            send_discord_alert(ticker, discord_signal, mtf_result)
                            record_alert_sent(ticker, direction.upper(), entry_price, confidence)
                            print(f"📱 Alert sent: {cooldown_reason}")
                        except Exception as e:
                            print(f"⚠️ Discord failed: {e}")
                    else:
                        print(f"🔇 Alert skipped: {cooldown_reason}")
                elif confidence >= 70:
                    # Log rejected signals but don't alert
                    print(f"\n⚠️ CRITERIA NOT MET: {ticker} {direction.upper()} {confidence}%")
                    add_log(f"⛔ Criteria failed: {ticker} - {', '.join(r for r in reasons if '❌' in r)}", "warning")
                
                # Save valid signals to Trade Journal
                if is_valid:
                    # Check Apex rules
                    blocked, block_reason = should_block_trading()
                    if blocked:
                        print(f"🚫 BLOCKED BY APEX: {block_reason}")
                        add_log(f"🚫 BLOCKED: {ticker} - {block_reason}", "error")
                    else:
                        dashboard_stats["signal_count"] += 1
                        add_log(f"✅ VALID: {ticker} {direction.upper()} {confidence}%", "success")
                    
                    signal_to_save = {
                        'ticker': ticker,
                        'direction': direction,
                        'confidence': confidence,
                        'entry': signal.get('entry'),
                        'stop': signal.get('stop'),
                        'takeProfit': signal.get('takeProfit'),
                        'currentPrice': signal.get('currentPrice'),
                        'entryType': signal.get('entryType'),
                        'rationale': signal.get('rationale'),
                        'is_valid': True
                    }
                    signal_id = save_signal(signal_to_save)
                    print(f"📍 Signal #{signal_id} saved to Trade Journal")
                    send_email_alert(ticker, signal, reasons)
                else:
                    add_log(f"⛔ Rejected: {ticker} {direction.upper()} {confidence}%", "warning")
            else:
                print(f"   No trade recommended")
                add_log(f"📊 {ticker}: No trade ({confidence}%)", "info")
            
            # Add to recent signals
            dashboard_stats["recent_signals"].appendleft(signal_entry)
        
        return jsonify({"status": "success", "message": f"Processed {ticker} {timeframe}"}), 200
        
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/test', methods=['POST'])
def test_endpoint():
    """Test endpoint to manually trigger analysis"""
    try:
        data = request.get_json(force=True, silent=True)
        ticker = data.get("ticker", "MNQ")
        
        print(f"\n🧪 TEST: Analyzing {ticker}...")
        
        data_text = format_data_for_ai(ticker)
        signal = analyze_with_ai(data_text)
        
        if signal:
            is_valid, reasons = validate_signal(signal, ticker)
            
            return jsonify({
                "signal": signal,
                "valid": is_valid,
                "reasons": reasons
            }), 200
        else:
            return jsonify({"error": "AI analysis failed"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========= RUN SERVER =========
ngrok_public_url = None

def start_ngrok():
    """Start ngrok tunnel in background"""
    global ngrok_public_url
    if not NGROK_AVAILABLE:
        print("⚠️  ngrok not available - run manually: ngrok http 5055")
        return
    
    try:
        # Kill any existing ngrok processes
        ngrok.kill()
        time.sleep(1)
        
        # Start new tunnel
        tunnel = ngrok.connect(5055)
        ngrok_public_url = tunnel.public_url
        
        print("\n" + "="*60)
        print("🌐 NGROK TUNNEL ACTIVE")
        print("="*60)
        print(f"📡 Public URL: {ngrok_public_url}")
        print(f"🔗 Webhook URL: {ngrok_public_url}/webhook")
        print("="*60)
        print("\n👆 Copy the Webhook URL above into TradingView alerts!")
        
    except Exception as e:
        print(f"⚠️  ngrok failed: {e}")
        print("   Run manually: ngrok http 5055")


def open_browser():
    """Open dashboard in browser after short delay"""
    time.sleep(2)  # Wait for server to start
    webbrowser.open('http://localhost:5055')


if __name__ == '__main__':
    print("\n" + "="*60)
    print("🕷️ SIGNALCRAWLER v2.0 STARTING")
    print("="*60)
    print("📋 v2.0 Settings:")
    print(f"   • Min Confidence: {MIN_CONFIDENCE}%")
    print(f"   • Min R:R: {MIN_RISK_REWARD}:1")
    print(f"   • Risk per Trade: $250")
    print(f"   • PDH/PDL Buffer: {PDH_PDL_BUFFER} pts")
    print(f"   • Analysis Interval: {ANALYSIS_INTERVAL_MINUTES} min")
    print(f"   • ORB Bias Required: Yes")
    print(f"   • Level Safety Required: Yes")
    print(f"   • News Filter: Active (FOMC, CPI, NFP)")
    print("="*60)
    
    # Show upcoming news events
    from news_filter import get_upcoming_events
    upcoming = get_upcoming_events(days_ahead=7)
    if upcoming:
        print("📅 Upcoming High-Impact Events:")
        for evt in upcoming[:3]:
            print(f"   • {evt['date']} {evt['time']} - {evt['event']}")
    print("="*60)
    
    # Initialize database and start outcome checker
    print("\n📦 Initializing trade journal database...")
    init_database()
    
    # Load recent signals from database (so they persist across restarts)
    print("📊 Loading recent signals from database...")
    try:
        db_signals = get_recent_signals(limit=50)
        for sig in reversed(db_signals):  # Oldest first so newest ends up at front
            # Extract time from timestamp or time_of_day
            ts = sig.get('time_of_day') or sig.get('timestamp', '')
            time_str = ts[-8:] if len(ts) >= 8 else ts  # Get HH:MM:SS part
            
            signal_entry = {
                "time": time_str,  # Dashboard looks for "time" key
                "ticker": sig.get('ticker', ''),
                "direction": sig.get('direction', ''),
                "confidence": sig.get('confidence', 0),
                "entry": sig.get('entry_price'),
                "stop": sig.get('stop_price'),
                "target": sig.get('target_price'),
                "rationale": sig.get('rationale', ''),
                "valid": sig.get('outcome') != 'PENDING',  # Show valid status
                "outcome": sig.get('outcome', 'PENDING')
            }
            dashboard_stats["recent_signals"].appendleft(signal_entry)
        print(f"   Loaded {len(db_signals)} recent signals")
    except Exception as e:
        print(f"⚠️  Could not load recent signals: {e}")
    
    print("📊 Outcome tracking: MANUAL ONLY (use Check Outcomes button)")
    
    # Use PORT env var for cloud deployment, default to 5055 for local
    port = int(os.environ.get("PORT", 5055))
    
    # Check if running on Railway (skip ngrok)
    railway_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
    if railway_domain:
        print(f"\n☁️  RUNNING ON RAILWAY CLOUD")
        print(f"🌐 Dashboard: https://{railway_domain}")
        print(f"📡 Webhook: https://{railway_domain}/webhook")
    else:
        # Local development - ngrok is optional
        print("\n🏠 RUNNING LOCALLY")
        print(f"🎨 Dashboard: http://localhost:{port}")
        print(f"📡 Webhook: http://localhost:{port}/webhook")
        print(f"💡 For public webhook, run: ngrok http {port}")
        
        # Open browser automatically (local only)
        threading.Thread(target=open_browser, daemon=True).start()
    
    print(f"💊 Health: http://localhost:{port}/health")
    print("="*60 + "\n")
    
    # Run Flask (use_reloader=False to prevent double ngrok)
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

