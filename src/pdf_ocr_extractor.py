import pytesseract
from pdf2image import convert_from_bytes
from typing import List, Dict, Any
import json
import os

# Set Tesseract path if not in system PATH
# Uncomment and modify the path below if Tesseract is installed but not in PATH
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

class PDFOCRExtractor:
    """
    Extracts text from a PDF using Tesseract OCR and structures it as JSON.
    """
    def __init__(self, pdf_bytes: bytes):
        self.pdf_bytes = pdf_bytes

    def extract_text(self) -> List[str]:
        """
        Convert PDF pages to images and extract text from each page using OCR.
        Returns a list of strings, one per page.
        """
        images = convert_from_bytes(self.pdf_bytes)
        page_texts = []
        for img in images:
            text = pytesseract.image_to_string(img)
            page_texts.append(text)
        return page_texts

    def structure_as_json(self) -> Dict[str, Any]:
        """
        Structure the extracted text in a JSON format.
        Returns a dictionary with page numbers and their corresponding text.
        """
        page_texts = self.extract_text()
        structured = {
            "pages": [
                {"page": i+1, "text": text}
                for i, text in enumerate(page_texts)
            ]
        }
        return structured

    def save_json(self, output_path: str):
        """
        Save the structured JSON to a file.
        """
        data = self.structure_as_json()
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# Example usage:
# with open('yourfile.pdf', 'rb') as f:
#     extractor = PDFOCRExtractor(f.read())
#     print(extractor.structure_as_json())
#     extractor.save_json('output.json')
