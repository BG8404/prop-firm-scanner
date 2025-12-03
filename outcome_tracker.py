"""
Outcome Tracker
Monitors price to determine if signals hit TP (win) or SL (loss)
Integrates with Apex Trader Funding rules for P&L tracking

Uses candle data from webhooks (preferred) or yfinance as fallback
"""

import threading
import time
from datetime import datetime, timedelta

# Import database functions
from database import get_pending_signals, update_signal_outcome, load_candles

# Import Apex rules for trade result tracking
try:
    from apex_rules import record_trade_result, check_all_rules
    APEX_ENABLED = True
except ImportError:
    APEX_ENABLED = False
    print("⚠️  Apex rules module not available")

# Tracking state
tracking_active = True
tracked_signals = {}

# Reference to candle storage (will be set by scanner)
candle_storage = None


def set_candle_storage(storage):
    """Set reference to candle storage from main scanner"""
    global candle_storage
    candle_storage = storage


def normalize_ticker(ticker):
    """Normalize ticker symbol - strip contract months like Z2025, G2026, etc."""
    import re
    base = ticker.replace('=F', '').upper()
    if ':' in base:
        base = base.split(':')[-1]
    # Remove contract month/year suffixes like Z2025, G2026, H2025, etc.
    base = re.sub(r'[FGHJKMNQUVXZ]\d{4}$', '', base)
    return base


def get_current_price(ticker):
    """
    Get current price for a ticker
    Priority: 1) Live candle storage, 2) Database candles, 3) yfinance fallback
    """
    # Normalize ticker (MNQZ2025 -> MNQ)
    base_ticker = normalize_ticker(ticker)
    
    # Try 1: Get from live candle storage (most recent)
    if candle_storage:
        try:
            candles_1m = candle_storage.get('1m', {}).get(base_ticker, [])
            if candles_1m and len(candles_1m) > 0:
                return float(candles_1m[-1].get('close', 0))
        except Exception:
            pass
    
    # Try 2: Get from database
    try:
        candles = load_candles(base_ticker, '1m', limit=1)
        if candles and len(candles) > 0:
            return float(candles[-1].get('close', 0))
    except Exception:
        pass
    
    # yfinance fallback disabled - causes SSL issues and crashes
    # Price must come from webhook candles or database
    return None


def check_signal_outcome(signal):
    """
    Check if a signal has hit its target or stop
    Returns: ('win', price, pnl) or ('loss', price, pnl) or (None, None, None)
    """
    ticker = signal['ticker']
    direction = signal['direction']
    entry = signal['entry_price']
    stop = signal['stop_price']
    target = signal['target_price']
    
    if not all([entry, stop, target]):
        return None, None, None
    
    current_price = get_current_price(ticker)
    if current_price is None:
        return None, None, None
    
    # Normalize direction to lowercase for comparison
    direction_lower = direction.lower() if direction else ''
    
    # Check if target or stop hit
    if direction_lower == 'long':
        if current_price >= target:
            pnl = target - entry
            return 'WIN', current_price, pnl
        elif current_price <= stop:
            pnl = stop - entry  # Negative
            return 'LOSS', current_price, pnl
    
    elif direction_lower == 'short':
        if current_price <= target:
            pnl = entry - target
            return 'WIN', current_price, pnl
        elif current_price >= stop:
            pnl = entry - stop  # Negative
            return 'LOSS', current_price, pnl
    
    return None, None, None


def track_signal(signal_id, signal_data, max_duration_hours=24):
    """
    Track a single signal until it hits TP, SL, or times out
    Runs in a separate thread
    """
    start_time = datetime.now()
    max_duration = timedelta(hours=max_duration_hours)
    check_interval = 30  # seconds
    
    ticker = signal_data.get('ticker', 'UNKNOWN')
    direction = signal_data.get('direction', 'no_trade')
    
    print(f"📍 Tracking signal #{signal_id}: {ticker} {direction.upper()}")
    
    while tracking_active:
        try:
            # Check if expired
            if datetime.now() - start_time > max_duration:
                print(f"⏰ Signal #{signal_id} expired (no TP/SL hit in {max_duration_hours}h)")
                update_signal_outcome(signal_id, 'DISCARDED', None, 0)  # Use DISCARDED for expired
                break
            
            # Build signal dict for checking
            signal = {
                'ticker': ticker,
                'direction': direction,
                'entry_price': signal_data.get('entry'),
                'stop_price': signal_data.get('stop'),
                'target_price': signal_data.get('target') or signal_data.get('takeProfit')
            }
            
            outcome, price, pnl = check_signal_outcome(signal)
            
            if outcome:
                emoji = '✅' if outcome == 'WIN' else '❌'
                print(f"{emoji} Signal #{signal_id} {outcome}: {ticker} @ {price:.2f} (P&L: {pnl:+.2f})")
                update_signal_outcome(signal_id, outcome, price, pnl)
                
                # Update Apex rules tracking
                if APEX_ENABLED:
                    try:
                        apex_result = record_trade_result(ticker, pnl)
                        if apex_result.get('alerts'):
                            for alert in apex_result['alerts']:
                                print(f"🚨 APEX ALERT: {alert['title']}")
                                print(f"   {alert['message']}")
                    except Exception as e:
                        print(f"⚠️  Error updating Apex tracking: {e}")
                
                break
            
            # Wait before next check
            time.sleep(check_interval)
            
        except Exception as e:
            print(f"⚠️  Error tracking signal #{signal_id}: {e}")
            time.sleep(check_interval)
    
    # Remove from tracked signals
    if signal_id in tracked_signals:
        del tracked_signals[signal_id]


