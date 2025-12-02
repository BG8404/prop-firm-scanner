"""
Multi-Timeframe Rule-Based Analyzer
Mechanical confluence system for high-probability trade signals

15m = Higher Timeframe Bias (trend direction)
5m  = Setup Confirmation (structure breaks, alignment)
1m  = Entry Trigger (micro alignment, entry conditions)

Confidence Scoring:
- 15m bias match = +40%
- 5m trend match = +30%
- 5m momentum match = +20%
- 5m structure break = +10%
"""

from collections import deque
from datetime import datetime
import statistics


class MTFAnalyzer:
    """
    Multi-Timeframe Analyzer with rule-based confluence scoring
    """
    
    def __init__(self):
        self.ema_periods = {
            '15m': 20,  # HTF trend EMA
            '5m': 21,   # Setup EMA
            '1m': 9     # Entry EMA
        }
    
    # ==================== HELPERS ====================
    
    def calculate_ema(self, candles, period):
        """Calculate EMA from candle closes"""
        if len(candles) < period:
            return None
        
        closes = [c.get('close', 0) for c in candles]
        multiplier = 2 / (period + 1)
        
        # Start with SMA
        ema = sum(closes[:period]) / period
        
        # Calculate EMA
        for close in closes[period:]:
            ema = (close - ema) * multiplier + ema
        
        return ema
    
    def find_swing_highs(self, candles, lookback=5):
        """Find swing high points"""
        swing_highs = []
        for i in range(lookback, len(candles) - lookback):
            high = candles[i].get('high', 0)
            is_swing = True
            for j in range(i - lookback, i + lookback + 1):
                if j != i and candles[j].get('high', 0) >= high:
                    is_swing = False
                    break
            if is_swing:
                swing_highs.append({'index': i, 'price': high, 'time': candles[i].get('time')})
        return swing_highs
    
    def find_swing_lows(self, candles, lookback=5):
        """Find swing low points"""
        swing_lows = []
        for i in range(lookback, len(candles) - lookback):
            low = candles[i].get('low', 0)
            is_swing = True
            for j in range(i - lookback, i + lookback + 1):
                if j != i and candles[j].get('low', 0) <= low:
                    is_swing = False
                    break
            if is_swing:
                swing_lows.append({'index': i, 'price': low, 'time': candles[i].get('time')})
        return swing_lows
    
    def detect_trend_structure(self, candles, lookback=3):
        """
        Detect HH/HL (bullish) or LL/LH (bearish) structure
        Returns: 'bullish', 'bearish', or 'neutral'
        """
        swing_highs = self.find_swing_highs(candles, lookback)
        swing_lows = self.find_swing_lows(candles, lookback)
        
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return 'neutral', {}
        
        # Get last 2 swing points
        recent_highs = swing_highs[-2:]
        recent_lows = swing_lows[-2:]
        
        hh = recent_highs[-1]['price'] > recent_highs[-2]['price']  # Higher High
        hl = recent_lows[-1]['price'] > recent_lows[-2]['price']    # Higher Low
        ll = recent_lows[-1]['price'] < recent_lows[-2]['price']    # Lower Low
        lh = recent_highs[-1]['price'] < recent_highs[-2]['price']  # Lower High
        
        structure_data = {
            'swing_highs': recent_highs,
            'swing_lows': recent_lows,
            'hh': hh, 'hl': hl, 'll': ll, 'lh': lh
        }
        
        if hh and hl:
            return 'bullish', structure_data
        elif ll and lh:
            return 'bearish', structure_data
        else:
            return 'neutral', structure_data
    
    def detect_bos(self, candles, direction, lookback=10):
        """
        Detect Break of Structure
        direction: 'bullish' or 'bearish'
        Returns: True if BOS detected, with details
        """
        if len(candles) < lookback + 5:
            return False, {}
        
        swing_highs = self.find_swing_highs(candles[:-3], lookback=3)  # Exclude last 3 candles
        swing_lows = self.find_swing_lows(candles[:-3], lookback=3)
        
        current_close = candles[-1].get('close', 0)
        current_high = candles[-1].get('high', 0)
        current_low = candles[-1].get('low', 0)
        
        if direction == 'bullish' and swing_highs:
            last_swing_high = swing_highs[-1]['price']
            if current_close > last_swing_high or current_high > last_swing_high:
                return True, {'type': 'bos_up', 'broken_level': last_swing_high, 'current': current_close}
        
        elif direction == 'bearish' and swing_lows:
            last_swing_low = swing_lows[-1]['price']
            if current_close < last_swing_low or current_low < last_swing_low:
                return True, {'type': 'bos_down', 'broken_level': last_swing_low, 'current': current_close}
        
        return False, {}
    
    def check_ema_position(self, candles, period):
        """Check if price is above or below EMA"""
        ema = self.calculate_ema(candles, period)
        if ema is None:
            return 'neutral', None
        
        current_close = candles[-1].get('close', 0)
        
        if current_close > ema * 1.001:  # Small buffer
            return 'above', ema
        elif current_close < ema * 0.999:
            return 'below', ema
        else:
            return 'at', ema
    
    def check_pullback_to_ema(self, candles, period, tolerance_pct=0.2):
        """Check if price recently pulled back to EMA"""
        ema = self.calculate_ema(candles, period)
        if ema is None:
            return False, {}
        
        # Check last 3 candles for EMA touch
        for i in range(-3, 0):
            candle = candles[i]
            low = candle.get('low', 0)
            high = candle.get('high', 0)
            
            tolerance = ema * (tolerance_pct / 100)
            
            if low <= ema + tolerance and high >= ema - tolerance:
                return True, {'ema': ema, 'touch_candle': i}
        
        return False, {}
    
    def check_momentum(self, candles, lookback=5):
        """
        Check momentum direction based on recent candles
        Returns: 'bullish', 'bearish', or 'neutral'
        """
        if len(candles) < lookback:
            return 'neutral', 0
        
        recent = candles[-lookback:]
        
        bullish_candles = sum(1 for c in recent if c.get('close', 0) > c.get('open', 0))
        bearish_candles = sum(1 for c in recent if c.get('close', 0) < c.get('open', 0))
        
        # Price change
        price_change = recent[-1].get('close', 0) - recent[0].get('open', 0)
        
        if bullish_candles >= 3 and price_change > 0:
            return 'bullish', bullish_candles
        elif bearish_candles >= 3 and price_change < 0:
            return 'bearish', bearish_candles
        else:
            return 'neutral', 0
    
    def check_micro_trend(self, candles_1m):
        """Check 1m micro trend alignment"""
        if len(candles_1m) < 10:
            return 'neutral', {}
        
        trend, structure = self.detect_trend_structure(candles_1m, lookback=2)
        return trend, structure
    
    def detect_expansion_candle(self, candles, threshold_mult=1.5):
        """Detect if last candle is an expansion/momentum candle"""
        if len(candles) < 10:
            return False, {}
        
        # Calculate average candle size
        recent_sizes = [abs(c.get('close', 0) - c.get('open', 0)) for c in candles[-10:-1]]
        avg_size = statistics.mean(recent_sizes) if recent_sizes else 0
        
        if avg_size == 0:
            return False, {}
        
        last_candle = candles[-1]
        last_size = abs(last_candle.get('close', 0) - last_candle.get('open', 0))
        
        if last_size > avg_size * threshold_mult:
            direction = 'bullish' if last_candle.get('close', 0) > last_candle.get('open', 0) else 'bearish'
            return True, {'size': last_size, 'avg_size': avg_size, 'direction': direction}
        
        return False, {}
    
    def check_choppiness(self, candles, lookback=10):
        """Detect if market is choppy (avoid trading)"""
        if len(candles) < lookback:
            return False, 0
        
        recent = candles[-lookback:]
        
        # Count direction changes
        direction_changes = 0
        for i in range(1, len(recent)):
            prev_dir = 'up' if recent[i-1].get('close', 0) > recent[i-1].get('open', 0) else 'down'
            curr_dir = 'up' if recent[i].get('close', 0) > recent[i].get('open', 0) else 'down'
            if prev_dir != curr_dir:
                direction_changes += 1
        
        choppiness_score = direction_changes / (lookback - 1)
        is_choppy = choppiness_score > 0.6  # More than 60% direction changes = choppy
        
        return is_choppy, choppiness_score
    
    # ==================== MAIN ANALYSIS ====================
    
    def analyze_15m(self, candles_15m):
        """
        15-MIN TIMEFRAME — Higher-Timeframe Bias + Major Structure
        
        Returns:
            htf_bias: 'BULLISH', 'BEARISH', or 'NEUTRAL'
            details: dict with analysis details
        """
        if not candles_15m or len(candles_15m) < 20:
            return 'NEUTRAL', {'error': 'Insufficient 15m data'}
        
        # 1. Trend Direction (HH/HL or LL/LH)
        trend, structure = self.detect_trend_structure(candles_15m, lookback=4)
        
        # 2. Key Levels
        swing_highs = self.find_swing_highs(candles_15m, lookback=4)
        swing_lows = self.find_swing_lows(candles_15m, lookback=4)
        
        key_levels = {
            'resistance': swing_highs[-1]['price'] if swing_highs else None,
            'support': swing_lows[-1]['price'] if swing_lows else None
        }
        
        # 3. Momentum Filter (EMA position)
        ema_pos, ema_value = self.check_ema_position(candles_15m, self.ema_periods['15m'])
        
        # 4. Determine HTF Bias
        if trend == 'bullish' and ema_pos == 'above':
            htf_bias = 'BULLISH'
        elif trend == 'bearish' and ema_pos == 'below':
            htf_bias = 'BEARISH'
        elif trend == 'bullish' or ema_pos == 'above':
            htf_bias = 'BULLISH'  # Lean bullish
        elif trend == 'bearish' or ema_pos == 'below':
            htf_bias = 'BEARISH'  # Lean bearish
        else:
            htf_bias = 'NEUTRAL'
        
        return htf_bias, {
            'trend': trend,
            'structure': structure,
            'ema_position': ema_pos,
            'ema_value': ema_value,
            'key_levels': key_levels,
            'current_price': candles_15m[-1].get('close')
        }
    
    def analyze_5m(self, candles_5m, htf_bias):
        """
        5-MIN TIMEFRAME — Setup Confirmation
        
        Scoring:
        - 15m bias match = +40%
        - 5m trend match = +30%
        - 5m momentum match = +20%
        - 5m structure break = +10%
        
        Returns:
            score: 0-100 confidence score
            setup_valid: bool
            details: dict
        """
        if not candles_5m or len(candles_5m) < 20:
            return 0, False, {'error': 'Insufficient 5m data'}
        
        score = 0
        details = {}
        
        # 1. 5m Trend Direction
        trend_5m, structure_5m = self.detect_trend_structure(candles_5m, lookback=3)
        details['trend'] = trend_5m
        details['structure'] = structure_5m
        
        # 2. Alignment with 15m Bias (+40%)
        bias_aligned = False
        if htf_bias == 'BULLISH' and trend_5m == 'bullish':
            score += 40
            bias_aligned = True
        elif htf_bias == 'BEARISH' and trend_5m == 'bearish':
            score += 40
            bias_aligned = True
        elif htf_bias == 'NEUTRAL':
            score += 20  # Partial credit for neutral
        
        details['bias_aligned'] = bias_aligned
        details['bias_score'] = 40 if bias_aligned else (20 if htf_bias == 'NEUTRAL' else 0)
        
        # 3. 5m Trend Match (+30%)
        ema_pos, ema_value = self.check_ema_position(candles_5m, self.ema_periods['5m'])
        trend_match = False
        
        if htf_bias == 'BULLISH' and ema_pos == 'above':
            score += 30
            trend_match = True
        elif htf_bias == 'BEARISH' and ema_pos == 'below':
            score += 30
            trend_match = True
        
        details['ema_position'] = ema_pos
        details['trend_match'] = trend_match
        details['trend_score'] = 30 if trend_match else 0
        
        # 4. 5m Momentum Match (+20%)
        momentum, momentum_strength = self.check_momentum(candles_5m, lookback=5)
        momentum_match = False
        
        if htf_bias == 'BULLISH' and momentum == 'bullish':
            score += 20
            momentum_match = True
        elif htf_bias == 'BEARISH' and momentum == 'bearish':
            score += 20
            momentum_match = True
        
        details['momentum'] = momentum
        details['momentum_match'] = momentum_match
        details['momentum_score'] = 20 if momentum_match else 0
        
        # 5. 5m Structure Break (+10%)
        direction = 'bullish' if htf_bias == 'BULLISH' else 'bearish' if htf_bias == 'BEARISH' else None
        bos_detected = False
        
        if direction:
            bos_detected, bos_details = self.detect_bos(candles_5m, direction)
            if bos_detected:
                score += 10
                details['bos'] = bos_details
        
        details['bos_detected'] = bos_detected
        details['bos_score'] = 10 if bos_detected else 0
        
        # 6. Pullback Check (bonus info)
        pullback, pullback_details = self.check_pullback_to_ema(candles_5m, self.ema_periods['5m'])
        details['pullback_to_ema'] = pullback
        
        details['total_score'] = score
        setup_valid = score >= 70
        
        return score, setup_valid, details
    
    def analyze_1m(self, candles_1m, htf_bias, setup_direction):
        """
        1-MIN TIMEFRAME — Entry Trigger
        
        Checks:
        - Micro trend alignment
        - Entry conditions (structure break, pullback, expansion)
        - Drift/choppiness control
        
        Returns:
            entry_valid: bool
            entry_type: str
            details: dict
        """
        if not candles_1m or len(candles_1m) < 15:
            return False, None, {'error': 'Insufficient 1m data'}
        
        details = {}
        entry_valid = False
        entry_type = None
        
        # 1. Micro Trend Alignment
        micro_trend, micro_structure = self.check_micro_trend(candles_1m)
        details['micro_trend'] = micro_trend
        
        trend_aligned = False
        if setup_direction == 'long' and micro_trend == 'bullish':
            trend_aligned = True
        elif setup_direction == 'short' and micro_trend == 'bearish':
            trend_aligned = True
        
        details['micro_aligned'] = trend_aligned
        
        # 2. Check for Choppiness (avoid)
        is_choppy, chop_score = self.check_choppiness(candles_1m, lookback=10)
        details['is_choppy'] = is_choppy
        details['choppiness_score'] = chop_score
        
        if is_choppy:
            details['rejection_reason'] = 'Market too choppy'
            return False, None, details
        
        # 3. Entry Conditions
        
        # A. Structure Break
        direction = 'bullish' if setup_direction == 'long' else 'bearish'
        micro_bos, bos_details = self.detect_bos(candles_1m, direction, lookback=5)
        details['micro_bos'] = micro_bos
        
        # B. Pullback to EMA
        pullback, pullback_details = self.check_pullback_to_ema(candles_1m, self.ema_periods['1m'])
        details['pullback'] = pullback
        
        # C. Expansion Candle
        expansion, expansion_details = self.detect_expansion_candle(candles_1m)
        details['expansion'] = expansion
        if expansion:
            details['expansion_details'] = expansion_details
        
        # 4. Determine Entry
        if trend_aligned:
            if micro_bos:
                entry_valid = True
                entry_type = 'STRUCTURE_BREAK'
            elif pullback:
                entry_valid = True
                entry_type = 'PULLBACK'
            elif expansion and expansion_details.get('direction') == direction:
                entry_valid = True
                entry_type = 'MOMENTUM_EXPANSION'
        
        details['entry_valid'] = entry_valid
        details['entry_type'] = entry_type
        
        return entry_valid, entry_type, details
    
    def full_analysis(self, candles_15m, candles_5m, candles_1m, ticker='UNKNOWN'):
        """
        Run full multi-timeframe analysis
        
        Returns comprehensive signal with confidence scoring
        """
        result = {
            'ticker': ticker,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'direction': 'no_trade',
            'confidence': 0,
            'htf_bias': 'NEUTRAL',
            'setup_valid': False,
            'entry_valid': False,
            'entry_type': None,
            'analysis': {}
        }
        
        # Step 1: 15m HTF Bias
        htf_bias, htf_details = self.analyze_15m(candles_15m)
        result['htf_bias'] = htf_bias
        result['analysis']['15m'] = htf_details
        
        if htf_bias == 'NEUTRAL':
            result['analysis']['rejection'] = 'No clear 15m bias'
            return result
        
        # Step 2: 5m Setup Confirmation
        score_5m, setup_valid, setup_details = self.analyze_5m(candles_5m, htf_bias)
        result['analysis']['5m'] = setup_details
        result['setup_valid'] = setup_valid
        result['confidence'] = score_5m
        
        if not setup_valid:
            result['analysis']['rejection'] = f'5m setup score too low ({score_5m}%)'
            return result
        
        # Step 3: 1m Entry Trigger
        setup_direction = 'long' if htf_bias == 'BULLISH' else 'short'
        entry_valid, entry_type, entry_details = self.analyze_1m(candles_1m, htf_bias, setup_direction)
        result['analysis']['1m'] = entry_details
        result['entry_valid'] = entry_valid
        result['entry_type'] = entry_type
        
        if not entry_valid:
            result['analysis']['rejection'] = entry_details.get('rejection_reason', 'No valid 1m entry trigger')
            return result
        
        # All conditions met!
        result['direction'] = setup_direction
        result['confidence'] = score_5m
        
        # Generate entry/stop/target
        current_price = candles_1m[-1].get('close', 0)
        result['current_price'] = current_price
        
        # Calculate levels based on structure
        if setup_direction == 'long':
            swing_lows = self.find_swing_lows(candles_1m, lookback=3)
            stop = swing_lows[-1]['price'] if swing_lows else current_price * 0.998
            risk = current_price - stop
            target = current_price + (risk * 2)  # 2:1 R:R
        else:
            swing_highs = self.find_swing_highs(candles_1m, lookback=3)
            stop = swing_highs[-1]['price'] if swing_highs else current_price * 1.002
            risk = stop - current_price
            target = current_price - (risk * 2)  # 2:1 R:R
        
        result['entry'] = round(current_price, 2)
        result['stop'] = round(stop, 2)
        result['target'] = round(target, 2)
        
        # Build rationale
        result['rationale'] = self._build_rationale(result)
        
        return result
    
    def _build_rationale(self, result):
        """Build human-readable rationale"""
        direction = result['direction'].upper()
        confidence = result['confidence']
        htf_bias = result['htf_bias']
        entry_type = result['entry_type']
        
        details_15m = result['analysis'].get('15m', {})
        details_5m = result['analysis'].get('5m', {})
        details_1m = result['analysis'].get('1m', {})
        
        rationale = f"""
{direction} Signal ({confidence}% confidence)

15m Analysis:
- HTF Bias: {htf_bias}
- Trend: {details_15m.get('trend', 'unknown')}
- EMA Position: {details_15m.get('ema_position', 'unknown')}

5m Analysis:
- Bias Aligned: {'Yes' if details_5m.get('bias_aligned') else 'No'} (+{details_5m.get('bias_score', 0)}%)
- Trend Match: {'Yes' if details_5m.get('trend_match') else 'No'} (+{details_5m.get('trend_score', 0)}%)
- Momentum Match: {'Yes' if details_5m.get('momentum_match') else 'No'} (+{details_5m.get('momentum_score', 0)}%)
- BOS Detected: {'Yes' if details_5m.get('bos_detected') else 'No'} (+{details_5m.get('bos_score', 0)}%)

1m Entry:
- Type: {entry_type}
- Micro Trend: {details_1m.get('micro_trend', 'unknown')}
- Choppy: {'Yes' if details_1m.get('is_choppy') else 'No'}
"""
        return rationale.strip()


# Singleton instance
mtf_analyzer = MTFAnalyzer()


def analyze_ticker(candles_15m, candles_5m, candles_1m, ticker='UNKNOWN'):
    """Convenience function for full MTF analysis"""
    return mtf_analyzer.full_analysis(candles_15m, candles_5m, candles_1m, ticker)


print("✅ Multi-Timeframe Analyzer loaded")

