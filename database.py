"""
Trade Journal Database - Enhanced Schema
SQLite storage with signal features for AI learning
"""

import sqlite3
import json
import os
from datetime import datetime
from threading import Lock

# Database file path
# Use /app/data for Railway persistent volume, fallback to local for development
if os.path.exists('/app/data'):
    DB_PATH = '/app/data/trade_journal.db'
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_journal.db')

# Thread-safe lock for database operations
db_lock = Lock()

# Hardcoded tickers (MNQ, MES, MGC)
# max_stop_points: Maximum stop loss in points (not ticks) for risk management
TICKERS = {
    'MNQ': {'name': 'Micro Nasdaq Futures', 'tick_size': 0.25, 'tick_value': 0.50, 'max_stop_points': 15},
    'MES': {'name': 'Micro S&P 500 Futures', 'tick_size': 0.25, 'tick_value': 1.25, 'max_stop_points': 6},
    'MGC': {'name': 'Micro Gold Futures', 'tick_size': 0.10, 'tick_value': 1.00, 'max_stop_points': 10},
}


def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    """Initialize database tables with enhanced schema"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        # ============================================================
        # TABLE 1: CANDLE HISTORY
        # Stores all incoming candles from TradingView
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS candle_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                timeframe TEXT NOT NULL DEFAULT '1m',
                timestamp DATETIME NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ticker, timeframe, timestamp)
            )
        ''')
        
        # Indexes for fast queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_candle_ticker_timeframe_timestamp 
            ON candle_history(ticker, timeframe, timestamp DESC)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_candle_timestamp 
            ON candle_history(timestamp DESC)
        ''')
        
        # ============================================================
        # TABLE 2: SIGNAL RECOMMENDATIONS
        # Stores every signal the app generates
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signal_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                
                -- Basic Signal Info
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT', 'NO_TRADE')),
                entry REAL,
                stop REAL,
                target REAL,
                
                -- Confidence & Outcome
                confidence_score INTEGER NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 100),
                outcome TEXT DEFAULT 'PENDING' CHECK (outcome IN ('PENDING', 'WIN', 'LOSS', 'DISCARDED')),
                
                -- Exit Information
                exit_price REAL,
                exit_time DATETIME,
                pnl_ticks REAL,
                
                -- Calculated Metrics
                risk_reward_ratio REAL,
                
                -- Timing Context
                recommended_at DATETIME NOT NULL,
                time_of_day TIME,
                day_of_week TEXT,
                
                -- AI Analysis
                rationale TEXT,
                entry_type TEXT,
                
                -- Strategy Version (for tracking improvements)
                strategy_version TEXT DEFAULT '1.0',
                
                -- Timestamps
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Indexes for performance
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_signal_ticker_outcome 
            ON signal_recommendations(ticker, outcome)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_signal_outcome 
            ON signal_recommendations(outcome)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_signal_confidence 
            ON signal_recommendations(confidence_score, outcome)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_signal_recommended_at 
            ON signal_recommendations(recommended_at DESC)
        ''')
        
        # ============================================================
        # TABLE 3: SIGNAL FEATURES
        # Stores all MTF analysis data for each signal (for AI learning)
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signal_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                
                -- 15-MINUTE TIMEFRAME DATA
                tf15_trend TEXT,
                tf15_strength TEXT,
                tf15_structure TEXT,
                tf15_open REAL,
                tf15_high REAL,
                tf15_low REAL,
                tf15_close REAL,
                tf15_range REAL,
                tf15_body_size REAL,
                tf15_body_percent REAL,
                
                -- 5-MINUTE TIMEFRAME DATA
                tf5_trend TEXT,
                tf5_strength TEXT,
                tf5_structure TEXT,
                tf5_open REAL,
                tf5_high REAL,
                tf5_low REAL,
                tf5_close REAL,
                tf5_range REAL,
                tf5_body_size REAL,
                tf5_body_percent REAL,
                tf5_alignment_with_tf15 INTEGER,
                
                -- 1-MINUTE TIMEFRAME DATA (ENTRY TRIGGER)
                tf1_trend TEXT,
                tf1_open REAL,
                tf1_high REAL,
                tf1_low REAL,
                tf1_close REAL,
                tf1_range REAL,
                tf1_body_size REAL,
                tf1_body_percent REAL,
                tf1_is_momentum_candle INTEGER,
                
                -- ALIGNMENT & CONFLUENCE
                all_timeframes_aligned INTEGER,
                num_timeframes_aligned INTEGER CHECK (num_timeframes_aligned >= 0 AND num_timeframes_aligned <= 3),
                higher_tf_aligned INTEGER,
                
                -- MARKET CONTEXT
                time_category TEXT,
                hour_of_day INTEGER CHECK (hour_of_day >= 0 AND hour_of_day <= 23),
                minute_of_hour INTEGER CHECK (minute_of_hour >= 0 AND minute_of_hour <= 59),
                
                -- Timestamps
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                
                -- Foreign Key
                FOREIGN KEY (signal_id) REFERENCES signal_recommendations(id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_feature_signal_id 
            ON signal_features(signal_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_feature_alignment 
            ON signal_features(all_timeframes_aligned)
        ''')
        
        # ============================================================
        # TABLE 4: STRATEGY VERSIONS
        # Tracks changes to the strategy over time
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL UNIQUE,
                description TEXT,
                confidence_formula TEXT,
                applied_filters TEXT,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                
                -- Performance tracking
                signals_generated INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                win_rate REAL,
                avg_risk_reward REAL,
                
                -- Status
                is_active INTEGER DEFAULT 1,
                
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # ============================================================
        # TABLE 5: DAILY STATS (for Apex Tracking)
        # ============================================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                total_signals INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                total_pnl_ticks REAL DEFAULT 0,
                total_pnl_dollars REAL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Insert initial strategy version if not exists
        cursor.execute('SELECT COUNT(*) FROM strategy_versions')
        if cursor.fetchone()[0] == 0:
            cursor.execute('''
                INSERT INTO strategy_versions (version, description, is_active)
                VALUES ('1.0', 'Initial baseline strategy - MTF alignment', 1)
            ''')
        
        conn.commit()
        conn.close()
        print("✅ Database initialized (enhanced schema)")


# ==================== TICKER HELPERS ====================

def get_ticker_list():
    """Get list of ticker symbols for scanner"""
    return [f"{t}=F" for t in TICKERS.keys()]


def get_ticker_settings(symbol):
    """Get ticker-specific settings"""
    base = symbol.replace('=F', '').upper()
    return TICKERS.get(base, TICKERS['MNQ'])


# ==================== SIGNAL MANAGEMENT ====================

def save_signal(signal_data, features_data=None):
    """
    Save a new signal to the database with optional features
    Returns the signal ID
    """
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        now = datetime.now()
        direction = signal_data.get('direction', 'NO_TRADE').upper()
        if direction not in ('LONG', 'SHORT', 'NO_TRADE'):
            direction = 'NO_TRADE'
        
        # Calculate risk:reward if we have entry, stop, target
        entry = signal_data.get('entry')
        stop = signal_data.get('stop')
        target = signal_data.get('takeProfit') or signal_data.get('target')
        rr_ratio = None
        
        if entry and stop and target and direction in ('LONG', 'SHORT'):
            risk = abs(entry - stop)
            reward = abs(target - entry)
            rr_ratio = round(reward / risk, 2) if risk > 0 else None
        
        cursor.execute('''
            INSERT INTO signal_recommendations (
                ticker, direction, entry, stop, target,
                confidence_score, risk_reward_ratio,
                recommended_at, time_of_day, day_of_week,
                rationale, entry_type, strategy_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal_data.get('ticker', 'UNKNOWN'),
            direction,
            entry,
            stop,
            target,
            signal_data.get('confidence', 0),
            rr_ratio,
            now.strftime('%Y-%m-%d %H:%M:%S'),
            now.strftime('%H:%M:%S'),
            now.strftime('%A'),
            signal_data.get('rationale', ''),
            signal_data.get('entryType', 'UNKNOWN'),
            '1.0'
        ))
        
        signal_id = cursor.lastrowid
        
        # Save features if provided
        if features_data and signal_id:
            save_signal_features(cursor, signal_id, features_data)
        
        # Update strategy version stats
        cursor.execute('''
            UPDATE strategy_versions 
            SET signals_generated = signals_generated + 1
            WHERE is_active = 1
        ''')
        
        conn.commit()
        conn.close()
        
        return signal_id


def save_signal_features(cursor, signal_id, features):
    """Save MTF features for a signal (called within transaction)"""
    now = datetime.now()
    
    cursor.execute('''
        INSERT INTO signal_features (
            signal_id,
            tf15_trend, tf15_strength, tf15_open, tf15_high, tf15_low, tf15_close,
            tf5_trend, tf5_strength, tf5_open, tf5_high, tf5_low, tf5_close, tf5_alignment_with_tf15,
            tf1_trend, tf1_open, tf1_high, tf1_low, tf1_close, tf1_is_momentum_candle,
            all_timeframes_aligned, num_timeframes_aligned, higher_tf_aligned,
            time_category, hour_of_day, minute_of_hour
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        signal_id,
        features.get('tf15_trend'),
        features.get('tf15_strength'),
        features.get('tf15_open'),
        features.get('tf15_high'),
        features.get('tf15_low'),
        features.get('tf15_close'),
        features.get('tf5_trend'),
        features.get('tf5_strength'),
        features.get('tf5_open'),
        features.get('tf5_high'),
        features.get('tf5_low'),
        features.get('tf5_close'),
        1 if features.get('tf5_alignment_with_tf15') else 0,
        features.get('tf1_trend'),
        features.get('tf1_open'),
        features.get('tf1_high'),
        features.get('tf1_low'),
        features.get('tf1_close'),
        1 if features.get('tf1_is_momentum_candle') else 0,
        1 if features.get('all_timeframes_aligned') else 0,
        features.get('num_timeframes_aligned', 0),
        1 if features.get('higher_tf_aligned') else 0,
        features.get('time_category', get_time_category(now.hour)),
        now.hour,
        now.minute
    ))


def get_time_category(hour):
    """Get time category based on hour"""
    if 9 <= hour < 10:
        return 'MARKET_OPEN'
    elif 10 <= hour < 12:
        return 'MORNING'
    elif 12 <= hour < 14:
        return 'MIDDAY'
    elif 14 <= hour < 16:
        return 'AFTERNOON'
    else:
        return 'OTHER'


def update_signal_outcome(signal_id, outcome, exit_price, pnl_ticks):
    """Update signal with outcome (WIN/LOSS)"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        outcome_upper = outcome.upper() if outcome else 'PENDING'
        if outcome_upper not in ('WIN', 'LOSS', 'DISCARDED'):
            outcome_upper = 'PENDING'
        
        cursor.execute('''
            UPDATE signal_recommendations 
            SET outcome = ?, exit_price = ?, exit_time = ?, pnl_ticks = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (
            outcome_upper,
            exit_price,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            pnl_ticks,
            signal_id
        ))
        
        # Update strategy version stats
        if outcome_upper in ('WIN', 'LOSS'):
            cursor.execute(f'''
                UPDATE strategy_versions 
                SET {outcome_upper.lower()}s = {outcome_upper.lower()}s + 1,
                    win_rate = CAST(wins AS REAL) / NULLIF(wins + losses, 0) * 100
                WHERE is_active = 1
            ''')
        
        conn.commit()
        conn.close()
        
        # Update daily stats
        update_daily_stats(outcome_upper, pnl_ticks)


def update_daily_stats(outcome, pnl_ticks):
    """Update daily statistics"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM daily_stats WHERE date = ?', (today,))
        row = cursor.fetchone()
        
        if row:
            wins = row['wins'] + (1 if outcome == 'WIN' else 0)
            losses = row['losses'] + (1 if outcome == 'LOSS' else 0)
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
                1 if outcome == 'WIN' else 0,
                1 if outcome == 'LOSS' else 0,
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
            SELECT id, ticker, direction, entry as entry_price, stop as stop_price, 
                   target as target_price, confidence_score as confidence,
                   recommended_at as timestamp, outcome
            FROM signal_recommendations 
            WHERE outcome = 'PENDING' AND direction IN ('LONG', 'SHORT')
            ORDER BY recommended_at DESC
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
            SELECT id, ticker, direction, entry as entry_price, stop as stop_price,
                   target as target_price, confidence_score as confidence,
                   outcome, exit_price as outcome_price, pnl_ticks,
                   recommended_at as timestamp, rationale, entry_type,
                   risk_reward_ratio, time_of_day, day_of_week
            FROM signal_recommendations 
            ORDER BY recommended_at DESC
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
        
        cursor.execute('''
            SELECT 
                COUNT(*) as total_signals,
                SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN outcome = 'PENDING' THEN 1 ELSE 0 END) as pending,
                SUM(COALESCE(pnl_ticks, 0)) as total_pnl,
                AVG(CASE WHEN outcome IN ('WIN', 'LOSS') THEN pnl_ticks END) as avg_pnl,
                AVG(CASE WHEN outcome IN ('WIN', 'LOSS') THEN risk_reward_ratio END) as avg_rr
            FROM signal_recommendations
            WHERE direction IN ('LONG', 'SHORT')
        ''')
        
        stats = dict(cursor.fetchone())
        
        completed = (stats['wins'] or 0) + (stats['losses'] or 0)
        stats['win_rate'] = round((stats['wins'] or 0) / completed * 100, 1) if completed > 0 else 0
        
        # Best ticker
        cursor.execute('''
            SELECT ticker, 
                   SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                   COUNT(*) as total
            FROM signal_recommendations
            WHERE outcome IN ('WIN', 'LOSS')
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


