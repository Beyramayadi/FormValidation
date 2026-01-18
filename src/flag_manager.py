"""
Flag Manager - Manages flag lifecycle and user interactions.

Handles:
- Flag persistence (save/load from file)
- User actions (accept, dismiss, auto-fix, manual correct)
- Learning from user decisions
- Flag state tracking
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
import pandas as pd

from form_rules_validator import Flag, FlagSeverity, ValidationResult


class FlagManager:
    """Manages validation flags and user interactions."""
    
    def __init__(self, data_dir: str = "data"):
        """Initialize flag manager."""
        self.data_dir = data_dir
        self.flag_history_path = os.path.join(data_dir, "flag_history.csv")
        self.dismissed_flags_path = os.path.join(data_dir, "dismissed_flags.json")
        
        os.makedirs(data_dir, exist_ok=True)
    
    def process_user_action(self, 
                           flag: Flag, 
                           action: str, 
                           user_value: Optional[Any] = None,
                           doc_hash: str = "") -> Flag:
        """
        Process user action on a flag.
        
        Args:
            flag: The flag being acted upon
            action: 'accept', 'dismiss', 'auto_fix', 'manual_correct'
            user_value: New value if manual_correct
            doc_hash: Document hash for tracking
        
        Returns:
            Updated flag with user action recorded
        """
        flag.user_action = action
        flag.timestamp = datetime.utcnow().isoformat()
        
        if action == 'manual_correct':
            flag.user_value = user_value
        
        # Save to history
        self._save_flag_action(flag, doc_hash)
        
        return flag
    
    def get_user_corrections(self, flag: Flag) -> Dict[str, Any]:
        """
        Get user's correction for a flag (if manual_correct action taken).
        
        Returns dict with:
        - field: field name
        - new_value: corrected value
        - action: user action taken
        """
        if flag.user_action == 'manual_correct' and flag.user_value is not None:
            return {
                'field': flag.field_name,
                'new_value': flag.user_value,
                'action': 'manual_correct'
            }
        elif flag.user_action == 'auto_fix' and flag.suggested_fix:
            return {
                'field': flag.field_name,
                'new_value': flag.suggested_fix,
                'action': 'auto_fix'
            }
        return {}
    
    def is_dismissed(self, flag: Flag, doc_hash: str = "") -> bool:
        """
        Check if a similar flag was dismissed before by user.
        Used for learning - don't show same flag twice.
        
        Returns True if user dismissed similar flag before.
        """
        try:
            if not os.path.exists(self.dismissed_flags_path):
                return False
            
            with open(self.dismissed_flags_path, 'r') as f:
                dismissed = json.load(f)
            
            # Check if same rule was dismissed for this doc
            for d_flag in dismissed:
                if (d_flag.get('rule') == flag.rule and 
                    d_flag.get('field') == flag.field_name):
                    return True
            
            return False
        except:
            return False
    
    def mark_as_dismissed(self, flag: Flag, doc_hash: str = ""):
        """Mark a flag as dismissed by user (don't show again)."""
        try:
            dismissed = []
            if os.path.exists(self.dismissed_flags_path):
                with open(self.dismissed_flags_path, 'r') as f:
                    dismissed = json.load(f)
            
            dismissed.append({
                'flag_id': flag.flag_id,
                'rule': flag.rule,
                'field': flag.field_name,
                'timestamp': datetime.utcnow().isoformat(),
                'doc_hash': doc_hash
            })
            
            with open(self.dismissed_flags_path, 'w') as f:
                json.dump(dismissed, f, indent=2)
        except Exception as e:
            print(f"Error saving dismissed flag: {e}")
    
    def get_flag_stats(self) -> Dict[str, Any]:
        """Get statistics about flag handling."""
        try:
            if not os.path.exists(self.flag_history_path):
                return {
                    'total_flags_seen': 0,
                    'accepted': 0,
                    'dismissed': 0,
                    'auto_fixed': 0,
                    'manually_corrected': 0
                }
            
            df = pd.read_csv(self.flag_history_path)
            
            return {
                'total_flags_seen': len(df),
                'accepted': len(df[df['user_action'] == 'accept']),
                'dismissed': len(df[df['user_action'] == 'dismiss']),
                'auto_fixed': len(df[df['user_action'] == 'auto_fix']),
                'manually_corrected': len(df[df['user_action'] == 'manual_correct'])
            }
        except:
            return {
                'total_flags_seen': 0,
                'accepted': 0,
                'dismissed': 0,
                'auto_fixed': 0,
                'manually_corrected': 0
            }
    
    def _save_flag_action(self, flag: Flag, doc_hash: str = ""):
        """Save flag action to history file."""
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            
            row = pd.DataFrame([{
                'doc_hash': doc_hash,
                'flag_id': flag.flag_id,
                'rule': flag.rule,
                'field': flag.field_name,
                'severity': flag.severity.value,
                'type': flag.flag_type.value,
                'issue': flag.issue,
                'current_value': str(flag.current_value),
                'user_action': flag.user_action,
                'user_value': str(flag.user_value) if flag.user_value else "",
                'confidence': flag.confidence,
                'timestamp': flag.timestamp
            }])
            
            row.to_csv(self.flag_history_path, mode='a', 
                      header=not os.path.exists(self.flag_history_path), 
                      index=False)
        except Exception as e:
            print(f"Error saving flag action: {e}")
    
    def clear_history(self):
        """Clear all flag history."""
        try:
            if os.path.exists(self.flag_history_path):
                os.remove(self.flag_history_path)
            if os.path.exists(self.dismissed_flags_path):
                os.remove(self.dismissed_flags_path)
        except Exception as e:
            print(f"Error clearing history: {e}")


def apply_flag_corrections(fields: Dict[str, Any], 
                          flags: List[Flag],
                          corrections: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply corrections from flag handling to fields.
    
    Args:
        fields: Original extracted fields
        flags: List of validation flags
        corrections: Dict of field -> new_value from user actions
    
    Returns:
        Updated fields with corrections applied
    """
    updated_fields = {}
    
    for field_name, field_info in fields.items():
        if field_name in corrections:
            # Apply correction
            if isinstance(field_info, dict):
                updated_fields[field_name] = field_info.copy()
                updated_fields[field_name]['value'] = corrections[field_name]
                updated_fields[field_name]['corrected'] = True
                updated_fields[field_name]['correction_source'] = 'flag_handling'
            else:
                updated_fields[field_name] = corrections[field_name]
        else:
            # Keep original
            updated_fields[field_name] = field_info
    
    return updated_fields
