"""
Prompt Evolver
Analyzes trading performance to suggest AI prompt improvements.
Tracks which analysis patterns correlate with winning trades.
"""

import json
import os
import re
from datetime import datetime
from collections import defaultdict

# File paths
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
PROMPT_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompt_history.json')

# Base system prompt template with placeholders for modifications
BASE_PROMPT_TEMPLATE = """
You are an advanced futures trading assistant specializing in MICRO futures contracts.
Analyze the provided multi-timeframe data and return ONE clear trade idea.

CRITICAL PRICE ACTION RULES:
- Only suggest trades when ALL timeframes align
- 15m must show clear trend direction (not choppy)
- 5m must show BOS + displacement in that direction
- 1m must show clean retracement (not continued opposite momentum)
- Recent 1m candles (last 3-5) should support the direction
- For LONG: Last 3 candles should NOT all be bearish
- For SHORT: Last 3 candles should NOT all be bullish

{emphasis_rules}

WHEN TO SAY NO_TRADE:
- Choppy, overlapping candles
- Mixed signals across timeframes
- Price in middle of range
- Recent strong momentum AGAINST proposed direction
- Risk:Reward less than 2:1
{caution_rules}

BE CONSERVATIVE. Better to skip 10 mediocre setups than take 1 bad trade.

ENTRY TIMING:
- "IMMEDIATE" - Price at ideal entry zone NOW
- "WAIT_FOR_PULLBACK" - Specify exact pullback level
- "WAIT_FOR_BREAKOUT" - Waiting for break + retest

{time_rules}

{direction_rules}

OUTPUT FORMAT (STRICT JSON):
{{
  "direction": "long" | "short" | "no_trade",
  "confidence": 0-100,
  "entryType": "IMMEDIATE" | "WAIT_FOR_PULLBACK" | "WAIT_FOR_BREAKOUT",
  "entry": number,
  "currentPrice": number,
  "stop": number,
  "takeProfit": number,
  "rationale": "Explain timeframe alignment and structure",
  "entryInstructions": "Detailed entry guidance with specific levels",
  "recentMomentum": "bullish" | "bearish" | "neutral"
}}
"""


