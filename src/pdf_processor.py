import io
import base64
import pdfplumber
import pypdfium2 as pdfium
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
from PIL import Image

# Try to support pypdf (new name) or PyPDF2 as a fallback
try:
    from pypdf import PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        PdfReader = None

class PDFProcessor:
    def __init__(self, pdf_bytes: bytes):
        """Initialize the PDF processor with the PDF file bytes."""
        self.pdf_bytes = pdf_bytes
        self.reader = PdfReader(io.BytesIO(pdf_bytes))
        
    def get_button_info(self, field: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract detailed information from a button field."""
        try:
            if field.get('/FT') != '/Btn':
                return None
                
            info = {
                'name': field.get('/T', ''),        # Technical name
                'title': field.get('/TU', ''),      # Display name/title
                'value': field.get('/V', ''),       # Current value
                'states': field.get('/_States_', []),  # Possible states
                'parent': None
            }
            
            # Try to get parent info
            if '/Parent' in field:
                parent = field['/Parent']
                if hasattr(parent, 'get_object'):
                    parent = parent.get_object()
                if hasattr(parent, 'get'):
                    info['parent'] = {
                        'name': parent.get('/T', ''),
                        'title': parent.get('/TU', '')
                    }
                    
            return info
        except Exception:
            return None
            
    def process_button_field(self, field: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[List[float]]]:
        """Process a button field and return if it's checked, field name, and its coordinates."""
        try:
            # Get the field type
            field_type = field.get('/FT', '')
            if field_type != '/Btn':
                return False, None, None
                
            # Get all possible values and states
            field_value = field.get('/V', '')  # Value
            field_state = field.get('/AS', '')  # Appearance state
            field_name = field.get('/T', '')    # Technical name
            field_title = field.get('/TU', '')  # User-friendly title
            
            # Get the button's coordinates
            rect = field.get('/Rect', [])
            
            # Check if button is selected/checked
            is_checked = any([
                field_value == '/On',
                field_value == 'Yes',
                field_value == 'Checked',
                field_state == '/Yes',
                field_state == '/On'
            ])
            
            # If not obviously checked, try other methods
            if not is_checked:
                # Check appearance dictionary
                ap_dict = field.get('/AP', {})
                if hasattr(ap_dict, 'get'):
                    n_dict = ap_dict.get('/N', {})
                    if hasattr(n_dict, 'keys'):
                        # Any key other than /Off might indicate checked state
                        other_keys = [k for k in n_dict.keys() if k != '/Off']
                        if other_keys and field_value in other_keys:
                            is_checked = True
            
            # Still not checked? Look at raw values
            if not is_checked and field_value:
                clean_value = field_value[1:] if field_value.startswith('/') else field_value
                if clean_value.lower() not in ['off', 'no', 'false', '0', 'null', '']:
                    is_checked = True
                    
            if not is_checked:
                return False, None, None
                
            # Get the display name
            field_label = None
            
            # First try to get parent name (for grouped buttons)
            if '/Parent' in field:
                try:
                    parent = field['/Parent']
                    if hasattr(parent, 'get_object'):
                        parent = parent.get_object()
                    if hasattr(parent, 'get'):
                        parent_title = parent.get('/TU', '')
                        parent_name = parent.get('/T', '')
                        if parent_title or parent_name:
                            field_label = parent_title or parent_name
                            # The button's own name becomes the value in case of radio buttons
                            if field_title or field_name:
                                return True, field_label, rect
                except:
                    pass
                    
            # No parent? Then use the field's own name
            if not field_label:
                field_label = field_title or field_name
                
            # Clean up the field label
            if field_label:
                field_label = field_label.split('_')[0].split('.')[0]
                
                # Handle special cases
                name_lower = field_label.lower()
                if any(yes in name_lower for yes in ['ja', 'yes', 'oui']):
                    field_label = 'ja'
                elif any(no in name_lower for no in ['nein', 'no', 'non']):
                    field_label = 'nein'
                    
            return True, field_label, rect
            
        except Exception:
            return False, None, None
            
    def get_all_buttons(self) -> List[Dict[str, Any]]:
        """Get information about all button fields in the PDF."""
        found_buttons = []
        
        for page_num, page in enumerate(self.reader.pages, 1):
            try:
                annots = page.get('/Annots', [])
                for annot in annots:
                    field = annot.get_object()
                    if not field:
                        continue
                        
                    field_type = field.get('/FT', '')
                    if field_type == '/Btn':  # Only process button fields
                        # Get field information
                        field_value = field.get('/V', '')
                        field_state = field.get('/AS', '')
                        field_name = field.get('/T', '')
                        field_title = field.get('/TU', '')
                        
                        # Get parent information if available
                        parent_info = ""
                        if '/Parent' in field:
                            try:
                                parent = field['/Parent'].get_object()
                                parent_title = parent.get('/TU', '')
                                parent_name = parent.get('/T', '')
                                if parent_title or parent_name:
                                    parent_info = parent_title or parent_name
                            except:
                                pass
                        
                        # Check if button is checked
                        is_checked = any([
                            field_value == '/On',
                            field_value == 'Yes',
                            field_value == 'Checked',
                            field_state == '/Yes',
                            field_state == '/On'
                        ])
                        
                        # Format the button information
                        button_info = {
                            'page': page_num,
                            'name': field_name,
                            'title': field_title,
                            'value': field_value,
                            'state': field_state,
                            'is_checked': is_checked,
                            'parent': parent_info
                        }
                        found_buttons.append(button_info)
            except Exception:
                continue
                
        return found_buttons
        
    def extract_text(self) -> str:
        """Extract visible text from the PDF."""
        text = ""
        try:
            with pdfplumber.open(io.BytesIO(self.pdf_bytes)) as pdf:
                for page in pdf.pages:
                    text += page.extract_text() or ""
        except Exception:
            pass
        return text

    def extract_text_with_llm(self) -> str:
        """
        Extracts text from the PDF by rendering pages as images and using a multimodal LLM.
        """
        full_text = ""
        try:
            from llm_processor import LLMFieldExtractor
            extractor = LLMFieldExtractor()
            pdf = pdfium.PdfDocument(self.pdf_bytes)
            
            for i in range(len(pdf)):
                page = pdf[i]
                # Render page to a PIL image
                image = page.render(scale=3).to_pil() # Higher scale for better OCR
                
                # Convert image to base64
                buffered = io.BytesIO()
                image.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                
                # Extract text using the LLM
                page_text = extractor.extract_text_from_image(img_str)
                full_text += f"\n\n--- Page {i+1} ---\n{page_text}"

        except Exception as e:
            print(f"Error during multimodal text extraction: {e}")
            # Fallback to standard text extraction if multimodal fails
            return self.extract_text()
            
        return full_text
        
    def get_metadata(self) -> Dict[str, str]:
        """Get PDF metadata."""
        try:
            return {k: str(v) for k, v in (self.reader.metadata or {}).items()}
        except Exception:
            return {}
            
    def get_form_fields(self, use_llm: bool = False) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Get all form fields from the PDF.
        
        Args:
            use_llm: Whether to use LLM-enhanced extraction
            
        Returns:
            A tuple containing the dictionary of form fields and an optional error message.
        """
        fields = {}
        error_message = None
        try:
            if hasattr(self.reader, "get_fields"):
                raw_fields = self.reader.get_fields()
                if raw_fields:
                    for field_name, field_data in raw_fields.items():
                        if not field_data:
                            continue
                        if isinstance(field_data, dict):
                            field_type = field_data.get('/FT', '')
                            field_value = field_data.get('/V', '')
                            display_name = field_data.get('/TU', '') or field_name
                            if field_type == '/Btn':
                                if field_value == '/On':
                                    name_lower = field_name.lower()
                                    if 'ja' in name_lower or 'yes' in name_lower:
                                        fields[display_name] = 'yes'
                                    elif 'nein' in name_lower or 'no' in name_lower:
                                        fields[display_name] = 'no'
                                    else:
                                        fields[display_name] = 'checked'
                            elif field_value:
                                fields[display_name] = str(field_value).strip('/')
                        else:
                            if field_data:
                                fields[field_name] = str(field_data)
                                
            if use_llm:
                from llm_processor import LLMFieldExtractor
                extractor = LLMFieldExtractor()
                
                pdf_text = self.extract_text_with_llm()
                buttons = self.get_all_buttons()
                
                try:
                    return extractor.extract_fields(pdf_text, fields, buttons)
                except Exception as e:
                    error_message = f"Error in LLM processing: {str(e)}"
                    return fields, error_message
                
        except Exception as e:
            error_message = f"Error extracting form fields: {str(e)}"
            pass
            
        return fields, error_message
        
    def analyze_checkbox_visually(self, page_num: int, rect: List[float]) -> bool:
        """Analyze a checkbox visually to determine if it's checked."""
        try:
            with pdfplumber.open(io.BytesIO(self.pdf_bytes)) as pdf:
                if page_num >= len(pdf.pages):
                    return False
                    
                page = pdf.pages[page_num]
                x0, y0, x1, y1 = [float(v) for v in rect]
                ph = page.height
                top = ph - y1
                bottom = ph - y0
                bbox = (x0, top, x1, bottom)
                
                cropped = page.within_bbox(bbox)
                img = cropped.to_image(resolution=150).original
                gray = img.convert('L')
                arr = np.array(gray)
                dark = np.sum(arr < 200)
                total = arr.size
                ratio = dark / total if total > 0 else 0
                
                return ratio > 0.02
                
        except Exception:
            return False
            
    def is_xfa_form(self) -> bool:
        """Check if the PDF is an XFA form."""
        try:
            return bool(self.reader.trailer["/Root"]["/AcroForm"].get("/XFA"))
        except Exception:
            return False
