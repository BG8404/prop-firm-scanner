"""
Apex Trader Funding Rules Engine
Monitors trading activity against prop firm rules

Features:
- Daily loss limit warnings (alert at 80%, block at 100%)
- Trailing drawdown tracker
- Consistency rule (no single day > 30% of total profits)
"""

import json
import os
from datetime import datetime, timedelta
from threading import Lock
import sqlite3

# Configuration defaults for Apex Trader Funding
DEFAULT_APEX_CONFIG = {
    # Account settings (user should configure these)
    "account_size": 50000,          # Account size in dollars
    "max_daily_loss": 2500,         # Max daily loss limit (5% of 50k)
    "max_trailing_drawdown": 2500,  # Max trailing drawdown
    "initial_balance": 50000,       # Starting balance
    
    # Alert thresholds
    "daily_loss_warning_pct": 80,   # Warn at 80% of daily limit
    "daily_loss_block_pct": 100,    # Block at 100% of daily limit
    
    # Consistency rule
    "max_day_profit_pct": 30,       # No day can be > 30% of total profits
    
    # Tick values (for P&L calculation)
    "tick_values": {
        "MNQ": 0.50,    # $0.50 per tick
        "MNQ=F": 0.50,
        "MES": 1.25,    # $1.25 per tick
        "MES=F": 1.25,
        "MGC": 1.00,    # $1.00 per tick
        "MGC=F": 1.00,
    }
}

# State file for persistence
APEX_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apex_state.json')
APEX_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apex_config.json')

# Thread safety
apex_lock = Lock()


def load_config():
    """Load Apex configuration from file"""
    try:
        if os.path.exists(APEX_CONFIG_FILE):
            with open(APEX_CONFIG_FILE, 'r') as f:
                config = json.load(f)
                # Merge with defaults
                merged = DEFAULT_APEX_CONFIG.copy()
                merged.update(config)
                return merged
    except Exception as e:
        print(f"⚠️  Error loading Apex config: {e}")
    return DEFAULT_APEX_CONFIG.copy()


def save_config(config):
    """Save Apex configuration to file"""
    try:
        with open(APEX_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"⚠️  Error saving Apex config: {e}")


def load_state():
    """Load Apex state (tracking data) from file"""
    default_state = {
        "high_water_mark": None,
        "trailing_drawdown_start": None,
        "current_balance": None,
        "daily_pnl": {},  # date -> P&L in dollars
        "alerts_sent": {},  # date -> list of alert types sent
        "last_updated": None
    }
    try:
        if os.path.exists(APEX_STATE_FILE):
            with open(APEX_STATE_FILE, 'r') as f:
                state = json.load(f)
                # Merge with defaults
                merged = default_state.copy()
                merged.update(state)
                return merged
    except Exception as e:
        print(f"⚠️  Error loading Apex state: {e}")
    return default_state


