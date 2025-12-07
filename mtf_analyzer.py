"""
SignalCrawler v3.0 Multi-Timeframe Analyzer
Advanced confidence scoring with time-tiered trading system

CONFIDENCE SCORING:
1. Timeframe Alignment    - 40% (Primary driver - MUST be 3/3 unanimous)
2. Market Structure       - 25% (Trend + liquidity clarity)
3. Volume Confirmation    - 15% (Breakout/pullback validation)
4. Risk/Reward Quality    - 10% (Time-based targets)
5. Catalysts & Volatility - 10% (News/time awareness)

POSITION SIZING:
- Formula: Contracts = Risk ÷ (Stop_Ticks × Tick_Value)
- Risk varies by tier: $250 PRIME, $175 MIDDAY, $125 EXTENDED
- Stop capped at max per instrument: MNQ 15pts, MES 6pts, MGC 10pts

TIME TIERS:
- PRIME (9:30-11:30 AM): 80% min, 1.5:1/2:1 targets
- MIDDAY (11:30-3:30 PM): 85% min, 1:1/1.5:1 targets
- EXTENDED (5-9 PM, 6-9:30 AM): 90% min, 1:1/1.5:1 targets
- BLOCKED (9 PM - 6 AM): No signals

15m = Bias Engine (backbone - if unclear, STAY AWAY)
5m  = Setup Quality Filter (must agree)
1m  = Execution Trigger (must agree)
"""

from datetime import datetime
import statistics
import re

# Import time tier configuration
try:
    from time_tiers import (
        get_current_tier, is_trading_blocked, get_tier_targets,
        get_tier_risk, get_tier_confidence_threshold, get_extended_hours_warning,
        get_tier_name, get_tier_emoji, get_session_window
    )
    TIME_TIERS_AVAILABLE = True
except ImportError:
    TIME_TIERS_AVAILABLE = False
    print("⚠️ time_tiers.py not found - using defaults")

# ============================================
# TICKER CONFIGURATION
# ============================================

# Tick values per contract
TICK_VALUES = {
    'MNQ': {'tick_size': 0.25, 'tick_value': 0.50, 'max_stop_points': 15},
    'MES': {'tick_size': 0.25, 'tick_value': 1.25, 'max_stop_points': 6},
    'MGC': {'tick_size': 0.10, 'tick_value': 1.00, 'max_stop_points': 10},
    'NQ':  {'tick_size': 0.25, 'tick_value': 5.00, 'max_stop_points': 15},
    'ES':  {'tick_size': 0.25, 'tick_value': 12.50, 'max_stop_points': 6},
    'GC':  {'tick_size': 0.10, 'tick_value': 10.00, 'max_stop_points': 10},
}

# Default fallback values
DEFAULT_RISK = 250
DEFAULT_TARGET1_RR = 1.5
DEFAULT_TARGET2_RR = 2.0


def get_base_ticker(ticker):
    """Extract base ticker from contract symbol (MNQZ2025 -> MNQ)"""
    base = ticker.replace('=F', '').upper()
    # Strip contract month codes (F,G,H,J,K,M,N,Q,U,V,X,Z followed by 4 digits)
    base = re.sub(r'[FGHJKMNQUVXZ]\d{4}$', '', base)
    return base


def get_ticker_info(ticker):
    """Get tick info for a ticker"""
    base = get_base_ticker(ticker)
    return TICK_VALUES.get(base, TICK_VALUES.get('MNQ'))


def cap_stop_loss(ticker, entry, calculated_stop, direction):
    """
    Cap stop loss at instrument maximum.
    
    Returns:
        tuple: (capped_stop, was_capped, stop_distance_points)
    """
    info = get_ticker_info(ticker)
    max_stop = info.get('max_stop_points', 15)
    
    stop_distance = abs(entry - calculated_stop)
    
    if stop_distance > max_stop:
        # Cap at maximum
        if direction == 'LONG':
            capped_stop = entry - max_stop
        else:
            capped_stop = entry + max_stop
        return round(capped_stop, 2), True, max_stop
    
    return calculated_stop, False, round(stop_distance, 2)


