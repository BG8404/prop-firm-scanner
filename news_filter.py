"""
SignalCrawler v2.0 - News Filter
Blocks trading signals around high-impact economic events

Major events tracked:
- FOMC (Federal Reserve) announcements
- CPI (Consumer Price Index)
- NFP (Non-Farm Payrolls)
- PPI (Producer Price Index)
- Retail Sales
- GDP releases

Default buffer: 30 minutes before and after event
"""

from datetime import datetime, time, timedelta
import pytz

EST = pytz.timezone('America/New_York')

# Buffer around news events (minutes)
NEWS_BUFFER_BEFORE = 30  # Don't trade 30 min before
NEWS_BUFFER_AFTER = 30   # Don't trade 30 min after

# ============================================
# 2024-2025 HIGH IMPACT ECONOMIC CALENDAR
# ============================================

# Format: (month, day, hour, minute, event_name)
# Times are in EST

# FOMC Announcements (2:00 PM EST) - 2025 Schedule
FOMC_2025 = [
    (1, 29, 14, 0),   # Jan 29
    (3, 19, 14, 0),   # Mar 19
    (5, 7, 14, 0),    # May 7
    (6, 18, 14, 0),   # Jun 18
    (7, 30, 14, 0),   # Jul 30
    (9, 17, 14, 0),   # Sep 17
    (11, 5, 14, 0),   # Nov 5
    (12, 17, 14, 0),  # Dec 17
]

# CPI Releases (8:30 AM EST) - Usually 2nd week of month
# NFP (8:30 AM EST) - First Friday of month
# These are approximate - update monthly as needed

# High-impact events for current month and next
# Format: (month, day, hour, minute, event_name)
SCHEDULED_EVENTS_2025 = [
    # December 2024
    (12, 6, 8, 30, "NFP - Non-Farm Payrolls"),
    (12, 11, 8, 30, "CPI - Consumer Price Index"),
    (12, 18, 14, 0, "FOMC Announcement"),
    
    # January 2025
    (1, 3, 8, 30, "NFP - Non-Farm Payrolls"),
    (1, 15, 8, 30, "CPI - Consumer Price Index"),
    (1, 29, 14, 0, "FOMC Announcement"),
    (1, 30, 8, 30, "GDP - Q4 Advance"),
    
    # February 2025
    (2, 7, 8, 30, "NFP - Non-Farm Payrolls"),
    (2, 12, 8, 30, "CPI - Consumer Price Index"),
    
    # March 2025
    (3, 7, 8, 30, "NFP - Non-Farm Payrolls"),
    (3, 12, 8, 30, "CPI - Consumer Price Index"),
    (3, 19, 14, 0, "FOMC Announcement"),
    
    # April 2025
    (4, 4, 8, 30, "NFP - Non-Farm Payrolls"),
    (4, 10, 8, 30, "CPI - Consumer Price Index"),
    
    # May 2025
    (5, 2, 8, 30, "NFP - Non-Farm Payrolls"),
    (5, 7, 14, 0, "FOMC Announcement"),
    (5, 13, 8, 30, "CPI - Consumer Price Index"),
    
    # June 2025
    (6, 6, 8, 30, "NFP - Non-Farm Payrolls"),
    (6, 11, 8, 30, "CPI - Consumer Price Index"),
    (6, 18, 14, 0, "FOMC Announcement"),
]

# Daily recurring danger times (high volatility periods)
# Note: Removed "Market Open" blocker - ORB filter already handles 9:30-10:00 AM
DAILY_DANGER_TIMES = []


def get_est_now():
    """Get current time in EST"""
    return datetime.now(EST)


