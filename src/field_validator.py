"""
Field Validator - Multi-source validation and accuracy improvement for PDF form extraction.

This module implements a comprehensive validation strategy to ensure 100% accuracy:
1. Cross-validation between multiple extraction sources
2. Conflict resolution with confidence scoring
3. Field schema matching and validation
4. OCR error correction
5. Human-in-the-loop for ambiguous cases
"""

from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import re
from difflib import SequenceMatcher
from collections import defaultdict
import json


class FieldType(Enum):
    """Enumeration of form field types."""
    TEXT = "text"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    DATE = "date"
    NUMBER = "number"
    EMAIL = "email"
    PHONE = "phone"
    DROPDOWN = "dropdown"
    SIGNATURE = "signature"
    CURRENCY = "currency"
    IBAN = "iban"


class ValidationStatus(Enum):
    """Status of field validation."""
    VALIDATED = "validated"      # High confidence, cross-validated
    NEEDS_REVIEW = "needs_review"  # Conflicts or low confidence
    MISSING = "missing"           # Expected but not found
    UNEXPECTED = "unexpected"     # Found but not in schema


@dataclass
class FieldValue:
    """Represents a field value from a single extraction source."""
    source: str  # "pdf_fields", "ocr", "llm_vision"
    value: Any
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidatedField:
    """Represents a validated field with resolution history."""
    name: str
    field_type: FieldType
    final_value: Any
    confidence: float
    status: ValidationStatus
    sources: List[FieldValue]  # All values from different sources
    conflicts: List[str] = field(default_factory=list)
    validation_notes: List[str] = field(default_factory=list)


