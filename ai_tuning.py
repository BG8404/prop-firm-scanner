"""
AI Self-Tuning Engine
Analyzes historical performance to optimize scanner settings

Features:
- Find optimal confidence threshold
- Identify best risk:reward ratios
- Recommend ticker-specific settings
- Auto-adjustment based on recent performance
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict

# Database path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_journal.db')
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
TUNING_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tuning_log.json')


def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def load_settings():
    """Load current scanner settings"""
    default = {
        "scan_interval": 2,
        "min_confidence": 80,
        "min_risk_reward": 2.0,
        "tickers": ["MNQ=F", "MES=F", "MGC=F"]
    }
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return default


def save_settings(settings):
    """Save scanner settings"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        print(f"⚠️  Error saving settings: {e}")
        return False


def log_tuning_action(action_type, old_value, new_value, reason, metrics):
    """Log tuning actions for transparency"""
    try:
        log = []
        if os.path.exists(TUNING_LOG_FILE):
            with open(TUNING_LOG_FILE, 'r') as f:
                log = json.load(f)
        
        log.append({
            "timestamp": datetime.now().isoformat(),
            "action": action_type,
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
            "metrics": metrics
        })
        
        # Keep last 100 entries
        log = log[-100:]
        
        with open(TUNING_LOG_FILE, 'w') as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        print(f"⚠️  Error logging tuning action: {e}")


def get_tuning_history():
    """Get tuning action history"""
    try:
        if os.path.exists(TUNING_LOG_FILE):
            with open(TUNING_LOG_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return []


def analyze_confidence_thresholds(min_trades=10):
    """
    Analyze which confidence levels perform best
    
    Returns optimal confidence threshold recommendation
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get performance at each confidence level
    cursor.execute('''
        SELECT 
            confidence,
            outcome,
            pnl_ticks
        FROM signals
        WHERE outcome IN ('win', 'loss') AND is_valid = 1
        ORDER BY confidence
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) < min_trades:
        return {
            "status": "insufficient_data",
            "message": f"Need at least {min_trades} completed trades for analysis",
            "current_trades": len(rows)
        }
    
    # Group by confidence threshold (what if we only took signals >= X)
    thresholds = list(range(50, 96, 5))  # 50, 55, 60, ..., 95
    results = []
    
    for threshold in thresholds:
        # Filter signals at or above this threshold
        filtered = [r for r in rows if r['confidence'] >= threshold]
        
        if len(filtered) < 5:  # Need at least 5 trades
            continue
        
        wins = sum(1 for r in filtered if r['outcome'] == 'win')
        losses = sum(1 for r in filtered if r['outcome'] == 'loss')
        total = wins + losses
        
        if total == 0:
            continue
        
        win_rate = wins / total * 100
        total_pnl = sum(r['pnl_ticks'] or 0 for r in filtered)
        avg_pnl = total_pnl / total if total > 0 else 0
        
        # Calculate profit factor
        gross_profit = sum(r['pnl_ticks'] for r in filtered if r['outcome'] == 'win' and r['pnl_ticks'])
        gross_loss = abs(sum(r['pnl_ticks'] for r in filtered if r['outcome'] == 'loss' and r['pnl_ticks']))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Calculate expectancy (average expected value per trade)
        avg_win = gross_profit / wins if wins > 0 else 0
        avg_loss = gross_loss / losses if losses > 0 else 0
        expectancy = (win_rate/100 * avg_win) - ((1 - win_rate/100) * avg_loss)
        
        results.append({
            "threshold": threshold,
            "trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "∞",
            "expectancy": round(expectancy, 2)
        })
    
    if not results:
        return {
            "status": "insufficient_data",
            "message": "Not enough trades at various confidence levels"
        }
    
    # Find optimal threshold (balance of expectancy, trades, and profit factor)
    def score_threshold(r):
        # Higher is better
        pf = r['profit_factor'] if isinstance(r['profit_factor'], (int, float)) else 10
        trade_score = min(r['trades'] / 20, 1)  # More trades = better, up to 20
        return r['expectancy'] * 0.4 + (pf * 0.3) + (trade_score * 0.3 * r['expectancy'])
    
    best = max(results, key=score_threshold)
    
    return {
        "status": "success",
        "analysis": results,
        "optimal_threshold": best['threshold'],
        "optimal_metrics": best,
        "recommendation": f"Set confidence threshold to {best['threshold']}% for best risk-adjusted returns"
    }


def analyze_risk_reward():
    """
    Analyze which R:R ratios perform best
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            entry_price,
            stop_price,
            target_price,
            outcome,
            pnl_ticks
        FROM signals
        WHERE outcome IN ('win', 'loss') 
        AND entry_price IS NOT NULL 
        AND stop_price IS NOT NULL 
        AND target_price IS NOT NULL
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) < 10:
        return {
            "status": "insufficient_data",
            "message": "Need at least 10 completed trades with price levels"
        }
    
    # Calculate R:R for each trade
    trades_by_rr = defaultdict(list)
    
    for row in rows:
        try:
            risk = abs(float(row['entry_price']) - float(row['stop_price']))
            reward = abs(float(row['target_price']) - float(row['entry_price']))
            
            if risk > 0:
                rr = reward / risk
                # Bucket into ranges
                if rr < 1.5:
                    bucket = "< 1.5"
                elif rr < 2.0:
                    bucket = "1.5-2.0"
                elif rr < 2.5:
                    bucket = "2.0-2.5"
                elif rr < 3.0:
                    bucket = "2.5-3.0"
                else:
                    bucket = "> 3.0"
                
                trades_by_rr[bucket].append({
                    "outcome": row['outcome'],
                    "pnl": row['pnl_ticks'] or 0,
                    "rr": rr
                })
        except (ValueError, TypeError):
            continue
    
    results = []
    for bucket, trades in sorted(trades_by_rr.items()):
        if len(trades) < 3:
            continue
        
        wins = sum(1 for t in trades if t['outcome'] == 'win')
        total = len(trades)
        win_rate = wins / total * 100
        total_pnl = sum(t['pnl'] for t in trades)
        
        results.append({
            "rr_range": bucket,
            "trades": total,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_rr": round(sum(t['rr'] for t in trades) / total, 2)
        })
    
    # Find best performing R:R range
    best = max(results, key=lambda x: x['total_pnl']) if results else None
    
    return {
        "status": "success" if results else "insufficient_data",
        "analysis": results,
        "best_range": best['rr_range'] if best else None,
        "recommendation": f"R:R range {best['rr_range']} shows best performance" if best else None
    }