def calculate_position_size(ticker, entry, stop, risk_amount=None):
    """
    Calculate position size using correct formula:
    Contracts = Risk ÷ (Stop_Ticks × Tick_Value)
    
    Args:
        ticker: Ticker symbol
        entry: Entry price
        stop: Stop price
        risk_amount: Risk per trade (uses tier-based if not specified)
    
    Returns:
        dict with position sizing details
    """
    # Get tier-based risk if not specified
    if risk_amount is None:
        if TIME_TIERS_AVAILABLE:
            risk_amount = get_tier_risk()
        else:
            risk_amount = DEFAULT_RISK
    
    # Get tick info
    info = get_ticker_info(ticker)
    tick_size = info['tick_size']
    tick_value = info['tick_value']
    
    # Calculate stop distance in ticks
    stop_distance_points = abs(entry - stop)
    ticks_to_stop = stop_distance_points / tick_size
    
    # Risk per contract = ticks × tick value
    risk_per_contract = ticks_to_stop * tick_value
    
    # Contracts = Risk ÷ Risk per contract
    if risk_per_contract > 0:
        contracts = int(risk_amount / risk_per_contract)
        contracts = max(1, contracts)  # Minimum 1 contract
    else:
        contracts = 1
    
    # Actual risk with this position
    actual_risk = contracts * risk_per_contract
    
    return {
        'contracts': contracts,
        'risk_per_contract': round(risk_per_contract, 2),
        'actual_risk': round(actual_risk, 2),
        'suggested_risk': risk_amount,
        'ticks_to_stop': round(ticks_to_stop, 1),
        'stop_distance_points': round(stop_distance_points, 2),
        'tick_value': tick_value,
        'tick_size': tick_size
    }


