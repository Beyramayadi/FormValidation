"""
Form Rules Validator - Validates extracted form data against business rules.

Implements Part 2 of the project: Rules validation with flagging system.
Generates flags for:
1. Field-level validation errors (format, type, ranges)
2. Cross-field inconsistencies (date ordering, cost relationships)
3. Suspicious values (unusually high costs, outliers)
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import re
from collections import defaultdict


class FlagSeverity(Enum):
    """Severity levels for validation flags."""
    ERROR = "ERROR"        # Critical - blocks processing
    WARNING = "WARNING"    # Should review - inconsistency/suspicious
    INFO = "INFO"          # Informational - FYI


class FlagType(Enum):
    """Types of validation issues."""
    VALIDATION_ERROR = "VALIDATION_ERROR"      # Format/type error
    MISSING_FIELD = "MISSING_FIELD"            # Required field empty
    INCONSISTENCY = "INCONSISTENCY"            # Cross-field rule violation
    SUSPICIOUS = "SUSPICIOUS"                  # Value seems unreasonable
    OUT_OF_RANGE = "OUT_OF_RANGE"             # Value outside expected range


@dataclass
class Flag:
    """Represents a single validation flag."""
    flag_id: str
    severity: FlagSeverity
    flag_type: FlagType
    origin: str = "rules"                           # Source: rules/web
    field_name: Optional[str] = None                    # Single field affected
    related_fields: List[str] = field(default_factory=list)  # Multiple fields
    rule: str = ""                                 # Rule name
    current_value: Any = None                      # Actual value
    current_values: Dict[str, Any] = field(default_factory=dict)  # For cross-field
    issue: str = ""                                # Human-readable issue
    expected: str = ""                             # What was expected
    suggested_fix: Optional[str] = None            # Auto-fix suggestion
    confidence: float = 1.0                        # 0.0-1.0, for suspicious flags
    user_action: Optional[str] = None              # accept/dismiss/auto_fix/manual_correct
    user_value: Optional[Any] = None               # User-corrected value
    timestamp: Optional[str] = None                # When user acted


@dataclass
class ValidationResult:
    """Result of form validation."""
    flags: List[Flag] = field(default_factory=list)
    can_proceed: bool = True
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    summary: str = ""


class FormRulesValidator:
    """Validates form data against business rules."""
    
    def __init__(self):
        """Initialize validator with German travel expense form rules."""
        self.form_type = "german_travel_expense"
        self.flag_counter = 0
    
    def validate(self, fields: Dict[str, Any]) -> ValidationResult:
        """
        Validate extracted form fields against all rules.
        
        Args:
            fields: Dictionary of field_name -> field_info (value, type, confidence, etc.)
        
        Returns:
            ValidationResult with list of flags and summary
        """
        result = ValidationResult()
        
        # Extract actual values from field_info
        field_values = self._extract_field_values(fields)
        
        # Run field-level validation
        self._validate_field_level(field_values, result)
        
        # Run cross-field validation
        self._validate_cross_field(field_values, result)
        
        # Run suspicious value checks
        self._check_suspicious_values(field_values, result)
        
        # Update summary
        result.error_count = sum(1 for f in result.flags if f.severity == FlagSeverity.ERROR)
        result.warning_count = sum(1 for f in result.flags if f.severity == FlagSeverity.WARNING)
        result.info_count = sum(1 for f in result.flags if f.severity == FlagSeverity.INFO)
        result.can_proceed = result.error_count == 0
        
        result.summary = self._generate_summary(result)
        
        return result
    
    def _extract_field_values(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Extract actual values from field_info structure."""
        values = {}
        for field_name, field_info in fields.items():
            if isinstance(field_info, dict):
                values[field_name] = field_info.get('value')
            else:
                values[field_name] = field_info
        return values
    
    def _validate_field_level(self, field_values: Dict[str, Any], result: ValidationResult):
        """Validate individual field constraints."""
        # Alias map helps match fields even if the PDF uses a slightly different label
        alias_map = {
            'antragsteller': ['antragsteller', 'nachname', 'name'],
            'vorname': ['vorname', 'first_name'],
            'anreise_am': ['anreise_am', 'anreise'],
            'rückreise_am': ['rückreise_am', 'rueckreise_am', 'rückreise', 'rueckreise'],
            'verkehrsmittel': ['verkehrsmittel'],
            'von_der': ['von_der', 'von'],
            'postal_code': ['postal_code', 'plz', 'postleitzahl', 'postleitzahl ort', 'postleitzahl, ort', 'plz ort'],
            'iban': ['iban', 'bankverbindung iban', 'iban nummer', 'iban_nr', 'iban konto'],
            'bic': ['bic', 'swift', 'swift code', 'bankverbindung bic']
        }
        normalized_map = self._build_normalized_map(field_values)

        # Required fields (now includes IBAN, BIC, and PLZ/Postleitzahl)
        required_fields = [
            'antragsteller', 'vorname', 'anreise_am', 'rückreise_am',
            'verkehrsmittel', 'von_der', 'iban', 'bic', 'postal_code'
        ]

        for field_name in required_fields:
            aliases = alias_map.get(field_name, [field_name])
            found_key, value = self._get_value_with_aliases(aliases, normalized_map)
            if self._is_empty_value(value):
                issue = f"'{field_name}' is a required field"
                expected = "Non-empty value"
                if field_name == 'iban':
                    issue = "IBAN is required for reimbursements"
                    expected = "Valid IBAN (e.g., DEkk...)"
                elif field_name == 'bic':
                    issue = "BIC/Swift code is required for reimbursements"
                    expected = "Valid BIC/Swift code"
                elif field_name == 'postal_code':
                    issue = "Postal code (PLZ) is required"
                    expected = "5-digit PLZ"

                self._add_flag(
                    result,
                    severity=FlagSeverity.ERROR,
                    flag_type=FlagType.MISSING_FIELD,
                    field_name=field_name,
                    rule="required_field",
                    current_value=value,
                    issue=issue,
                    expected=expected
                )
            else:
                # Make canonical keys available for later checks
                field_values.setdefault(field_name, value)
        
        # Name fields - alphabetic only
        for field_name in ['antragsteller', 'vorname']:
            value = field_values.get(field_name)
            if value and not self._is_valid_name(str(value)):
                self._add_flag(
                    result,
                    severity=FlagSeverity.ERROR,
                    flag_type=FlagType.VALIDATION_ERROR,
                    field_name=field_name,
                    rule="name_format",
                    current_value=value,
                    issue=f"'{field_name}' contains invalid characters",
                    expected="Only letters, spaces, and hyphens allowed"
                )
        
        # Date fields
        date_fields = ['anreise_am', 'rückreise_am', 'täglich_für_von', 'täglich_für_bis']
        for field_name in date_fields:
            value = field_values.get(field_name)
            if value and not self._is_valid_date(str(value)):
                self._add_flag(
                    result,
                    severity=FlagSeverity.ERROR,
                    flag_type=FlagType.VALIDATION_ERROR,
                    field_name=field_name,
                    rule="date_format",
                    current_value=value,
                    issue=f"'{field_name}' has invalid date format",
                    expected="Date format: DD.MM.YYYY"
                )
        
        # Cost fields - positive numbers, max 2 decimals
        cost_fields = ['fahrtkosten', 'übernachtungskosten', 'spesenkosten']
        for field_name in cost_fields:
            value = field_values.get(field_name)
            if value:
                if not self._is_valid_cost(str(value)):
                    self._add_flag(
                        result,
                        severity=FlagSeverity.ERROR,
                        flag_type=FlagType.VALIDATION_ERROR,
                        field_name=field_name,
                        rule="cost_format",
                        current_value=value,
                        issue=f"'{field_name}' is not a valid cost amount",
                        expected="Positive number with max 2 decimals (e.g., 123.45)"
                    )
                elif float(value) < 0:
                    self._add_flag(
                        result,
                        severity=FlagSeverity.ERROR,
                        flag_type=FlagType.VALIDATION_ERROR,
                        field_name=field_name,
                        rule="cost_non_negative",
                        current_value=value,
                        issue=f"'{field_name}' cannot be negative",
                        expected="Positive number (≥ 0)"
                    )
        
        # Duration field
        duration = field_values.get('dauer_um')
        if duration:
            try:
                dur_int = int(duration)
                if dur_int < 1 or dur_int > 365:
                    self._add_flag(
                        result,
                        severity=FlagSeverity.ERROR,
                        flag_type=FlagType.OUT_OF_RANGE,
                        field_name='dauer_um',
                        rule="duration_range",
                        current_value=duration,
                        issue=f"Duration '{duration}' is outside reasonable range",
                        expected="Duration between 1 and 365 days"
                    )
            except ValueError:
                self._add_flag(
                    result,
                    severity=FlagSeverity.ERROR,
                    flag_type=FlagType.VALIDATION_ERROR,
                    field_name='dauer_um',
                    rule="duration_format",
                    current_value=duration,
                    issue="Duration must be a whole number",
                    expected="Positive integer (e.g., 5)"
                )
        
        # Transport method
        valid_transports = ['Zug', 'Auto', 'Flugzeug', 'Bus', 'Bahn', 'Fahrrad', 'Taxi']
        for field_name in ['verkehrsmittel', 'verkehrsmittel_rückreise']:
            value = field_values.get(field_name)
            if value and str(value) not in valid_transports:
                self._add_flag(
                    result,
                    severity=FlagSeverity.WARNING,
                    flag_type=FlagType.VALIDATION_ERROR,
                    field_name=field_name,
                    rule="transport_type",
                    current_value=value,
                    issue=f"Unknown transport type: '{value}'",
                    expected=f"One of: {', '.join(valid_transports)}"
                )
        
        # Von/An field
        valid_origins = ['Wohnung', 'Dienststelle']
        for field_name in ['von_der', 'ankunft_an']:
            value = field_values.get(field_name)
            if value and str(value) not in valid_origins:
                self._add_flag(
                    result,
                    severity=FlagSeverity.WARNING,
                    flag_type=FlagType.VALIDATION_ERROR,
                    field_name=field_name,
                    rule="origin_type",
                    current_value=value,
                    issue=f"Unknown origin/destination: '{value}'",
                    expected=f"One of: {', '.join(valid_origins)}"
                )
        
        # Foreign travel consistency
        auslandsreise = field_values.get('auslandsreise')
        country = field_values.get('hereiats')
        
        if auslandsreise and str(auslandsreise).lower() in ['ja', 'yes', 'true']:
            if not country or str(country).strip() == "":
                self._add_flag(
                    result,
                    severity=FlagSeverity.ERROR,
                    flag_type=FlagType.MISSING_FIELD,
                    field_name='hereiats',
                    rule="country_required_for_foreign",
                    current_value=country,
                    issue="Foreign travel flagged but country/destination not specified",
                    expected="Country or destination name"
                )
    
    def _validate_cross_field(self, field_values: Dict[str, Any], result: ValidationResult):
        """Validate relationships between fields."""
        
        # Date ordering: arrival < return
        anreise = field_values.get('anreise_am')
        rückreise = field_values.get('rückreise_am')
        
        if anreise and rückreise:
            anreise_date = self._parse_date(str(anreise))
            rückreise_date = self._parse_date(str(rückreise))
            
            if anreise_date and rückreise_date:
                if anreise_date > rückreise_date:
                    self._add_flag(
                        result,
                        severity=FlagSeverity.ERROR,
                        flag_type=FlagType.INCONSISTENCY,
                        related_fields=['anreise_am', 'rückreise_am'],
                        rule="date_order_check",
                        current_values={'anreise_am': str(anreise), 'rückreise_am': str(rückreise)},
                        issue="Arrival date is after return date (impossible)",
                        expected="arrival_date < return_date",
                        suggested_fix="Swap the two dates"
                    )
                
                # Duration consistency
                actual_duration = (rückreise_date - anreise_date).days + 1
                stated_duration = field_values.get('dauer_um')
                
                if stated_duration:
                    try:
                        stated_dur = int(stated_duration)
                        if actual_duration != stated_dur:
                            self._add_flag(
                                result,
                                severity=FlagSeverity.WARNING,
                                flag_type=FlagType.INCONSISTENCY,
                                related_fields=['anreise_am', 'rückreise_am', 'dauer_um'],
                                rule="duration_consistency",
                                current_values={
                                    'anreise_am': str(anreise),
                                    'rückreise_am': str(rückreise),
                                    'dauer_um': str(stated_duration)
                                },
                                issue=f"Stated duration ({stated_dur} days) doesn't match date range ({actual_duration} days)",
                                expected=f"Duration should be {actual_duration} days",
                                suggested_fix=f"Update duration to {actual_duration}",
                                confidence=0.8
                            )
                    except ValueError:
                        pass
        
        # Daily range consistency
        täglich_von = field_values.get('täglich_für_von')
        täglich_bis = field_values.get('täglich_für_bis')
        
        if täglich_von and täglich_bis:
            von_date = self._parse_date(str(täglich_von))
            bis_date = self._parse_date(str(täglich_bis))
            
            if von_date and bis_date and von_date > bis_date:
                self._add_flag(
                    result,
                    severity=FlagSeverity.ERROR,
                    flag_type=FlagType.INCONSISTENCY,
                    related_fields=['täglich_für_von', 'täglich_für_bis'],
                    rule="daily_range_order",
                    current_values={'von': str(täglich_von), 'bis': str(täglich_bis)},
                    issue="Daily 'from' date is after 'to' date",
                    expected="täglich_für_von < täglich_für_bis",
                    suggested_fix="Swap the two dates"
                )
        
        # Cost logic: if mietfahrzeug=ja, fahrtkosten should be significant
        mietfahrzeug = field_values.get('mietfahrzeug')
        fahrtkosten = field_values.get('fahrtkosten')
        
        if mietfahrzeug and str(mietfahrzeug).lower() in ['ja', 'yes', 'true']:
            if not fahrtkosten or float(fahrtkosten) == 0:
                self._add_flag(
                    result,
                    severity=FlagSeverity.WARNING,
                    flag_type=FlagType.INCONSISTENCY,
                    related_fields=['mietfahrzeug', 'fahrtkosten'],
                    rule="rental_cost_required",
                    current_values={'mietfahrzeug': str(mietfahrzeug), 'fahrtkosten': str(fahrtkosten)},
                    issue="Rental car flagged but no travel costs recorded",
                    expected="fahrtkosten > 0 when mietfahrzeug=ja",
                    confidence=0.7
                )
    
    def _check_suspicious_values(self, field_values: Dict[str, Any], result: ValidationResult):
        """Check for suspicious/unreasonable values."""
        
        # Very high travel costs
        fahrtkosten = field_values.get('fahrtkosten')
        if fahrtkosten:
            try:
                cost = float(fahrtkosten)
                if cost > 5000:
                    self._add_flag(
                        result,
                        severity=FlagSeverity.INFO,
                        flag_type=FlagType.SUSPICIOUS,
                        field_name='fahrtkosten',
                        rule="cost_unusually_high",
                        current_value=fahrtkosten,
                        issue=f"Travel costs (€{cost}) are unusually high",
                        expected="Typically < €5,000 for business travel",
                        confidence=0.6
                    )
            except ValueError:
                pass
        
        # Very high accommodation costs
        übernachtung = field_values.get('übernachtungskosten')
        if übernachtung:
            try:
                cost = float(übernachtung)
                if cost > 10000:
                    self._add_flag(
                        result,
                        severity=FlagSeverity.INFO,
                        flag_type=FlagType.SUSPICIOUS,
                        field_name='übernachtungskosten',
                        rule="accommodation_unusually_high",
                        current_value=übernachtung,
                        issue=f"Accommodation costs (€{cost}) are unusually high",
                        expected="Typically < €10,000 for business travel",
                        confidence=0.6
                    )
            except ValueError:
                pass
        
        # Very long trip
        dauer = field_values.get('dauer_um')
        if dauer:
            try:
                days = int(dauer)
                if days > 180:
                    self._add_flag(
                        result,
                        severity=FlagSeverity.INFO,
                        flag_type=FlagType.SUSPICIOUS,
                        field_name='dauer_um',
                        rule="trip_very_long",
                        current_value=dauer,
                        issue=f"Trip duration ({days} days) is very long",
                        expected="Typical business trips: 1-90 days",
                        confidence=0.5
                    )
            except ValueError:
                pass
    
    def _build_normalized_map(self, field_values: Dict[str, Any]) -> Dict[str, Tuple[str, Any]]:
        """Return a map of normalized field names to (original_key, value)."""
        normalized = {}
        for key, value in field_values.items():
            normalized_key = self._normalize_key(key)
            if normalized_key:
                normalized[normalized_key] = (key, value)
        return normalized

    def _get_value_with_aliases(self, aliases: List[str], normalized_map: Dict[str, Tuple[str, Any]]) -> Tuple[Optional[str], Any]:
        """Find the first non-empty value matching any alias (case/spacing-insensitive)."""
        for alias in aliases:
            normalized_alias = self._normalize_key(alias)
            if normalized_alias in normalized_map:
                original_key, value = normalized_map[normalized_alias]
                if not self._is_empty_value(value):
                    return original_key, value
        return None, None

    def _normalize_key(self, key: str) -> str:
        """Normalize keys by stripping non-alphanumerics and lowering case."""
        return re.sub(r'[^a-z0-9]', '', str(key).lower())

    def _is_empty_value(self, value: Any) -> bool:
        """Determine if a value should be considered empty for required checks."""
        if value is None:
            return True
        return str(value).strip() == ""

    def _is_valid_name(self, name: str) -> bool:
        """Check if name contains only valid characters."""
        pattern = r"^[A-Za-zÄÖÜäöüß\s\-']+$"
        return bool(re.match(pattern, name))
    
    def _is_valid_date(self, date_str: str) -> bool:
        """Check if date is in valid format DD.MM.YYYY."""
        pattern = r"^\d{2}\.\d{2}\.\d{4}$"
        if not re.match(pattern, date_str):
            return False
        
        try:
            parts = date_str.split('.')
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            # Basic validation
            if month < 1 or month > 12:
                return False
            if day < 1 or day > 31:
                return False
            return True
        except:
            return False
    
    def _is_valid_cost(self, cost_str: str) -> bool:
        """Check if cost is valid number with max 2 decimals."""
        try:
            cost_str = str(cost_str).replace(',', '.')
            cost = float(cost_str)
            # Check decimals
            if '.' in cost_str:
                decimals = len(cost_str.split('.')[1])
                if decimals > 2:
                    return False
            return True
        except:
            return False
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string DD.MM.YYYY to datetime."""
        try:
            parts = date_str.split('.')
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            return datetime(year, month, day)
        except:
            return None
    
    def _add_flag(self, result: ValidationResult, **kwargs) -> None:
        """Add a flag to the validation result."""
        self.flag_counter += 1
        flag_id = f"flag_{self.flag_counter:04d}"
        
        flag = Flag(
            flag_id=flag_id,
            severity=kwargs.get('severity', FlagSeverity.INFO),
            flag_type=kwargs.get('flag_type', FlagType.VALIDATION_ERROR),
            origin=kwargs.get('origin', 'rules'),
            field_name=kwargs.get('field_name') or kwargs.get('field'),
            related_fields=kwargs.get('related_fields', []),
            rule=kwargs.get('rule', ''),
            current_value=kwargs.get('current_value'),
            current_values=kwargs.get('current_values', {}),
            issue=kwargs.get('issue', ''),
            expected=kwargs.get('expected', ''),
            suggested_fix=kwargs.get('suggested_fix'),
            confidence=kwargs.get('confidence', 1.0)
        )
        
        result.flags.append(flag)
    
    def _generate_summary(self, result: ValidationResult) -> str:
        """Generate a human-readable summary of validation results."""
        if result.error_count == 0 and result.warning_count == 0:
            return "✅ All validations passed!"
        
        parts = []
        if result.error_count > 0:
            parts.append(f"🔴 {result.error_count} error(s) - must be fixed")
        if result.warning_count > 0:
            parts.append(f"🟡 {result.warning_count} warning(s) - should review")
        if result.info_count > 0:
            parts.append(f"🔵 {result.info_count} info - FYI")
        
        return " | ".join(parts)
