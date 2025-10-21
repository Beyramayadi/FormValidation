import streamlit as st
import pdfplumber
import io
import pandas as pd
import numpy as np
from PIL import Image, ImageDraw
import base64

# Try to support pypdf (new name) or PyPDF2 as a fallback
try:
    from pypdf import PdfReader
except Exception:
    try:
        from PyPDF2 import PdfReader
    except Exception:
        PdfReader = None

st.title("AI Form Agent")

uploaded_file = st.file_uploader("Upload a PDF form", type=["pdf"])

def process_button_field(obj):
    """Process a button field and return if it's checked and its display name."""
    try:
        # Get the field type
        field_type = obj.get('/FT', '')
        if field_type != '/Btn':
            return False, None
            
        # Get all possible values and states
        field_value = obj.get('/V', '')  # Value
        field_state = obj.get('/AS', '')  # Appearance state
        field_name = obj.get('/T', '')    # Technical name
        field_title = obj.get('/TU', '')  # User-friendly title
        
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
            ap_dict = obj.get('/AP', {})
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
            return False, None
            
        # Get the display name for the checked button
        display_name = None
        
        # First try to get parent name (for grouped buttons)
        if '/Parent' in obj:
            try:
                parent = obj['/Parent']
                if hasattr(parent, 'get_object'):
                    parent = parent.get_object()
                if hasattr(parent, 'get'):
                    parent_title = parent.get('/TU', '')
                    parent_name = parent.get('/T', '')
                    if parent_title or parent_name:
                        display_name = parent_title or parent_name
            except:
                pass
                
        # No parent name? Use field's own name
        if not display_name:
            display_name = field_title or field_name
            
        # Clean up the name
        if display_name:
            display_name = display_name.split('_')[0].split('.')[0]
            
            # Handle special cases
            name_lower = display_name.lower()
            if any(yes in name_lower for yes in ['ja', 'yes', 'oui']):
                display_name = 'ja'
            elif any(no in name_lower for no in ['nein', 'no', 'non']):
                display_name = 'nein'
                
        if not display_name:
            display_name = "checked"
            
        return True, display_name
        
    except Exception as e:
        st.write(f"Error processing button: {str(e)}")
        st.write("Button data:", obj)
        return False, None

def extract_text_from_bytes(b):
    """Use pdfplumber to extract visible text and form field values."""
    text = ""
    checked_values = []
    
    try:
        # First get the checked button values
        reader = PdfReader(io.BytesIO(b))
        for page in reader.pages:
            try:
                annots = page.get('/Annots', [])
                for annot in annots:
                    field = annot.get_object()
                    is_checked, name = process_button_field(field)
                    if is_checked and name:
                        checked_values.append(name)
            except Exception as e:
                st.write(f"Error processing page annotations: {str(e)}")
                
        # Then get the regular text
        with pdfplumber.open(io.BytesIO(b)) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
                
        # Add checked values to the text
        if checked_values:
            text += "\n\nChecked Fields:\n"
            text += "\n".join(f"- {value}" for value in checked_values)
            
    except Exception as e:
        st.write(f"Error in text extraction: {str(e)}")
        text = ""
        
    return text

def get_button_info(obj):
    """Extract detailed information from a button field."""
    try:
        if obj.get('/FT') != '/Btn':
            return None
            
        info = {
            'name': obj.get('/T', ''),        # Technical name
            'title': obj.get('/TU', ''),      # Display name/title
            'value': obj.get('/V', ''),       # Current value
            'states': obj.get('/_States_', []),  # Possible states
            'parent': None
        }
        
        # Try to get parent info
        if '/Parent' in obj:
            parent = obj['/Parent']
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

