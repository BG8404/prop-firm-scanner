"""
Enhanced Futures Scanner with AI Analysis
Polling-based scanner that fetches data from yfinance

Port: 5060 (for health check endpoint)
"""

import sys
import json
import time
import datetime as dt
import threading

import pandas as pd
import yfinance as yf
from flask import Flask, jsonify
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText

# ========= OPENAI CONFIG =========
# TODO: Move to environment variables for security
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL_NAME = "gpt-4o-mini"
client = OpenAI(api_key=OPENAI_API_KEY)
# =================================

# ========= SCANNER CONFIG =========
# Default values (can be overridden by settings.json)
TICKERS = ["MNQ=F", "MES=F", "MGC=F"]  # micro futures you want scanned
CHECK_EVERY_MINUTES = 1               # scan every 1 minute

# Run 24/7 including nights
ALWAYS_ON = True

# If ALWAYS_ON = False, restrict scanning to times below
ACTIVE_SESSIONS = [
    ("09:30", "12:00"),
    ("13:30", "16:00"),
    ("20:00", "23:00"),
]

# ========= QUALITY FILTERS =========
MIN_CONFIDENCE = 70              # Only alert on 70%+ confidence signals
MAX_PRICE_DRIFT_TICKS = 15       # Max distance between AI entry and current price
REQUIRE_MOMENTUM_ALIGNMENT = True  # Check last 3 candles align with direction
CHECK_VOLUME_SPIKE = True        # Flag unusual volume (selling/buying pressure)
MIN_RISK_REWARD = 2.0            # Minimum R:R ratio to consider trade


# ========= DYNAMIC SETTINGS =========
import os
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'settings.json')

def load_dynamic_settings():
    """Load settings from shared JSON file (updated by dashboard)"""
    global TICKERS, CHECK_EVERY_MINUTES, MIN_CONFIDENCE, MIN_RISK_REWARD
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                TICKERS = settings.get('tickers', TICKERS)
                CHECK_EVERY_MINUTES = settings.get('scan_interval', CHECK_EVERY_MINUTES)
                MIN_CONFIDENCE = settings.get('min_confidence', MIN_CONFIDENCE)
                MIN_RISK_REWARD = settings.get('min_risk_reward', MIN_RISK_REWARD)
                return settings
    except Exception as e:
        print(f"⚠️  Could not load settings: {e}")
    return None
# =========================================

# ========= PRODUCT SETTINGS =========
TICK_SIZES = {
    "MNQ=F": 0.25,
    "MES=F": 0.25,
    "MGC=F": 0.10,
    "M2K=F": 0.10,
    "MCL=F": 0.01,
    "NQ=F": 0.25,
    "ES=F": 0.25,
    "GC=F": 0.10,
    "CL=F": 0.01,
    "YM=F": 1.00,
}

MAX_TICKS = {
    "MNQ=F": 30,
    "MES=F": 20,
    "MGC=F": 40,
    "M2K=F": 50,
    "MCL=F": 70,
    "NQ=F": 30,
    "ES=F": 20,
    "GC=F": 40,
    "CL=F": 70,
    "YM=F": 80,
}
# ====================================

# ========= EMAIL ALERT CONFIG =========
# TODO: Move to environment variables for security
ENABLE_EMAIL_ALERTS = True

EMAIL_FROM = "wtgrello@gmail.com"
EMAIL_TO = "williamgrello@icloud.com"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_USER = "wtgrello@gmail.com"
EMAIL_PASS = "gzvl bttv yezg snoo"
# ======================================