def load_settings():
    """Load current settings including prompt modifications"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️  Error loading settings: {e}")
    return {}


def load_prompt_history():
    """Load prompt modification history"""
    try:
        if os.path.exists(PROMPT_HISTORY_FILE):
            with open(PROMPT_HISTORY_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {'modifications': [], 'current_version': 1}


def save_prompt_history(history):
    """Save prompt modification history"""
    try:
        with open(PROMPT_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2, default=str)
    except Exception as e:
        print(f"⚠️  Error saving prompt history: {e}")


def build_dynamic_prompt():
    """
    Build the AI system prompt with all learned modifications
    
    Returns the complete prompt string
    """
    settings = load_settings()
    
    # Get prompt modifications from settings
    mods = settings.get('prompt_modifications', {})
    emphasize = mods.get('emphasize', [])
    caution = mods.get('caution', [])
    
    # Get time filters
    time_filters = settings.get('time_filters', {})
    avoid_hours = time_filters.get('avoid_hours', [])
    prefer_hours = time_filters.get('prefer_hours', [])
    
    # Get direction preference
    direction_pref = settings.get('direction_preference')
    
    # Build emphasis rules
    emphasis_rules = ""
    if emphasize:
        emphasis_rules = "\nHIGH-VALUE PATTERNS (historically strong):\n"
        for phrase in emphasize:
            emphasis_rules += f"- Pay special attention to {phrase.upper()} setups\n"
    
    # Build caution rules
    caution_rules = ""
    if caution:
        caution_rules = "\n\nCAUTION PATTERNS (require extra confirmation):\n"
        for phrase in caution:
            caution_rules += f"- Be more selective with {phrase} setups\n"
    
    # Build time rules
    time_rules = ""
    if avoid_hours:
        hours_str = ", ".join([f"{h:02d}:00" for h in avoid_hours])
        time_rules = f"\nTIME AWARENESS:\n- Exercise extra caution during: {hours_str} (historically weaker performance)\n"
    if prefer_hours:
        hours_str = ", ".join([f"{h:02d}:00" for h in prefer_hours])
        time_rules += f"- Higher confidence allowed during: {hours_str} (historically stronger)\n"
    
    # Build direction rules
    direction_rules = ""
    if direction_pref:
        direction_rules = f"\nDIRECTION GUIDANCE:\n- Current market conditions favor {direction_pref.upper()} trades\n"
        direction_rules += f"- Require higher confidence (85%+) for {('short' if direction_pref == 'long' else 'long')} setups\n"
    
    # Build final prompt
    prompt = BASE_PROMPT_TEMPLATE.format(
        emphasis_rules=emphasis_rules,
        caution_rules=caution_rules,
        time_rules=time_rules,
        direction_rules=direction_rules
    )
    
    return prompt


def get_current_prompt():
    """Get the current evolved prompt"""
    return build_dynamic_prompt()


def add_emphasis(phrase, reason=""):
    """Add a phrase to emphasize in the prompt"""
    settings = load_settings()
    
    if 'prompt_modifications' not in settings:
        settings['prompt_modifications'] = {'emphasize': [], 'caution': []}
    
    phrase = phrase.lower().strip()
    if phrase not in settings['prompt_modifications']['emphasize']:
        settings['prompt_modifications']['emphasize'].append(phrase)
        
        # Log to history
        history = load_prompt_history()
        history['modifications'].append({
            'type': 'emphasis_added',
            'phrase': phrase,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })
        history['current_version'] += 1
        save_prompt_history(history)
        
        # Save settings
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        
        return True
    return False


def add_caution(phrase, reason=""):
    """Add a phrase to add caution for in the prompt"""
    settings = load_settings()
    
    if 'prompt_modifications' not in settings:
        settings['prompt_modifications'] = {'emphasize': [], 'caution': []}
    
    phrase = phrase.lower().strip()
    if phrase not in settings['prompt_modifications']['caution']:
        settings['prompt_modifications']['caution'].append(phrase)
        
        # Log to history
        history = load_prompt_history()
        history['modifications'].append({
            'type': 'caution_added',
            'phrase': phrase,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })
        history['current_version'] += 1
        save_prompt_history(history)
        
        # Save settings
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        
        return True
    return False


def remove_emphasis(phrase):
    """Remove a phrase from emphasis list"""
    settings = load_settings()
    mods = settings.get('prompt_modifications', {})
    emphasize = mods.get('emphasize', [])
    
    phrase = phrase.lower().strip()
    if phrase in emphasize:
        emphasize.remove(phrase)
        settings['prompt_modifications']['emphasize'] = emphasize
        
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        
        return True
    return False


def remove_caution(phrase):
    """Remove a phrase from caution list"""
    settings = load_settings()
    mods = settings.get('prompt_modifications', {})
    caution = mods.get('caution', [])
    
    phrase = phrase.lower().strip()
    if phrase in caution:
        caution.remove(phrase)
        settings['prompt_modifications']['caution'] = caution
        
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        
        return True
    return False


def get_prompt_status():
    """Get current prompt modification status"""
    settings = load_settings()
    history = load_prompt_history()
    
    mods = settings.get('prompt_modifications', {})
    time_filters = settings.get('time_filters', {})
    
    return {
        'version': history.get('current_version', 1),
        'emphasized_patterns': mods.get('emphasize', []),
        'caution_patterns': mods.get('caution', []),
        'avoid_hours': time_filters.get('avoid_hours', []),
        'prefer_hours': time_filters.get('prefer_hours', []),
        'direction_preference': settings.get('direction_preference'),
        'total_modifications': len(history.get('modifications', [])),
        'last_modified': history['modifications'][-1]['timestamp'] if history.get('modifications') else None
    }


def reset_prompt():
    """Reset prompt to base version (remove all modifications)"""
    settings = load_settings()
    
    settings['prompt_modifications'] = {'emphasize': [], 'caution': []}
    settings['time_filters'] = {'avoid_hours': [], 'prefer_hours': []}
    if 'direction_preference' in settings:
        del settings['direction_preference']
    
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)
    
    # Log reset
    history = load_prompt_history()
    history['modifications'].append({
        'type': 'reset',
        'timestamp': datetime.now().isoformat()
    })
    history['current_version'] += 1
    save_prompt_history(history)
    
    return True


def get_modification_history(limit=20):
    """Get recent prompt modification history"""
    history = load_prompt_history()
    mods = history.get('modifications', [])
    return mods[-limit:] if len(mods) > limit else mods


print("✅ Prompt Evolver loaded")