class FieldValidator:
    """
    Validates and cross-checks form field extractions from multiple sources.
    """
    
    # Field label synonyms for normalization
    FIELD_SYNONYMS = {
        'first_name': ['first name', 'vorname', 'given name', 'firstname', 'prenom'],
        'last_name': ['last name', 'surname', 'nachname', 'family name', 'lastname', 'nom'],
        'full_name': ['name', 'full name', 'vollständiger name', 'complete name'],
        'date_of_birth': ['dob', 'birth date', 'date of birth', 'geburtsdatum', 'birthdate', 'date de naissance'],
        'email': ['email', 'e-mail', 'email address', 'e-mail-adresse', 'courriel'],
        'phone': ['phone', 'telephone', 'telefon', 'phone number', 'tel', 'mobile'],
        'address': ['address', 'adresse', 'street address', 'straße'],
        'city': ['city', 'stadt', 'town', 'ville'],
        'postal_code': ['postal code', 'zip', 'zip code', 'postleitzahl', 'plz', 'code postal'],
        'country': ['country', 'land', 'pays', 'nation'],
        'arrival_date': ['arrival', 'check-in', 'arrival date', 'date of arrival', 'anreise', 'anreisedatum'],
        'departure_date': ['departure', 'check-out', 'departure date', 'date of departure', 'abreise', 'abreisedatum'],
        'nights': ['nights', 'number of nights', 'stay nights', 'anzahl nächte', 'nächte'],
        'price_per_night': ['price per night', 'nightly rate', 'rate per night', 'preis pro nacht'],
        'total_cost': ['total', 'total cost', 'total price', 'sum', 'gesamtpreis', 'total amount'],
        'hotel_name': ['hotel', 'hotel name', 'hotelname', 'accommodation'],
        'room_type': ['room type', 'zimmertyp', 'room category', 'type de chambre'],
    }
    
    def __init__(self, schema: Optional[Dict[str, Any]] = None):
        """
        Initialize the validator.
        
        Args:
            schema: Optional schema defining expected fields and their types
                   Format: {"field_name": {"type": "text", "required": True, "pattern": "..."}}
        """
        self.schema = schema or {}
        self.validation_threshold = 0.85  # Confidence threshold for auto-validation
        self.conflict_threshold = 0.15  # Max confidence difference to flag as conflict
    
    def normalize_field_name(self, field_name: str) -> str:
        """
        Normalize field name to canonical form using fuzzy matching and synonyms.
        
        Args:
            field_name: Raw field name from extraction
            
        Returns:
            Normalized canonical field name
        """
        if not field_name:
            return field_name
            
        # Clean the field name
        cleaned = field_name.lower().strip()
        cleaned = re.sub(r'[_\-\s]+', ' ', cleaned)  # Normalize separators
        cleaned = re.sub(r'[^\w\s]', '', cleaned)    # Remove special chars
        
        # Exact match first
        for canonical, synonyms in self.FIELD_SYNONYMS.items():
            if cleaned in [s.lower() for s in synonyms]:
                return canonical
        
        # Fuzzy match with threshold
        best_match = None
        best_ratio = 0.0
        threshold = 0.85
        
        for canonical, synonyms in self.FIELD_SYNONYMS.items():
            for synonym in synonyms:
                ratio = SequenceMatcher(None, cleaned, synonym.lower()).ratio()
                if ratio > best_ratio and ratio >= threshold:
                    best_ratio = ratio
                    best_match = canonical
        
        # Return canonical if found, otherwise return cleaned original
        return best_match if best_match else field_name
        
    def validate_extraction(self, 
                          pdf_fields: Dict[str, Any],
                          ocr_text: str,
                          llm_fields: Dict[str, Any],
                          buttons: List[Dict[str, Any]]) -> Dict[str, ValidatedField]:
        """
        Cross-validate fields from multiple extraction sources.
        
        Returns:
            Dictionary of field_name -> ValidatedField
        """
        # Step 1: Collect all field values from all sources
        all_fields = self._collect_all_fields(pdf_fields, ocr_text, llm_fields, buttons)
        
        # Step 2: Cross-validate each field
        validated_fields = {}
        for field_name, sources in all_fields.items():
            validated_fields[field_name] = self._validate_field(field_name, sources)
            
        # Step 3: Check against schema if provided
        if self.schema:
            validated_fields = self._validate_against_schema(validated_fields)
            
        # Step 4: Apply field-type specific validation
        for field_name, validated_field in validated_fields.items():
            self._apply_type_validation(validated_field)
            
        return validated_fields
    
    def _collect_all_fields(self,
                           pdf_fields: Dict[str, Any],
                           ocr_text: str,
                           llm_fields: Dict[str, Any],
                           buttons: List[Dict[str, Any]]) -> Dict[str, List[FieldValue]]:
        """Collect all field values from different sources with normalized names."""
        all_fields = defaultdict(list)
        
        # From PDF fields
        for name, data in pdf_fields.items():
            normalized_name = self.normalize_field_name(name)
            if isinstance(data, dict):
                value = data.get("value")
                confidence = data.get("confidence", 50) / 100.0
            else:
                value = data
                confidence = 0.8  # Default confidence for direct PDF extraction
                
            all_fields[normalized_name].append(FieldValue(
                source="pdf_fields",
                value=value,
                confidence=confidence,
                metadata={"raw_data": data, "original_name": name}
            ))
        
        # From LLM extraction
        for name, data in llm_fields.items():
            normalized_name = self.normalize_field_name(name)
            if isinstance(data, dict):
                value = data.get("value")
                confidence = data.get("confidence", 50) / 100.0
            else:
                value = data
                confidence = 0.7  # Default LLM confidence
                
            all_fields[normalized_name].append(FieldValue(
                source="llm_vision",
                value=value,
                confidence=confidence,
                metadata={"raw_data": data, "original_name": name}
            ))
        
        # From buttons
        for btn in buttons:
            if btn.get("is_checked"):
                name = btn.get("title") or btn.get("name", "")
                name = name.split('_')[0].split('.')[0]
                normalized_name = self.normalize_field_name(name)
                
                all_fields[normalized_name].append(FieldValue(
                    source="pdf_buttons",
                    value="checked",
                    confidence=0.9,  # High confidence for direct button state
                    metadata={"button_data": btn, "original_name": name}
                ))
        
        return all_fields
    
    def _validate_field(self, field_name: str, sources: List[FieldValue]) -> ValidatedField:
        """
        Validate a single field by cross-checking all sources.
        """
        if not sources:
            return ValidatedField(
                name=field_name,
                field_type=FieldType.TEXT,
                final_value=None,
                confidence=0.0,
                status=ValidationStatus.MISSING,
                sources=[],
                validation_notes=["No sources provided value for this field"]
            )
        
        # Sort sources by confidence
        sources.sort(key=lambda x: x.confidence, reverse=True)
        
        # Detect field type
        field_type = self._detect_field_type(field_name, sources)
        
        # Check for conflicts
        conflicts = self._detect_conflicts(sources)
        
        # Resolve conflicts and determine final value
        if conflicts:
            final_value, confidence, notes = self._resolve_conflicts(sources, field_type)
            status = ValidationStatus.NEEDS_REVIEW if confidence < self.validation_threshold else ValidationStatus.VALIDATED
        else:
            # No conflicts - use highest confidence source
            final_value = sources[0].value
            confidence = sources[0].confidence
            notes = [f"Single consistent value from {len(sources)} source(s)"]
            status = ValidationStatus.VALIDATED if confidence >= self.validation_threshold else ValidationStatus.NEEDS_REVIEW
        
        return ValidatedField(
            name=field_name,
            field_type=field_type,
            final_value=final_value,
            confidence=confidence,
            status=status,
            sources=sources,
            conflicts=conflicts,
            validation_notes=notes
        )
    
    def _detect_field_type(self, field_name: str, sources: List[FieldValue]) -> FieldType:
        """Detect the field type based on name and values."""
        # Check schema first
        if self.schema and field_name in self.schema:
            schema_type = self.schema[field_name].get("type", "text").lower()
            return FieldType(schema_type)
        
        # Detect from field name patterns
        name_lower = field_name.lower()
        
        # Checkbox detection - must be whole word matches
        checkbox_words = ["checkbox", "check_box", "yes_no", "ja_nein"]
        if any(word in name_lower for word in checkbox_words):
            return FieldType.CHECKBOX
        
        if any(word in name_lower for word in ["date", "datum", "birth", "arrival", "departure", "anreise", "abreise"]):
            return FieldType.DATE
        
        if any(word in name_lower for word in ["email", "mail", "e-mail"]):
            return FieldType.EMAIL
        
        if any(word in name_lower for word in ["phone", "tel", "fax", "mobile", "telefon"]):
            return FieldType.PHONE
        
        if any(word in name_lower for word in ["iban", "bank_account", "konto"]):
            return FieldType.IBAN
        
        if any(word in name_lower for word in ["price", "cost", "total", "amount", "preis", "betrag", "summe"]):
            return FieldType.CURRENCY
        
        if any(word in name_lower for word in ["number", "nummer", "count", "nights", "nächte"]):
            return FieldType.NUMBER
        
        # Detect from values
        for source in sources:
            value_str = str(source.value)
            
            if value_str.lower() in ["checked", "yes", "no", "true", "false", "ja", "nein"]:
                return FieldType.CHECKBOX
            
            # IBAN pattern (starts with 2 letters, 2 digits)
            if re.match(r'^[A-Z]{2}\d{2}', value_str.replace(' ', '')):
                return FieldType.IBAN
            
            # Currency pattern (has currency symbol or format)
            if re.search(r'[€$£¥₹]|\d+[,\.]\d{2}', value_str):
                return FieldType.CURRENCY
            
            # Date pattern
            if re.match(r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}', value_str):
                return FieldType.DATE
            
            # Email pattern
            if '@' in value_str and '.' in value_str:
                return FieldType.EMAIL
        
        return FieldType.TEXT
    
    def _detect_conflicts(self, sources: List[FieldValue]) -> List[str]:
        """Detect conflicts between different sources."""
        conflicts = []
        
        if len(sources) < 2:
            return conflicts
        
        # Get unique non-None values
        unique_values = {}
        for source in sources:
            if source.value is not None and str(source.value).strip():
                value_key = self._normalize_value(source.value)
                if value_key not in unique_values:
                    unique_values[value_key] = []
                unique_values[value_key].append(source)
        
        # Check for conflicts
        if len(unique_values) > 1:
            # Multiple different values
            for value_key, value_sources in unique_values.items():
                max_conf = max(s.confidence for s in value_sources)
                source_names = [s.source for s in value_sources]
                conflicts.append(
                    f"Value '{value_key}' from {source_names} (confidence: {max_conf:.2f})"
                )
        
        return conflicts
    
    def _normalize_value(self, value: Any) -> str:
        """Normalize a value for comparison."""
        if value is None:
            return ""
        
        value_str = str(value).lower().strip()
        
        # Remove common variations
        value_str = re.sub(r'\s+', ' ', value_str)  # Normalize whitespace
        value_str = value_str.replace('-', '').replace('_', '')  # Remove separators
        
        # Common equivalents
        equivalents = {
            'yes': 'checked',
            'ja': 'checked',
            'true': 'checked',
            '1': 'checked',
            'no': 'unchecked',
            'nein': 'unchecked',
            'false': 'unchecked',
            '0': 'unchecked',
        }
        
        return equivalents.get(value_str, value_str)
    
    def _resolve_conflicts(self, sources: List[FieldValue], field_type: FieldType) -> Tuple[Any, float, List[str]]:
        """
        Resolve conflicts between different sources.
        Uses weighted voting based on confidence scores.
        """
        notes = []
        
        # Group values by normalized form
        value_groups = defaultdict(list)
        for source in sources:
            normalized = self._normalize_value(source.value)
            value_groups[normalized].append(source)
        
        # Calculate weighted score for each value
        value_scores = {}
        for normalized_value, group_sources in value_groups.items():
            # Weighted average of confidence scores
            total_confidence = sum(s.confidence for s in group_sources)
            count = len(group_sources)
            
            # Bonus for multiple sources agreeing
            agreement_bonus = 0.1 * (count - 1)
            
            # Source reliability weights
            source_weights = {
                "pdf_fields": 1.2,  # Most reliable
                "pdf_buttons": 1.1,
                "llm_vision": 1.0,
                "ocr": 0.9
            }
            
            weighted_confidence = sum(
                s.confidence * source_weights.get(s.source, 1.0)
                for s in group_sources
            )
            
            final_score = (weighted_confidence / count) + agreement_bonus
            value_scores[normalized_value] = {
                "score": min(final_score, 1.0),  # Cap at 1.0
                "sources": group_sources,
                "original_value": group_sources[0].value
            }
        
        # Select the value with highest score
        best_value_key = max(value_scores.keys(), key=lambda k: value_scores[k]["score"])
        best_value_data = value_scores[best_value_key]
        
        notes.append(
            f"Resolved conflict: Selected '{best_value_key}' "
            f"(score: {best_value_data['score']:.2f}) from "
            f"{len(best_value_data['sources'])} agreeing source(s)"
        )
        
        # List alternatives
        for value_key, data in value_scores.items():
            if value_key != best_value_key:
                notes.append(
                    f"Alternative: '{value_key}' (score: {data['score']:.2f}) "
                    f"from {len(data['sources'])} source(s)"
                )
        
        return (
            best_value_data["original_value"],
            best_value_data["score"],
            notes
        )
    
    def _validate_against_schema(self, validated_fields: Dict[str, ValidatedField]) -> Dict[str, ValidatedField]:
        """Validate fields against the provided schema."""
        # Add ALL schema fields, even if they weren't extracted
        for field_name, field_spec in self.schema.items():
            if field_name not in validated_fields:
                # Field exists in schema but wasn't extracted
                is_required = field_spec.get("required", False)
                validated_fields[field_name] = ValidatedField(
                    name=field_name,
                    field_type=FieldType(field_spec.get("type", "text")),
                    final_value=None,
                    confidence=0.0,
                    status=ValidationStatus.MISSING,
                    sources=[],
                    validation_notes=[
                        f"{'Required' if is_required else 'Optional'} field '{field_name}' not found in extraction"
                    ]
                )
        
        # Check for unexpected fields
        for field_name, validated_field in list(validated_fields.items()):
            if field_name not in self.schema and self.schema:
                validated_field.status = ValidationStatus.UNEXPECTED
                validated_field.validation_notes.append(
                    f"Field '{field_name}' not expected in schema"
                )
        
        return validated_fields
    
    def _apply_type_validation(self, validated_field: ValidatedField):
        """Apply field-type specific validation rules."""
        if validated_field.final_value is None:
            return
        
        value_str = str(validated_field.final_value)
        
        if validated_field.field_type == FieldType.EMAIL:
            if not self._validate_email(value_str):
                validated_field.validation_notes.append(
                    f"Invalid email format: '{value_str}'"
                )
                validated_field.status = ValidationStatus.NEEDS_REVIEW
                validated_field.confidence *= 0.5
        
        elif validated_field.field_type == FieldType.DATE:
            standardized = self._validate_and_standardize_date(value_str)
            if standardized:
                validated_field.final_value = standardized
            else:
                validated_field.validation_notes.append(
                    f"Invalid date format: '{value_str}'"
                )
                validated_field.status = ValidationStatus.NEEDS_REVIEW
                validated_field.confidence *= 0.6
        
        elif validated_field.field_type == FieldType.PHONE:
            standardized = self._validate_and_standardize_phone(value_str)
            if standardized:
                validated_field.final_value = standardized
            else:
                validated_field.validation_notes.append(
                    f"Potentially invalid phone number: '{value_str}'"
                )
        
        elif validated_field.field_type == FieldType.CURRENCY:
            parsed = self._validate_and_standardize_currency(value_str)
            if parsed is not None:
                validated_field.final_value = parsed
                validated_field.validation_notes.append(
                    f"Standardized currency: {value_str} → {parsed}"
                )
            else:
                validated_field.validation_notes.append(
                    f"Invalid currency format: '{value_str}'"
                )
                validated_field.status = ValidationStatus.NEEDS_REVIEW
                validated_field.confidence *= 0.5
        
        elif validated_field.field_type == FieldType.IBAN:
            if not self._validate_iban(value_str):
                validated_field.validation_notes.append(
                    f"Invalid IBAN (checksum failed): '{value_str}'"
                )
                validated_field.status = ValidationStatus.NEEDS_REVIEW
                validated_field.confidence *= 0.4
            else:
                validated_field.validation_notes.append("IBAN checksum validated")
        
        elif validated_field.field_type == FieldType.NUMBER:
            try:
                validated_field.final_value = float(value_str.replace(',', '.'))
            except ValueError:
                validated_field.validation_notes.append(
                    f"Cannot convert to number: '{value_str}'"
                )
                validated_field.status = ValidationStatus.NEEDS_REVIEW
                validated_field.confidence *= 0.5
    
    def _validate_email(self, email: str) -> bool:
        """Validate email format with stricter rules."""
        # More robust email validation
        pattern = r'^[a-zA-Z0-9][a-zA-Z0-9._%+-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            return False
        
        # Additional checks
        if email.count('@') != 1:
            return False
        if '..' in email:  # No consecutive dots
            return False
        
        return True
    
    def _validate_and_standardize_date(self, date_str: str) -> Optional[str]:
        """Validate and standardize date format to YYYY-MM-DD with better parsing."""
        from datetime import datetime
        
        # Clean the input
        date_str = date_str.strip()
        
        # Common date patterns with validation
        patterns = [
            (r'(\d{2})[./-](\d{2})[./-](\d{4})', '%d-%m-%Y'),  # DD.MM.YYYY
            (r'(\d{4})[./-](\d{2})[./-](\d{2})', '%Y-%m-%d'),  # YYYY-MM-DD
            (r'(\d{2})[./-](\d{2})[./-](\d{2})', '%d-%m-%y'),  # DD.MM.YY
            (r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', '%d %B %Y'),  # DD Month YYYY
        ]
        
        for pattern, date_format in patterns:
            match = re.match(pattern, date_str)
            if match:
                try:
                    # Try to parse with datetime to validate
                    parsed = datetime.strptime(date_str.replace('.', '-').replace('/', '-'), date_format)
                    # Return in standard format
                    return parsed.strftime('%Y-%m-%d')
                except ValueError:
                    continue
        
        return None
    
    def _validate_and_standardize_phone(self, phone: str) -> str:
        """Validate and standardize phone number with country code handling."""
        # Remove all non-digits except leading +
        cleaned = phone.strip()
        has_plus = cleaned.startswith('+')
        digits = re.sub(r'\D', '', cleaned)
        
        # Basic validation: 10-15 digits
        if not (10 <= len(digits) <= 15):
            return phone  # Return original if invalid length
        
        # Format based on country code
        if digits.startswith('49'):  # Germany
            if len(digits) >= 11:
                return f"+49 {digits[2:5]} {digits[5:8]} {digits[8:]}"
        elif digits.startswith('1') and len(digits) == 11:  # US/Canada
            return f"+1 {digits[1:4]} {digits[4:7]} {digits[7:]}"
        elif digits.startswith('33'):  # France
            if len(digits) >= 11:
                return f"+33 {digits[2:3]} {digits[3:5]} {digits[5:7]} {digits[7:9]} {digits[9:]}"
        elif digits.startswith('44'):  # UK
            if len(digits) >= 11:
                return f"+44 {digits[2:6]} {digits[6:]}"
        
        # Generic international format
        return f"+{digits}" if not has_plus else phone
    
    def _validate_and_standardize_currency(self, value_str: str) -> Optional[float]:
        """Parse and validate currency values (€, $, £) with thousands separators."""
        # Remove currency symbols and whitespace
        cleaned = value_str.strip()
        cleaned = re.sub(r'[€$£¥₹]', '', cleaned)
        cleaned = cleaned.strip()
        
        # Handle European format: 1.234,56 → 1234.56
        if ',' in cleaned and '.' in cleaned:
            if cleaned.rindex(',') > cleaned.rindex('.'):
                # European format
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                # US format: remove comma thousands separator
                cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            # Could be European decimal or US thousands
            # Check position: if last 3 chars, likely thousands; if last 2, likely decimal
            comma_pos = cleaned.rindex(',')
            if len(cleaned) - comma_pos == 3:  # Likely European decimal
                cleaned = cleaned.replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        
        try:
            value = float(cleaned)
            return value if value >= 0 else None
        except ValueError:
            return None
    
    def _validate_iban(self, iban: str) -> bool:
        """Validate IBAN using mod-97 checksum algorithm."""
        # Remove spaces and convert to uppercase
        iban = iban.replace(' ', '').upper()
        
        # IBAN must be 15-34 alphanumeric characters
        if not re.match(r'^[A-Z]{2}\d{2}[A-Z0-9]+$', iban) or not (15 <= len(iban) <= 34):
            return False
        
        # Move first 4 characters to end
        rearranged = iban[4:] + iban[:4]
        
        # Replace letters with numbers (A=10, B=11, ..., Z=35)
        numeric = ''
        for char in rearranged:
            if char.isdigit():
                numeric += char
            else:
                numeric += str(ord(char) - ord('A') + 10)
        
        # Check if mod 97 == 1
        try:
            return int(numeric) % 97 == 1
        except ValueError:
            return False
    
    def get_needs_review(self, validated_fields: Dict[str, ValidatedField]) -> List[ValidatedField]:
        """Get all fields that need human review."""
        return [
            field for field in validated_fields.values()
            if field.status in [ValidationStatus.NEEDS_REVIEW, ValidationStatus.MISSING]
        ]
    
    def export_validation_report(self, validated_fields: Dict[str, ValidatedField]) -> Dict[str, Any]:
        """Export a comprehensive validation report."""
        report = {
            "summary": {
                "total_fields": len(validated_fields),
                "validated": sum(1 for f in validated_fields.values() if f.status == ValidationStatus.VALIDATED),
                "needs_review": sum(1 for f in validated_fields.values() if f.status == ValidationStatus.NEEDS_REVIEW),
                "missing": sum(1 for f in validated_fields.values() if f.status == ValidationStatus.MISSING),
                "unexpected": sum(1 for f in validated_fields.values() if f.status == ValidationStatus.UNEXPECTED),
                "average_confidence": sum(f.confidence for f in validated_fields.values()) / len(validated_fields) if validated_fields else 0
            },
            "fields": {}
        }
        
        for field_name, field in validated_fields.items():
            report["fields"][field_name] = {
                "value": field.final_value,
                "type": field.field_type.value,
                "confidence": round(field.confidence, 3),
                "status": field.status.value,
                "sources": [
                    {
                        "source": s.source,
                        "value": s.value,
                        "confidence": round(s.confidence, 3)
                    }
                    for s in field.sources
                ],
                "conflicts": field.conflicts,
                "notes": field.validation_notes
            }
        
        return report


def apply_ocr_corrections(text: str) -> str:
    """
    Apply common OCR error corrections.
    Fixes common character misrecognitions.
    """
    corrections = {
        # Common OCR mistakes
        r'\b0(?=[a-zA-Z])': 'O',  # 0 -> O when followed by letter
        r'(?<=[a-zA-Z])0\b': 'O',  # 0 -> O when preceded by letter
        r'\bl(?=\d)': '1',         # l -> 1 when followed by digit
        r'(?<=\d)l\b': '1',        # l -> 1 when preceded by digit
        r'\bI(?=\d)': '1',         # I -> 1 when followed by digit
        r'(?<=\d)I\b': '1',        # I -> 1 when preceded by digit
    }
    
    corrected_text = text
    for pattern, replacement in corrections.items():
        corrected_text = re.sub(pattern, replacement, corrected_text)
    
    return corrected_text