# ========= ENHANCED SYSTEM PROMPT =========
SYSTEM_PROMPT = """
You are an advanced futures trading assistant specializing in MICRO futures contracts.
Your job is to analyze the provided 1-minute, 5-minute, and 15-minute OHLCV data and 
return ONE clear trade idea (long, short, or no_trade).

=====================================================================
INSTRUMENT SETTINGS (AUTO-DETECT BASED ON TICKER)
=====================================================================

Use the following tick sizes and typical stop-loss ranges:

Micro Nasdaq (MNQ=F):
- Tick size: 0.25  
- Typical SL: 12–30 ticks  
- Volatility: high  

Micro S&P (MES=F):
- Tick size: 0.25  
- Typical SL: 10–20 ticks  

Micro GOLD (MGC=F):
- Tick size: 0.10  
- Typical SL: 15–40 ticks  
- Strong London & NY session behavior  

Micro Crude Oil (MCL=F):
- Tick size: 0.01  
- Typical SL: 30–70 ticks  
- Extreme volatility  

=====================================================================
CRITICAL PRICE ACTION RULES
=====================================================================

ONLY suggest trades when ALL timeframes align:

1. **15m must show clear trend direction** - not choppy/ranging
2. **5m must show BOS + displacement in that direction**
3. **1m must show clean retracement** - not continued momentum against you
4. **Recent 1m candles (last 3-5) should support the direction:**
   - For LONG: Last 3 candles should NOT all be bearish closes
   - For SHORT: Last 3 candles should NOT all be bullish closes
5. **No conflicting signals** - if 1m momentum is opposite 15m trend, say NO_TRADE

WHEN TO SAY NO_TRADE:
- Choppy, overlapping candles (low momentum)
- Mixed signals across timeframes
- Price in the middle of range (no clear structure)
- Recent strong momentum AGAINST the proposed direction
- Weak volume on key moves
- Risk:Reward less than 2:1

BE CONSERVATIVE. It's better to skip 10 mediocre setups than take 1 bad trade.

=====================================================================
ENTRY TIMING INSTRUCTIONS
=====================================================================

DO NOT suggest entry at current price unless price is ACTIVELY at an ideal entry zone.

Instead, specify WHERE to enter based on price action structure:

LONG ENTRIES - Wait for pullback to:
- FVG (Fair Value Gap) fill on 1m/5m
- Previous swing low / demand zone
- 50% retracement of displacement move
- Order block / breaker block

SHORT ENTRIES - Wait for pullback to:
- FVG fill on 1m/5m  
- Previous swing high / supply zone
- 50% retracement of displacement move
- Order block / breaker block

ENTRY TYPES:
1. "IMMEDIATE" - Price is at ideal entry zone NOW, all structure aligns
2. "WAIT_FOR_PULLBACK" - Price has moved away, specify exact pullback level
3. "WAIT_FOR_BREAKOUT" - Waiting for break + retest of key level

Always specify the EXACT price level to wait for, not just "wait for pullback"

=====================================================================
CONFIDENCE SCORE (BE STRICT)
=====================================================================

0–20 = no trade / chop  
21–40 = weak idea, skip it
41–60 = moderate, probably skip
61–75 = good setup, tradeable if patient
76–90 = high probability, strong setup
91–100 = A+ textbook setup, rare

Most scans should return 0-60 confidence. Only exceptional setups deserve 70+.

=====================================================================
OUTPUT FORMAT (STRICT JSON ONLY)
=====================================================================

{
  "direction": "long" | "short" | "no_trade",
  "confidence": 0-100,
  "entryType": "IMMEDIATE" | "WAIT_FOR_PULLBACK" | "WAIT_FOR_BREAKOUT",
  "entry": number,
  "currentPrice": number,
  "stop": number,
  "takeProfit": number,
  "rationale": "Explain timeframe alignment, structure, and why this specific entry",
  "entryInstructions": "Detailed entry guidance with specific levels and reasoning",
  "recentMomentum": "bullish" | "bearish" | "neutral",
  "volumeProfile": "high" | "normal" | "low"
}
"""
# ==================================


# ========= FLASK APP (Health Check) =========
app = Flask(__name__)
scanner_stats = {
    "status": "stopped",
    "last_scan": None,
    "tickers": TICKERS,
    "alerts_sent": 0,
    "scans_completed": 0
}