class MTFAnalyzer:
    """
    SignalCrawler v3.0 Multi-Timeframe Analyzer
    Requires UNANIMOUS 3/3 timeframe alignment
    """
    
    # Confidence weights
    WEIGHT_TF_ALIGNMENT = 40
    WEIGHT_STRUCTURE = 25
    WEIGHT_VOLUME = 15
    WEIGHT_RISK_REWARD = 10
    WEIGHT_CATALYSTS = 10
    
    # Minimum R:R threshold
    MIN_RISK_REWARD = 1.0  # Lowered since targets are tier-based
    
    def __init__(self):
        pass
    
    # ==================== TIMEFRAME ANALYSIS ====================
    
    def analyze_trend(self, candles):
        """
        Analyze trend direction and strength from candles
        Returns: direction ('bullish'/'bearish'/'neutral'), strength ('strong'/'moderate'/'weak'), details
        """
        if not candles or len(candles) < 3:
            return 'neutral', 'weak', {}
        
        # Calculate trend metrics
        first_open = candles[0].get('open', 0)
        last_close = candles[-1].get('close', 0)
        
        # Higher highs / lower lows analysis
        highs = [c.get('high', 0) for c in candles]
        lows = [c.get('low', 0) for c in candles]
        closes = [c.get('close', 0) for c in candles]
        
        # Count bullish vs bearish candles
        bullish_count = sum(1 for c in candles if c.get('close', 0) > c.get('open', 0))
        bearish_count = sum(1 for c in candles if c.get('close', 0) < c.get('open', 0))
        total = len(candles)
        
        # Check for higher highs / higher lows (bullish) or lower highs / lower lows (bearish)
        recent_highs = highs[-3:]
        recent_lows = lows[-3:]
        
        higher_highs = recent_highs[-1] > recent_highs[0] if len(recent_highs) >= 2 else False
        higher_lows = recent_lows[-1] > recent_lows[0] if len(recent_lows) >= 2 else False
        lower_highs = recent_highs[-1] < recent_highs[0] if len(recent_highs) >= 2 else False
        lower_lows = recent_lows[-1] < recent_lows[0] if len(recent_lows) >= 2 else False
        
        # Determine direction
        if first_open > 0:
            change_pct = ((last_close - first_open) / first_open) * 100
        else:
            change_pct = 0
        
        # Direction determination
        if higher_highs and higher_lows and change_pct > 0.05:
            direction = 'bullish'
        elif lower_highs and lower_lows and change_pct < -0.05:
            direction = 'bearish'
        elif abs(change_pct) < 0.03:
            direction = 'neutral'
        elif change_pct > 0:
            direction = 'bullish'
        else:
            direction = 'bearish'
        
        # Strength determination
        bullish_ratio = bullish_count / total if total > 0 else 0
        bearish_ratio = bearish_count / total if total > 0 else 0
        
        if direction == 'bullish':
            if bullish_ratio >= 0.7 and higher_highs and higher_lows:
                strength = 'strong'
            elif bullish_ratio >= 0.5:
                strength = 'moderate'
            else:
                strength = 'weak'
        elif direction == 'bearish':
            if bearish_ratio >= 0.7 and lower_highs and lower_lows:
                strength = 'strong'
            elif bearish_ratio >= 0.5:
                strength = 'moderate'
            else:
                strength = 'weak'
        else:
            strength = 'weak'
        
        details = {
            'change_pct': round(change_pct, 3),
            'bullish_candles': bullish_count,
            'bearish_candles': bearish_count,
            'higher_highs': higher_highs,
            'higher_lows': higher_lows,
            'lower_highs': lower_highs,
            'lower_lows': lower_lows,
            'high': max(highs) if highs else 0,
            'low': min(lows) if lows else 0,
            'last_close': last_close
        }
        
        return direction, strength, details
    
    def generate_written_analysis(self, timeframe, direction, strength, details, candles):
        """
        Generate human-readable written analysis for a timeframe
        """
        if not candles or len(candles) < 3:
            return f"The {timeframe} chart has insufficient data for analysis."
        
        # Get price action details
        change_pct = details.get('change_pct', 0)
        hh = details.get('higher_highs', False)
        hl = details.get('higher_lows', False)
        lh = details.get('lower_highs', False)
        ll = details.get('lower_lows', False)
        
        # Build descriptive text
        if direction == 'bullish':
            if strength == 'strong':
                base = f"Strong bullish momentum"
                if hh and hl:
                    base += ", making higher highs and higher lows"
            elif strength == 'moderate':
                base = f"Bullish momentum confirmed"
                if hl:
                    base += ", forming higher lows"
            else:  # weak
                base = f"Mild bullish bias, weak momentum"
                
        elif direction == 'bearish':
            if strength == 'strong':
                base = f"Strong bearish momentum"
                if lh and ll:
                    base += ", making lower highs and lower lows"
            elif strength == 'moderate':
                base = f"Bearish momentum confirmed"
                if lh:
                    base += ", forming lower highs"
            else:  # weak
                base = f"Mild bearish bias, weak momentum"
                
        else:  # neutral
            base = f"Choppy/sideways - no clear direction"
        
        return base
    
    def analyze_structure(self, candles):
        """
        Analyze market structure cleanliness
        Returns: score (0-100), is_clean (bool), issues (list)
        """
        if not candles or len(candles) < 5:
            return 50, False, ['Insufficient data']
        
        issues = []
        score = 100
        
        highs = [c.get('high', 0) for c in candles]
        lows = [c.get('low', 0) for c in candles]
        
        # Check for overlapping highs/lows (chop)
        avg_range = statistics.mean([h - l for h, l in zip(highs, lows)])
        
        # Count overlapping candles
        overlaps = 0
        for i in range(1, len(candles)):
            prev_low, prev_high = lows[i-1], highs[i-1]
            curr_low, curr_high = lows[i], highs[i]
            
            overlap = min(prev_high, curr_high) - max(prev_low, curr_low)
            if overlap > avg_range * 0.5:
                overlaps += 1
        
        overlap_ratio = overlaps / (len(candles) - 1) if len(candles) > 1 else 0
        
        if overlap_ratio > 0.6:
            score -= 30
            issues.append('High overlap (choppy)')
        elif overlap_ratio > 0.4:
            score -= 15
            issues.append('Moderate overlap')
        
        # Check for wick dominance
        wick_dominated = 0
        for c in candles:
            body = abs(c.get('close', 0) - c.get('open', 0))
            total_range = c.get('high', 0) - c.get('low', 0)
            if total_range > 0 and body / total_range < 0.3:
                wick_dominated += 1
        
        wick_ratio = wick_dominated / len(candles)
        if wick_ratio > 0.5:
            score -= 20
            issues.append('Wick-dominated candles')
        elif wick_ratio > 0.3:
            score -= 10
            issues.append('Some wick dominance')
        
        # Check for clear structure
        direction, strength, _ = self.analyze_trend(candles)
        if strength == 'weak':
            score -= 15
            issues.append('Weak trend structure')
        
        is_clean = score >= 70 and len(issues) <= 1
        
        return max(0, score), is_clean, issues
    
    def analyze_volume(self, candles):
        """
        Analyze volume confirmation
        Returns: score (0-100), is_confirming (bool), details
        """
        if not candles or len(candles) < 3:
            return 50, False, {'reason': 'Insufficient data'}
        
        volumes = [c.get('volume', 0) for c in candles if c.get('volume', 0) > 0]
        
        if not volumes or len(volumes) < 3:
            return 50, False, {'reason': 'No volume data'}
        
        score = 75  # Base score
        
        direction, _, _ = self.analyze_trend(candles)
        
        recent_vol = volumes[-3:] if len(volumes) >= 3 else volumes
        older_vol = volumes[:-3] if len(volumes) > 3 else volumes[:1]
        
        avg_recent = statistics.mean(recent_vol) if recent_vol else 0
        avg_older = statistics.mean(older_vol) if older_vol else avg_recent
        
        vol_change = ((avg_recent - avg_older) / avg_older * 100) if avg_older > 0 else 0
        
        details = {
            'avg_recent_volume': avg_recent,
            'avg_older_volume': avg_older,
            'volume_change_pct': round(vol_change, 1),
            'trend_direction': direction
        }
        
        if direction in ('bullish', 'bearish'):
            if vol_change > 20:
                score += 25
                details['assessment'] = 'Strong volume confirmation'
            elif vol_change > 0:
                score += 10
                details['assessment'] = 'Moderate volume support'
            elif vol_change < -20:
                score -= 25
                details['assessment'] = 'Volume divergence (warning)'
            else:
                details['assessment'] = 'Flat volume'
        else:
            details['assessment'] = 'Neutral trend, volume less relevant'
        
        is_confirming = score >= 75
        
        return min(100, max(0, score)), is_confirming, details
    
    def check_catalyst_risk(self):
        """
        Check for catalyst/volatility danger zones
        Uses time tiers if available
        """
        # Check if trading is blocked (overnight)
        if TIME_TIERS_AVAILABLE:
            blocked, msg = is_trading_blocked()
            if blocked:
                return 0, False, [f'⛔ {msg}']
        
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()
        
        warnings = []
        score = 100
        
        # Weekend
        if weekday >= 5:
            return 0, False, ['Weekend - markets closed']
        
        # Best trading windows
        if (10 <= hour < 12) or (14 <= hour < 15):
            score = min(100, score + 10)
        
        is_safe = score >= 70
        
        return max(0, score), is_safe, warnings
    
    def calculate_risk_reward(self, entry, stop, target, direction):
        """
        Calculate risk:reward ratio
        """
        if not all([entry, stop, target]):
            return 0, False, 0
        
        if direction.lower() == 'long':
            risk = abs(entry - stop)
            reward = abs(target - entry)
        else:
            risk = abs(stop - entry)
            reward = abs(entry - target)
        
        if risk <= 0:
            return 0, False, 0
        
        ratio = reward / risk
        
        # Score based on R:R
        if ratio >= 2.0:
            score = 100
        elif ratio >= 1.5:
            score = 80
        elif ratio >= 1.0:
            score = 60
        else:
            score = 30
        
        is_valid = ratio >= self.MIN_RISK_REWARD
        
        return round(ratio, 2), is_valid, score
    
    # ==================== MAIN ANALYSIS ====================
    
    def full_analysis(self, candles_15m, candles_5m, candles_1m, entry=None, stop=None, target=None, ticker='MNQ'):
        """
        Full SignalCrawler v3.0 analysis across all timeframes
        REQUIRES UNANIMOUS 3/3 ALIGNMENT - no conditional signals
        """
        result = {
            'direction': 'STAY_AWAY',
            'confidence': 0,
            'signal_type': 'NO_TRADE',
            'components': {},
            'warnings': [],
            'stay_away_reason': None,
            'tier': None,
            'tier_name': None,
            'tier_emoji': None,
            'session_window': None
        }
        
        # ========== CHECK TIME TIER ==========
        if TIME_TIERS_AVAILABLE:
            tier = get_current_tier()
            result['tier'] = tier
            result['tier_name'] = get_tier_name()
            result['tier_emoji'] = get_tier_emoji()
            result['session_window'] = get_session_window()
            result['suggested_risk'] = get_tier_risk()
            
            # Check if trading is blocked
            blocked, msg = is_trading_blocked()
            if blocked:
                result['stay_away_reason'] = msg
                result['warnings'].append('⛔ Trading blocked during overnight hours (9 PM - 6 AM)')
                return result
        else:
            result['suggested_risk'] = DEFAULT_RISK
        
        # ========== 1. TIMEFRAME ANALYSIS (40%) ==========
        tf15_dir, tf15_str, tf15_details = self.analyze_trend(candles_15m)
        tf5_dir, tf5_str, tf5_details = self.analyze_trend(candles_5m)
        tf1_dir, tf1_str, tf1_details = self.analyze_trend(candles_1m)
        
        # Generate written analysis
        tf15_analysis = self.generate_written_analysis('15m', tf15_dir, tf15_str, tf15_details, candles_15m)
        tf5_analysis = self.generate_written_analysis('5m', tf5_dir, tf5_str, tf5_details, candles_5m)
        tf1_analysis = self.generate_written_analysis('1m', tf1_dir, tf1_str, tf1_details, candles_1m)
        
        # Always populate timeframe data
        result['components']['timeframe'] = {
            'score': 0,
            'weight': self.WEIGHT_TF_ALIGNMENT,
            'alignment': 'none',
            'tf15': {'direction': tf15_dir, 'strength': tf15_str, 'analysis': tf15_analysis},
            'tf5': {'direction': tf5_dir, 'strength': tf5_str, 'analysis': tf5_analysis},
            'tf1': {'direction': tf1_dir, 'strength': tf1_str, 'analysis': tf1_analysis}
        }
        
        result['mtf_analysis'] = {
            '15m': tf15_analysis,
            '5m': tf5_analysis,
            '1m': tf1_analysis
        }
        
        # ========== v3.0: STRICT ALIGNMENT REQUIREMENTS ==========
        
        # Check 1: 15m backbone must be clear
        if tf15_dir == 'neutral':
            result['stay_away_reason'] = '15m chart unclear - no directional bias'
            result['warnings'].append('15m timeframe is neutral/choppy')
            return result
        
        # Check 2: 15m and 5m must NOT be weak (higher timeframes need conviction)
        if tf15_str == 'weak':
            result['stay_away_reason'] = '15m momentum too weak - backbone invalid'
            result['warnings'].append('15m shows weak momentum - waiting for strength')
            return result
        
        if tf5_str == 'weak':
            result['stay_away_reason'] = '5m momentum too weak - no setup quality'
            result['warnings'].append('5m shows weak momentum - caution advised')
            return result
        
        # Check 3: UNANIMOUS 3/3 alignment required (no 2/3 conditional signals)
        directions = [tf15_dir, tf5_dir, tf1_dir]
        bullish_count = directions.count('bullish')
        bearish_count = directions.count('bearish')
        
        if bullish_count == 3:
            alignment = 'full'
            bias = 'LONG'
            tf_score = 40
        elif bearish_count == 3:
            alignment = 'full'
            bias = 'SHORT'
            tf_score = 40
        else:
            # v3.0: NO 2/3 signals - must be unanimous
            conflicting = []
            if tf15_dir != tf5_dir:
                conflicting.append(f"15m={tf15_dir} vs 5m={tf5_dir}")
            if tf5_dir != tf1_dir:
                conflicting.append(f"5m={tf5_dir} vs 1m={tf1_dir}")
            if tf15_dir != tf1_dir:
                conflicting.append(f"15m={tf15_dir} vs 1m={tf1_dir}")
            
            result['stay_away_reason'] = f'MTF Conflict - All 3 timeframes must agree ({", ".join(conflicting)})'
            result['warnings'].append('Timeframes not aligned - waiting for unanimous agreement')
            return result
        
        # Update timeframe score
        result['components']['timeframe']['score'] = tf_score
        result['components']['timeframe']['alignment'] = alignment
        
        # ========== 2. STRUCTURE ANALYSIS (25%) ==========
        struct_score_15, clean_15, issues_15 = self.analyze_structure(candles_15m)
        struct_score_5, clean_5, issues_5 = self.analyze_structure(candles_5m)
        
        structure_score = (struct_score_15 * 0.6 + struct_score_5 * 0.4)
        structure_weighted = (structure_score / 100) * self.WEIGHT_STRUCTURE
        
        if structure_score < 50:
            result['stay_away_reason'] = 'Structure too sloppy/chaotic'
            result['warnings'].extend(issues_15 + issues_5)
            return result
        
        result['components']['structure'] = {
            'score': round(structure_score),
            'weight': self.WEIGHT_STRUCTURE,
            'weighted_score': round(structure_weighted, 1),
            'is_clean': clean_15 and clean_5,
            'issues': issues_15 + issues_5
        }
        
        # ========== 3. VOLUME ANALYSIS (15%) ==========
        vol_score, vol_confirming, vol_details = self.analyze_volume(candles_5m)
        volume_weighted = (vol_score / 100) * self.WEIGHT_VOLUME
        
        if vol_score < 40:
            result['warnings'].append('Volume non-confirming')
        
        result['components']['volume'] = {
            'score': vol_score,
            'weight': self.WEIGHT_VOLUME,
            'weighted_score': round(volume_weighted, 1),
            'is_confirming': vol_confirming,
            'details': vol_details
        }
        
        # ========== 4. CATALYST CHECK (10%) ==========
        catalyst_score, catalyst_safe, catalyst_warnings = self.check_catalyst_risk()
        catalyst_weighted = (catalyst_score / 100) * self.WEIGHT_CATALYSTS
        
        if not catalyst_safe:
            result['warnings'].extend(catalyst_warnings)
        
        result['components']['catalysts'] = {
            'score': catalyst_score,
            'weight': self.WEIGHT_CATALYSTS,
            'weighted_score': round(catalyst_weighted, 1),
            'is_safe': catalyst_safe,
            'warnings': catalyst_warnings
        }
        
        # ========== GENERATE ENTRY/STOP/TARGET ==========
        if candles_1m:
            last_candle = candles_1m[-1]
            current_price = last_candle.get('close', 0)
            result['current_price'] = current_price
            result['entry'] = current_price
            
            # Calculate ATR for stop
            atr = self._calculate_atr(candles_5m)
            if atr < 1:
                atr = 5
            
            # Stop based on 1.5x ATR
            stop_distance = atr * 1.5
            
            if bias == 'LONG':
                raw_stop = round(current_price - stop_distance, 2)
            else:
                raw_stop = round(current_price + stop_distance, 2)
            
            # Cap stop at instrument maximum
            capped_stop, was_capped, final_stop_dist = cap_stop_loss(ticker, current_price, raw_stop, bias)
            result['stop'] = capped_stop
            result['stop_capped'] = was_capped
            result['stop_pips'] = final_stop_dist
            
            if was_capped:
                ticker_info = get_ticker_info(ticker)
                result['warnings'].append(f"Stop capped at {ticker_info['max_stop_points']} pts (max for instrument)")
            
            # Get tier-based targets
            if TIME_TIERS_AVAILABLE:
                t1_rr, t2_rr = get_tier_targets()
            else:
                t1_rr, t2_rr = DEFAULT_TARGET1_RR, DEFAULT_TARGET2_RR
            
            # Calculate targets based on tier
            if bias == 'LONG':
                result['target1'] = round(current_price + (final_stop_dist * t1_rr), 2)
                result['target2'] = round(current_price + (final_stop_dist * t2_rr), 2)
            else:
                result['target1'] = round(current_price - (final_stop_dist * t1_rr), 2)
                result['target2'] = round(current_price - (final_stop_dist * t2_rr), 2)
            
            result['target'] = result['target2']  # Primary target
            result['target1_pips'] = round(final_stop_dist * t1_rr, 2)
            result['target2_pips'] = round(final_stop_dist * t2_rr, 2)
            result['target1_rr'] = t1_rr
            result['target2_rr'] = t2_rr
            
            result['targets'] = {
                'target1': {'price': result['target1'], 'rr': t1_rr, 'pips': result['target1_pips']},
                'target2': {'price': result['target2'], 'rr': t2_rr, 'pips': result['target2_pips']}
            }
            
            # ========== 5. RISK/REWARD (10%) ==========
            rr_ratio, rr_valid, rr_score = self.calculate_risk_reward(
                result['entry'], result['stop'], result['target2'], bias
            )
            rr_weighted = (rr_score / 100) * self.WEIGHT_RISK_REWARD
            
            result['risk_reward'] = rr_ratio
            result['components']['risk_reward'] = {
                'score': rr_score,
                'weight': self.WEIGHT_RISK_REWARD,
                'weighted_score': round(rr_weighted, 1),
                'ratio': rr_ratio,
                'is_valid': rr_valid
            }
            
            # ========== FINAL CONFIDENCE CALCULATION ==========
            total_confidence = (
                tf_score +
                structure_weighted +
                volume_weighted +
                rr_weighted +
                catalyst_weighted
            )
            
            result['direction'] = bias
            result['confidence'] = round(min(100, max(0, total_confidence)))
            result['signal_type'] = bias if result['confidence'] >= 60 else 'NO_TRADE'
            result['entry_type'] = 'MTF_UNANIMOUS'
            
            # ========== POSITION SIZING ==========
            risk_amount = result.get('suggested_risk', DEFAULT_RISK)
            position = calculate_position_size(ticker, result['entry'], result['stop'], risk_amount)
            result['position_size'] = position
            
            # Calculate potential profits
            t1_profit = position['contracts'] * (result['target1_pips'] / position['tick_size']) * position['tick_value']
            t2_profit = position['contracts'] * (result['target2_pips'] / position['tick_size']) * position['tick_value']
            result['potential_profit_t1'] = round(t1_profit, 2)
            result['potential_profit_t2'] = round(t2_profit, 2)
            
            # ========== ENTRY INSTRUCTIONS ==========
            instructions = []
            
            # Tier-specific guidance
            if TIME_TIERS_AVAILABLE:
                tier_name = get_tier_name()
                if 'EXTENDED' in tier_name.upper() or 'EVENING' in tier_name.upper() or 'PRE-MARKET' in tier_name.upper():
                    instructions.append("⚠️ EXTENDED HOURS - Use smaller size, expect wider spreads")
            
            # Entry timing based on momentum
            tf1_strength = tf1_str
            tf5_strength = tf5_str
            
            if tf1_strength == 'strong' and tf5_strength in ['strong', 'moderate']:
                if vol_confirming:
                    instructions.append("🚀 STRONG MOMENTUM - Market order OK")
                else:
                    instructions.append("⚡ Good momentum - Enter on next candle close")
            else:
                instructions.append("⏳ WAIT FOR PULLBACK to entry level")
                if bias == 'LONG':
                    pullback_target = round(current_price - (atr * 0.3), 2)
                    instructions.append(f"   Look for pullback toward {pullback_target}")
                else:
                    pullback_target = round(current_price + (atr * 0.3), 2)
                    instructions.append(f"   Look for pullback toward {pullback_target}")
            
            # Stop management
            if result['confidence'] >= 85:
                instructions.append("📍 Move stop to breakeven at Target 1")
            else:
                instructions.append("📍 Give trade room - don't move stop early")
            
            # Target management
            if vol_confirming and tf5_strength == 'strong':
                instructions.append("🎯 Can trail stop after Target 1")
            else:
                instructions.append("🎯 Take partial profit at Target 1")
            
            result['entry_instruction'] = "\n".join(instructions)
            
            # Add extended hours warning if applicable
            if TIME_TIERS_AVAILABLE:
                warning = get_extended_hours_warning()
                if warning:
                    result['extended_hours_warning'] = warning
        
        return result
    
    def _calculate_atr(self, candles, period=14):
        """Calculate Average True Range"""
        if not candles or len(candles) < 2:
            return 10
        
        trs = []
        for i in range(1, len(candles)):
            high = candles[i].get('high', 0)
            low = candles[i].get('low', 0)
            prev_close = candles[i-1].get('close', 0)
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            trs.append(tr)
        
        return statistics.mean(trs[-period:]) if trs else 10
    
    def _build_rationale(self, result):
        """Build human-readable rationale"""
        lines = []
        
        # Tier info
        if result.get('tier_name'):
            lines.append(f"Session: {result['tier_emoji']} {result['tier_name']} ({result.get('session_window', '')})")
        
        comp = result.get('components', {})
        
        # Timeframe summary
        tf = comp.get('timeframe', {})
        if tf:
            lines.append(f"TF Alignment: {tf.get('alignment', 'unknown').upper()}")
            lines.append(f"  15m: {tf.get('tf15', {}).get('direction', '?')} ({tf.get('tf15', {}).get('strength', '?')})")
            lines.append(f"  5m: {tf.get('tf5', {}).get('direction', '?')} ({tf.get('tf5', {}).get('strength', '?')})")
            lines.append(f"  1m: {tf.get('tf1', {}).get('direction', '?')} ({tf.get('tf1', {}).get('strength', '?')})")
        
        # Structure
        struct = comp.get('structure', {})
        if struct:
            lines.append(f"Structure: {'Clean' if struct.get('is_clean') else 'Issues detected'} ({struct.get('score', 0)}%)")
        
        # Volume
        vol = comp.get('volume', {})
        if vol:
            lines.append(f"Volume: {'Confirming' if vol.get('is_confirming') else 'Not confirming'}")
        
        # Warnings
        if result.get('warnings'):
            lines.append("Warnings: " + ", ".join(result['warnings']))
        
        return "\n".join(lines)


# ==================== CONVENIENCE FUNCTION ====================

def analyze_ticker(candles_15m, candles_5m, candles_1m, entry=None, stop=None, target=None, ticker='MNQ'):
    """
    Convenience function for analyzing a ticker
    """
    analyzer = MTFAnalyzer()
    result = analyzer.full_analysis(candles_15m, candles_5m, candles_1m, entry, stop, target, ticker)
    result['rationale'] = analyzer._build_rationale(result)
    return result


print("✅ SignalCrawler v3.0 MTF Analyzer loaded")
print("   • Unanimous 3/3 alignment required")
print("   • Time-tiered confidence & targets")
print("   • Stop capped at instrument max")