def save_state(state):
    """Save Apex state to file"""
    try:
        state['last_updated'] = datetime.now().isoformat()
        with open(APEX_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠️  Error saving Apex state: {e}")


# Global state
apex_config = load_config()
apex_state = load_state()


def get_tick_value(ticker):
    """Get dollar value per tick for a ticker"""
    base_ticker = ticker.split(":")[0] if ":" in ticker else ticker
    return apex_config["tick_values"].get(base_ticker, 1.0)


def ticks_to_dollars(ticker, ticks):
    """Convert ticks to dollars"""
    return ticks * get_tick_value(ticker)


def update_apex_config(new_config):
    """Update Apex configuration"""
    global apex_config, apex_state
    with apex_lock:
        apex_config.update(new_config)
        save_config(apex_config)
        
        # Reset state if account size changed
        if 'account_size' in new_config:
            apex_state['current_balance'] = new_config.get('initial_balance', new_config['account_size'])
            apex_state['high_water_mark'] = apex_state['current_balance']
            apex_state['trailing_drawdown_start'] = apex_state['current_balance']
            save_state(apex_state)
    
    return apex_config


def reset_apex_state():
    """Reset Apex state (start fresh)"""
    global apex_state
    with apex_lock:
        apex_state = {
            "high_water_mark": apex_config.get('initial_balance', apex_config['account_size']),
            "trailing_drawdown_start": apex_config.get('initial_balance', apex_config['account_size']),
            "current_balance": apex_config.get('initial_balance', apex_config['account_size']),
            "daily_pnl": {},
            "alerts_sent": {},
            "last_updated": datetime.now().isoformat()
        }
        save_state(apex_state)
    return apex_state


def initialize_state_if_needed():
    """Initialize state with config values if not set"""
    global apex_state
    if apex_state['current_balance'] is None:
        apex_state['current_balance'] = apex_config.get('initial_balance', apex_config['account_size'])
        apex_state['high_water_mark'] = apex_state['current_balance']
        apex_state['trailing_drawdown_start'] = apex_state['current_balance']
        save_state(apex_state)


def record_trade_result(ticker, pnl_ticks, trade_time=None):
    """
    Record a trade result and update Apex tracking
    
    Args:
        ticker: The trading symbol
        pnl_ticks: Profit/loss in ticks (positive = profit)
        trade_time: Optional datetime, defaults to now
    
    Returns:
        dict with alerts and status
    """
    global apex_state
    
    initialize_state_if_needed()
    
    if trade_time is None:
        trade_time = datetime.now()
    
    date_key = trade_time.strftime('%Y-%m-%d')
    pnl_dollars = ticks_to_dollars(ticker, pnl_ticks)
    
    alerts = []
    
    with apex_lock:
        # Update daily P&L
        if date_key not in apex_state['daily_pnl']:
            apex_state['daily_pnl'][date_key] = 0
        apex_state['daily_pnl'][date_key] += pnl_dollars
        
        # Update current balance
        apex_state['current_balance'] += pnl_dollars
        
        # Update high water mark (trailing drawdown reference)
        if apex_state['current_balance'] > apex_state['high_water_mark']:
            apex_state['high_water_mark'] = apex_state['current_balance']
        
        # Check rules and generate alerts
        alerts = check_all_rules(date_key)
        
        save_state(apex_state)
    
    return {
        "pnl_dollars": pnl_dollars,
        "daily_pnl": apex_state['daily_pnl'].get(date_key, 0),
        "current_balance": apex_state['current_balance'],
        "alerts": alerts
    }


def check_all_rules(date_key=None):
    """
    Check all Apex trading rules
    
    Returns list of alert dicts
    """
    if date_key is None:
        date_key = datetime.now().strftime('%Y-%m-%d')
    
    alerts = []
    
    # Rule 1: Daily Loss Limit
    daily_alerts = check_daily_loss_limit(date_key)
    alerts.extend(daily_alerts)
    
    # Rule 2: Trailing Drawdown
    drawdown_alerts = check_trailing_drawdown()
    alerts.extend(drawdown_alerts)
    
    # Rule 3: Consistency Rule
    consistency_alerts = check_consistency_rule()
    alerts.extend(consistency_alerts)
    
    return alerts


def check_daily_loss_limit(date_key=None):
    """
    Check if approaching or exceeding daily loss limit
    
    Returns list of alerts
    """
    if date_key is None:
        date_key = datetime.now().strftime('%Y-%m-%d')
    
    alerts = []
    daily_pnl = apex_state['daily_pnl'].get(date_key, 0)
    max_daily_loss = apex_config['max_daily_loss']
    warning_pct = apex_config['daily_loss_warning_pct']
    block_pct = apex_config['daily_loss_block_pct']
    
    # Only check if in a loss for the day
    if daily_pnl < 0:
        loss_amount = abs(daily_pnl)
        loss_pct = (loss_amount / max_daily_loss) * 100
        
        # Initialize alerts_sent for today
        if date_key not in apex_state['alerts_sent']:
            apex_state['alerts_sent'][date_key] = []
        
        # Check for 100% block
        if loss_pct >= block_pct and 'daily_loss_block' not in apex_state['alerts_sent'][date_key]:
            alerts.append({
                "type": "daily_loss_block",
                "severity": "critical",
                "title": "🚫 DAILY LOSS LIMIT REACHED",
                "message": f"Daily loss ${loss_amount:.2f} has reached 100% of limit (${max_daily_loss:.2f}). STOP TRADING!",
                "value": loss_amount,
                "limit": max_daily_loss,
                "percentage": loss_pct,
                "action": "block"
            })
            apex_state['alerts_sent'][date_key].append('daily_loss_block')
        
        # Check for 80% warning
        elif loss_pct >= warning_pct and 'daily_loss_warning' not in apex_state['alerts_sent'][date_key]:
            alerts.append({
                "type": "daily_loss_warning",
                "severity": "warning",
                "title": "⚠️ DAILY LOSS WARNING",
                "message": f"Daily loss ${loss_amount:.2f} is at {loss_pct:.1f}% of limit (${max_daily_loss:.2f}). Reduce risk!",
                "value": loss_amount,
                "limit": max_daily_loss,
                "percentage": loss_pct,
                "action": "warn"
            })
            apex_state['alerts_sent'][date_key].append('daily_loss_warning')
    
    return alerts


def check_trailing_drawdown():
    """
    Check trailing drawdown status
    
    Returns list of alerts
    """
    alerts = []
    
    current = apex_state['current_balance']
    high_water = apex_state['high_water_mark']
    max_drawdown = apex_config['max_trailing_drawdown']
    
    if current is None or high_water is None:
        return alerts
    
    # Calculate current drawdown
    drawdown = high_water - current
    drawdown_pct = (drawdown / max_drawdown) * 100 if max_drawdown > 0 else 0
    
    # Calculate floor (minimum allowed balance)
    floor = high_water - max_drawdown
    distance_to_floor = current - floor
    
    today_key = datetime.now().strftime('%Y-%m-%d')
    if today_key not in apex_state['alerts_sent']:
        apex_state['alerts_sent'][today_key] = []
    
    # Check if breached
    if drawdown >= max_drawdown and 'drawdown_breach' not in apex_state['alerts_sent'][today_key]:
        alerts.append({
            "type": "drawdown_breach",
            "severity": "critical",
            "title": "🚫 TRAILING DRAWDOWN BREACHED",
            "message": f"Account has fallen ${drawdown:.2f} below high water mark. Maximum allowed: ${max_drawdown:.2f}",
            "value": drawdown,
            "limit": max_drawdown,
            "percentage": drawdown_pct,
            "action": "block"
        })
        apex_state['alerts_sent'][today_key].append('drawdown_breach')
    
    # Check for 80% warning
    elif drawdown_pct >= 80 and 'drawdown_warning' not in apex_state['alerts_sent'][today_key]:
        alerts.append({
            "type": "drawdown_warning",
            "severity": "warning",
            "title": "⚠️ TRAILING DRAWDOWN WARNING",
            "message": f"Only ${distance_to_floor:.2f} remaining before breaching drawdown limit",
            "value": drawdown,
            "limit": max_drawdown,
            "percentage": drawdown_pct,
            "action": "warn"
        })
        apex_state['alerts_sent'][today_key].append('drawdown_warning')
    
    return alerts


def check_consistency_rule():
    """
    Check consistency rule: no single day > 30% of total profits
    
    Returns list of alerts
    """
    alerts = []
    
    max_pct = apex_config['max_day_profit_pct']
    
    # Calculate total profits (only profitable days)
    total_profit = sum(pnl for pnl in apex_state['daily_pnl'].values() if pnl > 0)
    
    if total_profit <= 0:
        return alerts
    
    # Check each day
    violations = []
    for date, pnl in apex_state['daily_pnl'].items():
        if pnl > 0:
            day_pct = (pnl / total_profit) * 100
            if day_pct > max_pct:
                violations.append({
                    "date": date,
                    "profit": pnl,
                    "percentage": day_pct
                })
    
    today_key = datetime.now().strftime('%Y-%m-%d')
    if today_key not in apex_state['alerts_sent']:
        apex_state['alerts_sent'][today_key] = []
    
    if violations and 'consistency_warning' not in apex_state['alerts_sent'][today_key]:
        worst = max(violations, key=lambda x: x['percentage'])
        alerts.append({
            "type": "consistency_warning",
            "severity": "warning",
            "title": "⚠️ CONSISTENCY RULE WARNING",
            "message": f"Day {worst['date']} profit ${worst['profit']:.2f} is {worst['percentage']:.1f}% of total profits. Max allowed: {max_pct}%",
            "violations": violations,
            "max_allowed_pct": max_pct,
            "action": "warn"
        })
        apex_state['alerts_sent'][today_key].append('consistency_warning')
    
    return alerts


def get_apex_status():
    """
    Get current Apex rules status for dashboard
    
    Returns comprehensive status dict
    """
    initialize_state_if_needed()
    
    today_key = datetime.now().strftime('%Y-%m-%d')
    daily_pnl = apex_state['daily_pnl'].get(today_key, 0)
    
    # Calculate drawdown info
    current = apex_state['current_balance'] or 0
    high_water = apex_state['high_water_mark'] or current
    max_drawdown = apex_config['max_trailing_drawdown']
    
    drawdown = high_water - current
    drawdown_pct = (drawdown / max_drawdown) * 100 if max_drawdown > 0 else 0
    floor = high_water - max_drawdown
    distance_to_floor = current - floor
    
    # Calculate daily loss info
    max_daily_loss = apex_config['max_daily_loss']
    daily_loss_pct = (abs(daily_pnl) / max_daily_loss) * 100 if daily_pnl < 0 and max_daily_loss > 0 else 0
    daily_remaining = max_daily_loss - abs(min(daily_pnl, 0))
    
    # Calculate consistency info
    total_profit = sum(pnl for pnl in apex_state['daily_pnl'].values() if pnl > 0)
    max_day_pct = apex_config['max_day_profit_pct']
    
    best_day = None
    best_day_pct = 0
    for date, pnl in apex_state['daily_pnl'].items():
        if pnl > 0 and total_profit > 0:
            pct = (pnl / total_profit) * 100
            if pct > best_day_pct:
                best_day = date
                best_day_pct = pct
    
    consistency_ok = best_day_pct <= max_day_pct if total_profit > 0 else True
    
    return {
        "config": apex_config,
        "account": {
            "initial_balance": apex_config.get('initial_balance', apex_config['account_size']),
            "current_balance": current,
            "high_water_mark": high_water,
            "total_pnl": current - apex_config.get('initial_balance', apex_config['account_size'])
        },
        "daily_loss": {
            "today_pnl": daily_pnl,
            "max_allowed": max_daily_loss,
            "used_pct": daily_loss_pct,
            "remaining": daily_remaining,
            "status": "blocked" if daily_loss_pct >= 100 else "warning" if daily_loss_pct >= 80 else "ok"
        },
        "trailing_drawdown": {
            "current_drawdown": drawdown,
            "max_allowed": max_drawdown,
            "used_pct": drawdown_pct,
            "floor": floor,
            "distance_to_floor": distance_to_floor,
            "status": "breached" if drawdown >= max_drawdown else "warning" if drawdown_pct >= 80 else "ok"
        },
        "consistency": {
            "total_profit": total_profit,
            "max_day_pct_allowed": max_day_pct,
            "best_day": best_day,
            "best_day_pct": best_day_pct,
            "status": "ok" if consistency_ok else "warning"
        },
        "daily_history": apex_state['daily_pnl'],
        "last_updated": apex_state.get('last_updated')
    }


def should_block_trading():
    """
    Quick check if trading should be blocked
    
    Returns tuple: (should_block, reason)
    """
    initialize_state_if_needed()
    
    today_key = datetime.now().strftime('%Y-%m-%d')
    daily_pnl = apex_state['daily_pnl'].get(today_key, 0)
    
    # Check daily loss limit
    if daily_pnl < 0:
        loss_pct = (abs(daily_pnl) / apex_config['max_daily_loss']) * 100
        if loss_pct >= 100:
            return True, "Daily loss limit reached"
    
    # Check trailing drawdown
    current = apex_state['current_balance'] or 0
    high_water = apex_state['high_water_mark'] or current
    drawdown = high_water - current
    
    if drawdown >= apex_config['max_trailing_drawdown']:
        return True, "Trailing drawdown breached"
    
    return False, None


# Initialize on import
initialize_state_if_needed()
print("✅ Apex Trader Funding rules engine loaded")

