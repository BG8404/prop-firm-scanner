"""
Multi-Timeframe Rule-Based Analyzer v2
SIMPLIFIED: All 3 timeframes aligned = SIGNAL

15m = Higher Timeframe Direction
5m  = Mid Timeframe Confirmation  
1m  = Entry Timeframe Alignment

Confidence Scoring (NEW):
- 15m direction clear = +35%
- 5m same direction = +35%
- 1m same direction = +20%
- BOS detected = +10%

Optional factors tracked for AI Coach learning:
- Volume, Time of day, Candle size, etc.
"""

from datetime import datetime
import statistics


class MTFAnalyzer:
    """
    Simplified Multi-Timeframe Analyzer
    Core rule: All 3 timeframes must align
    """
    
    def __init__(self):
        pass
    
    # ==================== HELPERS ====================
    
    def get_candle_direction(self, candle):
        """Determine if a single candle is bullish or bearish"""
        open_price = candle.get('open', 0)
        close_price = candle.get('close', 0)
        
        if close_price > open_price:
            return 'bullish'
        elif close_price < open_price:
            return 'bearish'
        else:
            return 'neutral'
    
    def get_trend_direction(self, candles):
        """
        Determine overall trend direction from candles
        Simple: Compare first candle open to last candle close
        """
        if not candles or len(candles) < 1:
            return 'neutral', {}
        
        first_open = candles[0].get('open', 0)
        last_close = candles[-1].get('close', 0)
        
        # Calculate change
        if first_open > 0:
            change_pct = ((last_close - first_open) / first_open) * 100
        else:
            change_pct = 0
        
        # Get high/low range
        high = max(c.get('high', 0) for c in candles)
        low = min(c.get('low', float('inf')) for c in candles)
        
        # Count bullish vs bearish candles
        bullish_count = sum(1 for c in candles if c.get('close', 0) > c.get('open', 0))
        bearish_count = sum(1 for c in candles if c.get('close', 0) < c.get('open', 0))
        
        details = {
            'first_open': first_open,
            'last_close': last_close,
            'change_pct': round(change_pct, 3),
            'high': high,
            'low': low,
            'bullish_candles': bullish_count,
            'bearish_candles': bearish_count,
            'total_candles': len(candles)
        }
        
        # Determine direction
        if last_close > first_open and bullish_count >= bearish_count:
            return 'bullish', details
        elif last_close < first_open and bearish_count >= bullish_count:
            return 'bearish', details
        elif change_pct > 0.05:  # Slight upward bias
            return 'bullish', details
        elif change_pct < -0.05:  # Slight downward bias
            return 'bearish', details
        else:
            return 'neutral', details
    
    def detect_bos(self, candles, direction):
        """
        Detect Break of Structure
        Simple: Did price break recent high (bullish) or low (bearish)?
        """
        if len(candles) < 3:
            return False, {}
        
        # Get recent range (excluding last candle)
        recent = candles[:-1]
        recent_high = max(c.get('high', 0) for c in recent)
        recent_low = min(c.get('low', float('inf')) for c in recent)
        
        # Check if last candle broke the range
        last_candle = candles[-1]
        last_high = last_candle.get('high', 0)
        last_low = last_candle.get('low', float('inf'))
        last_close = last_candle.get('close', 0)
        
        if direction == 'bullish':
            # Bullish BOS: Price closed above recent high
            if last_close > recent_high or last_high > recent_high:
                return True, {'type': 'bullish_bos', 'broken_level': recent_high}
        elif direction == 'bearish':
            # Bearish BOS: Price closed below recent low
            if last_close < recent_low or last_low < recent_low:
                return True, {'type': 'bearish_bos', 'broken_level': recent_low}
        
        return False, {}
    
    def check_volume(self, candles):
        """Check if current volume is above average (tracked for AI learning)"""
        if len(candles) < 2:
            return False, 0
        
        volumes = [c.get('volume', 0) for c in candles[:-1]]
        if not volumes or sum(volumes) == 0:
            return False, 0
        
        avg_volume = statistics.mean(volumes)
        current_volume = candles[-1].get('volume', 0)
        
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        is_spike = volume_ratio > 1.5
        
        return is_spike, round(volume_ratio, 2)
    
    def get_candle_size(self, candle):
        """Get candle size relative info (tracked for AI learning)"""
        high = candle.get('high', 0)
        low = candle.get('low', 0)
        open_price = candle.get('open', 0)
        close_price = candle.get('close', 0)
        
        total_range = high - low
        body_size = abs(close_price - open_price)
        
        return {
            'total_range': total_range,
            'body_size': body_size,
            'body_pct': round((body_size / total_range * 100) if total_range > 0 else 0, 1)
        }
    
    def get_time_info(self):
        """Get time of day info (tracked for AI learning)"""
        now = datetime.now()
        hour = now.hour
        
        # Trading sessions (EST assumed)
        if 9 <= hour < 12:
            session = 'morning'
        elif 12 <= hour < 14:
            session = 'midday'
        elif 14 <= hour < 16:
            session = 'afternoon'
        else:
            session = 'extended'
        
        return {
            'hour': hour,
            'minute': now.minute,
            'session': session,
            'day_of_week': now.strftime('%A')
        }
    
    # ==================== MAIN ANALYSIS ====================
    
    def analyze_timeframe(self, candles, timeframe_name):
        """
        Analyze a single timeframe
        Returns direction and details
        """
        if not candles or len(candles) < 1:
            return 'neutral', {'error': f'No {timeframe_name} data'}
        
        direction, details = self.get_trend_direction(candles)
        
        # Add BOS detection
        if direction != 'neutral' and len(candles) >= 3:
            bos, bos_details = self.detect_bos(candles, direction)
            details['bos_detected'] = bos
            details['bos_details'] = bos_details
        else:
            details['bos_detected'] = False
        
        # Add volume info
        vol_spike, vol_ratio = self.check_volume(candles)
        details['volume_spike'] = vol_spike
        details['volume_ratio'] = vol_ratio
        
        # Add last candle info
        if candles:
            details['last_candle'] = self.get_candle_size(candles[-1])
            details['current_price'] = candles[-1].get('close', 0)
        
        return direction, details
    
    def full_analysis(self, candles_15m, candles_5m, candles_1m, ticker='UNKNOWN'):
        """
        Run full multi-timeframe analysis
        
        NEW SIMPLIFIED SCORING:
        - 15m direction clear = +35%
        - 5m same direction = +35%  
        - 1m same direction = +20%
        - BOS detected (any TF) = +10%
        
        SIGNAL: All 3 timeframes aligned (90%+ confidence)
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
            'analysis': {},
            'tracking': {}  # For AI Coach learning
        }
        
        # Add time tracking for AI learning
        result['tracking']['time'] = self.get_time_info()
        
        # ===== STEP 1: 15m Analysis (+35%) =====
        direction_15m, details_15m = self.analyze_timeframe(candles_15m, '15m')
        result['analysis']['15m'] = details_15m
        result['analysis']['15m']['direction'] = direction_15m
        
        if direction_15m == 'neutral':
            result['rejection'] = 'No clear 15m direction'
            return result
        
        # 15m has direction - add 35%
        result['confidence'] += 35
        result['htf_bias'] = direction_15m.upper()
        
        # ===== STEP 2: 5m Analysis (+35%) =====
        direction_5m, details_5m = self.analyze_timeframe(candles_5m, '5m')
        result['analysis']['5m'] = details_5m
        result['analysis']['5m']['direction'] = direction_5m
        
        # Check if 5m aligns with 15m
        if direction_5m == direction_15m:
            result['confidence'] += 35
            result['analysis']['5m']['aligned'] = True
        else:
            result['analysis']['5m']['aligned'] = False
            result['rejection'] = f'5m ({direction_5m}) not aligned with 15m ({direction_15m})'
            return result
        
        # ===== STEP 3: 1m Analysis (+20%) =====
        direction_1m, details_1m = self.analyze_timeframe(candles_1m, '1m')
        result['analysis']['1m'] = details_1m
        result['analysis']['1m']['direction'] = direction_1m
        
        # Check if 1m aligns
        if direction_1m == direction_15m:
            result['confidence'] += 20
            result['analysis']['1m']['aligned'] = True
        else:
            result['analysis']['1m']['aligned'] = False
            result['rejection'] = f'1m ({direction_1m}) not aligned with 15m/5m ({direction_15m})'
            return result
        
        # ===== STEP 4: BOS Bonus (+10%) =====
        bos_found = False
        for tf in ['15m', '5m', '1m']:
            if result['analysis'].get(tf, {}).get('bos_detected', False):
                bos_found = True
                result['analysis']['bos_timeframe'] = tf
                break
        
        if bos_found:
            result['confidence'] += 10
        
        result['tracking']['bos_detected'] = bos_found
        
        # ===== ALL ALIGNED - GENERATE SIGNAL =====
        result['setup_valid'] = True
        result['entry_valid'] = True
        result['direction'] = 'long' if direction_15m == 'bullish' else 'short'
        result['entry_type'] = 'MTF_ALIGNMENT'
        
        # Calculate entry, stop, target
        current_price = candles_1m[-1].get('close', 0) if candles_1m else 0
        
        # Get recent swing points for stop
        if candles_1m and len(candles_1m) >= 3:
            if result['direction'] == 'long':
                recent_low = min(c.get('low', float('inf')) for c in candles_1m[-5:])
                stop = recent_low
                risk = current_price - stop
                target = current_price + (risk * 2)  # 2:1 R:R
            else:
                recent_high = max(c.get('high', 0) for c in candles_1m[-5:])
                stop = recent_high
                risk = stop - current_price
                target = current_price - (risk * 2)  # 2:1 R:R
        else:
            # Default stops
            if result['direction'] == 'long':
                stop = current_price * 0.998
                target = current_price * 1.004
            else:
                stop = current_price * 1.002
                target = current_price * 0.996
        
        result['entry'] = round(current_price, 2)
        result['stop'] = round(stop, 2)
        result['target'] = round(target, 2)
        
        # Track additional factors for AI learning
        result['tracking']['volume_spike_15m'] = details_15m.get('volume_spike', False)
        result['tracking']['volume_spike_5m'] = details_5m.get('volume_spike', False)
        result['tracking']['volume_spike_1m'] = details_1m.get('volume_spike', False)
        result['tracking']['candle_body_pct'] = details_1m.get('last_candle', {}).get('body_pct', 0)
        
        # Build rationale
        result['rationale'] = self._build_rationale(result)
        
        return result
    
    def _build_rationale(self, result):
        """Build human-readable rationale"""
        direction = result['direction'].upper()
        confidence = result['confidence']
        
        a15 = result['analysis'].get('15m', {})
        a5 = result['analysis'].get('5m', {})
        a1 = result['analysis'].get('1m', {})
        
        rationale = f"""
{direction} SIGNAL ({confidence}% confidence)

✅ 15m: {a15.get('direction', 'unknown').upper()} (+35%)
   Change: {a15.get('change_pct', 0)}%
   Candles: {a15.get('bullish_candles', 0)} bullish / {a15.get('bearish_candles', 0)} bearish

✅ 5m: {a5.get('direction', 'unknown').upper()} - ALIGNED (+35%)
   Change: {a5.get('change_pct', 0)}%

✅ 1m: {a1.get('direction', 'unknown').upper()} - ALIGNED (+20%)
   Change: {a1.get('change_pct', 0)}%

{'✅ BOS Detected (+10%)' if result.get('tracking', {}).get('bos_detected') else '❌ No BOS'}

Entry: {result.get('entry')}
Stop: {result.get('stop')}
Target: {result.get('target')}
"""
        return rationale.strip()


# Singleton instance
mtf_analyzer = MTFAnalyzer()


def analyze_ticker(candles_15m, candles_5m, candles_1m, ticker='UNKNOWN'):
    """Convenience function for full MTF analysis"""
    return mtf_analyzer.full_analysis(candles_15m, candles_5m, candles_1m, ticker)


print("✅ MTF Analyzer v2 loaded (Simplified: All 3 TFs aligned = signal)")
