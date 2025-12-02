"""
Outcome Tracker
Monitors price to determine if signals hit TP (win) or SL (loss)
Integrates with Apex Trader Funding rules for P&L tracking
"""

import threading
import time
import yfinance as yf
from datetime import datetime, timedelta

# Import database functions
from database import get_pending_signals, update_signal_outcome

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


def get_current_price(ticker):
    """Fetch current price for a ticker"""
    try:
        # Convert ticker format if needed
        yf_ticker = ticker if '=' in ticker else f"{ticker}=F"
        
        data = yf.download(yf_ticker, period='1d', interval='1m', progress=False)
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except Exception as e:
        print(f"⚠️  Error fetching price for {ticker}: {e}")
    
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
    
    # Check if target or stop hit
    if direction == 'long':
        if current_price >= target:
            pnl = target - entry
            return 'win', current_price, pnl
        elif current_price <= stop:
            pnl = stop - entry  # Negative
            return 'loss', current_price, pnl
    
    elif direction == 'short':
        if current_price <= target:
            pnl = entry - target
            return 'win', current_price, pnl
        elif current_price >= stop:
            pnl = entry - stop  # Negative
            return 'loss', current_price, pnl
    
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
                update_signal_outcome(signal_id, 'expired', None, 0)
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
                emoji = '✅' if outcome == 'win' else '❌'
                print(f"{emoji} Signal #{signal_id} {outcome.upper()}: {ticker} @ {price:.2f} (P&L: {pnl:+.2f})")
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

