"""
SignalCrawler Multi-Timeframe Analyzer
Advanced confidence scoring with 5 weighted components

CONFIDENCE SCORING:
1. Timeframe Alignment    - 40% (Primary driver)
2. Market Structure       - 25% (Trend + liquidity clarity)
3. Volume Confirmation    - 15% (Breakout/pullback validation)
4. Risk/Reward Quality    - 10% (Min 1.5:1 required)
5. Catalysts & Volatility - 10% (News/time awareness)

POSITION SIZING:
- Fixed $500 risk per trade
- Exact 2:1 R:R (target = 2× stop distance)
- Calculate contracts based on tick value

15m = Bias Engine (backbone - if unclear, STAY AWAY)
5m  = Setup Quality Filter
1m  = Execution Trigger
"""

from datetime import datetime
import statistics

# Position sizing configuration
RISK_PER_TRADE = 500  # $500 risk per trade
TARGET_RR = 2.0       # Exact 2:1 risk/reward

# Tick values per contract (how much $1 move = in dollars)
TICK_VALUES = {
    'MNQ': {'tick_size': 0.25, 'tick_value': 0.50},   # Micro Nasdaq: $0.50 per tick
    'MES': {'tick_size': 0.25, 'tick_value': 1.25},   # Micro S&P: $1.25 per tick  
    'MGC': {'tick_size': 0.10, 'tick_value': 1.00},   # Micro Gold: $1.00 per tick
    'NQ':  {'tick_size': 0.25, 'tick_value': 5.00},   # E-mini Nasdaq
    'ES':  {'tick_size': 0.25, 'tick_value': 12.50},  # E-mini S&P
    'GC':  {'tick_size': 0.10, 'tick_value': 10.00},  # Gold futures
}

def calculate_position_size(ticker, entry, stop):
    """
    Calculate position size for $500 risk
    Returns: contracts, risk_per_contract, potential_profit
    """
    # Get tick info for ticker
    base_ticker = ticker.replace('=F', '').upper()
    # Strip contract month (MNQZ2025 -> MNQ)
    import re
    base_ticker = re.sub(r'[FGHJKMNQUVXZ]\d{4}$', '', base_ticker)
    
    tick_info = TICK_VALUES.get(base_ticker, TICK_VALUES.get('MNQ'))  # Default to MNQ
    tick_size = tick_info['tick_size']
    tick_value = tick_info['tick_value']
    
    # Calculate stop distance in ticks
    stop_distance = abs(entry - stop)
    ticks_to_stop = stop_distance / tick_size
    
    # Risk per contract
    risk_per_contract = ticks_to_stop * tick_value
    
    # Contracts needed for $500 risk
    if risk_per_contract > 0:
        contracts = int(RISK_PER_TRADE / risk_per_contract)
        contracts = max(1, contracts)  # Minimum 1 contract
    else:
        contracts = 1
    
    # Actual risk with this position
    actual_risk = contracts * risk_per_contract
    
    # Potential profit at 2:1
    potential_profit = actual_risk * TARGET_RR
    
    return {
        'contracts': contracts,
        'risk_per_contract': round(risk_per_contract, 2),
        'actual_risk': round(actual_risk, 2),
        'potential_profit': round(potential_profit, 2),
        'ticks_to_stop': round(ticks_to_stop, 1)
    }


