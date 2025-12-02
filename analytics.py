"""
Performance Analytics Engine
Advanced statistics and chart data for the dashboard

Features:
- Win rate over time (rolling)
- P&L cumulative chart
- Best/worst tickers analysis
- Trade distribution by hour/day
- Streak tracking
"""

import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import os

# Database path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_journal.db')


def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_win_rate_chart_data(days=30):
    """
    Get win rate data over time for charting
    
    Returns daily win rate for the past N days
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    cursor.execute('''
        SELECT 
            DATE(timestamp) as date,
            COUNT(*) as total,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses
        FROM signals
        WHERE outcome IN ('win', 'loss')
        AND DATE(timestamp) >= ?
        GROUP BY DATE(timestamp)
        ORDER BY DATE(timestamp)
    ''', (start_date,))
    
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        total = row['wins'] + row['losses']
        win_rate = (row['wins'] / total * 100) if total > 0 else 0
        result.append({
            "date": row['date'],
            "win_rate": round(win_rate, 1),
            "wins": row['wins'],
            "losses": row['losses'],
            "total": total
        })
    
    return result


def get_pnl_chart_data(days=30):
    """
    Get P&L data over time for charting
    
    Returns daily and cumulative P&L
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    cursor.execute('''
        SELECT 
            DATE(timestamp) as date,
            SUM(COALESCE(pnl_ticks, 0)) as daily_pnl,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses
        FROM signals
        WHERE outcome IN ('win', 'loss')
        AND DATE(timestamp) >= ?
        GROUP BY DATE(timestamp)
        ORDER BY DATE(timestamp)
    ''', (start_date,))
    
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    cumulative = 0
    
    for row in rows:
        daily = row['daily_pnl'] or 0
        cumulative += daily
        result.append({
            "date": row['date'],
            "daily_pnl": round(daily, 2),
            "cumulative_pnl": round(cumulative, 2),
            "wins": row['wins'],
            "losses": row['losses']
        })
    
    return result


def get_ticker_performance():
    """
    Get performance breakdown by ticker
    
    Returns best and worst performers
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            ticker,
            COUNT(*) as total_trades,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
            SUM(COALESCE(pnl_ticks, 0)) as total_pnl,
            AVG(CASE WHEN outcome = 'win' THEN pnl_ticks END) as avg_win,
            AVG(CASE WHEN outcome = 'loss' THEN pnl_ticks END) as avg_loss
        FROM signals
        WHERE outcome IN ('win', 'loss')
        GROUP BY ticker
        ORDER BY total_pnl DESC
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    tickers = []
    for row in rows:
        total = row['wins'] + row['losses']
        win_rate = (row['wins'] / total * 100) if total > 0 else 0
        
        tickers.append({
            "ticker": row['ticker'],
            "total_trades": total,
            "wins": row['wins'],
            "losses": row['losses'],
            "win_rate": round(win_rate, 1),
            "total_pnl": round(row['total_pnl'] or 0, 2),
            "avg_win": round(row['avg_win'] or 0, 2),
            "avg_loss": round(row['avg_loss'] or 0, 2)
        })
    
    # Sort for best and worst
    best = sorted(tickers, key=lambda x: x['total_pnl'], reverse=True)[:5]
    worst = sorted(tickers, key=lambda x: x['total_pnl'])[:5]
    
    return {
        "all": tickers,
        "best": best,
        "worst": worst
    }


def get_hourly_distribution():
    """
    Get trade distribution by hour
    
    Helps identify best/worst trading hours
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            CAST(strftime('%H', timestamp) AS INTEGER) as hour,
            COUNT(*) as total_trades,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
            SUM(COALESCE(pnl_ticks, 0)) as total_pnl
        FROM signals
        WHERE outcome IN ('win', 'loss')
        GROUP BY hour
        ORDER BY hour
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        total = row['wins'] + row['losses']
        win_rate = (row['wins'] / total * 100) if total > 0 else 0
        result.append({
            "hour": row['hour'],
            "label": f"{row['hour']:02d}:00",
            "total_trades": total,
            "wins": row['wins'],
            "losses": row['losses'],
            "win_rate": round(win_rate, 1),
            "total_pnl": round(row['total_pnl'] or 0, 2)
        })
    
    return result