def extract_form_fields_from_bytes(b):
    """Try multiple strategies to extract PDF form (AcroForm) fields and widget annotation values.
    Returns a dict: {field_name: value}
    """
    if PdfReader is None:
        return None, "pypdf/PyPDF2 not installed"

    fields = {}
    try:
        reader = PdfReader(io.BytesIO(b))
    except Exception as e:
        return None, f"PdfReader failed: {e}"

    # Try to open a pdfplumber copy for visual analysis (checkbox appearance)
    try:
        import pdfplumber as _pdfplumber
        _ppages = None
        try:
            _ppdf = _pdfplumber.open(io.BytesIO(b))
            _ppages = list(_ppdf.pages)
        except Exception:
            _ppages = None
    except Exception:
        _ppages = None

    # Strategy 1: high level helper if available
    try:
        if hasattr(reader, "get_form_text_fields"):
            try:
                f = reader.get_form_text_fields() or {}
                if f:
                    return f, None
            except Exception:
                pass
    except Exception:
        pass

    def process_button_field(obj):
        """Process a button field and return its name and value."""
        try:
            # Get the field type
            field_type = obj.get('/FT', '')
            if field_type != '/Btn':
                return None, None
                
            # Get field name and display name
            field_name = obj.get('/T', '')  # Original field name
            display_name = obj.get('/TU', '') or field_name.split('_')[0]
            
            # Get the value
            value = obj.get('/V', '')
            actual_value = display_name if value == '/On' else ''
            
            return field_name, actual_value
            
        except Exception as e:
            st.write(f"Error processing button: {str(e)}")
            return None, None
            
    def extract_checkbox_label(page, rect, margin=20):
        """Extract text near a checkbox to get its label."""
        try:
            x0, y0, x1, y1 = [float(v) for v in rect]
            # Extend the box to the right to capture the label
            search_bbox = (x0-margin, y0-margin, x1+margin*4, y1+margin)
            
            # Convert PDF coordinates (bottom-left origin) to image coordinates (top-left origin)
            ph = float(page.height)
            search_bbox = (search_bbox[0], ph-search_bbox[3], search_bbox[2], ph-search_bbox[1])
            
            # Extract text from the expanded area
            text = page.within_bbox(search_bbox).extract_text() or ""
            return text.strip()
        except Exception as e:
            return f"Error: {e}"

    def extract_button_values(fields):
        """Extract checked button values from form fields."""
        checked_fields = []
        
        for field_name, field_data in fields.items():
            try:
                # Check if it's a button field
                if '/FT' in field_data and field_data['/FT'] == '/Btn':
                    # Check if the value is /On
                    if '/V' in field_data and field_data['/V'] == '/On':
                        # Get the field name without any suffix numbers
                        base_name = field_data.get('/TU', '') or field_name.split('_')[0]
                        checked_fields.append(base_name)
                        
                        # Debug output
                        st.write(f"Found checked button:")
                        st.write(f"Name: {field_name}")
                        st.write(f"Base name: {base_name}")
                        st.write(f"Full data: {field_data}")
            except Exception as e:
                st.write(f"Error processing field {field_name}: {str(e)}")
                continue
                
        return checked_fields

    def _normalize_val(v, field_type=None, states=None, field_dict=None, label=None):
        """Normalize PDF field values to python primitives."""
        # Handle button fields
        if str(field_type).find('/Btn') != -1:
            # Get the button value
            value = field_dict.get('/V', '')
            
            # If it's not checked, return empty string
            if value != '/On':
                return ""
                
            # Get the field name and parent info
            field_name = field_dict.get('/T', '')  # Technical name
            field_title = field_dict.get('/TU', '')  # Display name/title
            parent_name = field_dict.get('/Parent', {})
            if hasattr(parent_name, 'get'):
                parent_name = parent_name.get('/T', '')
            
            # First try to get value from TU (this is usually the most accurate)
            if field_title:
                return field_title
                
            # If no TU, try to clean up the technical name
            if field_name:
                # Remove common suffixes
                clean_name = field_name.split('_')[0]
                # Special case for ja/nein
                name_lower = field_name.lower()
                if 'ja' in name_lower:
                    return 'ja'
                elif 'nein' in name_lower:
                    return 'nein'
                return clean_name
                
            return "checked"
            
        # For non-button fields, return as is
        return str(v) if v is not None else ""
            
        # For checkboxes (type Btn), default to unchecked
        if v is None:
            debug['reason'] = 'no_value'
            st.write(f"DEBUG: {debug}")
            return False
            
        # Convert value to string, handling PDF name objects
        try:
            if hasattr(v, 'get_object'):
                v = v.get_object()
            s = str(v)
            if s.startswith('/'):
                s = s[1:]  # Strip leading slash from PDF name objects
        except Exception:
            debug['reason'] = 'value_error'
            st.write(f"DEBUG: {debug}")
            return False
            
        s_low = s.lower()
        debug['normalized_value'] = s_low
        
        # Get possible states for this checkbox
        valid_states = []
        if states:
            try:
                valid_states = [str(x).lower().strip('/') for x in states]
                debug['valid_states'] = valid_states
            except Exception:
                pass
                
        # Look for export value in field dictionary
        export_value = None
        if field_dict:
            try:
                # Try to get the export value for the "checked" state
                ap = field_dict.get('/AP', {})
                if hasattr(ap, 'get'):
                    n = ap.get('/N', {})
                    if hasattr(n, 'keys'):
                        # The keys other than /Off are typically the export value
                        keys = [k for k in n.keys() if k != '/Off']
                        if keys:
                            export_value = keys[0].strip('/')
                            debug['export_value'] = export_value
            except Exception:
                pass
                
        # Definite unchecked cases
        if not s or s_low in ('off', 'no', 'false', '0'):
            debug['reason'] = 'explicit_unchecked'
            st.write(f"DEBUG: {debug}")
            return False
            
        # Definite checked cases
        if s_low in ('on', 'yes', 'true', '1'):
            debug['reason'] = 'explicit_checked'
            st.write(f"DEBUG: {debug}")
            return True
            
        # Check against valid states
        if valid_states:
            if 'on' in valid_states:
                is_checked = (s_low == 'on')
                debug['reason'] = 'state_match_on'
                st.write(f"DEBUG: {debug}")
                return is_checked
            if 'yes' in valid_states:
                is_checked = (s_low == 'yes')
                debug['reason'] = 'state_match_yes'
                st.write(f"DEBUG: {debug}")
                return is_checked
                
        # Check against export value
        if export_value:
            is_checked = (s_low == export_value.lower())
            debug['reason'] = 'export_value_match'
            st.write(f"DEBUG: {debug}")
            return is_checked
            
        # Conservative default: only mark as checked if we have a clear "on" value
        is_checked = (s_low == 'on')
        debug['reason'] = 'conservative_default'
        st.write(f"DEBUG: {debug}")
        return is_checked

    # Strategy 2: Process all fields with improved accuracy
    try:
        if hasattr(reader, "get_fields"):
            # First collect all button fields by their grouping
            button_groups = {}
            
            # Scan all pages for buttons
            for page in reader.pages:
                try:
                    annots = page.get('/Annots', [])
                    for annot in annots:
                        field = annot.get_object()
                        button_info = get_button_info(field)
                        
                        if not button_info:
                            continue
                            
                        # Determine the group key for this button
                        group_key = None
                        
                        # Try to get group from parent first
                        if button_info['parent'] and button_info['parent']['title']:
                            group_key = button_info['parent']['title']
                        # Then try the button's own title
                        elif button_info['title']:
                            # For ja/nein groups, use the base name
                            base_name = button_info['title'].split('_')[0]
                            if 'ja' in button_info['name'].lower() or 'nein' in button_info['name'].lower():
                                group_key = base_name
                            else:
                                group_key = button_info['title']
                        # Finally use the technical name base
                        else:
                            group_key = button_info['name'].split('_')[0]
                            
                        # Store button in its group
                        if group_key not in button_groups:
                            button_groups[group_key] = []
                        button_groups[group_key].append(button_info)
                        
                except Exception as e:
                    st.write(f"Error processing page annotations: {str(e)}")
                    continue
                    
            # Now process each group to find checked values
            for group_name, buttons in button_groups.items():
                checked_value = None
                for button in buttons:
                    if button['value'] == '/On':
                        # For ja/nein buttons
                        btn_name = button['name'].lower()
                        if 'ja' in btn_name:
                            checked_value = 'ja'
                        elif 'nein' in btn_name:
                            checked_value = 'nein'
                        # For other buttons
                        else:
                            checked_value = button['title'] or button['name'].split('_')[0]
                            
                if checked_value:
                    fields[group_name] = checked_value
                    
            # Process non-button fields
            raw = reader.get_fields() or {}
            for k, v in raw.items():
                if isinstance(v, dict):
                    field_type = v.get('/FT') or v.get('FT')
                    # Skip buttons as we already processed them
                    if str(field_type) != '/Btn':
                        field_title = v.get('/TU', '') or k
                        val = v.get('/V') or v.get('V') or v.get('value')
                        if val:
                            fields[field_title] = str(val)
                elif v:  # Simple fields
                    fields[k] = str(v)
    except Exception as e:
        st.write(f"Error processing fields: {str(e)}")
        pass

    # Strategy 3: inspect page annotations for widget fields
    if not fields:
        try:
            # reader.pages is an iterable of page objects
            for i, p in enumerate(reader.pages):
                # page objects behave like dicts; look for /Annots
                try:
                    annots = p.get('/Annots') or p.get("/Annots")
                except Exception:
                    annots = None
                if not annots:
                    continue
                for a in annots:
                    try:
                        obj = a.get_object()
                        name = obj.get('/T') or obj.get('T')
                        if not name:
                            continue
                        # For widget annotations/buttons, check /V (value) or /AS (appearance state)
                        raw_val = None
                        # check standard keys
                        for key in ('/V', 'V', '/AS', 'AS'):
                            try:
                                if obj.get(key) is not None:
                                    raw_val = obj.get(key)
                                    break
                            except Exception:
                                continue

                        # If still None, try to look at parent field dictionary (/Parent or annotation indirect)
                        if raw_val is None:
                            try:
                                parent = obj.get('/Parent') or obj.get('Parent')
                                if parent and hasattr(parent, 'get'):
                                    raw_val = parent.get('/V') or parent.get('V')
                            except Exception:
                                pass

                        # Get field type and states for checkbox normalization
                        ft = None
                        states = None
                        try:
                            ft = obj.get('/FT') or obj.get('FT')
                            states = obj.get('/_States_')
                        except Exception:
                            pass

                        # Normalize value using field type info
                        norm = _normalize_val(raw_val, ft, states)
                        try:
                            is_button = False
                            if ft and str(ft).lower().find('btn') != -1:
                                is_button = True
                        except Exception:
                            is_button = False

                        # Visual fallback: crop the widget rect from the pdf image and compute dark pixel ratio
                        if is_button and (norm is False or norm == "") and _ppages is not None:
                            rect = None
                            try:
                                rect = obj.get('/Rect') or obj.get('Rect')
                            except Exception:
                                rect = None
                            if rect:
                                try:
                                    x0, y0, x1, y1 = [float(v) for v in rect]
                                    # pdfplumber pages use origin top-left; PDF rect is bottom-left origin
                                    # map to pdfplumber bbox: (x0, top, x1, bottom)
                                    # ensure matching page exists in pdfplumber pages
                                    if i < len(_ppages):
                                        pdf_page = _ppages[i]
                                    else:
                                        pdf_page = _ppages[0]
                                    ph = pdf_page.height
                                    top = ph - y1
                                    bottom = ph - y0
                                    bbox = (x0, top, x1, bottom)
                                    cropped = pdf_page.within_bbox(bbox)
                                    img = cropped.to_image(resolution=150).original
                                    gray = img.convert('L')
                                    arr = np.array(gray)
                                    # threshold dark pixels
                                    dark = np.sum(arr < 200)
                                    total = arr.size
                                    ratio = dark / total if total > 0 else 0
                                    # small threshold for marks inside boxes
                                    if ratio > 0.02:
                                        norm = True
                                    else:
                                        norm = False
                                except Exception:
                                    pass
                        fields[str(name)] = norm
                    except Exception:
                        continue
        except Exception:
            pass

    if fields:
        return fields, None
    return {}, None


