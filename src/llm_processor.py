from typing import Dict, List, Any, Optional, Tuple
import json
import os
import openai
from pathlib import Path
from dotenv import load_dotenv

# Explicitly load .env from the project root
project_root = Path(__file__).resolve().parent.parent
dotenv_path = project_root / '.env'
load_dotenv(dotenv_path=dotenv_path)

class LLMFieldExtractor:
    """Class to handle LLM-based field extraction from PDF forms."""
    
    def __init__(self):
        """Initialize the LLM field extractor."""
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY not found in environment variables. "
                f"Please create a .env file at {dotenv_path} with your API key."
            )
            
        self.system_prompt = '''You are a world-class expert document analysis AI. Your task is to meticulously analyze PDF form content and extracting structured field information with high accuracy.

**Your process must be:**
1.  **Analyze Holistically:** Review the entire provided text, form fields, and button data to understand the document's structure and context.
2.  **Identify & Extract:** Identify all potential form fields and their corresponding values. Be decisive. If you see a clear label and a value next to it, extract it.
3.  **Structure the Output:** Return a clean, structured JSON object. Do not include any extra commentary or text outside of the JSON.
4.  **Assign Confidence:** For each field, you MUST assign a confidence score based on the provided rubric. Trust your analysis. If a field is clear, assign a high score. Do not be overly cautious.

**Confidence Score Rubric:**
- 1.0: Absolutely certain. The value is clearly present, the label is unambiguous and adjacent.
- 0.9-0.99: Very high confidence. The value is clearly extracted but might have minor formatting ambiguity (e.g., a date format).
- 0.7-0.89: Medium confidence. The value is inferred from context, or the label is not directly adjacent but the relationship is logical.
- 0.5-0.69: Low confidence. The value is a plausible guess based on loose context or a poorly legible source.
- < 0.5: Very low confidence. A speculative extraction. Do not include fields with confidence below 0.5.

**Crucial Final Instruction:** Your primary goal is to find the best possible value for each field. If the initial data seems plausible, re-evaluate it. If you are more confident in a different value, or even the same value, you must report it with your own calculated confidence score. Do not simply ignore fields.
'''

    def safe_confidence(self, value: float) -> float:
        """Ensure confidence value is valid finite float between 0 and 1"""
        try:
            conf = float(value)
            if not (isinstance(conf, float) and conf >= 0 and conf <= 1):
                return 0.8  # default fallback
            return round(conf, 3)  # round to 3 decimal places
        except (TypeError, ValueError):
            return 0.8  # default fallback

    def extract_text_from_image(self, image_data: str) -> str:
        """
        Extracts text from a single page image using a multimodal LLM.

        Args:
            image_data: Base64 encoded string of the page image.

        Returns:
            The extracted text.
        """
        try:
            client = openai.OpenAI(api_key=self.api_key)
            
            response = client.chat.completions.create(
                model="gpt-4o",
                max_tokens=4000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_data}"
                                }
                            },
                            {
                                "type": "text",
                                "text": "Perform OCR on this image. Extract all text content, including form fields, labels, and values. Preserve the spatial layout and structure of the text as accurately as possible."
                            }
                        ]
                    }
                ]
            )
            
            return response.choices[0].message.content

        except Exception as e:
            print(f"Error in multimodal text extraction: {str(e)}")
            return ""

    def format_field_data(self, pdf_text: str, form_fields: Dict[str, Any], 
                         buttons: List[Dict[str, Any]]) -> str:
        """Format the PDF data for LLM processing."""
        context = {
            "extracted_text": pdf_text,
            "form_fields": form_fields,
            "button_fields": [
                {
                    "name": btn["name"],
                    "title": btn["title"],
                    "value": btn["value"],
                    "is_checked": btn["is_checked"],
                    "parent": btn["parent"]
                }
                for btn in buttons
            ]
        }
        
        prompt = '''Please analyze this form data and verify/improve the extraction of checked buttons and form fields.

Analyze the provided form data and:
1. Verify which buttons/checkboxes are actually checked
2. Extract their values accurately
3. Clean up field names to be consistent
4. Ensure proper value formatting
5. Focus on checkbox and radio button states

For each checked button or field:
- Confirm if it's really checked/selected
- Extract the correct field name and value
- Validate any text field values
- Set appropriate confidence scores

Return a JSON object with this exact structure:
{
    "fields": [
        {"name": "field1", "value": "yes", "type": "checkbox", "confidence": 0.95},
        {"name": "field2", "value": "some text", "type": "text", "confidence": 0.90}
    ],
    "metadata": {"total_fields": 1, "extracted_from": "form", "confidence_score": 0.95}
}

Context:
{}'''.format(json.dumps(context, indent=2))
        return prompt

    def extract_fields(self, pdf_text: str, form_fields: Dict[str, Any], 
                      buttons: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Extract and structure form fields using an LLM, returning a dictionary
        formatted for the Streamlit app and an optional error message.
        """
        verified_fields = []
        error_message = None

        # Add existing form fields with a lower base confidence
        for field_name, value in form_fields.items():
            clean_name = field_name.split('_')[0].split('.')[0]
            if value and str(value).strip('/').lower() not in ['off', 'null', '']:
                verified_fields.append({
                    "name": clean_name,
                    "value": str(value).strip('/'),
                    "type": "text",
                    "confidence": self.safe_confidence(0.6)  # Lower base confidence
                })

        # Add button fields with a lower base confidence
        for btn in buttons:
            if btn["is_checked"]:
                name = (btn["title"] or btn["name"]).split('_')[0]
                verified_fields.append({
                    "name": name,
                    "value": "checked",
                    "type": "checkbox",
                    "confidence": self.safe_confidence(0.7)  # Lower base confidence
                })

        # Process with LLM
        llm_result = None
        try:
            prompt = self.format_field_data(pdf_text, form_fields, buttons)
            client = openai.OpenAI(api_key=self.api_key)

            response = client.chat.completions.create(
                model="gpt-4o",
                max_tokens=4000,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ]
            )

            llm_text = response.choices[0].message.content

            # Parse LLM response
            if '```json' in llm_text:
                json_start = llm_text.find('```json') + len('```json')
                json_end = llm_text.rfind('```')
            else:
                json_start = llm_text.find('{')
                json_end = llm_text.rfind('}') + 1

            if json_start != -1 and json_end != -1 and json_end > json_start:
                json_str = llm_text[json_start:json_end].strip()
                try:
                    llm_result = json.loads(json_str)
                except json.JSONDecodeError as json_e:
                    error_message = f"Failed to parse JSON from LLM: {json_e}. Response: '{json_str}'"
                    llm_result = None
            else:
                error_message = f"Could not find JSON in the LLM response. Full response: '{llm_text}'"
                llm_result = None
        except Exception as e:
            error_message = f"Error during LLM API call: {str(e)}"
            llm_result = None

        # Process LLM results if available
        if llm_result and "fields" in llm_result and isinstance(llm_result["fields"], list):
            for field in llm_result["fields"]:
                if isinstance(field, dict) and "name" in field and "value" in field:
                    existing = next(
                        (f for f in verified_fields if f["name"] == field["name"]),
                        None
                    )

                    confidence = self.safe_confidence(field.get("confidence", 0.85))

                    if existing:
                        if confidence > self.safe_confidence(existing["confidence"]):
                            existing.update({
                                "value": field["value"],
                                "type": field.get("type", "text"),
                                "confidence": confidence
                            })
                    else:
                        verified_fields.append({
                            "name": field["name"],
                            "value": field["value"],
                            "type": field.get("type", "text"),
                            "confidence": confidence
                        })
        elif llm_result:
            error_message = f"LLM output was missing the 'fields' list. Got: {json.dumps(llm_result)}"

        # Convert the list of fields into the dictionary format required by the app
        final_fields = {}
        for field in verified_fields:
            final_fields[field["name"]] = {
                "value": field["value"],
                "type": field["type"],
                "confidence": int(self.safe_confidence(field.get("confidence", 0.5)) * 100)
            }

        return final_fields, error_message