def analyze_ticker_settings():
    """
    Analyze if different tickers need different settings
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            ticker,
            confidence,
            outcome,
            pnl_ticks
        FROM signals
        WHERE outcome IN ('win', 'loss') AND is_valid = 1
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    ticker_data = defaultdict(list)
    for row in rows:
        ticker_data[row['ticker']].append({
            "confidence": row['confidence'],
            "outcome": row['outcome'],
            "pnl": row['pnl_ticks'] or 0
        })
    
    recommendations = {}
    
    for ticker, trades in ticker_data.items():
        if len(trades) < 10:
            continue
        
        # Find optimal confidence for this ticker
        best_threshold = None
        best_win_rate = 0
        
        for threshold in range(50, 96, 5):
            filtered = [t for t in trades if t['confidence'] >= threshold]
            if len(filtered) < 5:
                continue
            
            wins = sum(1 for t in filtered if t['outcome'] == 'win')
            win_rate = wins / len(filtered) * 100
            
            if win_rate > best_win_rate:
                best_win_rate = win_rate
                best_threshold = threshold
        
        if best_threshold:
            overall_wins = sum(1 for t in trades if t['outcome'] == 'win')
            overall_win_rate = overall_wins / len(trades) * 100
            
            recommendations[ticker] = {
                "total_trades": len(trades),
                "overall_win_rate": round(overall_win_rate, 1),
                "recommended_threshold": best_threshold,
                "win_rate_at_threshold": round(best_win_rate, 1),
                "improvement": round(best_win_rate - overall_win_rate, 1)
            }
    
    return {
        "status": "success" if recommendations else "insufficient_data",
        "ticker_recommendations": recommendations
    }


def get_optimization_summary():
    """
    Get comprehensive optimization recommendations
    """
    confidence_analysis = analyze_confidence_thresholds()
    rr_analysis = analyze_risk_reward()
    ticker_analysis = analyze_ticker_settings()
    
    current_settings = load_settings()
    
    recommendations = []
    
    # Confidence recommendation
    if confidence_analysis.get('status') == 'success':
        optimal = confidence_analysis['optimal_threshold']
        current = current_settings.get('min_confidence', 70)
        
        if optimal != current:
            recommendations.append({
                "type": "confidence_threshold",
                "current": current,
                "recommended": optimal,
                "impact": confidence_analysis['optimal_metrics'],
                "reason": confidence_analysis['recommendation']
            })
    
    # R:R recommendation
    if rr_analysis.get('status') == 'success' and rr_analysis.get('best_range'):
        best_range = rr_analysis['best_range']
        current_rr = current_settings.get('min_risk_reward', 2.0)
        
        # Parse range to get minimum
        if best_range == "< 1.5":
            recommended_rr = 1.0
        elif best_range == "1.5-2.0":
            recommended_rr = 1.5
        elif best_range == "2.0-2.5":
            recommended_rr = 2.0
        elif best_range == "2.5-3.0":
            recommended_rr = 2.5
        else:
            recommended_rr = 3.0
        
        if recommended_rr != current_rr:
            recommendations.append({
                "type": "risk_reward",
                "current": current_rr,
                "recommended": recommended_rr,
                "reason": rr_analysis['recommendation']
            })
    
    return {
        "current_settings": current_settings,
        "confidence_analysis": confidence_analysis,
        "rr_analysis": rr_analysis,
        "ticker_analysis": ticker_analysis,
        "recommendations": recommendations,
        "auto_tune_available": len(recommendations) > 0
    }


def auto_tune(apply_changes=False, conservative=True):
    """
    Automatically tune settings based on analysis
    
    Args:
        apply_changes: If True, actually applies changes to settings
        conservative: If True, only make changes with strong evidence
    
    Returns:
        Dict with proposed/applied changes
    """
    summary = get_optimization_summary()
    
    if not summary['recommendations']:
        return {
            "status": "no_changes",
            "message": "Current settings appear optimal based on available data"
        }
    
    current_settings = load_settings()
    proposed_changes = {}
    applied_changes = {}
    
    for rec in summary['recommendations']:
        rec_type = rec['type']
        
        # Apply conservative filters
        if conservative:
            if rec_type == 'confidence_threshold':
                # Only change if we have enough evidence
                if summary['confidence_analysis'].get('optimal_metrics', {}).get('trades', 0) < 20:
                    continue
                # Don't change by more than 10 points at a time
                diff = abs(rec['recommended'] - rec['current'])
                if diff > 10:
                    rec['recommended'] = rec['current'] + (10 if rec['recommended'] > rec['current'] else -10)
        
        proposed_changes[rec_type] = {
            "from": rec['current'],
            "to": rec['recommended'],
            "reason": rec.get('reason', 'Based on performance analysis')
        }
        
        if apply_changes:
            if rec_type == 'confidence_threshold':
                current_settings['min_confidence'] = rec['recommended']
                applied_changes['min_confidence'] = rec['recommended']
            elif rec_type == 'risk_reward':
                current_settings['min_risk_reward'] = rec['recommended']
                applied_changes['min_risk_reward'] = rec['recommended']
    
    if apply_changes and applied_changes:
        save_settings(current_settings)
        
        # Log the tuning action
        for change_type, new_value in applied_changes.items():
            old_value = proposed_changes.get(
                'confidence_threshold' if change_type == 'min_confidence' else 'risk_reward',
                {}
            ).get('from')
            log_tuning_action(
                change_type,
                old_value,
                new_value,
                proposed_changes.get(
                    'confidence_threshold' if change_type == 'min_confidence' else 'risk_reward',
                    {}
                ).get('reason'),
                summary.get('confidence_analysis', {}).get('optimal_metrics', {})
            )
    
    return {
        "status": "applied" if apply_changes else "proposed",
        "proposed_changes": proposed_changes,
        "applied_changes": applied_changes if apply_changes else None,
        "new_settings": current_settings if apply_changes else None,
        "analysis_summary": {
            "confidence": summary['confidence_analysis'].get('status'),
            "rr": summary['rr_analysis'].get('status'),
            "tickers": summary['ticker_analysis'].get('status')
        }
    }


def get_performance_trend(days=14):
    """
    Analyze recent performance trend to detect degradation
    
    Returns True if performance is declining
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get recent performance by week
    cursor.execute('''
        SELECT 
            CAST(strftime('%W', timestamp) AS INTEGER) as week,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
            SUM(COALESCE(pnl_ticks, 0)) as pnl
        FROM signals
        WHERE outcome IN ('win', 'loss')
        AND DATE(timestamp) >= DATE('now', ?)
        GROUP BY week
        ORDER BY week
    ''', (f'-{days} days',))
    
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) < 2:
        return {
            "status": "insufficient_data",
            "trend": "unknown"
        }
    
    # Calculate trend
    pnls = [row['pnl'] for row in rows]
    win_rates = [(row['wins'] / (row['wins'] + row['losses']) * 100) if (row['wins'] + row['losses']) > 0 else 0 for row in rows]
    
    # Simple trend: compare first half to second half
    mid = len(pnls) // 2
    first_half_avg = sum(pnls[:mid]) / mid if mid > 0 else 0
    second_half_avg = sum(pnls[mid:]) / (len(pnls) - mid) if (len(pnls) - mid) > 0 else 0
    
    trend = "improving" if second_half_avg > first_half_avg else "declining" if second_half_avg < first_half_avg else "stable"
    
    return {
        "status": "success",
        "trend": trend,
        "first_period_avg_pnl": round(first_half_avg, 2),
        "recent_period_avg_pnl": round(second_half_avg, 2),
        "should_review_settings": trend == "declining"
    }


print("✅ AI Self-Tuning engine loaded")