if uploaded_file:
    # Read bytes once and reuse for both text extraction and field extraction
    file_bytes = uploaded_file.read()

    # Extract visible text and checked values
    text = extract_text_from_bytes(file_bytes)

    st.subheader("Extracted Content")
    
    # Display regular text
    st.text_area("Visible Text", text if text else "(no visible text extracted)", height=200)
    
    # Create a dropdown for button field debug info
    with st.expander("🔍 Found Button Fields"):
        # Process the PDF to find buttons
        reader = PdfReader(io.BytesIO(file_bytes))
        found_buttons = []
        
        for page_num, page in enumerate(reader.pages, 1):
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
                                    parent_info = f"\nParent: {parent_title or parent_name}"
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
                            'parent_info': parent_info
                        }
                        found_buttons.append(button_info)
            except Exception as e:
                st.error(f"Error processing page {page_num}: {str(e)}")
                
        # Display the found buttons
        if found_buttons:
            for btn in found_buttons:
                with st.container():
                    status = "✅ CHECKED" if btn['is_checked'] else "❌ UNCHECKED"
                    st.markdown(f"**Button on Page {btn['page']}** - {status}")
                    st.code(
                        f"Name: {btn['name']}\n"
                        f"Title: {btn['title']}\n"
                        f"Value: {btn['value']}\n"
                        f"State: {btn['state']}"
                        f"{btn['parent_info']}"
                    )
        else:
            st.info("No button fields found in this PDF.")

    # Debug panel to show raw PDF data
    with st.expander("🔍 Debug Information (Raw PDF Data)"):
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            st.write("PDF Basic Info:")
            try:
                info = {k: str(v) for k,v in (reader.metadata or {}).items()}
                st.json(info)
            except Exception as e:
                st.error(f"Error reading metadata: {e}")
            
            st.write("Form Fields (Raw):")
            try:
                if hasattr(reader, "get_fields"):
                    fields_raw = reader.get_fields()
                    if fields_raw:
                        st.json({k: str(v) for k,v in fields_raw.items()})
                    else:
                        st.info("No form fields found via get_fields()")
            except Exception as e:
                st.error(f"Error reading form fields: {e}")
            
            st.write("Widget Annotations by Page:")
            for i, page in enumerate(reader.pages):
                try:
                    annots = page.get("/Annots")
                    if annots:
                        st.write(f"Page {i+1}:")
                        for a in annots:
                            try:
                                obj = a.get_object()
                                name = obj.get('/T', '<no-name>')
                                ft = obj.get('/FT', '<no-type>')
                                v = obj.get('/V', '<no-value>')
                                rect = obj.get('/Rect', [])
                                st.code(f"Name: {name}\nType: {ft}\nValue: {v}\nRect: {rect}")
                            except Exception as e:
                                st.error(f"Error reading annotation: {e}")
                except Exception as e:
                    st.error(f"Error reading page {i+1}: {e}")
            
            # Visual analysis debug
            st.write("Visual Analysis of Potential Checkboxes:")
            try:
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    for i, page in enumerate(pdf.pages):
                        annots = None
                        try:
                            reader_page = reader.pages[i]
                            annots = reader_page.get("/Annots", [])
                        except Exception:
                            continue
                            
                        if not annots:
                            continue
                            
                        for a in annots:
                            try:
                                obj = a.get_object()
                                ft = obj.get('/FT', '')
                                if not (ft and str(ft).lower().find('btn') != -1):
                                    continue
                                    
                                rect = obj.get('/Rect')
                                if not rect:
                                    continue
                                    
                                x0, y0, x1, y1 = [float(v) for v in rect]
                                ph = page.height
                                top = ph - y1
                                bottom = ph - y0
                                bbox = (x0, top, x1, bottom)
                                
                                try:
                                    cropped = page.within_bbox(bbox)
                                    img = cropped.to_image(resolution=150).original
                                    gray = img.convert('L')
                                    arr = np.array(gray)
                                    dark = np.sum(arr < 200)
                                    total = arr.size
                                    ratio = dark / total if total > 0 else 0
                                    
                                    # Draw rectangle on preview
                                    preview = img.copy()
                                    draw = ImageDraw.Draw(preview)
                                    draw.rectangle((0, 0, preview.width-1, preview.height-1), outline='red')
                                    
                                    # Convert to base64 for display
                                    buffered = io.BytesIO()
                                    preview.save(buffered, format="PNG")
                                    img_str = base64.b64encode(buffered.getvalue()).decode()
                                    
                                    name = obj.get('/T', '<no-name>')
                                    st.write(f"Field: {name}")
                                    st.write(f"Dark pixel ratio: {ratio:.3f}")
                                    st.markdown(f'<img src="data:image/png;base64,{img_str}" style="border:1px solid gray"/>', unsafe_allow_html=True)
                                    if ratio > 0.02:
                                        st.write("✅ Detected as CHECKED")
                                    else:
                                        st.write("❌ Detected as UNCHECKED")
                                    st.markdown("---")
                                except Exception as e:
                                    st.error(f"Error in visual analysis: {e}")
                            except Exception:
                                continue
            except Exception as e:
                st.error(f"Error in visual analysis setup: {e}")
                
            # Add XFA check
            st.write("XFA Form Check:")
            try:
                xfa = reader.trailer["/Root"]["/AcroForm"].get("/XFA")
                if xfa:
                    st.warning("⚠️ This appears to be an XFA form - different parsing may be needed")
                else:
                    st.info("Not an XFA form")
            except Exception:
                st.info("Not an XFA form (no /XFA key found)")
                
        except Exception as e:
            st.error(f"Error reading PDF structure: {e}")

    # Extract form fields (AcroForm/widget values)
    st.subheader("Form field values (if present)")
    
    def process_form_fields(pdf_bytes):
        """Process all form fields from a PDF, handling various field types and structures."""
        fields = {}
        reader = PdfReader(io.BytesIO(pdf_bytes))
        
        for page in reader.pages:
            try:
                annots = page.get('/Annots', [])
                for annot in annots:
                    field = annot.get_object()
                    
                    # Skip if not a valid field
                    if not field:
                        continue
                        
                    # Get basic field properties
                    field_type = field.get('/FT', '')
                    field_name = field.get('/T', '')
                    field_value = field.get('/V', '')
                    field_title = field.get('/TU', '')  # User-friendly name
                    field_state = field.get('/AS', '')  # Appearance state
                    
                    # Get parent field info if available
                    parent = field.get('/Parent', {})
                    if hasattr(parent, 'get_object'):
                        parent = parent.get_object()
                    parent_title = parent.get('/TU', '') if hasattr(parent, 'get') else None
                    
                    # Determine the proper field name (from most specific to least)
                    display_name = (parent_title or  # Parent's title
                                  field_title or     # Field's title
                                  field_name)        # Technical name
                    
                    if not display_name:  # Skip fields without names
                        continue
                        
                    # Handle different field types
                    if field_type == '/Btn':  # Buttons/Checkboxes
                        if field_value == '/On' or field_state == '/Yes':
                            # Try to get the value from various sources
                            value = None
                            
                            # 1. Check if it's a yes/no field
                            name_lower = field_name.lower()
                            if any(yes in name_lower for yes in ['ja', 'yes', 'oui', 'si']):
                                value = 'yes'
                            elif any(no in name_lower for no in ['nein', 'no', 'non']):
                                value = 'no'
                                
                            # 2. Check for value in export value
                            if not value and '/AP' in field:
                                ap = field['/AP']
                                if hasattr(ap, 'get'):
                                    n = ap.get('/N', {})
                                    if hasattr(n, 'keys'):
                                        keys = [k.strip('/') for k in n.keys() if k != '/Off']
                                        if keys:
                                            value = keys[0]
                            
                            # 3. Use the field title or name as value
                            if not value:
                                value = "checked"
                                
                            fields[display_name] = value
                            
                    elif field_type == '/Tx':  # Text fields
                        if field_value:
                            fields[display_name] = str(field_value)
                            
                    elif field_type == '/Ch':  # Choice fields
                        if field_value:
                            if isinstance(field_value, list):
                                fields[display_name] = ', '.join(str(v) for v in field_value)
                            else:
                                fields[display_name] = str(field_value)
                                
            except Exception as e:
                st.write(f"Error processing page annotations: {str(e)}")
                continue
                
        return fields
    
    # Process the form fields
    fields = process_form_fields(file_bytes)
    
    if fields:
        try:
            # Convert to dataframe and sort
            df = pd.DataFrame(list(fields.items()), columns=["field", "value"])
            # Only show rows where value is not empty
            df = df[df['value'].astype(str).str.strip() != '']
            df = df.sort_values('field')
            st.dataframe(df)
        except Exception as e:
            st.write(f"Error creating dataframe: {str(e)}")
            st.write(fields)
    else:
        st.info("No form fields detected in this PDF (or fields are not populated).")