# ==================== CANDLE STORAGE ====================

def save_candle(ticker, timeframe, candle_data):
    """Save a single candle to database"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        base_ticker = ticker.split(':')[-1].replace('=F', '').upper()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO candle_history 
                (ticker, timeframe, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                base_ticker,
                timeframe,
                candle_data.get('time', ''),
                float(candle_data.get('open', 0)),
                float(candle_data.get('high', 0)),
                float(candle_data.get('low', 0)),
                float(candle_data.get('close', 0)),
                float(candle_data.get('volume', 0))
            ))
            conn.commit()
        except Exception as e:
            print(f"⚠️  Error saving candle: {e}")
        finally:
            conn.close()


def save_candles_batch(ticker, timeframe, candles):
    """Save multiple candles efficiently"""
    if not candles:
        return 0
    
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        base_ticker = ticker.split(':')[-1].replace('=F', '').upper()
        
        data = [
            (base_ticker, timeframe, c.get('time', ''),
             float(c.get('open', 0)), float(c.get('high', 0)),
             float(c.get('low', 0)), float(c.get('close', 0)),
             float(c.get('volume', 0)))
            for c in candles if c.get('time')
        ]
        
        try:
            cursor.executemany('''
                INSERT OR REPLACE INTO candle_history 
                (ticker, timeframe, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', data)
            conn.commit()
            count = len(data)
            conn.close()
            return count
        except Exception as e:
            print(f"⚠️  Error saving candles batch: {e}")
            conn.close()
            return 0


def load_candles(ticker, timeframe, limit=100):
    """Load candles from database for a ticker/timeframe"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        base_ticker = ticker.split(':')[-1].replace('=F', '').upper()
        
        cursor.execute('''
            SELECT timestamp, open, high, low, close, volume
            FROM candle_history
            WHERE ticker = ? AND timeframe = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (base_ticker, timeframe, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {'time': row['timestamp'], 'open': row['open'], 'high': row['high'],
             'low': row['low'], 'close': row['close'], 'volume': row['volume']}
            for row in reversed(rows)
        ]


def load_all_candles():
    """Load all candles organized by ticker and timeframe"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT DISTINCT ticker, timeframe FROM candle_history')
        combos = cursor.fetchall()
        
        result = {}
        
        for row in combos:
            ticker = row['ticker']
            timeframe = row['timeframe']
            
            if ticker not in result:
                result[ticker] = {'1m': [], '5m': [], '15m': []}
            
            limit = 100 if timeframe == '1m' else 50 if timeframe == '5m' else 30
            cursor.execute('''
                SELECT timestamp, open, high, low, close, volume
                FROM candle_history
                WHERE ticker = ? AND timeframe = ?
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (ticker, timeframe, limit))
            
            result[ticker][timeframe] = [
                {'time': r['timestamp'], 'open': r['open'], 'high': r['high'],
                 'low': r['low'], 'close': r['close'], 'volume': r['volume']}
                for r in reversed(cursor.fetchall())
            ]
        
        conn.close()
        return result