@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        "status": scanner_stats["status"],
        "scanner": "Enhanced Futures Scanner",
        "port": 5060,
        "last_scan": scanner_stats["last_scan"],
        "tickers": scanner_stats["tickers"],
        "alerts_sent": scanner_stats["alerts_sent"],
        "scans_completed": scanner_stats["scans_completed"],
        "config": {
            "check_interval_minutes": CHECK_EVERY_MINUTES,
            "min_confidence": MIN_CONFIDENCE,
            "min_risk_reward": MIN_RISK_REWARD,
            "always_on": ALWAYS_ON
        }
    })
# ============================================


# ========= UTILITIES =========
def get_tick_size(ticker):
    return TICK_SIZES.get(ticker, 0.25)


def get_max_ticks(ticker):
    return MAX_TICKS.get(ticker, 999)


def round_to_tick(price, tick):
    return round(price / tick) * tick


# ========= DATA FETCHING =========
def fetch_futures_data(ticker, period="5d"):
    """
    Fetch futures data for multiple timeframes
    Returns dict with 1m, 5m, 15m dataframes
    """
    try:
        # Fetch 1-minute data (last 7 days to ensure we have enough)
        data_1m = yf.download(ticker, period="7d", interval="1m", progress=False)
        
        # Fetch 5-minute data
        data_5m = yf.download(ticker, period="5d", interval="5m", progress=False)
        
        # Fetch 15-minute data
        data_15m = yf.download(ticker, period="5d", interval="15m", progress=False)
        
        if data_1m.empty or data_5m.empty or data_15m.empty:
            print(f"⚠️  No data returned for {ticker}")
            return None
            
        # Get last 100 candles for each timeframe
        data_1m = data_1m.tail(100)
        data_5m = data_5m.tail(50)
        data_15m = data_15m.tail(30)
        
        print(f"✓ Fetched {len(data_1m)} 1m candles, {len(data_5m)} 5m candles, {len(data_15m)} 15m candles")
        
        return {
            "1m": data_1m,
            "5m": data_5m,
            "15m": data_15m
        }
        
    except Exception as e:
        print(f"❌ Error fetching data for {ticker}: {e}")
        return None


def format_data_for_ai(data_dict, ticker):
    """
    Format multi-timeframe data into text for AI analysis
    """
    if not data_dict:
        return None
    
    tick_size = get_tick_size(ticker)
    max_ticks = get_max_ticks(ticker)
    
    output = f"TICKER: {ticker}\n"
    output += f"TICK_SIZE: {tick_size}\n"
    output += f"MAX_STOP_TICKS: {max_ticks}\n\n"
    
    for timeframe in ["15m", "5m", "1m"]:
        df = data_dict[timeframe].copy()
        
        # Flatten multi-level columns if they exist
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        output += f"=== {timeframe.upper()} DATA (last 10 candles) ===\n"
        
        # Get last 10 candles
        recent = df.tail(10)
        
        for idx, row in recent.iterrows():
            try:
                timestamp = idx.strftime("%Y-%m-%d %H:%M")
                o = float(row['Open'])
                h = float(row['High'])
                l = float(row['Low'])
                c = float(row['Close'])
                v = int(row['Volume']) if pd.notna(row['Volume']) else 0
                
                output += f"{timestamp} | O:{o:.2f} H:{h:.2f} L:{l:.2f} C:{c:.2f} V:{v}\n"
            except Exception as e:
                print(f"⚠️  Skipping malformed candle: {e}")
                continue
        
        output += "\n"
    
    return output


# ========= QUALITY FILTERS =========
def check_momentum_alignment(data_1m, direction):
    """
    Check if recent 1m candles support the trade direction
    Returns: (is_aligned: bool, momentum_strength: str)
    """
    if data_1m is None or len(data_1m) < 3:
        return False, "insufficient_data"
    
    # Flatten columns if needed
    df = data_1m.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # Get last 3 candles
    recent = df.tail(3)
    
    bullish_count = 0
    bearish_count = 0
    
    for idx, row in recent.iterrows():
        close = float(row['Close'])
        open_price = float(row['Open'])
        
        if close > open_price:
            bullish_count += 1
        elif close < open_price:
            bearish_count += 1
    
    # Check alignment
    if direction == "long":
        if bearish_count == 3:
            return False, "strong_bearish_momentum"
        elif bearish_count == 2:
            return False, "weak_bearish_momentum"
        else:
            return True, "aligned"
    
    elif direction == "short":
        if bullish_count == 3:
            return False, "strong_bullish_momentum"
        elif bullish_count == 2:
            return False, "weak_bullish_momentum"
        else:
            return True, "aligned"
    
    return True, "neutral"


