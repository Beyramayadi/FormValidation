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

def extract_text_from_bytes(b):
    """Use pdfplumber to extract visible text."""
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(b)) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
    except Exception:
        # pdfplumber may fail for some PDFs; return empty string on error
        text = ""
    return text

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

    def _normalize_val(v, field_type=None, states=None, field_dict=None, label=None):
        """Normalize PDF field values to python primitives (bool if checkbox-like)."""
        # For debugging
        debug = {}
        debug['raw_value'] = str(v)
        debug['field_type'] = str(field_type)
        debug['states'] = str(states)
        debug['label'] = label
        
        # Handle button/checkbox fields specially
        is_button = field_type and str(field_type).lower().find('btn') != -1
        if not is_button:
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

    # Strategy 2: get_fields() - PyPDF2 style
    try:
        if hasattr(reader, "get_fields"):
            raw = reader.get_fields() or {}
            for k, v in raw.items():
                # v might be a dictionary or a primitive
                if isinstance(v, dict):
                    # common keys for value: '/V' or 'V' or 'value'
                    # Get field value and type
                    val = v.get('/V') or v.get('V') or v.get('value') or v.get('/AS') or v.get('AS') or None
                    field_type = v.get('/FT') or v.get('FT')
                    states = v.get('/_States_')
                    
                    # For checkboxes/buttons, try to get the associated label text
                    label = None
                    if str(field_type).find('/Btn') != -1:
                        try:
                            # Get field's rectangle
                            rect = v.get('/Rect')
                            if rect:
                                # Find the page this field is on
                                for page_num, page in enumerate(reader.pages):
                                    annots = page.get('/Annots', [])
                                    if any(a.get_object().get('/T') == k for a in annots if hasattr(a, 'get_object')):
                                        # Found the page, extract nearby text
                                        with pdfplumber.open(io.BytesIO(b)) as pdf:
                                            pdf_page = pdf.pages[page_num]
                                            label = extract_checkbox_label(pdf_page, rect)
                                            break
                        except Exception as e:
                            label = f"Error extracting label: {e}"
                    
                    # For checkboxes, try to get the export value from appearance streams
                    if str(field_type).find('/Btn') != -1:
                        st.write(f"\nDEBUG Field {k}:")
                        st.write("Raw field dict:", {str(key): str(value) for key, value in v.items()})
                        if label:
                            st.write("Extracted label:", label)
                    
                    # Store both the checkbox state and its label
                    is_checked = _normalize_val(val, field_type, states, v, label)
                    if label:
                        fields[f"{k} ({label})"] = is_checked
                    else:
                        fields[k] = is_checked
                else:
                    fields[k] = _normalize_val(v)
    except Exception:
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

    # Extract visible text
    text = extract_text_from_bytes(file_bytes)

    st.subheader("Extracted visible text")
    st.text_area("Content", text if text else "(no visible text extracted)", height=300)

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
    fields, err = extract_form_fields_from_bytes(file_bytes)
    if err:
        st.warning(err)
        st.info("Install 'pypdf' (or 'PyPDF2') to improve form field extraction. Add to requirements.txt")
    else:
        if fields:
            try:
                df = pd.DataFrame(list(fields.items()), columns=["field", "value"] )
                st.dataframe(df)
            except Exception:
                st.write(fields)
        else:
            st.info("No form fields detected in this PDF (or fields are not populated).")