def check_news_blackout():
    """
    Check if we're currently in a news blackout period.
    
    Returns:
        tuple: (is_blackout: bool, event_info: dict or None)
    """
    now = get_est_now()
    current_year = now.year
    
    # Check scheduled events
    for event in SCHEDULED_EVENTS_2025:
        month, day, hour, minute, event_name = event
        
        try:
            event_time = EST.localize(datetime(current_year, month, day, hour, minute))
        except ValueError:
            continue  # Invalid date
        
        # Calculate blackout window
        blackout_start = event_time - timedelta(minutes=NEWS_BUFFER_BEFORE)
        blackout_end = event_time + timedelta(minutes=NEWS_BUFFER_AFTER)
        
        if blackout_start <= now <= blackout_end:
            minutes_until = int((event_time - now).total_seconds() / 60)
            if minutes_until > 0:
                status = f"Event in {minutes_until} min"
            else:
                minutes_after = abs(minutes_until)
                status = f"Event was {minutes_after} min ago"
            
            return True, {
                'event': event_name,
                'event_time': event_time.strftime('%I:%M %p EST'),
                'blackout_start': blackout_start.strftime('%I:%M %p'),
                'blackout_end': blackout_end.strftime('%I:%M %p'),
                'status': status,
                'minutes_until_clear': int((blackout_end - now).total_seconds() / 60)
            }
    
    # Check daily danger times
    for danger in DAILY_DANGER_TIMES:
        start_hour, start_min, end_hour, end_min, reason = danger
        
        danger_start = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
        danger_end = now.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)
        
        if danger_start <= now <= danger_end:
            minutes_until_clear = int((danger_end - now).total_seconds() / 60)
            return True, {
                'event': reason,
                'event_time': f"{start_hour}:{start_min:02d} - {end_hour}:{end_min:02d} EST",
                'blackout_start': danger_start.strftime('%I:%M %p'),
                'blackout_end': danger_end.strftime('%I:%M %p'),
                'status': 'In progress',
                'minutes_until_clear': minutes_until_clear
            }
    
    return False, None


def get_upcoming_events(days_ahead=7):
    """
    Get list of upcoming high-impact events.
    
    Args:
        days_ahead: Number of days to look ahead
        
    Returns:
        list of event dicts
    """
    now = get_est_now()
    current_year = now.year
    cutoff = now + timedelta(days=days_ahead)
    
    upcoming = []
    
    for event in SCHEDULED_EVENTS_2025:
        month, day, hour, minute, event_name = event
        
        try:
            event_time = EST.localize(datetime(current_year, month, day, hour, minute))
        except ValueError:
            continue
        
        if now <= event_time <= cutoff:
            days_until = (event_time.date() - now.date()).days
            
            if days_until == 0:
                day_str = "TODAY"
            elif days_until == 1:
                day_str = "Tomorrow"
            else:
                day_str = event_time.strftime('%a %b %d')
            
            upcoming.append({
                'event': event_name,
                'date': day_str,
                'time': event_time.strftime('%I:%M %p EST'),
                'datetime': event_time,
                'days_until': days_until
            })
    
    # Sort by datetime
    upcoming.sort(key=lambda x: x['datetime'])
    
    return upcoming


def get_news_status():
    """
    Get current news filter status for dashboard/API.
    
    Returns:
        dict with status info
    """
    is_blackout, event_info = check_news_blackout()
    upcoming = get_upcoming_events(days_ahead=3)
    
    return {
        'is_blackout': is_blackout,
        'current_event': event_info,
        'upcoming_events': upcoming[:5],  # Next 5 events
        'buffer_before': NEWS_BUFFER_BEFORE,
        'buffer_after': NEWS_BUFFER_AFTER,
        'checked_at': get_est_now().strftime('%I:%M:%S %p EST')
    }


def format_news_for_alert():
    """Format news status for Discord/display"""
    status = get_news_status()
    
    lines = []
    
    if status['is_blackout']:
        event = status['current_event']
        lines.append(f"🚫 **NEWS BLACKOUT ACTIVE**")
        lines.append(f"📰 {event['event']}")
        lines.append(f"⏰ {event['event_time']}")
        lines.append(f"⏳ Clear in {event['minutes_until_clear']} min")
    else:
        lines.append("✅ **No active news blackout**")
        
        if status['upcoming_events']:
            lines.append("\n📅 **Upcoming Events:**")
            for evt in status['upcoming_events'][:3]:
                lines.append(f"• {evt['date']} {evt['time']} - {evt['event']}")
    
    return '\n'.join(lines)


# Test on import
if __name__ == '__main__':
    print("📰 News Filter Status:")
    print("=" * 50)
    
    is_blackout, event = check_news_blackout()
    
    if is_blackout:
        print(f"🚫 BLACKOUT ACTIVE: {event['event']}")
        print(f"   Time: {event['event_time']}")
        print(f"   Clear in: {event['minutes_until_clear']} min")
    else:
        print("✅ No current blackout")
    
    print("\n📅 Upcoming Events:")
    for evt in get_upcoming_events()[:5]:
        print(f"   {evt['date']} {evt['time']} - {evt['event']}")


print("✅ News Filter loaded (FOMC, CPI, NFP, GDP)")