class MTFAnalyzer:
    """
    SignalCrawler Multi-Timeframe Analyzer
    """
    
    # Confidence weights
    WEIGHT_TF_ALIGNMENT = 40
    WEIGHT_STRUCTURE = 25
    WEIGHT_VOLUME = 15
    WEIGHT_RISK_REWARD = 10
    WEIGHT_CATALYSTS = 10
    
    # Minimum R:R threshold
    MIN_RISK_REWARD = 1.5
    
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
        closes = [c.get('close', 0) for c in candles]
        opens = [c.get('open', 0) for c in candles]
        
        # Check for overlapping highs/lows (chop)
        avg_range = statistics.mean([h - l for h, l in zip(highs, lows)])
        
        # Count overlapping candles
        overlaps = 0
        for i in range(1, len(candles)):
            prev_low, prev_high = lows[i-1], highs[i-1]
            curr_low, curr_high = lows[i], highs[i]
            
            # Check if candles overlap significantly
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
        
        # Check for wick dominance (manipulation risk)
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
        
        # Check for clear structure (HH/HL or LH/LL)
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
        
        # Check if volume is increasing with trend
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
        
        # Volume should increase with trend moves
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
        Returns: score (0-100), is_safe (bool), warnings (list)
        """
        now = datetime.now()
        hour = now.hour
        minute = now.minute
        weekday = now.weekday()  # 0=Monday, 6=Sunday
        
        warnings = []
        score = 100
        
        # Weekend - no trading
        if weekday >= 5:
            return 0, False, ['Weekend - markets closed']
        
        # Pre-market (before 9:30 ET)
        if hour < 9 or (hour == 9 and minute < 30):
            score -= 20
            warnings.append('Pre-market session')
        
        # Market open volatility (9:30-10:00)
        if hour == 9 and minute >= 30:
            score -= 15
            warnings.append('Market open volatility window')
        
        # Lunch chop (12:00-13:30)
        if 12 <= hour < 14:
            score -= 20
            warnings.append('Lunch hour - typically choppy')
        
        # Power hour (15:00-16:00) - can be volatile
        if hour == 15:
            score -= 10
            warnings.append('Power hour - increased volatility')
        
        # After hours
        if hour >= 16:
            score -= 30
            warnings.append('After hours - low liquidity')
        
        # Best trading windows (10:00-11:30 and 14:00-15:00)
        if (10 <= hour < 12) or (14 <= hour < 15):
            score = min(100, score + 10)
        
        is_safe = score >= 70
        
        return max(0, score), is_safe, warnings
    
    def calculate_risk_reward(self, entry, stop, target, direction):
        """
        Calculate risk:reward ratio
        Returns: ratio (float), is_valid (bool), score (0-100)
        """
        if not all([entry, stop, target]):
            return 0, False, 0
        
        if direction.lower() == 'long':
            risk = abs(entry - stop)
            reward = abs(target - entry)
        else:  # short
            risk = abs(stop - entry)
            reward = abs(entry - target)
        
        if risk <= 0:
            return 0, False, 0
        
        ratio = reward / risk
        
        # Score based on R:R
        if ratio >= 3.0:
            score = 100
        elif ratio >= 2.5:
            score = 90
        elif ratio >= 2.0:
            score = 80
        elif ratio >= 1.5:
            score = 60
        elif ratio >= 1.0:
            score = 30
        else:
            score = 0
        
        is_valid = ratio >= self.MIN_RISK_REWARD
        
        return round(ratio, 2), is_valid, score
    
    # ==================== MAIN ANALYSIS ====================
    
    def full_analysis(self, candles_15m, candles_5m, candles_1m, entry=None, stop=None, target=None, ticker='MNQ'):
        """
        Full QuantCrawler analysis across all timeframes
        Returns comprehensive analysis with confidence score
        """
        result = {
            'direction': 'STAY_AWAY',
            'confidence': 0,
            'signal_type': 'NO_TRADE',
            'components': {},
            'warnings': [],
            'stay_away_reason': None
        }
        
        # ========== 1. TIMEFRAME ANALYSIS (40%) ==========
        tf15_dir, tf15_str, tf15_details = self.analyze_trend(candles_15m)
        tf5_dir, tf5_str, tf5_details = self.analyze_trend(candles_5m)
        tf1_dir, tf1_str, tf1_details = self.analyze_trend(candles_1m)
        
        # Check 15m backbone - if unclear, STAY AWAY
        if tf15_dir == 'neutral' or tf15_str == 'weak':
            result['stay_away_reason'] = '15m chart unclear - backbone invalid'
            result['warnings'].append('15m timeframe is choppy/unclear')
            return result
        
        # Count alignments
        directions = [tf15_dir, tf5_dir, tf1_dir]
        bullish_count = directions.count('bullish')
        bearish_count = directions.count('bearish')
        
        # Determine alignment
        if bullish_count == 3:
            alignment = 'full'
            bias = 'LONG'
            tf_score = 40
        elif bearish_count == 3:
            alignment = 'full'
            bias = 'SHORT'
            tf_score = 40
        elif bullish_count == 2:
            alignment = 'conditional'
            bias = 'LONG'
            tf_score = 25  # Reduced for 2/3
            diverging = 'tf1' if tf1_dir != 'bullish' else ('tf5' if tf5_dir != 'bullish' else 'tf15')
            result['warnings'].append(f'Conditional read: {diverging} diverging')
        elif bearish_count == 2:
            alignment = 'conditional'
            bias = 'SHORT'
            tf_score = 25
            diverging = 'tf1' if tf1_dir != 'bearish' else ('tf5' if tf5_dir != 'bearish' else 'tf15')
            result['warnings'].append(f'Conditional read: {diverging} diverging')
        else:
            result['stay_away_reason'] = 'Timeframe breakdown - no alignment'
            return result
        
        result['components']['timeframe'] = {
            'score': tf_score,
            'weight': self.WEIGHT_TF_ALIGNMENT,
            'alignment': alignment,
            'tf15': {'direction': tf15_dir, 'strength': tf15_str},
            'tf5': {'direction': tf5_dir, 'strength': tf5_str},
            'tf1': {'direction': tf1_dir, 'strength': tf1_str}
        }
        
        # ========== 2. STRUCTURE ANALYSIS (25%) ==========
        struct_score_15, clean_15, issues_15 = self.analyze_structure(candles_15m)
        struct_score_5, clean_5, issues_5 = self.analyze_structure(candles_5m)
        
        # Weight 15m structure more heavily
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
        
        # ========== 4. RISK/REWARD (10%) ==========
        if entry and stop and target:
            rr_ratio, rr_valid, rr_score = self.calculate_risk_reward(entry, stop, target, bias)
            
            if not rr_valid:
                result['stay_away_reason'] = f'Invalid R:R ({rr_ratio}:1 < {self.MIN_RISK_REWARD}:1 minimum)'
                return result
            
            rr_weighted = (rr_score / 100) * self.WEIGHT_RISK_REWARD
        else:
            rr_ratio = 0
            rr_score = 50  # Neutral if not provided
            rr_weighted = 5
            rr_valid = True
        
        result['components']['risk_reward'] = {
            'score': rr_score,
            'weight': self.WEIGHT_RISK_REWARD,
            'weighted_score': round(rr_weighted, 1),
            'ratio': rr_ratio,
            'is_valid': rr_valid
        }
        
        # ========== 5. CATALYST CHECK (10%) ==========
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
        
        # ========== FINAL CONFIDENCE CALCULATION ==========
        total_confidence = (
            tf_score +
            structure_weighted +
            volume_weighted +
            rr_weighted +
            catalyst_weighted
        )
        
        # Apply conditional penalty if 2/3 alignment
        if alignment == 'conditional':
            penalty = total_confidence * 0.25  # 25% reduction
            total_confidence -= penalty
            result['warnings'].append(f'Confidence reduced by {penalty:.0f}% (2/3 alignment)')
        
        result['direction'] = bias
        result['confidence'] = round(min(100, max(0, total_confidence)))
        result['signal_type'] = bias if result['confidence'] >= 60 else 'NO_TRADE'
        result['entry_type'] = 'MTF_CONFLUENCE'
        
        # Always generate entry/stop/target from candle data
        if candles_1m:
            last_candle = candles_1m[-1]
            current_price = last_candle.get('close', 0)
            result['current_price'] = current_price
            result['entry'] = current_price
            
            # ATR-based stop, then calculate target for exact 2:1 R:R
            atr = self._calculate_atr(candles_5m)
            if atr < 1:
                atr = 5  # Minimum ATR fallback
            
            # Calculate stop based on ATR
            stop_distance = atr * 1.5
            
            if bias == 'LONG':
                result['stop'] = stop if stop else round(current_price - stop_distance, 2)
                # Target = Entry + (2 × stop distance) for exact 2:1 R:R
                actual_stop_dist = abs(current_price - result['stop'])
                result['target'] = round(current_price + (actual_stop_dist * TARGET_RR), 2)
            else:  # SHORT
                result['stop'] = stop if stop else round(current_price + stop_distance, 2)
                actual_stop_dist = abs(result['stop'] - current_price)
                result['target'] = round(current_price - (actual_stop_dist * TARGET_RR), 2)
            
            # R:R is now exactly 2:1
            result['risk_reward'] = TARGET_RR
            
            # ========== POSITION SIZING ($500 risk) ==========
            position = calculate_position_size(ticker, result['entry'], result['stop'])
            result['position_size'] = position
            
            # ========== ENTRY INSTRUCTIONS ==========
            # Based on strength, alignment, and momentum
            tf1_strength = result['components'].get('timeframe', {}).get('tf1', {}).get('strength', 'weak')
            tf5_strength = result['components'].get('timeframe', {}).get('tf5', {}).get('strength', 'weak')
            volume_confirming = result['components'].get('volume', {}).get('is_confirming', False)
            
            instructions = []
            
            # Entry timing based on momentum
            if tf1_strength == 'strong' and tf5_strength in ['strong', 'moderate']:
                if volume_confirming:
                    instructions.append("🚀 STRONG MOMENTUM - Market order OK")
                else:
                    instructions.append("⚡ Good momentum - Enter on next candle close")
            elif alignment == 'full':
                instructions.append("⏳ WAIT FOR PULLBACK to entry level")
                if bias == 'LONG':
                    pullback_target = round(current_price - (atr * 0.5), 2)
                    instructions.append(f"   Look for pullback toward {pullback_target}")
                else:
                    pullback_target = round(current_price + (atr * 0.5), 2)
                    instructions.append(f"   Look for pullback toward {pullback_target}")
            else:  # conditional alignment
                instructions.append("⚠️ WAIT FOR CONFIRMATION")
                instructions.append("   Need diverging timeframe to align first")
            
            # Stop management
            if result['confidence'] >= 80:
                instructions.append("📍 Move stop to breakeven at +1R")
            else:
                instructions.append("📍 Give trade room - don't move stop early")
            
            # Target management
            if volume_confirming and alignment == 'full':
                instructions.append("🎯 Can trail stop for runners")
            else:
                instructions.append("🎯 Take profit at target - don't get greedy")
            
            result['entry_instruction'] = "\n".join(instructions)
        
        return result
    
    def _calculate_atr(self, candles, period=14):
        """Calculate Average True Range"""
        if not candles or len(candles) < 2:
            return 10  # Default
        
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


print("✅ SignalCrawler MTF Analyzer loaded")
print("   Weights: TF=40%, Structure=25%, Volume=15%, R:R=10%, Catalysts=10%")
