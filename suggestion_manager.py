"""
Suggestion Manager
Tracks AI Coach suggestions, approvals, rejections, and outcomes.
Measures actual vs projected impact of approved changes.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from threading import Lock

# Database and state files
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_journal.db')
SUGGESTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'coach_suggestions.json')
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')

# Thread safety
suggestion_lock = Lock()


def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_suggestions_table():
    """Initialize suggestions tracking table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS coach_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suggestion_id TEXT UNIQUE NOT NULL,
            type TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            explanation TEXT,
            action TEXT,
            projected_impact TEXT,
            confidence REAL,
            sample_size INTEGER,
            p_value REAL,
            data TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            reviewed_at TEXT,
            rejection_reason TEXT,
            applied_settings TEXT,
            baseline_win_rate REAL,
            baseline_trades INTEGER,
            post_win_rate REAL,
            post_trades INTEGER,
            actual_impact TEXT
        )
    ''')
    
    conn.commit()
    conn.close()


def load_suggestions_state():
    """Load suggestions state from file"""
    default = {
        'pending': [],
        'approved': [],
        'rejected': [],
        'last_analysis': None,
        'changes_this_week': 0,
        'week_start': None
    }
    try:
        if os.path.exists(SUGGESTIONS_FILE):
            with open(SUGGESTIONS_FILE, 'r') as f:
                state = json.load(f)
                # Merge with defaults
                for key in default:
                    if key not in state:
                        state[key] = default[key]
                return state
    except Exception as e:
        print(f"⚠️  Error loading suggestions state: {e}")
    return default


def save_suggestions_state(state):
    """Save suggestions state to file"""
    try:
        with open(SUGGESTIONS_FILE, 'w') as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        print(f"⚠️  Error saving suggestions state: {e}")


def generate_suggestion_id(suggestion):
    """Generate unique ID for a suggestion"""
    import hashlib
    content = f"{suggestion['type']}_{suggestion['category']}_{suggestion.get('title', '')}"
    return hashlib.md5(content.encode()).hexdigest()[:12]


def add_suggestions(suggestions):
    """
    Add new suggestions from analysis
    Deduplicates and tracks in database
    """
    with suggestion_lock:
        state = load_suggestions_state()
        conn = get_connection()
        cursor = conn.cursor()
        
        # Get existing suggestion IDs
        existing_ids = set()
        for s in state['pending']:
            existing_ids.add(s.get('suggestion_id'))
        for s in state['approved']:
            existing_ids.add(s.get('suggestion_id'))
        
        # Also check recently rejected (within 7 days)
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        for s in state['rejected']:
            if s.get('reviewed_at', '') > week_ago:
                existing_ids.add(s.get('suggestion_id'))
        
        added = 0
        for suggestion in suggestions:
            suggestion_id = generate_suggestion_id(suggestion)
            
            if suggestion_id in existing_ids:
                continue
            
            suggestion['suggestion_id'] = suggestion_id
            suggestion['created_at'] = datetime.now().isoformat()
            suggestion['status'] = 'pending'
            
            # Add to pending
            state['pending'].append(suggestion)
            
            # Also store in database
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO coach_suggestions (
                        suggestion_id, type, category, title, explanation,
                        action, projected_impact, confidence, sample_size,
                        p_value, data, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    suggestion_id,
                    suggestion.get('type'),
                    suggestion.get('category'),
                    suggestion.get('title'),
                    suggestion.get('explanation'),
                    suggestion.get('action'),
                    suggestion.get('projected_impact'),
                    suggestion.get('confidence'),
                    suggestion.get('sample_size'),
                    suggestion.get('p_value'),
                    json.dumps(suggestion.get('data', {})),
                    'pending',
                    suggestion['created_at']
                ))
                added += 1
            except Exception as e:
                print(f"⚠️  Error storing suggestion: {e}")
        
        conn.commit()
        conn.close()
        
        state['last_analysis'] = datetime.now().isoformat()
        save_suggestions_state(state)
        
        return added


def get_pending_suggestions():
    """Get all pending suggestions"""
    with suggestion_lock:
        state = load_suggestions_state()
        # Sort by confidence descending
        pending = sorted(
            state.get('pending', []),
            key=lambda x: (-x.get('confidence', 0), x.get('p_value', 1))
        )
        return pending


def get_suggestion_by_id(suggestion_id):
    """Get a specific suggestion"""
    with suggestion_lock:
        state = load_suggestions_state()
        for s in state['pending']:
            if s.get('suggestion_id') == suggestion_id:
                return s
        return None


def approve_suggestion(suggestion_id, apply_change=True):
    """
    Approve a suggestion and optionally apply the change
    
    Returns dict with result and any applied changes
    """
    with suggestion_lock:
        state = load_suggestions_state()
        
        # Check weekly limit
        now = datetime.now()
        week_start = state.get('week_start')
        if week_start:
            week_start_dt = datetime.fromisoformat(week_start)
            if (now - week_start_dt).days >= 7:
                state['week_start'] = now.isoformat()
                state['changes_this_week'] = 0
        else:
            state['week_start'] = now.isoformat()
            state['changes_this_week'] = 0
        
        # Find and remove from pending
        suggestion = None
        for i, s in enumerate(state['pending']):
            if s.get('suggestion_id') == suggestion_id:
                suggestion = state['pending'].pop(i)
                break
        
        if not suggestion:
            return {'status': 'error', 'message': 'Suggestion not found'}
        
        # Record baseline metrics before change
        baseline = get_current_metrics()
        suggestion['baseline_win_rate'] = baseline['win_rate']
        suggestion['baseline_trades'] = baseline['total_trades']
        
        # Apply change if requested
        applied_settings = None
        if apply_change:
            applied_settings = apply_suggestion_change(suggestion)
            suggestion['applied_settings'] = applied_settings
            state['changes_this_week'] += 1
        
        # Move to approved
        suggestion['status'] = 'approved'
        suggestion['reviewed_at'] = now.isoformat()
        state['approved'].append(suggestion)
        
        # Update database
        update_suggestion_status(suggestion_id, 'approved', suggestion)
        
        save_suggestions_state(state)
        
        return {
            'status': 'success',
            'suggestion': suggestion,
            'applied_settings': applied_settings,
            'changes_this_week': state['changes_this_week']
        }


def reject_suggestion(suggestion_id, reason=None):
    """
    Reject a suggestion with optional reason
    """
    with suggestion_lock:
        state = load_suggestions_state()
        
        # Find and remove from pending
        suggestion = None
        for i, s in enumerate(state['pending']):
            if s.get('suggestion_id') == suggestion_id:
                suggestion = state['pending'].pop(i)
                break
        
        if not suggestion:
            return {'status': 'error', 'message': 'Suggestion not found'}
        
        # Move to rejected
        suggestion['status'] = 'rejected'
        suggestion['reviewed_at'] = datetime.now().isoformat()
        suggestion['rejection_reason'] = reason
        state['rejected'].append(suggestion)
        
        # Update database
        update_suggestion_status(suggestion_id, 'rejected', suggestion)
        
        save_suggestions_state(state)
        
        return {'status': 'success', 'suggestion': suggestion}


def apply_suggestion_change(suggestion):
    """
    Apply a suggestion's recommended change to settings
    
    Returns dict of changes made
    """
    try:
        # Load current settings
        settings = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
        
        changes = {}
        category = suggestion.get('category', '')
        data = suggestion.get('data', {})
        
        # Apply based on category
        if category == 'confidence_threshold':
            old_value = settings.get('min_confidence', 70)
            new_value = data.get('threshold', old_value)
            settings['min_confidence'] = new_value
            changes['min_confidence'] = {'old': old_value, 'new': new_value}
        
        elif category == 'rr_threshold':
            old_value = settings.get('min_risk_reward', 2.0)
            new_value = data.get('threshold', old_value)
            settings['min_risk_reward'] = new_value
            changes['min_risk_reward'] = {'old': old_value, 'new': new_value}
        
        elif category in ['avoid_hour', 'best_hour']:
            # Store time filters
            if 'time_filters' not in settings:
                settings['time_filters'] = {'avoid_hours': [], 'prefer_hours': []}
            
            hour = data.get('hour')
            if category == 'avoid_hour' and hour is not None:
                if hour not in settings['time_filters']['avoid_hours']:
                    settings['time_filters']['avoid_hours'].append(hour)
                    changes['avoid_hours'] = settings['time_filters']['avoid_hours']
            elif category == 'best_hour' and hour is not None:
                if hour not in settings['time_filters']['prefer_hours']:
                    settings['time_filters']['prefer_hours'].append(hour)
                    changes['prefer_hours'] = settings['time_filters']['prefer_hours']
        
        elif category == 'direction_filter':
            weak_direction = data.get('weak_direction')
            if weak_direction:
                settings['direction_preference'] = 'short' if weak_direction == 'long' else 'long'
                changes['direction_preference'] = settings['direction_preference']
        
        elif category in ['phrase_emphasis', 'phrase_caution']:
            # Store prompt modifications
            if 'prompt_modifications' not in settings:
                settings['prompt_modifications'] = {'emphasize': [], 'caution': []}
            
            phrase = data.get('phrase', '')
            if category == 'phrase_emphasis':
                if phrase not in settings['prompt_modifications']['emphasize']:
                    settings['prompt_modifications']['emphasize'].append(phrase)
                    changes['emphasize_phrases'] = settings['prompt_modifications']['emphasize']
            else:
                if phrase not in settings['prompt_modifications']['caution']:
                    settings['prompt_modifications']['caution'].append(phrase)
                    changes['caution_phrases'] = settings['prompt_modifications']['caution']
        
        # Save updated settings
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        
        return changes
        
    except Exception as e:
        print(f"⚠️  Error applying suggestion: {e}")
        return {'error': str(e)}


def undo_suggestion(suggestion_id):
    """
    Undo an approved suggestion's changes
    """
    with suggestion_lock:
        state = load_suggestions_state()
        
        # Find in approved
        suggestion = None
        for i, s in enumerate(state['approved']):
            if s.get('suggestion_id') == suggestion_id:
                suggestion = state['approved'].pop(i)
                break
        
        if not suggestion:
            return {'status': 'error', 'message': 'Approved suggestion not found'}
        
        # Revert changes
        applied = suggestion.get('applied_settings', {})
        reverted = revert_settings(applied)
        
        # Move back to rejected with note
        suggestion['status'] = 'undone'
        suggestion['rejection_reason'] = 'Manually undone by user'
        state['rejected'].append(suggestion)
        
        save_suggestions_state(state)
        
        return {'status': 'success', 'reverted': reverted}


def revert_settings(applied_changes):
    """Revert applied settings changes"""
    try:
        settings = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
        
        reverted = {}
        
        for key, change in applied_changes.items():
            if isinstance(change, dict) and 'old' in change:
                settings[key] = change['old']
                reverted[key] = change['old']
        
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        
        return reverted
    except Exception as e:
        return {'error': str(e)}


def get_current_metrics():
    """Get current performance metrics for baseline comparison"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins
            FROM signals
            WHERE outcome IN ('win', 'loss') AND is_valid = 1
        ''')
        
        row = cursor.fetchone()
        conn.close()
        
        total = row['total'] or 0
        wins = row['wins'] or 0
        
        return {
            'total_trades': total,
            'win_rate': round(wins / total * 100, 1) if total > 0 else 0
        }
    except:
        return {'total_trades': 0, 'win_rate': 0}


