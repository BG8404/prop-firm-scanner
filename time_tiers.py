"""
SignalCrawler v3.0 - Time-Based Signal Tiers
Dynamic confidence thresholds and risk sizing based on trading session

Trading Windows (All times EST):
- PRIME:     9:30 AM - 11:30 AM  (80% conf, $250 risk, 1.5:1 / 2:1 targets)
- MIDDAY:    11:30 AM - 3:30 PM  (85% conf, $175 risk, 1:1 / 1.5:1 targets)
- CLOSE:     3:30 PM - 5:00 PM   (85% conf, $175 risk, 1:1 / 1.5:1 targets)
- EVENING:   5:00 PM - 9:00 PM   (90% conf, $125 risk, 1:1 / 1.5:1 targets)
- BLOCKED:   9:00 PM - 6:00 AM   (NO SIGNALS - overnight)
- PREMARKET: 6:00 AM - 9:30 AM   (90% conf, $125 risk, 1:1 / 1.5:1 targets)
"""

from datetime import datetime, time
import pytz

EST = pytz.timezone('America/New_York')

# ============================================
# TIME TIER CONFIGURATION
# ============================================

TIERS = {
    'PRIME': {
        'name': 'PRIME TIME',
        'start': time(9, 30),
        'end': time(11, 30),
        'min_confidence': 80,
        'risk': 250,
        'emoji': '🟢',
        'color': 0x1a472a,  # Dark green
        'targets': {'t1_rr': 1.5, 't2_rr': 2.0},
        'warning': False,
        'blocked': False
    },
    'MIDDAY': {
        'name': 'MID-DAY',
        'start': time(11, 30),
        'end': time(15, 30),
        'min_confidence': 85,
        'risk': 175,
        'emoji': '🟡',
        'color': 0xb8860b,  # Dark goldenrod
        'targets': {'t1_rr': 1.0, 't2_rr': 1.5},
        'warning': False,
        'blocked': False
    },
    'CLOSE': {
        'name': 'MARKET CLOSE',
        'start': time(15, 30),
        'end': time(17, 0),
        'min_confidence': 85,
        'risk': 175,
        'emoji': '🟡',
        'color': 0xb8860b,  # Dark goldenrod
        'targets': {'t1_rr': 1.0, 't2_rr': 1.5},
        'warning': False,
        'blocked': False
    },
    'EVENING': {
        'name': 'EVENING SESSION',
        'start': time(17, 0),
        'end': time(21, 0),
        'min_confidence': 90,
        'risk': 125,
        'emoji': '🔴',
        'color': 0x8b0000,  # Dark red
        'targets': {'t1_rr': 1.0, 't2_rr': 1.5},
        'warning': True,
        'blocked': False
    },
    'BLOCKED': {
        'name': 'OVERNIGHT - NO TRADING',
        'start': time(21, 0),
        'end': time(6, 0),  # Crosses midnight
        'min_confidence': 100,  # Impossible to meet
        'risk': 0,
        'emoji': '⛔',
        'color': 0x2f3136,  # Discord dark
        'targets': {'t1_rr': 1.0, 't2_rr': 1.0},
        'warning': True,
        'blocked': True
    },
    'PREMARKET': {
        'name': 'PRE-MARKET',
        'start': time(6, 0),
        'end': time(9, 30),
        'min_confidence': 90,
        'risk': 125,
        'emoji': '🔴',
        'color': 0x8b0000,  # Dark red
        'targets': {'t1_rr': 1.0, 't2_rr': 1.5},
        'warning': True,
        'blocked': False
    }
}


def get_est_now():
    """Get current time in EST"""
    return datetime.now(EST)


def get_current_tier():
    """
    Determine current trading tier based on EST time.
    
    Returns:
        dict: Tier configuration with all settings
    """
    now = get_est_now()
    current_time = now.time()
    
    # Check each tier in order
    # PRIME: 9:30 AM - 11:30 AM
    if time(9, 30) <= current_time < time(11, 30):
        return TIERS['PRIME']
    
    # MIDDAY: 11:30 AM - 3:30 PM
    if time(11, 30) <= current_time < time(15, 30):
        return TIERS['MIDDAY']
    
    # CLOSE: 3:30 PM - 5:00 PM
    if time(15, 30) <= current_time < time(17, 0):
        return TIERS['CLOSE']
    
    # EVENING: 5:00 PM - 9:00 PM
    if time(17, 0) <= current_time < time(21, 0):
        return TIERS['EVENING']
    
    # BLOCKED: 9:00 PM - 6:00 AM (crosses midnight)
    if current_time >= time(21, 0) or current_time < time(6, 0):
        return TIERS['BLOCKED']
    
    # PREMARKET: 6:00 AM - 9:30 AM
    if time(6, 0) <= current_time < time(9, 30):
        return TIERS['PREMARKET']
    
    # Fallback (shouldn't happen)
    return TIERS['MIDDAY']