def check_volume_profile(data_1m):
    """
    Detect unusual volume (potential selling/buying pressure)
    Returns: (volume_level: str, avg_volume: float)
    """
    if data_1m is None or len(data_1m) < 10:
        return "unknown", 0
    
    df = data_1m.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # Get last 10 candles volume
    recent = df.tail(10)
    volumes = [float(row['Volume']) for idx, row in recent.iterrows() if pd.notna(row['Volume'])]
    
    if len(volumes) < 5:
        return "unknown", 0
    
    avg_volume = sum(volumes) / len(volumes)
    last_candle_volume = volumes[-1]
    
    # Check if last candle has unusual volume
    if last_candle_volume > avg_volume * 2:
        return "high", avg_volume
    elif last_candle_volume < avg_volume * 0.5:
        return "low", avg_volume
    else:
        return "normal", avg_volume


def check_price_drift(current_price, entry_price, tick_size, max_ticks):
    """
    Check if current price has drifted too far from AI's suggested entry
    Returns: (is_valid: bool, drift_ticks: float)
    """
    drift = abs(current_price - entry_price)
    drift_ticks = drift / tick_size
    
    is_valid = drift_ticks <= max_ticks
    
    return is_valid, drift_ticks


def calculate_risk_reward(entry, stop, target):
    """
    Calculate risk:reward ratio
    Returns: float (reward/risk ratio)
    """
    try:
        risk = abs(float(entry) - float(stop))
        reward = abs(float(target) - float(entry))
        
        if risk == 0:
            return 0
        
        return reward / risk
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


def validate_signal(signal, data_dict, ticker):
    """
    Run all quality checks on the AI signal
    Returns: (is_valid: bool, reasons: list)
    """
    reasons = []
    
    direction = signal.get('direction', 'no_trade')
    confidence = signal.get('confidence', 0)
    entry = signal.get('entry')
    stop = signal.get('stop')
    target = signal.get('takeProfit')
    current_price = signal.get('currentPrice')
    
    # Check 1: Confidence threshold
    if confidence < MIN_CONFIDENCE:
        reasons.append(f"❌ Confidence {confidence}% below threshold {MIN_CONFIDENCE}%")
        return False, reasons
    
    # Check 2: Direction must be long or short
    if direction == "no_trade":
        reasons.append("⚠️  AI suggests no trade")
        return False, reasons
    
    # Check 3: Required fields
    if entry is None or stop is None or target is None or current_price is None:
        reasons.append("❌ Missing required price levels")
        return False, reasons
    
    # Check 4: Risk:Reward ratio
    rr = calculate_risk_reward(entry, stop, target)
    if rr < MIN_RISK_REWARD:
        reasons.append(f"❌ R:R {rr:.2f} below minimum {MIN_RISK_REWARD}")
        return False, reasons
    
    # Check 5: Price drift
    tick_size = get_tick_size(ticker)
    is_valid_drift, drift_ticks = check_price_drift(
        float(current_price), 
        float(entry), 
        tick_size, 
        MAX_PRICE_DRIFT_TICKS
    )
    
    if not is_valid_drift:
        reasons.append(f"❌ Price drifted {drift_ticks:.1f} ticks from entry (max {MAX_PRICE_DRIFT_TICKS})")
        return False, reasons
    
    # Check 6: Momentum alignment
    if REQUIRE_MOMENTUM_ALIGNMENT:
        is_aligned, momentum_desc = check_momentum_alignment(data_dict['1m'], direction)
        if not is_aligned:
            reasons.append(f"❌ Recent 1m momentum conflicts: {momentum_desc}")
            return False, reasons
        else:
            reasons.append(f"✓ Momentum aligned: {momentum_desc}")
    
    # Check 7: Volume profile
    if CHECK_VOLUME_SPIKE:
        volume_level, avg_vol = check_volume_profile(data_dict['1m'])
        if volume_level == "high" and direction == "long":
            reasons.append(f"⚠️  High volume spike detected (possible distribution)")
        elif volume_level == "low":
            reasons.append(f"⚠️  Low volume (weak conviction)")
        else:
            reasons.append(f"✓ Volume: {volume_level}")
    
    # All checks passed
    reasons.append(f"✓ Confidence: {confidence}%")
    reasons.append(f"✓ R:R: {rr:.2f}")
    reasons.append(f"✓ Price drift: {drift_ticks:.1f} ticks")
    
    return True, reasons