def update_suggestion_status(suggestion_id, status, suggestion_data):
    """Update suggestion in database"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE coach_suggestions
            SET status = ?,
                reviewed_at = ?,
                rejection_reason = ?,
                applied_settings = ?,
                baseline_win_rate = ?,
                baseline_trades = ?
            WHERE suggestion_id = ?
        ''', (
            status,
            suggestion_data.get('reviewed_at'),
            suggestion_data.get('rejection_reason'),
            json.dumps(suggestion_data.get('applied_settings', {})),
            suggestion_data.get('baseline_win_rate'),
            suggestion_data.get('baseline_trades'),
            suggestion_id
        ))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️  Error updating suggestion status: {e}")


def measure_suggestion_impact(suggestion_id):
    """
    Measure actual impact of an approved suggestion
    Called after enough new trades to compare
    """
    with suggestion_lock:
        state = load_suggestions_state()
        
        # Find in approved
        suggestion = None
        for s in state['approved']:
            if s.get('suggestion_id') == suggestion_id:
                suggestion = s
                break
        
        if not suggestion:
            return None
        
        # Get current metrics
        current = get_current_metrics()
        baseline_rate = suggestion.get('baseline_win_rate', 0)
        baseline_trades = suggestion.get('baseline_trades', 0)
        
        # Calculate new trades since approval
        new_trades = current['total_trades'] - baseline_trades
        
        if new_trades < 10:
            return {
                'status': 'insufficient_data',
                'new_trades': new_trades,
                'needed': 10
            }
        
        # Calculate impact
        actual_change = current['win_rate'] - baseline_rate
        projected = suggestion.get('projected_impact', '')
        
        # Extract projected number if possible
        import re
        projected_num = None
        match = re.search(r'([+-]?\d+)', projected)
        if match:
            projected_num = int(match.group(1))
        
        result = {
            'status': 'measured',
            'baseline_win_rate': baseline_rate,
            'current_win_rate': current['win_rate'],
            'actual_change': actual_change,
            'projected_change': projected_num,
            'new_trades': new_trades,
            'verdict': 'positive' if actual_change > 0 else 'negative' if actual_change < -2 else 'neutral'
        }
        
        # Update suggestion with results
        suggestion['post_win_rate'] = current['win_rate']
        suggestion['post_trades'] = current['total_trades']
        suggestion['actual_impact'] = json.dumps(result)
        
        save_suggestions_state(state)
        
        return result


def get_history(limit=50):
    """Get suggestion history (approved and rejected)"""
    with suggestion_lock:
        state = load_suggestions_state()
        
        history = []
        
        for s in state.get('approved', []):
            s['list_type'] = 'approved'
            history.append(s)
        
        for s in state.get('rejected', []):
            s['list_type'] = 'rejected'
            history.append(s)
        
        # Sort by reviewed_at descending
        history.sort(key=lambda x: x.get('reviewed_at', ''), reverse=True)
        
        return history[:limit]


def get_stats():
    """Get suggestion statistics"""
    with suggestion_lock:
        state = load_suggestions_state()
        
        return {
            'pending_count': len(state.get('pending', [])),
            'approved_count': len(state.get('approved', [])),
            'rejected_count': len(state.get('rejected', [])),
            'changes_this_week': state.get('changes_this_week', 0),
            'last_analysis': state.get('last_analysis')
        }


def clear_old_suggestions(days=30):
    """Clear suggestions older than N days"""
    with suggestion_lock:
        state = load_suggestions_state()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        # Clear old rejected
        state['rejected'] = [
            s for s in state.get('rejected', [])
            if s.get('reviewed_at', '') > cutoff
        ]
        
        save_suggestions_state(state)


# Initialize on import
init_suggestions_table()
print("✅ Suggestion Manager loaded")