def get_weekday_distribution():
    """
    Get trade distribution by day of week
    
    0 = Sunday, 6 = Saturday
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            CAST(strftime('%w', timestamp) AS INTEGER) as weekday,
            COUNT(*) as total_trades,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
            SUM(COALESCE(pnl_ticks, 0)) as total_pnl
        FROM signals
        WHERE outcome IN ('win', 'loss')
        GROUP BY weekday
        ORDER BY weekday
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    day_names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    
    result = []
    for row in rows:
        total = row['wins'] + row['losses']
        win_rate = (row['wins'] / total * 100) if total > 0 else 0
        result.append({
            "weekday": row['weekday'],
            "label": day_names[row['weekday']],
            "total_trades": total,
            "wins": row['wins'],
            "losses": row['losses'],
            "win_rate": round(win_rate, 1),
            "total_pnl": round(row['total_pnl'] or 0, 2)
        })
    
    return result


def get_streak_info():
    """
    Calculate current and max win/loss streaks
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT outcome
        FROM signals
        WHERE outcome IN ('win', 'loss')
        ORDER BY timestamp DESC
    ''')
    
    outcomes = [row['outcome'] for row in cursor.fetchall()]
    conn.close()
    
    if not outcomes:
        return {
            "current_streak": 0,
            "current_streak_type": None,
            "max_win_streak": 0,
            "max_loss_streak": 0
        }
    
    # Current streak
    current_type = outcomes[0]
    current_streak = 1
    for outcome in outcomes[1:]:
        if outcome == current_type:
            current_streak += 1
        else:
            break
    
    # Max streaks
    max_win = 0
    max_loss = 0
    current_win = 0
    current_loss = 0
    
    for outcome in reversed(outcomes):
        if outcome == 'win':
            current_win += 1
            current_loss = 0
            max_win = max(max_win, current_win)
        else:
            current_loss += 1
            current_win = 0
            max_loss = max(max_loss, current_loss)
    
    return {
        "current_streak": current_streak,
        "current_streak_type": current_type,
        "max_win_streak": max_win,
        "max_loss_streak": max_loss
    }


def get_confidence_performance():
    """
    Analyze performance by confidence level
    
    Helps find optimal confidence threshold
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            CASE 
                WHEN confidence >= 90 THEN '90-100'
                WHEN confidence >= 80 THEN '80-89'
                WHEN confidence >= 70 THEN '70-79'
                WHEN confidence >= 60 THEN '60-69'
                WHEN confidence >= 50 THEN '50-59'
                ELSE 'Below 50'
            END as confidence_range,
            confidence,
            COUNT(*) as total_trades,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
            SUM(COALESCE(pnl_ticks, 0)) as total_pnl,
            AVG(CASE WHEN outcome IN ('win', 'loss') THEN pnl_ticks END) as avg_pnl
        FROM signals
        WHERE outcome IN ('win', 'loss') AND is_valid = 1
        GROUP BY confidence_range
        ORDER BY MIN(confidence) DESC
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        total = row['wins'] + row['losses']
        win_rate = (row['wins'] / total * 100) if total > 0 else 0
        result.append({
            "range": row['confidence_range'],
            "total_trades": total,
            "wins": row['wins'],
            "losses": row['losses'],
            "win_rate": round(win_rate, 1),
            "total_pnl": round(row['total_pnl'] or 0, 2),
            "avg_pnl": round(row['avg_pnl'] or 0, 2)
        })
    
    return result


def get_direction_performance():
    """
    Analyze performance by trade direction (long vs short)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            direction,
            COUNT(*) as total_trades,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
            SUM(COALESCE(pnl_ticks, 0)) as total_pnl,
            AVG(CASE WHEN outcome IN ('win', 'loss') THEN pnl_ticks END) as avg_pnl
        FROM signals
        WHERE outcome IN ('win', 'loss') AND direction IN ('long', 'short')
        GROUP BY direction
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    result = {}
    for row in rows:
        total = row['wins'] + row['losses']
        win_rate = (row['wins'] / total * 100) if total > 0 else 0
        result[row['direction']] = {
            "total_trades": total,
            "wins": row['wins'],
            "losses": row['losses'],
            "win_rate": round(win_rate, 1),
            "total_pnl": round(row['total_pnl'] or 0, 2),
            "avg_pnl": round(row['avg_pnl'] or 0, 2)
        }
    
    return result


def get_recent_performance(days=7):
    """
    Get performance summary for recent period
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    cursor.execute('''
        SELECT 
            COUNT(*) as total_trades,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
            SUM(COALESCE(pnl_ticks, 0)) as total_pnl,
            AVG(CASE WHEN outcome IN ('win', 'loss') THEN pnl_ticks END) as avg_pnl
        FROM signals
        WHERE outcome IN ('win', 'loss')
        AND DATE(timestamp) >= ?
    ''', (start_date,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row or row['total_trades'] == 0:
        return {
            "period_days": days,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_pnl": 0
        }
    
    total = row['wins'] + row['losses']
    win_rate = (row['wins'] / total * 100) if total > 0 else 0
    
    return {
        "period_days": days,
        "total_trades": total,
        "wins": row['wins'],
        "losses": row['losses'],
        "win_rate": round(win_rate, 1),
        "total_pnl": round(row['total_pnl'] or 0, 2),
        "avg_pnl": round(row['avg_pnl'] or 0, 2)
    }


def get_full_analytics():
    """
    Get all analytics data in one call
    """
    return {
        "win_rate_chart": get_win_rate_chart_data(30),
        "pnl_chart": get_pnl_chart_data(30),
        "tickers": get_ticker_performance(),
        "hourly": get_hourly_distribution(),
        "weekday": get_weekday_distribution(),
        "streaks": get_streak_info(),
        "confidence": get_confidence_performance(),
        "direction": get_direction_performance(),
        "recent_7d": get_recent_performance(7),
        "recent_30d": get_recent_performance(30)
    }


print("✅ Analytics engine loaded")

