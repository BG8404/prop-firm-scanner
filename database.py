"""
Trade Journal Database
SQLite storage for signals with outcome tracking
"""

import sqlite3
import json
import os
from datetime import datetime
from threading import Lock

# Database file path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_journal.db')

# Thread-safe lock for database operations
db_lock = Lock()


def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Initialize database tables"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Signals table - stores all AI signals
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                entry_price REAL,
                stop_price REAL,
                target_price REAL,
                current_price REAL,
                entry_type TEXT,
                rationale TEXT,
                outcome TEXT DEFAULT 'pending',
                outcome_price REAL,
                outcome_time TEXT,
                pnl_ticks REAL,
                is_valid INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Daily stats table - for Apex tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                total_signals INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                total_pnl_ticks REAL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Database initialized")


def save_signal(signal_data):
    """
    Save a new signal to the database
    Returns the signal ID
    """
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO signals (
                timestamp, ticker, direction, confidence,
                entry_price, stop_price, target_price, current_price,
                entry_type, rationale, is_valid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            signal_data.get('ticker', 'UNKNOWN'),
            signal_data.get('direction', 'no_trade'),
            signal_data.get('confidence', 0),
            signal_data.get('entry'),
            signal_data.get('stop'),
            signal_data.get('takeProfit'),
            signal_data.get('currentPrice'),
            signal_data.get('entryType', 'UNKNOWN'),
            signal_data.get('rationale', ''),
            1 if signal_data.get('is_valid', True) else 0
        ))
        
        signal_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return signal_id


def update_signal_outcome(signal_id, outcome, outcome_price, pnl_ticks):
    """
    Update signal with outcome (win/loss)
    """
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE signals 
            SET outcome = ?, outcome_price = ?, outcome_time = ?, pnl_ticks = ?
            WHERE id = ?
        ''', (
            outcome,
            outcome_price,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            pnl_ticks,
            signal_id
        ))
        
        conn.commit()
        conn.close()
        
        # Update daily stats
        update_daily_stats(outcome, pnl_ticks)


def update_daily_stats(outcome, pnl_ticks):
    """Update daily statistics"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Get or create today's record
        cursor.execute('SELECT * FROM daily_stats WHERE date = ?', (today,))
        row = cursor.fetchone()
        
        if row:
            wins = row['wins'] + (1 if outcome == 'win' else 0)
            losses = row['losses'] + (1 if outcome == 'loss' else 0)
            total_pnl = row['total_pnl_ticks'] + (pnl_ticks or 0)
            
            cursor.execute('''
                UPDATE daily_stats 
                SET wins = ?, losses = ?, total_pnl_ticks = ?, total_signals = total_signals + 1
                WHERE date = ?
            ''', (wins, losses, total_pnl, today))
        else:
            cursor.execute('''
                INSERT INTO daily_stats (date, total_signals, wins, losses, total_pnl_ticks)
                VALUES (?, 1, ?, ?, ?)
            ''', (
                today,
                1 if outcome == 'win' else 0,
                1 if outcome == 'loss' else 0,
                pnl_ticks or 0
            ))
        
        conn.commit()
        conn.close()


def get_pending_signals():
    """Get all signals with pending outcomes"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM signals 
            WHERE outcome = 'pending' AND direction != 'no_trade'
            ORDER BY timestamp DESC
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


def get_recent_signals(limit=50):
    """Get recent signals for dashboard"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM signals 
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


def get_performance_stats():
    """Get overall performance statistics"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Overall stats
        cursor.execute('''
            SELECT 
                COUNT(*) as total_signals,
                SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN outcome = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(COALESCE(pnl_ticks, 0)) as total_pnl,
                AVG(CASE WHEN outcome IN ('win', 'loss') THEN pnl_ticks END) as avg_pnl
            FROM signals
            WHERE direction != 'no_trade'
        ''')
        
        stats = dict(cursor.fetchone())
        
        # Calculate win rate
        completed = (stats['wins'] or 0) + (stats['losses'] or 0)
        stats['win_rate'] = round((stats['wins'] or 0) / completed * 100, 1) if completed > 0 else 0
        
        # Best ticker
        cursor.execute('''
            SELECT ticker, 
                   SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                   COUNT(*) as total
            FROM signals
            WHERE outcome IN ('win', 'loss')
            GROUP BY ticker
            ORDER BY wins DESC
            LIMIT 1
        ''')
        
        best_ticker = cursor.fetchone()
        stats['best_ticker'] = dict(best_ticker) if best_ticker else None
        
        # Today's stats
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('SELECT * FROM daily_stats WHERE date = ?', (today,))
        today_stats = cursor.fetchone()
        stats['today'] = dict(today_stats) if today_stats else {
            'total_signals': 0, 'wins': 0, 'losses': 0, 'total_pnl_ticks': 0
        }
        
        conn.close()
        
        return stats


# Initialize database on import
init_database()

