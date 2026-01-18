"""
Test script for enhanced field validators.
Tests the new label normalization and enhanced type validators.
"""

from src.field_validator import FieldValidator, FieldValue, FieldType

def test_label_normalization():
    """Test label normalization with field synonyms."""
    print("=" * 60)
    print("Testing Label Normalization")
    print("=" * 60)
    
    validator = FieldValidator()
    
    test_cases = [
        # First name variations
        ("First Name", "first_name"),
        ("Vorname", "first_name"),
        ("given name", "first_name"),
        ("Prénom", "first_name"),
        
        # Date variations
        ("Date of Birth", "date_of_birth"),
        ("Geburtsdatum", "date_of_birth"),
        ("Birth Date", "date_of_birth"),
        ("DoB", "date_of_birth"),
        
        # Arrival date variations
        ("Arrival Date", "arrival_date"),
        ("Check-in", "arrival_date"),
        ("Anreise", "arrival_date"),
        ("Date d'arrivée", "arrival_date"),
        
        # Email variations
        ("E-Mail", "email"),
        ("Email Address", "email"),
        ("Courrier électronique", "email"),
        
        # Price variations
        ("Price per Night", "price_per_night"),
        ("Preis pro Nacht", "price_per_night"),
        ("Night Rate", "price_per_night"),
        
        # Unknown field (should clean but not map)
        ("Custom Field 123", "custom field 123"),
    ]
    
    for original, expected in test_cases:
        normalized = validator.normalize_field_name(original)
        status = "✓" if normalized == expected else "✗"
        print(f"{status} '{original}' → '{normalized}' (expected: '{expected}')")
    
    print()

def test_enhanced_email_validator():
    """Test enhanced email validation."""
    print("=" * 60)
    print("Testing Enhanced Email Validator")
    print("=" * 60)
    
    validator = FieldValidator()
    
    test_cases = [
        ("user@example.com", True),
        ("john.doe@company.co.uk", True),
        ("test+filter@domain.org", True),
        ("invalid@", False),
        ("@invalid.com", False),
        ("user..name@domain.com", False),  # Consecutive dots
        ("user@domain", False),  # No TLD
        ("user@@domain.com", False),  # Multiple @
    ]
    
    for email, expected in test_cases:
        result = validator._validate_email(email)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{email}' → {result} (expected: {expected})")
    
    print()

def test_enhanced_date_validator():
    """Test enhanced date validation and standardization."""
    print("=" * 60)
    print("Testing Enhanced Date Validator")
    print("=" * 60)
    
    validator = FieldValidator()
    
    test_cases = [
        ("31.12.2023", "2023-12-31"),
        ("2023-12-31", "2023-12-31"),
        ("31/12/23", "2023-12-31"),
        ("01.05.2024", "2024-05-01"),
        ("invalid-date", None),
        ("32.13.2023", None),  # Invalid day/month
    ]
    
    for date_str, expected in test_cases:
        result = validator._validate_and_standardize_date(date_str)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{date_str}' → '{result}' (expected: '{expected}')")
    
    print()

def test_enhanced_phone_validator():
    """Test enhanced phone number validation and formatting."""
    print("=" * 60)
    print("Testing Enhanced Phone Validator")
    print("=" * 60)
    
    validator = FieldValidator()
    
    test_cases = [
        ("491234567890", "+49 123 456 7890"),  # Germany
        ("+49 123 456 7890", "+49 123 456 7890"),  # Already formatted
        ("11234567890", "+1 123 456 7890"),  # US
        ("441234567890", "+44 1234 567890"),  # UK
        ("123", "123"),  # Too short, return original
    ]
    
    for phone, expected in test_cases:
        result = validator._validate_and_standardize_phone(phone)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{phone}' → '{result}' (expected: '{expected}')")
    
    print()

def test_currency_validator():
    """Test currency parsing and validation."""
    print("=" * 60)
    print("Testing Currency Validator")
    print("=" * 60)
    
    validator = FieldValidator()
    
    test_cases = [
        ("€1.234,56", 1234.56),  # European format
        ("$1,234.56", 1234.56),  # US format
        ("£2.500,00", 2500.0),   # European with pounds
        ("1234.56", 1234.56),    # Plain number
        ("€100", 100.0),
        ("invalid", None),
        ("-100", None),  # Negative
    ]
    
    for value_str, expected in test_cases:
        result = validator._validate_and_standardize_currency(value_str)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{value_str}' → {result} (expected: {expected})")
    
    print()

def test_iban_validator():
    """Test IBAN validation with checksum."""
    print("=" * 60)
    print("Testing IBAN Validator")
    print("=" * 60)
    
    validator = FieldValidator()
    
    test_cases = [
        ("DE89370400440532013000", True),   # Valid German IBAN
        ("GB82WEST12345698765432", True),   # Valid UK IBAN
        ("FR1420041010050500013M02606", True),  # Valid French IBAN
        ("DE89370400440532013001", False),  # Invalid checksum
        ("INVALID", False),
        ("DE8937", False),  # Too short
    ]
    
    for iban, expected in test_cases:
        result = validator._validate_iban(iban)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{iban}' → {result} (expected: {expected})")
    
    print()

def test_field_type_detection():
    """Test enhanced field type detection."""
    print("=" * 60)
    print("Testing Field Type Detection")
    print("=" * 60)
    
    validator = FieldValidator()
    
    test_cases = [
        ("email", [FieldValue("test", "user@example.com", 0.9)], FieldType.EMAIL),
        ("arrival_date", [FieldValue("test", "31.12.2023", 0.9)], FieldType.DATE),
        ("phone", [FieldValue("test", "123456789", 0.9)], FieldType.PHONE),
        ("iban", [FieldValue("test", "DE89370400440532013000", 0.9)], FieldType.IBAN),
        ("price", [FieldValue("test", "€123,45", 0.9)], FieldType.CURRENCY),
        ("total_cost", [FieldValue("test", "$1,234.56", 0.9)], FieldType.CURRENCY),
        ("nights", [FieldValue("test", "3", 0.9)], FieldType.NUMBER),
        ("unknown", [FieldValue("test", "some text", 0.9)], FieldType.TEXT),
    ]
    
    for field_name, sources, expected in test_cases:
        result = validator._detect_field_type(field_name, sources)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{field_name}' with value '{sources[0].value}' → {result.value} (expected: {expected.value})")
    
    print()

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("ENHANCED VALIDATORS TEST SUITE")
    print("=" * 60 + "\n")
    
    test_label_normalization()
    test_enhanced_email_validator()
    test_enhanced_date_validator()
    test_enhanced_phone_validator()
    test_currency_validator()
    test_iban_validator()
    test_field_type_detection()
    
    print("=" * 60)
    print("TEST SUITE COMPLETE")
    print("=" * 60)
