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

# Auto ngrok tunnel
try:
    from pyngrok import ngrok
    NGROK_AVAILABLE = True
except ImportError:
    NGROK_AVAILABLE = False
    print("⚠️  pyngrok not installed - run: pip install pyngrok")

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import save_signal, get_recent_signals, get_performance_stats, init_database
from outcome_tracker import start_tracking, resume_pending_tracking, get_tracking_status
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

# ========= QUALITY FILTERS =========
MIN_CONFIDENCE = 70
MAX_PRICE_DRIFT_TICKS = 15
REQUIRE_MOMENTUM_ALIGNMENT = True
MIN_RISK_REWARD = 1.5
# ===================================

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
# Store recent candles in memory (last 100 1m, 50 5m, 30 15m)
candle_storage = {
    "1m": {},   # ticker -> deque of candles
    "5m": {},
    "15m": {}
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

def load_candle_history():
    """Load candle history from file on startup"""
    global candle_storage
    
    if not os.path.exists(CANDLE_HISTORY_FILE):
        print("📂 No candle history file found - starting fresh")
        return False
    
    try:
        with open(CANDLE_HISTORY_FILE, 'r') as f:
            data = json.load(f)
        
        total_loaded = 0
        for tf in ["1m", "5m", "15m"]:
            if tf in data:
                for ticker, candles in data[tf].items():
                    maxlen = 100 if tf == "1m" else 50 if tf == "5m" else 30
                    candle_storage[tf][ticker] = deque(candles, maxlen=maxlen)
                    total_loaded += len(candles)
        
        if total_loaded > 0:
            print(f"✅ Loaded {total_loaded} candles from history!")
            for tf in ["1m", "5m", "15m"]:
                for ticker, candles in candle_storage[tf].items():
                    if len(candles) > 0:
                        print(f"   {ticker}: {len(candle_storage['1m'].get(ticker, []))} x 1m, {len(candle_storage['5m'].get(ticker, []))} x 5m, {len(candle_storage['15m'].get(ticker, []))} x 15m")
                        break  # Only print once per ticker
            return True
        
    except Exception as e:
        print(f"⚠️  Error loading candle history: {e}")
    
    return False

# Initialize storage for each ticker
for ticker in ["MNQ", "MES", "MGC"]:
    candle_storage["1m"][ticker] = deque(maxlen=100)
    candle_storage["5m"][ticker] = deque(maxlen=50)
    candle_storage["15m"][ticker] = deque(maxlen=30)

# Load history from previous session
load_candle_history()

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
    """Store candle in memory"""
    base_ticker = ticker.split(":")[0] if ":" in ticker else ticker
    
    # Ensure ticker exists in storage
    if base_ticker not in candle_storage[timeframe]:
        maxlen = 100 if timeframe == "1m" else 50 if timeframe == "5m" else 30
        candle_storage[timeframe][base_ticker] = deque(maxlen=maxlen)
    
    candle_storage[timeframe][base_ticker].append(candle_data)
    print(f"  📊 Stored {timeframe} candle for {base_ticker} (total: {len(candle_storage[timeframe][base_ticker])})")
    
    # Auto-aggregate 1m candles into 5m and 15m
    if timeframe == "1m":
        aggregate_candles(base_ticker)
        
        # Auto-save every 5 candles (5 minutes)
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
        maxlen = 50 if target_tf == "5m" else 30
        candle_storage[target_tf][ticker] = deque(maxlen=maxlen)
    
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
    """Run quality checks on AI signal"""
    reasons = []
    
    direction = signal.get('direction', 'no_trade')
    confidence = signal.get('confidence', 0)
    entry = signal.get('entry')
    stop = signal.get('stop')
    target = signal.get('takeProfit')
    current_price = signal.get('currentPrice')
    
    # Check 1: Confidence
    if confidence < MIN_CONFIDENCE:
        reasons.append(f"❌ Confidence {confidence}% below threshold {MIN_CONFIDENCE}%")
        return False, reasons
    
    # Check 2: Direction
    if direction == "no_trade":
        reasons.append("⚠️  AI suggests no trade")
        return False, reasons
    
    # Check 3: Required fields
    if entry is None or stop is None or target is None or current_price is None:
        reasons.append("❌ Missing required price levels")
        return False, reasons
    
    # Check 4: R:R
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
    
    # Check 6: Momentum alignment
    if REQUIRE_MOMENTUM_ALIGNMENT:
        is_aligned, momentum_desc = check_momentum_alignment(ticker, direction)
        if not is_aligned:
            reasons.append(f"❌ Recent momentum conflicts: {momentum_desc}")
            return False, reasons
        reasons.append(f"✓ Momentum: {momentum_desc}")
    
    # All checks passed
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
        trades = get_recent_signals(limit=100)
        return jsonify(trades)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
        result = mtf_analyze(candles_15m, candles_5m, candles_1m, ticker)
        
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
    for tf in ["1m", "5m", "15m"]:
        for ticker in candle_storage[tf]:
            candle_storage[tf][ticker].clear()
    
    if os.path.exists(CANDLE_HISTORY_FILE):
        os.remove(CANDLE_HISTORY_FILE)
    
    return jsonify({"status": "cleared"})


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
        
        # Store the candle
        candle_data = {
            "time": data.get("time"),
            "open": float(data.get("open", 0)),
            "high": float(data.get("high", 0)),
            "low": float(data.get("low", 0)),
            "close": float(data.get("close", 0)),
            "volume": int(data.get("volume", 0))
        }
        
        store_candle(ticker, timeframe, candle_data)
        
        # Only analyze on 1m candle closes
        if timeframe == "1m":
            base_ticker = ticker.split(":")[0] if ":" in ticker else ticker
            
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
            
            print(f"\n📊 Running MTF Analysis on {ticker}...")
            print(f"   Data: {len(candles_15m)} x 15m, {len(candles_5m)} x 5m, {len(candles_1m)} x 1m")
            
            # Run rule-based MTF analysis
            mtf_result = mtf_analyze(candles_15m, candles_5m, candles_1m, ticker)
            
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
            signal = {
                'direction': direction,
                'confidence': confidence,
                'entry': mtf_result.get('entry'),
                'stop': mtf_result.get('stop'),
                'takeProfit': mtf_result.get('target'),
                'currentPrice': mtf_result.get('current_price'),
                'entryType': mtf_result.get('entry_type', 'MTF_CONFLUENCE'),
                'rationale': mtf_result.get('rationale', ''),
                'recentMomentum': 'bullish' if direction == 'long' else 'bearish' if direction == 'short' else 'neutral'
            }
            
            # Store signal for dashboard
            signal_entry = {
                "time": dt.datetime.now().strftime("%H:%M:%S"),
                "ticker": ticker,
                "direction": direction,
                "confidence": confidence,
                "entry": signal.get('entry'),
                "stop": signal.get('stop'),
                "target": signal.get('takeProfit'),
                "valid": False
            }
            
            if direction != "no_trade":
                # Validate signal
                is_valid, reasons = validate_signal(signal, ticker)
                signal_entry["valid"] = is_valid
                
                print(f"\n🔍 Quality Check:")
                for reason in reasons:
                    print(f"   {reason}")
                
                if is_valid:
                    # Check Apex rules before allowing trade
                    blocked, block_reason = should_block_trading()
                    if blocked:
                        print(f"\n🚫 TRADE BLOCKED BY APEX RULES: {block_reason}")
                        add_log(f"🚫 BLOCKED: {ticker} - {block_reason}", "error")
                        signal_entry["valid"] = False
                        is_valid = False
                    else:
                        print(f"\n✅ SIGNAL PASSED - SENDING ALERT")
                        dashboard_stats["signal_count"] += 1
                        add_log(f"✅ VALID SIGNAL: {ticker} {direction.upper()} {confidence}%", "success")
                    
                    # Save to database and start tracking
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
                    start_tracking(signal_id, signal_to_save)
                    print(f"📍 Signal #{signal_id} saved and tracking started")
                    
                    send_email_alert(ticker, signal, reasons)
                else:
                    print(f"\n⛔ SIGNAL REJECTED")
                    add_log(f"⛔ Rejected: {ticker} {direction.upper()} {confidence}%", "warning")
                    
                    # Save rejected signal too (for analysis)
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
                        'is_valid': False
                    }
                    save_signal(signal_to_save)
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
    print("🚀 TRADINGVIEW WEBHOOK SCANNER STARTING")
    print("="*60)
    print(f"Email Alerts: {ENABLE_EMAIL_ALERTS}")
    print(f"Min Confidence: {MIN_CONFIDENCE}%")
    print(f"Min R:R: {MIN_RISK_REWARD}:1")
    print(f"Momentum Check: {REQUIRE_MOMENTUM_ALIGNMENT}")
    print("="*60)
    
    # Initialize database and resume tracking
    print("\n📦 Initializing trade journal database...")
    init_database()
    print("📍 Resuming tracking for pending signals...")
    resume_pending_tracking()
    
    # Start ngrok tunnel
    print("\n🌐 Starting ngrok tunnel...")
    start_ngrok()
    
    # Open browser automatically
    print("\n🌐 Opening dashboard in browser...")
    threading.Thread(target=open_browser, daemon=True).start()
    
    print("\n🎨 DASHBOARD: http://localhost:5055")
    # Use PORT env var for cloud deployment, default to 5055 for local
    port = int(os.environ.get("PORT", 5055))
    
    print(f"📡 LOCAL WEBHOOK: http://localhost:{port}/webhook")
    print(f"💊 HEALTH: http://localhost:{port}/health")
    print("="*60 + "\n")
    
    # Run Flask (use_reloader=False to prevent double ngrok)
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