def start_tracking(signal_id, signal_data):
    """Start tracking a signal in a background thread"""
    if signal_id in tracked_signals:
        return  # Already tracking
    
    thread = threading.Thread(
        target=track_signal,
        args=(signal_id, signal_data),
        daemon=True
    )
    tracked_signals[signal_id] = thread
    thread.start()


def resume_pending_tracking():
    """Resume tracking for any pending signals (on startup)"""
    pending = get_pending_signals()
    
    if pending:
        print(f"📍 Resuming tracking for {len(pending)} pending signals...")
        
        for signal in pending:
            signal_data = {
                'ticker': signal['ticker'],
                'direction': signal['direction'],
                'entry': signal['entry_price'],
                'stop': signal['stop_price'],
                'takeProfit': signal['target_price']
            }
            start_tracking(signal['id'], signal_data)


def stop_all_tracking():
    """Stop all tracking threads"""
    global tracking_active
    tracking_active = False
    print("🛑 Stopping all signal tracking...")


def get_tracking_status():
    """Get current tracking status"""
    return {
        'active': tracking_active,
        'tracking_count': len(tracked_signals),
        'signal_ids': list(tracked_signals.keys())
    }


def check_all_pending_outcomes():
    """
    Check ALL pending signals for outcomes - more reliable than threads.
    Returns list of updated signals.
    """
    pending = get_pending_signals()
    updated = []
    
    for signal in pending:
        try:
            outcome, price, pnl = check_signal_outcome(signal)
            
            if outcome:
                emoji = '✅' if outcome == 'WIN' else '❌'
                print(f"{emoji} Signal #{signal['id']} {outcome}: {signal['ticker']} @ {price:.2f} (P&L: {pnl:+.2f})")
                update_signal_outcome(signal['id'], outcome, price, pnl)
                
                updated.append({
                    'id': signal['id'],
                    'ticker': signal['ticker'],
                    'outcome': outcome,
                    'price': price,
                    'pnl': pnl
                })
                
                # Update Apex rules tracking
                if APEX_ENABLED:
                    try:
                        apex_result = record_trade_result(signal['ticker'], pnl)
                        if apex_result.get('alerts'):
                            for alert in apex_result['alerts']:
                                print(f"🚨 APEX ALERT: {alert['title']}")
                    except Exception as e:
                        print(f"⚠️  Error updating Apex tracking: {e}")
        
        except Exception as e:
            print(f"⚠️  Error checking signal #{signal.get('id')}: {e}")
    
    return updated


def start_outcome_checker(interval_seconds=60):
    """
    Start a reliable periodic outcome checker.
    Runs every interval_seconds to check all pending trades.
    """
    def checker_loop():
        # Wait a bit before starting to let app fully initialize
        time.sleep(10)
        
        while tracking_active:
            try:
                pending = get_pending_signals()
                if pending:
                    # Limit checks to avoid overwhelming the system
                    max_checks = min(len(pending), 10)  # Max 10 at a time
                    print(f"⏰ Checking {max_checks} of {len(pending)} pending trades...")
                    
                    checked = 0
                    for signal in pending[:max_checks]:
                        try:
                            outcome, price, pnl = check_signal_outcome(signal)
                            if outcome:
                                emoji = '✅' if outcome == 'WIN' else '❌'
                                print(f"{emoji} Signal #{signal['id']} {outcome}")
                                update_signal_outcome(signal['id'], outcome, price, pnl)
                                checked += 1
                        except Exception as e:
                            pass  # Silently skip errors
                    
                    if checked > 0:
                        print(f"📊 Outcome checker: {checked} trades resolved")
            except Exception as e:
                print(f"⚠️  Outcome checker error: {e}")
            
            time.sleep(interval_seconds)
    
    thread = threading.Thread(target=checker_loop, daemon=True)
    thread.start()
    print(f"⏰ Outcome checker started (every {interval_seconds}s, max 10 trades/cycle)")

