"""
Web Verifier - lightweight web/data plausibility checks.

This module adds a "web search" style validation layer without requiring
external API keys. It performs:
- Email domain MX existence (best-effort via dns, fallback heuristic)
- Phone country code plausibility
- Postal code format per country (basic)
- Hotel/venue name plausibility (length/keywords)

Flags produced are tagged with origin="web" so the UI can separate them
from business-rule flags.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import re

from form_rules_validator import (
    Flag,
    FlagSeverity,
    FlagType,
    ValidationResult,
)

try:
    import dns.resolver  # type: ignore
    _DNS_AVAILABLE = True
except Exception:
    _DNS_AVAILABLE = False


@dataclass
class WebCheckConfig:
    enable_email_mx: bool = True
    enable_phone_country: bool = True
    enable_postal_format: bool = True
    enable_hotel_plausibility: bool = True


class WebVerifier:
    def __init__(self, config: Optional[WebCheckConfig] = None):
        self.config = config or WebCheckConfig()
        self.flag_counter = 0

    def validate(self, fields: Dict[str, Any]) -> ValidationResult:
        """Run web-style plausibility checks and return ValidationResult."""
        result = ValidationResult()
        values = self._extract_values(fields)

        if self.config.enable_email_mx:
            self._check_email_domain(values, result)
        if self.config.enable_phone_country:
            self._check_phone_country(values, result)
        if self.config.enable_postal_format:
            self._check_postal(values, result)
        if self.config.enable_hotel_plausibility:
            self._check_hotel(values, result)

        result.error_count = sum(1 for f in result.flags if f.severity == FlagSeverity.ERROR)
        result.warning_count = sum(1 for f in result.flags if f.severity == FlagSeverity.WARNING)
        result.info_count = sum(1 for f in result.flags if f.severity == FlagSeverity.INFO)
        result.can_proceed = result.error_count == 0
        result.summary = self._summary(result)
        return result

    # ---------- checks ----------
    def _check_email_domain(self, values: Dict[str, Any], result: ValidationResult):
        email = values.get('email') or values.get('E-Mail') or values.get('e_mail')
        if not email:
            return
        if '@' not in str(email):
            return
        domain = str(email).split('@')[-1].strip().lower()
        if not domain:
            return

        mx_exists = None
        if _DNS_AVAILABLE:
            try:
                answers = dns.resolver.resolve(domain, 'MX')  # type: ignore
                mx_exists = len(answers) > 0
            except Exception:
                mx_exists = False
        else:
            # Heuristic fallback: has a dot and reasonable TLD length
            mx_exists = ('.' in domain and 2 <= len(domain.split('.')[-1]) <= 6)

        if not mx_exists:
            self._add_flag(
                result,
                severity=FlagSeverity.WARNING,
                flag_type=FlagType.SUSPICIOUS,
                field_name='email',
                rule='email_domain_mx',
                current_value=email,
                issue=f"Email domain '{domain}' has no MX records (or check failed)",
                expected='Domain with valid mail exchanger records',
                confidence=0.6,
            )

    def _check_phone_country(self, values: Dict[str, Any], result: ValidationResult):
        phone = values.get('phone') or values.get('Telefon') or values.get('telefon')
        country = (values.get('country') or values.get('Land') or values.get('land') or '').strip()
        if not phone:
            return
        digits = re.sub(r'\D', '', str(phone))
        if not digits:
            return

        prefix_map = {
            '49': 'DE',
            '1': 'US/CA',
            '44': 'UK',
            '33': 'FR',
            '34': 'ES',
            '39': 'IT',
        }
        detected = None
        for pref in sorted(prefix_map.keys(), key=lambda x: -len(x)):
            if digits.startswith(pref):
                detected = prefix_map[pref]
                break

        if detected and country:
            if detected != country.upper() and not (detected == 'US/CA' and country.upper() in ['US', 'CA']):
                self._add_flag(
                    result,
                    severity=FlagSeverity.WARNING,
                    flag_type=FlagType.INCONSISTENCY,
                    field_name='phone',
                    rule='phone_country_mismatch',
                    current_value=phone,
                    issue=f"Phone country ({detected}) differs from address country ({country})",
                    expected='Phone country code matches address country',
                    confidence=0.6,
                )

    def _check_postal(self, values: Dict[str, Any], result: ValidationResult):
        postal = values.get('postal_code') or values.get('PLZ') or values.get('plz')
        country = (values.get('country') or values.get('Land') or values.get('land') or '').strip()
        if not postal:
            return
        if country.upper() == 'DE' or country.lower() in ['deutschland', 'germany']:
            if not re.match(r'^\d{5}$', str(postal)):
                self._add_flag(
                    result,
                    severity=FlagSeverity.WARNING,
                    flag_type=FlagType.VALIDATION_ERROR,
                    field_name='postal_code',
                    rule='postal_format_de',
                    current_value=postal,
                    issue='German postal code should be 5 digits',
                    expected='5-digit German postal code',
                )
        else:
            # generic sanity: 3-10 alnum
            if not re.match(r'^[A-Za-z0-9\s-]{3,10}$', str(postal)):
                self._add_flag(
                    result,
                    severity=FlagSeverity.INFO,
                    flag_type=FlagType.SUSPICIOUS,
                    field_name='postal_code',
                    rule='postal_generic',
                    current_value=postal,
                    issue='Postal code format looks unusual',
                    expected='3-10 alphanumeric characters',
                    confidence=0.5,
                )

    def _check_hotel(self, values: Dict[str, Any], result: ValidationResult):
        hotel = values.get('hotel_name') or values.get('Unterkunft') or values.get('unterkunft')
        city = values.get('city') or values.get('Ort') or values.get('ort')
        if not hotel:
            return
        name = str(hotel).strip()
        if len(name) < 3:
            self._add_flag(
                result,
                severity=FlagSeverity.WARNING,
                flag_type=FlagType.SUSPICIOUS,
                field_name='hotel_name',
                rule='hotel_name_short',
                current_value=hotel,
                issue='Hotel/venue name is very short',
                expected='Longer venue/hotel name',
                confidence=0.5,
            )
        banned = ['test', 'sample', 'n/a']
        if name.lower() in banned:
            self._add_flag(
                result,
                severity=FlagSeverity.WARNING,
                flag_type=FlagType.SUSPICIOUS,
                field_name='hotel_name',
                rule='hotel_name_placeholder',
                current_value=hotel,
                issue='Hotel name looks like placeholder',
                expected='Real hotel/venue name',
                confidence=0.6,
            )
        # Light plausibility with city
        if city and len(name) >= 3:
            if city.lower() not in name.lower():
                # Not fatal; just info
                self._add_flag(
                    result,
                    severity=FlagSeverity.INFO,
                    flag_type=FlagType.SUSPICIOUS,
                    field_name='hotel_name',
                    rule='hotel_city_mismatch',
                    current_value=hotel,
                    issue=f"Hotel name does not mention city '{city}'",
                    expected='Hotel/venue name aligned with city (optional)',
                    confidence=0.4,
                )

    # ---------- helpers ----------
    def _extract_values(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        vals: Dict[str, Any] = {}
        for k, v in fields.items():
            if isinstance(v, dict):
                vals[k] = v.get('value')
            else:
                vals[k] = v
        return vals

    def _add_flag(self, result: ValidationResult, **kwargs) -> None:
        self.flag_counter += 1
        flag_id = f"web_{self.flag_counter:04d}"
        flag = Flag(
            flag_id=flag_id,
            severity=kwargs.get('severity', FlagSeverity.INFO),
            flag_type=kwargs.get('flag_type', FlagType.SUSPICIOUS),
            origin='web',
            field_name=kwargs.get('field_name'),
            related_fields=kwargs.get('related_fields', []),
            rule=kwargs.get('rule', ''),
            current_value=kwargs.get('current_value'),
            current_values=kwargs.get('current_values', {}),
            issue=kwargs.get('issue', ''),
            expected=kwargs.get('expected', ''),
            suggested_fix=kwargs.get('suggested_fix'),
            confidence=kwargs.get('confidence', 1.0),
        )
        result.flags.append(flag)

    def _summary(self, result: ValidationResult) -> str:
        if result.error_count == 0 and result.warning_count == 0:
            return "✅ Web checks passed"
        parts = []
        if result.error_count:
            parts.append(f"🔴 {result.error_count} error(s)")
        if result.warning_count:
            parts.append(f"🟡 {result.warning_count} warning(s)")
        if result.info_count:
            parts.append(f"🔵 {result.info_count} info")
        return " | ".join(parts)
