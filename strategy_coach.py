"""
AI Strategy Coach
Continuously analyzes trading performance and suggests improvements
with clear explanations for user approval.

Features:
- Prompt Evolution Analysis
- Smart Filter Optimization
- Pattern Recognition
- Time Optimization
- Market Regime Detection
"""

import json
import os
import re
from datetime import datetime, timedelta
from collections import defaultdict
import math

# Import shared database connection
from database import get_connection


# Statistical helper functions
def calculate_significance(wins1, total1, wins2, total2):
    """
    Calculate if difference between two win rates is statistically significant
    Using chi-square approximation
    Returns p-value estimate
    """
    if total1 < 5 or total2 < 5:
        return 1.0  # Not significant with small samples
    
    rate1 = wins1 / total1
    rate2 = wins2 / total2
    pooled = (wins1 + wins2) / (total1 + total2)
    
    if pooled == 0 or pooled == 1:
        return 1.0
    
    se = math.sqrt(pooled * (1 - pooled) * (1/total1 + 1/total2))
    if se == 0:
        return 1.0
    
    z = abs(rate1 - rate2) / se
    
    # Approximate p-value from z-score
    if z > 2.58:
        return 0.01
    elif z > 1.96:
        return 0.05
    elif z > 1.64:
        return 0.10
    else:
        return 0.5