def get_candle_counts():
    """Get count of candles per ticker/timeframe"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT ticker, timeframe, COUNT(*) as count
            FROM candle_history
            GROUP BY ticker, timeframe
            ORDER BY ticker, timeframe
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        result = {}
        for row in rows:
            ticker = row['ticker']
            if ticker not in result:
                result[ticker] = {}
            result[ticker][row['timeframe']] = row['count']
        
        return result


def clear_old_candles(days=7):
    """Clear candles older than N days"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM candle_history 
            WHERE created_at < datetime('now', ?)
        ''', (f'-{days} days',))
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted > 0:
            print(f"🧹 Cleaned {deleted} old candles")
        return deleted


def clear_all_candles():
    """Clear all candle data"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM candle_history')
        conn.commit()
        conn.close()
        print("🗑️  All candles cleared")


# ==================== AI LEARNING QUERIES ====================

def get_signals_with_features(outcome_filter=None, limit=500):
    """Get signals with their MTF features for AI analysis"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        query = '''
            SELECT sr.*, sf.*
            FROM signal_recommendations sr
            LEFT JOIN signal_features sf ON sr.id = sf.signal_id
            WHERE sr.direction IN ('LONG', 'SHORT')
        '''
        
        if outcome_filter:
            query += f" AND sr.outcome = '{outcome_filter}'"
        
        query += ' ORDER BY sr.recommended_at DESC LIMIT ?'
        
        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


def get_win_rate_by_confidence():
    """Get win rate grouped by confidence buckets"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                CASE 
                    WHEN confidence_score >= 90 THEN '90-100'
                    WHEN confidence_score >= 80 THEN '80-89'
                    WHEN confidence_score >= 70 THEN '70-79'
                    WHEN confidence_score >= 60 THEN '60-69'
                    ELSE '50-59'
                END as confidence_bucket,
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                ROUND(100.0 * SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
            FROM signal_recommendations
            WHERE outcome IN ('WIN', 'LOSS')
            GROUP BY confidence_bucket
            ORDER BY confidence_score DESC
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


def get_win_rate_by_alignment():
    """Get win rate based on timeframe alignment"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                sf.all_timeframes_aligned,
                sf.num_timeframes_aligned,
                COUNT(*) as total,
                SUM(CASE WHEN sr.outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                ROUND(100.0 * SUM(CASE WHEN sr.outcome = 'WIN' THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
            FROM signal_recommendations sr
            JOIN signal_features sf ON sr.id = sf.signal_id
            WHERE sr.outcome IN ('WIN', 'LOSS')
            GROUP BY sf.all_timeframes_aligned, sf.num_timeframes_aligned
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


def get_strategy_version_stats():
    """Get performance stats for all strategy versions"""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM strategy_versions ORDER BY applied_at DESC')
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


# Initialize database on import
init_database()