def is_trading_blocked():
    """
    Check if we're in the overnight blocked period (9 PM - 6 AM).
    
    Returns:
        tuple: (is_blocked: bool, message: str or None)
    """
    tier = get_current_tier()
    
    if tier.get('blocked', False):
        now = get_est_now()
        
        # Calculate time until trading resumes
        if now.hour >= 21:
            # After 9 PM, calculate hours until 6 AM next day
            hours_until = (24 - now.hour) + 6
        else:
            # Before 6 AM, calculate hours until 6 AM
            hours_until = 6 - now.hour
        
        return True, f"Overnight block (9 PM - 6 AM). Trading resumes in ~{hours_until} hours."
    
    return False, None


def get_tier_confidence_threshold():
    """Get minimum confidence for current tier."""
    tier = get_current_tier()
    return tier['min_confidence']


def get_tier_risk():
    """Get suggested risk amount for current tier."""
    tier = get_current_tier()
    return tier['risk']


def get_tier_targets():
    """
    Get R:R targets for current tier.
    
    Returns:
        tuple: (target1_rr, target2_rr)
    """
    tier = get_current_tier()
    targets = tier['targets']
    return targets['t1_rr'], targets['t2_rr']


def get_tier_emoji():
    """Get emoji indicator for current tier."""
    tier = get_current_tier()
    return tier['emoji']


def get_tier_name():
    """Get display name for current tier."""
    tier = get_current_tier()
    return tier['name']


def get_tier_color():
    """Get Discord embed color for current tier."""
    tier = get_current_tier()
    return tier['color']


def should_show_warning():
    """Check if current tier requires extended hours warning."""
    tier = get_current_tier()
    return tier.get('warning', False)


def get_session_window():
    """
    Get the current session's time window for display.
    
    Returns:
        str: Formatted time window (e.g., "9:30 AM - 11:30 AM")
    """
    tier = get_current_tier()
    start = tier['start']
    end = tier['end']
    
    def format_time(t):
        hour = t.hour
        minute = t.minute
        am_pm = 'AM' if hour < 12 else 'PM'
        if hour > 12:
            hour -= 12
        elif hour == 0:
            hour = 12
        if minute == 0:
            return f"{hour} {am_pm}"
        return f"{hour}:{minute:02d} {am_pm}"
    
    return f"{format_time(start)} - {format_time(end)}"


def get_extended_hours_warning():
    """
    Get warning text for extended hours trading.
    
    Returns:
        str: Warning message or empty string
    """
    if not should_show_warning():
        return ""
    
    tier = get_current_tier()
    
    if tier.get('blocked', False):
        return "⛔ **OVERNIGHT - NO SIGNALS**\nTrading blocked from 9 PM - 6 AM EST"
    
    return """⚠️ **EXTENDED HOURS NOTICE**
• Lower liquidity - wider spreads expected
• Expect 1-3 tick slippage on entry/exit
• Consider waiting for RTH if not urgent"""


def get_tier_summary():
    """
    Get a summary of all tiers for display/logging.
    
    Returns:
        str: Formatted tier summary
    """
    lines = ["📊 Time-Based Signal Tiers (EST):"]
    for key, tier in TIERS.items():
        if tier.get('blocked'):
            status = "BLOCKED"
        else:
            status = f"{tier['min_confidence']}% conf, ${tier['risk']} risk"
        
        start = tier['start'].strftime('%I:%M %p').lstrip('0')
        end = tier['end'].strftime('%I:%M %p').lstrip('0')
        
        lines.append(f"  {tier['emoji']} {tier['name']}: {start} - {end} ({status})")
    
    return '\n'.join(lines)


# ============================================
# INITIALIZATION
# ============================================

if __name__ == '__main__':
    print(get_tier_summary())
    print()
    
    tier = get_current_tier()
    now = get_est_now()
    
    print(f"Current time: {now.strftime('%I:%M %p EST')}")
    print(f"Current tier: {tier['emoji']} {tier['name']}")
    print(f"Min confidence: {tier['min_confidence']}%")
    print(f"Suggested risk: ${tier['risk']}")
    print(f"Targets: {tier['targets']['t1_rr']}:1 / {tier['targets']['t2_rr']}:1")
    
    blocked, msg = is_trading_blocked()
    if blocked:
        print(f"\n⛔ {msg}")


print("✅ Time Tiers loaded (PRIME/MIDDAY/CLOSE/EVENING/BLOCKED/PREMARKET)")