def get_trade_data(min_trades=20):
    """Get all completed trades for analysis"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM signals
        WHERE outcome IN ('win', 'loss') AND is_valid = 1
        ORDER BY timestamp DESC
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) < min_trades:
        return None, f"Need at least {min_trades} trades for analysis (have {len(rows)})"
    
    return [dict(row) for row in rows], None


# ============ ANALYZER MODULES ============

class PromptEvolutionAnalyzer:
    """
    Analyzes AI rationales to identify patterns that correlate with wins
    """
    
    # Key phrases to track in rationales
    KEY_PHRASES = [
        'bos', 'break of structure', 'displacement', 'liquidity sweep',
        'fair value gap', 'fvg', 'order block', 'pullback', 'retracement',
        'trend continuation', 'reversal', 'momentum', 'volume', 'confluence',
        'support', 'resistance', 'higher high', 'lower low', 'choch',
        'change of character', 'imbalance', 'mitigation'
    ]
    
    def analyze(self, trades):
        """Analyze rationales for winning vs losing patterns"""
        if not trades:
            return []
        
        suggestions = []
        phrase_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0})
        
        # Count phrase occurrences in wins vs losses
        for trade in trades:
            rationale = (trade.get('rationale') or '').lower()
            outcome = trade['outcome']
            
            for phrase in self.KEY_PHRASES:
                if phrase in rationale:
                    phrase_stats[phrase]['total'] += 1
                    if outcome == 'win':
                        phrase_stats[phrase]['wins'] += 1
                    else:
                        phrase_stats[phrase]['losses'] += 1
        
        # Calculate overall win rate
        total_wins = sum(1 for t in trades if t['outcome'] == 'win')
        overall_rate = total_wins / len(trades) * 100
        
        # Find phrases with significantly different win rates
        for phrase, stats in phrase_stats.items():
            if stats['total'] < 5:
                continue
            
            phrase_rate = stats['wins'] / stats['total'] * 100
            diff = phrase_rate - overall_rate
            
            # Check statistical significance
            p_value = calculate_significance(
                stats['wins'], stats['total'],
                total_wins, len(trades)
            )
            
            if abs(diff) >= 10 and p_value < 0.1:
                if diff > 0:
                    suggestions.append({
                        'type': 'prompt',
                        'category': 'phrase_emphasis',
                        'title': f'Emphasize "{phrase.upper()}" in Analysis',
                        'explanation': f'Signals mentioning "{phrase}" have a {phrase_rate:.0f}% win rate vs {overall_rate:.0f}% overall ({stats["total"]} trades). This {diff:+.0f}% difference suggests this pattern is a strong predictor of success.',
                        'action': f'Add emphasis to AI prompt: "Pay special attention to {phrase} setups as they show strong historical performance."',
                        'projected_impact': f'+{diff:.0f}% win rate when present',
                        'confidence': min(stats['total'] / 20, 1.0),
                        'sample_size': stats['total'],
                        'p_value': p_value,
                        'data': {
                            'phrase': phrase,
                            'phrase_win_rate': phrase_rate,
                            'overall_win_rate': overall_rate,
                            'occurrences': stats['total']
                        }
                    })
                else:
                    suggestions.append({
                        'type': 'prompt',
                        'category': 'phrase_caution',
                        'title': f'Add Caution for "{phrase.upper()}" Setups',
                        'explanation': f'Signals mentioning "{phrase}" have only a {phrase_rate:.0f}% win rate vs {overall_rate:.0f}% overall ({stats["total"]} trades). This pattern may be leading to lower quality signals.',
                        'action': f'Add caution to AI prompt: "Be more selective with {phrase} setups - require additional confluence."',
                        'projected_impact': f'Filtering these could improve overall win rate',
                        'confidence': min(stats['total'] / 20, 1.0),
                        'sample_size': stats['total'],
                        'p_value': p_value,
                        'data': {
                            'phrase': phrase,
                            'phrase_win_rate': phrase_rate,
                            'overall_win_rate': overall_rate,
                            'occurrences': stats['total']
                        }
                    })
        
        return suggestions


class SmartFilterOptimizer:
    """
    Analyzes filter combinations to find optimal settings
    """
    
    def analyze(self, trades):
        """Test various filter combinations"""
        if not trades:
            return []
        
        suggestions = []
        
        # Current baseline
        total_wins = sum(1 for t in trades if t['outcome'] == 'win')
        baseline_rate = total_wins / len(trades) * 100
        baseline_pnl = sum(t.get('pnl_ticks') or 0 for t in trades)
        
        # Test confidence thresholds
        confidence_results = self._test_confidence_thresholds(trades, baseline_rate)
        suggestions.extend(confidence_results)
        
        # Test R:R combinations
        rr_results = self._test_rr_thresholds(trades, baseline_rate)
        suggestions.extend(rr_results)
        
        # Test combination filters
        combo_results = self._test_combinations(trades, baseline_rate)
        suggestions.extend(combo_results)
        
        return suggestions
    
    def _test_confidence_thresholds(self, trades, baseline_rate):
        """Test different confidence thresholds"""
        suggestions = []
        
        for threshold in [75, 80, 85, 90]:
            filtered = [t for t in trades if t.get('confidence', 0) >= threshold]
            
            if len(filtered) < 10:
                continue
            
            wins = sum(1 for t in filtered if t['outcome'] == 'win')
            rate = wins / len(filtered) * 100
            diff = rate - baseline_rate
            
            p_value = calculate_significance(wins, len(filtered), 
                sum(1 for t in trades if t['outcome'] == 'win'), len(trades))
            
            if diff >= 5 and p_value < 0.1:
                # Calculate trade reduction
                reduction = (1 - len(filtered) / len(trades)) * 100
                
                suggestions.append({
                    'type': 'filter',
                    'category': 'confidence_threshold',
                    'title': f'Increase Confidence Threshold to {threshold}%',
                    'explanation': f'Signals with {threshold}%+ confidence have a {rate:.0f}% win rate vs {baseline_rate:.0f}% baseline. You would take {len(filtered)} trades instead of {len(trades)} ({reduction:.0f}% fewer), but with better quality.',
                    'action': f'Update min_confidence setting from current to {threshold}',
                    'projected_impact': f'+{diff:.0f}% win rate, -{reduction:.0f}% trade volume',
                    'confidence': min(len(filtered) / 30, 1.0),
                    'sample_size': len(filtered),
                    'p_value': p_value,
                    'data': {
                        'threshold': threshold,
                        'filtered_win_rate': rate,
                        'baseline_win_rate': baseline_rate,
                        'trades_filtered': len(filtered),
                        'trades_total': len(trades)
                    }
                })
        
        return suggestions
    
    def _test_rr_thresholds(self, trades, baseline_rate):
        """Test different R:R thresholds"""
        suggestions = []
        
        def calc_rr(trade):
            try:
                entry = trade.get('entry_price')
                stop = trade.get('stop_price')
                target = trade.get('target_price')
                if not all([entry, stop, target]):
                    return None
                risk = abs(float(entry) - float(stop))
                reward = abs(float(target) - float(entry))
                return reward / risk if risk > 0 else None
            except:
                return None
        
        for threshold in [2.0, 2.5, 3.0]:
            filtered = [t for t in trades if (calc_rr(t) or 0) >= threshold]
            
            if len(filtered) < 10:
                continue
            
            wins = sum(1 for t in filtered if t['outcome'] == 'win')
            rate = wins / len(filtered) * 100
            diff = rate - baseline_rate
            
            p_value = calculate_significance(wins, len(filtered),
                sum(1 for t in trades if t['outcome'] == 'win'), len(trades))
            
            if diff >= 5 and p_value < 0.1:
                reduction = (1 - len(filtered) / len(trades)) * 100
                
                suggestions.append({
                    'type': 'filter',
                    'category': 'rr_threshold',
                    'title': f'Increase R:R Requirement to {threshold}:1',
                    'explanation': f'Signals with {threshold}:1+ R:R have a {rate:.0f}% win rate vs {baseline_rate:.0f}% baseline. Higher R:R setups are performing better in your trading.',
                    'action': f'Update min_risk_reward setting to {threshold}',
                    'projected_impact': f'+{diff:.0f}% win rate, -{reduction:.0f}% trade volume',
                    'confidence': min(len(filtered) / 30, 1.0),
                    'sample_size': len(filtered),
                    'p_value': p_value,
                    'data': {
                        'threshold': threshold,
                        'filtered_win_rate': rate,
                        'baseline_win_rate': baseline_rate
                    }
                })
        
        return suggestions
    
    def _test_combinations(self, trades, baseline_rate):
        """Test combination filters"""
        suggestions = []
        
        # Test confidence + direction combinations
        for direction in ['long', 'short']:
            dir_trades = [t for t in trades if t.get('direction') == direction]
            if len(dir_trades) < 15:
                continue
            
            dir_wins = sum(1 for t in dir_trades if t['outcome'] == 'win')
            dir_rate = dir_wins / len(dir_trades) * 100
            diff = dir_rate - baseline_rate
            
            if abs(diff) >= 10:
                p_value = calculate_significance(dir_wins, len(dir_trades),
                    sum(1 for t in trades if t['outcome'] == 'win'), len(trades))
                
                if diff < -10 and p_value < 0.1:
                    opposite = 'short' if direction == 'long' else 'long'
                    suggestions.append({
                        'type': 'filter',
                        'category': 'direction_filter',
                        'title': f'Consider {opposite.upper()}-Only Mode',
                        'explanation': f'Your {direction} trades have a {dir_rate:.0f}% win rate vs {baseline_rate:.0f}% overall. {opposite.capitalize()} trades are significantly outperforming. Consider focusing on {opposite} setups until {direction} performance improves.',
                        'action': f'Add direction filter to prefer {opposite} trades',
                        'projected_impact': f'Could improve win rate by focusing on stronger direction',
                        'confidence': min(len(dir_trades) / 30, 1.0),
                        'sample_size': len(dir_trades),
                        'p_value': p_value,
                        'data': {
                            'weak_direction': direction,
                            'weak_rate': dir_rate,
                            'baseline_rate': baseline_rate
                        }
                    })
        
        return suggestions


class PatternRecognizer:
    """
    Identifies winning patterns and setup types
    """
    
    def analyze(self, trades):
        """Analyze patterns in winning vs losing trades"""
        if not trades:
            return []
        
        suggestions = []
        
        # Analyze by entry type
        entry_suggestions = self._analyze_entry_types(trades)
        suggestions.extend(entry_suggestions)
        
        # Analyze by ticker
        ticker_suggestions = self._analyze_tickers(trades)
        suggestions.extend(ticker_suggestions)
        
        return suggestions
    
    def _analyze_entry_types(self, trades):
        """Analyze performance by entry type"""
        suggestions = []
        entry_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0})
        
        for trade in trades:
            entry_type = trade.get('entry_type', 'UNKNOWN')
            entry_stats[entry_type]['total'] += 1
            if trade['outcome'] == 'win':
                entry_stats[entry_type]['wins'] += 1
            else:
                entry_stats[entry_type]['losses'] += 1
        
        baseline_wins = sum(1 for t in trades if t['outcome'] == 'win')
        baseline_rate = baseline_wins / len(trades) * 100
        
        for entry_type, stats in entry_stats.items():
            if stats['total'] < 10 or entry_type == 'UNKNOWN':
                continue
            
            rate = stats['wins'] / stats['total'] * 100
            diff = rate - baseline_rate
            
            p_value = calculate_significance(stats['wins'], stats['total'],
                baseline_wins, len(trades))
            
            if diff >= 10 and p_value < 0.1:
                suggestions.append({
                    'type': 'pattern',
                    'category': 'entry_type',
                    'title': f'Prioritize {entry_type} Entries',
                    'explanation': f'{entry_type} entries have a {rate:.0f}% win rate vs {baseline_rate:.0f}% overall ({stats["total"]} trades). This entry style is working well for you.',
                    'action': f'Add preference in AI prompt for {entry_type} setups',
                    'projected_impact': f'+{diff:.0f}% win rate when using this entry type',
                    'confidence': min(stats['total'] / 25, 1.0),
                    'sample_size': stats['total'],
                    'p_value': p_value,
                    'data': {
                        'entry_type': entry_type,
                        'win_rate': rate,
                        'baseline_rate': baseline_rate
                    }
                })
            elif diff <= -10 and p_value < 0.1:
                suggestions.append({
                    'type': 'pattern',
                    'category': 'entry_type_avoid',
                    'title': f'Reduce {entry_type} Entries',
                    'explanation': f'{entry_type} entries have only a {rate:.0f}% win rate vs {baseline_rate:.0f}% overall. These setups are underperforming.',
                    'action': f'Add caution in AI prompt for {entry_type} entries - require extra confirmation',
                    'projected_impact': f'Avoiding these could improve overall performance',
                    'confidence': min(stats['total'] / 25, 1.0),
                    'sample_size': stats['total'],
                    'p_value': p_value,
                    'data': {
                        'entry_type': entry_type,
                        'win_rate': rate,
                        'baseline_rate': baseline_rate
                    }
                })
        
        return suggestions
    
    def _analyze_tickers(self, trades):
        """Analyze performance by ticker"""
        suggestions = []
        ticker_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0, 'pnl': 0})
        
        for trade in trades:
            ticker = trade.get('ticker', 'UNKNOWN')
            ticker_stats[ticker]['total'] += 1
            ticker_stats[ticker]['pnl'] += trade.get('pnl_ticks') or 0
            if trade['outcome'] == 'win':
                ticker_stats[ticker]['wins'] += 1
            else:
                ticker_stats[ticker]['losses'] += 1
        
        baseline_wins = sum(1 for t in trades if t['outcome'] == 'win')
        baseline_rate = baseline_wins / len(trades) * 100
        
        for ticker, stats in ticker_stats.items():
            if stats['total'] < 10:
                continue
            
            rate = stats['wins'] / stats['total'] * 100
            diff = rate - baseline_rate
            
            p_value = calculate_significance(stats['wins'], stats['total'],
                baseline_wins, len(trades))
            
            if diff <= -15 and p_value < 0.1:
                suggestions.append({
                    'type': 'pattern',
                    'category': 'ticker_performance',
                    'title': f'Review {ticker} Trading',
                    'explanation': f'{ticker} has a {rate:.0f}% win rate vs {baseline_rate:.0f}% overall with {stats["pnl"]:+.1f} ticks P&L. Consider reducing exposure or requiring higher confidence for this ticker.',
                    'action': f'Add ticker-specific filter: require 85%+ confidence for {ticker}',
                    'projected_impact': f'Improved {ticker} trade selection',
                    'confidence': min(stats['total'] / 25, 1.0),
                    'sample_size': stats['total'],
                    'p_value': p_value,
                    'data': {
                        'ticker': ticker,
                        'win_rate': rate,
                        'baseline_rate': baseline_rate,
                        'total_pnl': stats['pnl']
                    }
                })
        
        return suggestions


class TimeOptimizer:
    """
    Identifies best and worst trading times
    """
    
    def analyze(self, trades):
        """Analyze performance by time of day and day of week"""
        if not trades:
            return []
        
        suggestions = []
        
        # Analyze by hour
        hour_suggestions = self._analyze_hours(trades)
        suggestions.extend(hour_suggestions)
        
        # Analyze by day of week
        day_suggestions = self._analyze_days(trades)
        suggestions.extend(day_suggestions)
        
        return suggestions
    
    def _analyze_hours(self, trades):
        """Analyze performance by hour"""
        suggestions = []
        hour_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0})
        
        for trade in trades:
            try:
                timestamp = trade.get('timestamp', '')
                hour = int(timestamp.split(' ')[1].split(':')[0])
                hour_stats[hour]['total'] += 1
                if trade['outcome'] == 'win':
                    hour_stats[hour]['wins'] += 1
                else:
                    hour_stats[hour]['losses'] += 1
            except:
                continue
        
        baseline_wins = sum(1 for t in trades if t['outcome'] == 'win')
        baseline_rate = baseline_wins / len(trades) * 100
        
        # Find worst hours
        worst_hours = []
        for hour, stats in hour_stats.items():
            if stats['total'] < 5:
                continue
            
            rate = stats['wins'] / stats['total'] * 100
            diff = rate - baseline_rate
            
            if diff <= -15:
                p_value = calculate_significance(stats['wins'], stats['total'],
                    baseline_wins, len(trades))
                if p_value < 0.15:
                    worst_hours.append({
                        'hour': hour,
                        'rate': rate,
                        'diff': diff,
                        'total': stats['total'],
                        'p_value': p_value
                    })
        
        if worst_hours:
            worst_hours.sort(key=lambda x: x['rate'])
            worst = worst_hours[0]
            hour_label = f"{worst['hour']:02d}:00-{worst['hour']:02d}:59"
            
            suggestions.append({
                'type': 'timing',
                'category': 'avoid_hour',
                'title': f'Avoid Trading {hour_label}',
                'explanation': f'Your signals during {hour_label} have a {worst["rate"]:.0f}% win rate vs {baseline_rate:.0f}% overall ({worst["total"]} trades). This hour consistently underperforms.',
                'action': f'Add time filter to skip signals between {worst["hour"]:02d}:00 and {worst["hour"]:02d}:59',
                'projected_impact': f'Avoiding this hour could improve win rate by ~{abs(worst["diff"]):.0f}%',
                'confidence': min(worst['total'] / 15, 1.0),
                'sample_size': worst['total'],
                'p_value': worst['p_value'],
                'data': {
                    'hour': worst['hour'],
                    'hour_win_rate': worst['rate'],
                    'baseline_rate': baseline_rate
                }
            })
        
        # Find best hours
        best_hours = []
        for hour, stats in hour_stats.items():
            if stats['total'] < 5:
                continue
            
            rate = stats['wins'] / stats['total'] * 100
            diff = rate - baseline_rate
            
            if diff >= 15:
                p_value = calculate_significance(stats['wins'], stats['total'],
                    baseline_wins, len(trades))
                if p_value < 0.15:
                    best_hours.append({
                        'hour': hour,
                        'rate': rate,
                        'diff': diff,
                        'total': stats['total'],
                        'p_value': p_value
                    })
        
        if best_hours:
            best_hours.sort(key=lambda x: x['rate'], reverse=True)
            best = best_hours[0]
            hour_label = f"{best['hour']:02d}:00-{best['hour']:02d}:59"
            
            suggestions.append({
                'type': 'timing',
                'category': 'best_hour',
                'title': f'Focus on {hour_label} Trading Window',
                'explanation': f'Your signals during {hour_label} have a {best["rate"]:.0f}% win rate vs {baseline_rate:.0f}% overall ({best["total"]} trades). This is your strongest trading hour.',
                'action': f'Consider increasing position size or lowering confidence threshold during {hour_label}',
                'projected_impact': f'This window shows {best["diff"]:+.0f}% better performance',
                'confidence': min(best['total'] / 15, 1.0),
                'sample_size': best['total'],
                'p_value': best['p_value'],
                'data': {
                    'hour': best['hour'],
                    'hour_win_rate': best['rate'],
                    'baseline_rate': baseline_rate
                }
            })
        
        return suggestions
    
    def _analyze_days(self, trades):
        """Analyze performance by day of week"""
        suggestions = []
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        day_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0})
        
        for trade in trades:
            try:
                timestamp = trade.get('timestamp', '')
                date_part = timestamp.split(' ')[0]
                dt = datetime.strptime(date_part, '%Y-%m-%d')
                day = dt.weekday()
                day_stats[day]['total'] += 1
                if trade['outcome'] == 'win':
                    day_stats[day]['wins'] += 1
                else:
                    day_stats[day]['losses'] += 1
            except:
                continue
        
        baseline_wins = sum(1 for t in trades if t['outcome'] == 'win')
        baseline_rate = baseline_wins / len(trades) * 100
        
        for day, stats in day_stats.items():
            if stats['total'] < 8:
                continue
            
            rate = stats['wins'] / stats['total'] * 100
            diff = rate - baseline_rate
            
            p_value = calculate_significance(stats['wins'], stats['total'],
                baseline_wins, len(trades))
            
            if diff <= -15 and p_value < 0.15:
                suggestions.append({
                    'type': 'timing',
                    'category': 'avoid_day',
                    'title': f'Reduce {day_names[day]} Trading',
                    'explanation': f'{day_names[day]} trades have a {rate:.0f}% win rate vs {baseline_rate:.0f}% overall ({stats["total"]} trades). Consider being more selective on this day.',
                    'action': f'Increase confidence requirement to 85%+ on {day_names[day]}s',
                    'projected_impact': f'Better {day_names[day]} trade selection',
                    'confidence': min(stats['total'] / 20, 1.0),
                    'sample_size': stats['total'],
                    'p_value': p_value,
                    'data': {
                        'day': day,
                        'day_name': day_names[day],
                        'day_win_rate': rate,
                        'baseline_rate': baseline_rate
                    }
                })
        
        return suggestions


# ============ MAIN COACH CLASS ============

class StrategyCoach:
    """
    Main AI Strategy Coach that coordinates all analyzers
    """
    
    def __init__(self):
        self.analyzers = [
            PromptEvolutionAnalyzer(),
            SmartFilterOptimizer(),
            PatternRecognizer(),
            TimeOptimizer()
        ]
    
    def run_full_analysis(self, min_trades=20):
        """
        Run all analyzers and return prioritized suggestions
        """
        trades, error = get_trade_data(min_trades)
        
        if error:
            return {
                'status': 'insufficient_data',
                'message': error,
                'suggestions': []
            }
        
        all_suggestions = []
        
        for analyzer in self.analyzers:
            try:
                suggestions = analyzer.analyze(trades)
                all_suggestions.extend(suggestions)
            except Exception as e:
                print(f"⚠️  Analyzer error: {e}")
        
        # Sort by confidence and statistical significance
        all_suggestions.sort(key=lambda x: (
            -x.get('confidence', 0),
            x.get('p_value', 1)
        ))
        
        # Calculate summary stats
        total_trades = len(trades)
        total_wins = sum(1 for t in trades if t['outcome'] == 'win')
        
        return {
            'status': 'success',
            'summary': {
                'total_trades': total_trades,
                'win_rate': round(total_wins / total_trades * 100, 1),
                'suggestions_count': len(all_suggestions),
                'analyzers_run': len(self.analyzers),
                'analysis_time': datetime.now().isoformat()
            },
            'suggestions': all_suggestions
        }
    
    def get_insights(self, min_trades=20):
        """
        Get quick insights without full suggestions
        """
        trades, error = get_trade_data(min_trades)
        
        if error:
            return {'status': 'insufficient_data', 'message': error}
        
        total = len(trades)
        wins = sum(1 for t in trades if t['outcome'] == 'win')
        
        # Recent trend (last 20 vs previous)
        recent = trades[:20]
        previous = trades[20:40] if len(trades) >= 40 else []
        
        recent_rate = sum(1 for t in recent if t['outcome'] == 'win') / len(recent) * 100
        prev_rate = sum(1 for t in previous if t['outcome'] == 'win') / len(previous) * 100 if previous else None
        
        trend = 'improving' if prev_rate and recent_rate > prev_rate + 5 else \
                'declining' if prev_rate and recent_rate < prev_rate - 5 else 'stable'
        
        return {
            'status': 'success',
            'insights': {
                'total_trades': total,
                'overall_win_rate': round(wins / total * 100, 1),
                'recent_win_rate': round(recent_rate, 1),
                'previous_win_rate': round(prev_rate, 1) if prev_rate else None,
                'trend': trend,
                'data_quality': 'good' if total >= 50 else 'building'
            }
        }


# Singleton instance
coach = StrategyCoach()


def run_analysis():
    """Run full strategy analysis"""
    return coach.run_full_analysis()


def get_insights():
    """Get quick insights"""
    return coach.get_insights()


print("✅ Strategy Coach loaded")

