"""
Form Schemas - Define expected fields for different form types.

This module contains schema definitions for various form types to enable
validation and ensure completeness of extraction.
"""

from typing import Dict, Any, List


# Example schema for a German application form (Antrag)
GERMAN_APPLICATION_FORM_SCHEMA = {
    "Nachname": {
        "type": "text",
        "required": True,
        "description": "Last name / Surname",
        "validation_pattern": r"^[A-Za-zÄÖÜäöüß\s\-']+$"
    },
    "Vorname": {
        "type": "text",
        "required": True,
        "description": "First name",
        "validation_pattern": r"^[A-Za-zÄÖÜäöüß\s\-']+$"
    },
    "Geburtsdatum": {
        "type": "date",
        "required": True,
        "description": "Date of birth",
        "validation_pattern": r"\d{2}\.\d{2}\.\d{4}"
    },
    "Straße": {
        "type": "text",
        "required": True,
        "description": "Street address"
    },
    "Hausnummer": {
        "type": "text",
        "required": True,
        "description": "House number"
    },
    "PLZ": {
        "type": "text",
        "required": True,
        "description": "Postal code",
        "validation_pattern": r"^\d{5}$"
    },
    "Ort": {
        "type": "text",
        "required": True,
        "description": "City"
    },
    "Telefon": {
        "type": "phone",
        "required": False,
        "description": "Phone number"
    },
    "E-Mail": {
        "type": "email",
        "required": False,
        "description": "Email address"
    },
    "Staatsangehörigkeit": {
        "type": "text",
        "required": True,
        "description": "Nationality"
    }
}


# Example schema for a tax form
TAX_FORM_SCHEMA = {
    "Steuernummer": {
        "type": "text",
        "required": True,
        "description": "Tax identification number",
        "validation_pattern": r"^\d{11}$"
    },
    "Name": {
        "type": "text",
        "required": True,
        "description": "Full name"
    },
    "Adresse": {
        "type": "text",
        "required": True,
        "description": "Address"
    },
    "Einkommen": {
        "type": "number",
        "required": True,
        "description": "Income"
    },
    "Verheiratet": {
        "type": "checkbox",
        "required": False,
        "description": "Married status"
    }
}


# Generic form schema (when form type is unknown)
GENERIC_FORM_SCHEMA = {
    # This is intentionally minimal - will be populated dynamically
}


class SchemaManager:
    """Manages form schemas and provides schema matching capabilities."""
    
    def __init__(self):
        """Initialize the schema manager with predefined schemas."""
        self.schemas = {
            "german_application": GERMAN_APPLICATION_FORM_SCHEMA,
            "tax_form": TAX_FORM_SCHEMA,
            "generic": GENERIC_FORM_SCHEMA
        }
    
    def add_custom_schema(self, schema_name: str, schema: Dict[str, Any]):
        """Add a custom schema to the manager."""
        self.schemas[schema_name] = schema
    
    def get_schema(self, schema_name: str) -> Dict[str, Any]:
        """Get a schema by name."""
        return self.schemas.get(schema_name, GENERIC_FORM_SCHEMA)
    
    def detect_schema(self, extracted_fields: List[str]) -> str:
        """
        Attempt to detect which schema matches the extracted fields.
        
        Args:
            extracted_fields: List of field names extracted from the form
            
        Returns:
            The name of the best matching schema
        """
        extracted_set = set(f.lower() for f in extracted_fields)
        best_match = "generic"
        best_score = 0.0
        
        for schema_name, schema in self.schemas.items():
            if schema_name == "generic":
                continue
            
            schema_fields = set(f.lower() for f in schema.keys())
            
            # Calculate overlap score
            if not schema_fields:
                continue
            
            overlap = len(extracted_set & schema_fields)
            score = overlap / len(schema_fields)
            
            if score > best_score:
                best_score = score
                best_match = schema_name
        
        # Require at least 30% match to use a specific schema
        if best_score < 0.3:
            return "generic"
        
        return best_match
    
    def create_schema_from_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a dynamic schema from extracted fields.
        Useful when working with unknown form types.
        
        Args:
            fields: Dictionary of extracted fields with their values
            
        Returns:
            A schema dictionary
        """
        schema = {}
        
        for field_name, field_data in fields.items():
            # Extract field type if available
            if isinstance(field_data, dict):
                field_type = field_data.get("type", "text")
                field_value = field_data.get("value")
            else:
                field_type = "text"
                field_value = field_data
            
            # Infer additional properties from the value
            schema[field_name] = {
                "type": field_type,
                "required": False,  # Unknown forms default to optional
                "description": f"Auto-detected field: {field_name}"
            }
            
            # Add validation patterns based on detected type
            if field_type == "email":
                schema[field_name]["validation_pattern"] = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            elif field_type == "date":
                schema[field_name]["validation_pattern"] = r"\d{2}[./-]\d{2}[./-]\d{2,4}"
            elif field_type == "phone":
                schema[field_name]["validation_pattern"] = r"[\d\s\-\+\(\)]{10,}"
        
        return schema
    
    def validate_field_against_schema(self, field_name: str, value: Any, schema: Dict[str, Any]) -> tuple[bool, List[str]]:
        """
        Validate a single field against its schema definition.
        
        Args:
            field_name: Name of the field
            value: Value to validate
            schema: Schema dictionary
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        import re
        
        errors = []
        
        if field_name not in schema:
            errors.append(f"Field '{field_name}' not defined in schema")
            return False, errors
        
        field_spec = schema[field_name]
        
        # Check if required field is empty
        if field_spec.get("required", False) and (value is None or str(value).strip() == ""):
            errors.append(f"Required field '{field_name}' is empty")
            return False, errors
        
        # Skip further validation if value is empty and field is not required
        if value is None or str(value).strip() == "":
            return True, []
        
        # Validate against pattern if provided
        if "validation_pattern" in field_spec:
            pattern = field_spec["validation_pattern"]
            if not re.match(pattern, str(value)):
                errors.append(
                    f"Field '{field_name}' value '{value}' does not match "
                    f"expected pattern: {pattern}"
                )
                return False, errors
        
        return True, []
    
    def get_missing_required_fields(self, extracted_fields: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
        """
        Get list of required fields that are missing from extraction.
        
        Args:
            extracted_fields: Dictionary of extracted fields
            schema: Schema dictionary
            
        Returns:
            List of missing required field names
        """
        missing = []
        
        for field_name, field_spec in schema.items():
            if field_spec.get("required", False):
                # Check if field exists and has a value
                if field_name not in extracted_fields:
                    missing.append(field_name)
                else:
                    value = extracted_fields[field_name]
                    if isinstance(value, dict):
                        value = value.get("value")
                    
                    if value is None or str(value).strip() == "":
                        missing.append(field_name)
        
        return missing
