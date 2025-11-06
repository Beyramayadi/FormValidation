import ollama
import os
import json
import io
import base64
from pdf2image import convert_from_path

# --- CONFIGURATION ---
# For Windows: Set the path to the Poppler 'bin' folder
poppler_bin_path = r"C:\Program Files\poppler\poppler-25.07.0\Library\bin"

# The PDF you want to process
pdf_file_path = r"C:\Users\MSI\Desktop\MSc CS\3rd semester MSc CS\Applied Artificial Intelligence Lab\FormValidation\u_kn_travel_expense_report_1.pdf"
# ---------------------

def pdf_page_to_base64(pdf_path, page_num=0, poppler_path=None):
    """Converts a single PDF page to a base64-encoded image."""
    try:
        # On Windows, you MUST provide the poppler_path
        if os.name == 'nt':
            images = convert_from_path(pdf_path, first_page=page_num+1, last_page=page_num+1, poppler_path=poppler_path)
        else:
            images = convert_from_path(pdf_path, first_page=page_num+1, last_page=page_num+1)
        
        if not images:
            raise Exception("Could not convert PDF to image. Is Poppler installed?")
            
        # Convert the PIL image to bytes
        buffered = io.BytesIO()
        images[0].save(buffered, format="PNG")
        
        # Encode bytes to base64
        img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
        return img_str
        
    except Exception as e:
        print(f"Error converting PDF: {e}")
        if "Poppler" in str(e):
             print("\n*** POLLER ERROR ***\nMake sure 'poppler_bin_path' is set correctly.")
        return None

# --- Main Execution ---

if not os.path.exists(pdf_file_path):
    print(f"Error: PDF file not found at {pdf_file_path}")
    exit()

print("Converting PDF to image...")
# Get the first page (page_num=0) as a base64 string
image_base64 = pdf_page_to_base64(pdf_file_path, page_num=0, poppler_path=poppler_bin_path)

if not image_base64:
    print("Failed to convert PDF. Exiting.")
    exit()

# This prompt is the "brain" of the operation.
# We are instructing the VLM to act as an extractor and to ONLY return JSON.
prompt = """
You are an expert data extraction.
Analyze the attached image of a form.
Extract all key-value pairs.

- Return the results in the following JSON format:

{
  "key_value_pairs": {
    "Label 1": "Value 1",
    "Label 2": "Value 2",
    ...
  }

}
Respond ONLY with a valid JSON object.
Do not include any other text, explanations, or markdown formatting like ```json.
"""

print("Sending image to local VLM. This may take up to a minute...")

try:
    response = ollama.chat(
        model='llava-phi3:3.8b', # Use your desired VLM model here
        messages=[
            {
                'role': 'user',
                'content': prompt,
                'images': [image_base64] # Pass the image here
            }
        ],
        format='json' # Request JSON output
    )

    print("\n--- EXTRACTION COMPLETE ---")
    
    # The response content should be a JSON string
    json_string = response['message']['content']
    
    # Parse the string into a Python dictionary
    try:
        parsed_json = json.loads(json_string)
        print(json.dumps(parsed_json, indent=2, ensure_ascii=False))
    
    except json.JSONDecodeError:
        print("VLM did not return valid JSON. Raw output:")
        print(json_string)

except Exception as e:
    print(f"An error occurred while contacting Ollama: {e}")
    print("Is the Ollama application running?")