# ==========================================


# ========= AI ANALYSIS =========
def analyze_with_ai(data_text):
    """
    Send data to OpenAI for analysis
    """
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
        
        result = json.loads(response.choices[0].message.content)
        return result
        
    except Exception as e:
        print(f"❌ AI Analysis Error: {e}")
        return None


# ========= EMAIL ALERTS =========
def send_email_alert(ticker, trade_signal, validation_reasons):
    """
    Send email alert for trade signal
    """
    global scanner_stats
    
    if not ENABLE_EMAIL_ALERTS:
        return
    
    try:
        direction = trade_signal['direction'].upper()
        confidence = trade_signal['confidence']
        entry_type = trade_signal.get('entryType', 'UNKNOWN')
        current_price = trade_signal.get('currentPrice', 'N/A')
        entry = trade_signal.get('entry', 'N/A')
        stop = trade_signal.get('stop', 'N/A')
        tp = trade_signal.get('takeProfit', 'N/A')
        rationale = trade_signal.get('rationale', '')
        entry_instructions = trade_signal.get('entryInstructions', 'No specific instructions provided')
        
        # Calculate R:R if possible
        rr_text = ""
        if entry != 'N/A' and stop != 'N/A' and tp != 'N/A':
            try:
                risk = abs(float(entry) - float(stop))
                reward = abs(float(tp) - float(entry))
                if risk > 0:
                    rr_ratio = reward / risk
                    rr_text = f"\n💰 Risk:Reward Ratio: 1:{rr_ratio:.2f}"
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        
        # Format validation checks
        validation_text = "\n".join(validation_reasons)
        
        subject = f"🚨 {ticker} {direction} ({confidence}% • {entry_type})"
        
        body = f"""
🎯 FUTURES SCANNER ALERT
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
            
        print(f"📧 Email alert sent for {ticker}")
        scanner_stats["alerts_sent"] += 1
        
    except Exception as e:
        print(f"❌ Email error: {e}")


# ========= TIME CHECKS =========
def is_in_active_session():
    """
    Check if current time is within active trading sessions
    """
    if ALWAYS_ON:
        return True
    
    now = dt.datetime.now().time()
    
    for start_str, end_str in ACTIVE_SESSIONS:
        start = dt.datetime.strptime(start_str, "%H:%M").time()
        end = dt.datetime.strptime(end_str, "%H:%M").time()
        
        if start <= now <= end:
            return True
    
    return False


# ========= MAIN SCANNER LOOP =========
def run_scanner():
    """
    Main scanner loop with enhanced filtering
    """
    global scanner_stats
    
    print("=" * 60)
    print("🔥 ENHANCED FUTURES SCANNER")
    print("=" * 60)
    print(f"Tickers: {TICKERS}")
    print(f"Scan Interval: {CHECK_EVERY_MINUTES} minutes")
    print(f"24/7 Mode: {ALWAYS_ON}")
    print(f"Email Alerts: {ENABLE_EMAIL_ALERTS}")
    print(f"\n📊 QUALITY FILTERS ACTIVE:")
    print(f"  • Min Confidence: {MIN_CONFIDENCE}%")
    print(f"  • Max Price Drift: {MAX_PRICE_DRIFT_TICKS} ticks")
    print(f"  • Momentum Alignment: {REQUIRE_MOMENTUM_ALIGNMENT}")
    print(f"  • Volume Check: {CHECK_VOLUME_SPIKE}")
    print(f"  • Min R:R: {MIN_RISK_REWARD}:1")
    print("=" * 60)
    
    scanner_stats["status"] = "running"
    
    while True:
        try:
            # Reload settings from dashboard (if changed)
            load_dynamic_settings()
            
            if not is_in_active_session():
                print(f"⏸️  Outside active sessions. Next check in {CHECK_EVERY_MINUTES} min...")
                time.sleep(CHECK_EVERY_MINUTES * 60)
                continue
            
            print(f"\n🔍 SCAN STARTED: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Settings: interval={CHECK_EVERY_MINUTES}min, confidence={MIN_CONFIDENCE}%, tickers={TICKERS}")
            print("-" * 60)
            
            scanner_stats["last_scan"] = dt.datetime.now().isoformat()
            
            for ticker in TICKERS:
                print(f"\nAnalyzing {ticker}...")
                
                # Fetch data
                data_dict = fetch_futures_data(ticker)
                if not data_dict:
                    continue
                
                # Format for AI
                data_text = format_data_for_ai(data_dict, ticker)
                if not data_text:
                    continue
                
                # Get AI analysis
                signal = analyze_with_ai(data_text)
                if not signal:
                    continue
                
                # Display result
                direction = signal.get('direction', 'no_trade')
                confidence = signal.get('confidence', 0)
                entry_type = signal.get('entryType', 'UNKNOWN')
                
                print(f"\n📊 {ticker} AI Analysis:")
                print(f"   Direction: {direction.upper()}")
                print(f"   Confidence: {confidence}%")
                print(f"   Entry Type: {entry_type}")
                
                if direction != "no_trade":
                    # Run quality filters
                    is_valid, reasons = validate_signal(signal, data_dict, ticker)
                    
                    print(f"\n🔍 Quality Check Results:")
                    for reason in reasons:
                        print(f"   {reason}")
                    
                    if is_valid:
                        print(f"\n✅ SIGNAL PASSED ALL FILTERS - ALERTING")
                        print(f"   Current Price: {signal.get('currentPrice', 'N/A')}")
                        print(f"   Entry: {signal.get('entry', 'N/A')}")
                        print(f"   Stop: {signal.get('stop', 'N/A')}")
                        print(f"   Target: {signal.get('takeProfit', 'N/A')}")
                        print(f"   Rationale: {signal.get('rationale', '')}")
                        print(f"   📍 Entry Instructions: {signal.get('entryInstructions', 'No specific instructions')}")
                        
                        # Send email alert
                        send_email_alert(ticker, signal, reasons)
                    else:
                        print(f"\n⛔ SIGNAL REJECTED - Did not pass quality filters")
                else:
                    print(f"   AI recommends: NO TRADE")
                
                # Small delay between tickers
                time.sleep(2)
            
            scanner_stats["scans_completed"] += 1
            
            print("-" * 60)
            print(f"✓ Scan complete. Next scan in {CHECK_EVERY_MINUTES} minutes...\n")
            
            # Wait for next scan
            time.sleep(CHECK_EVERY_MINUTES * 60)
            
        except KeyboardInterrupt:
            print("\n\n⚠️  Scanner stopped by user")
            scanner_stats["status"] = "stopped"
            break
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
            print(f"Retrying in {CHECK_EVERY_MINUTES} minutes...")
            time.sleep(CHECK_EVERY_MINUTES * 60)


def start_flask_server():
    """Start Flask in a separate thread"""
    app.run(host='0.0.0.0', port=5060, debug=False, use_reloader=False)


# ========= RUN =========
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🚀 FUTURES SCANNER STARTING")
    print("=" * 60)
    print("🌐 Health check endpoint: http://localhost:5060")
    print("=" * 60 + "\n")
    
    # Start Flask server in background thread for health checks
    flask_thread = threading.Thread(target=start_flask_server, daemon=True)
    flask_thread.start()
    
    # Run the main scanner loop
    run_scanner()

