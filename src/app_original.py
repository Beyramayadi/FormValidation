import streamlit as st
import io
import pandas as pd
import numpy as np
import json
from pdf_processor import PDFProcessor
from pdf_ocr_extractor import PDFOCRExtractor

st.title("AI Form Agent")

uploaded_file = st.file_uploader("Upload a PDF form", type=["pdf"])

if uploaded_file:
    # Read bytes once and reuse for both text extraction and field extraction
    file_bytes = uploaded_file.read()
    
    # Create PDF processor instance
    pdf = PDFProcessor(file_bytes)

    st.subheader("Extracted Content")
    
    # Display regular text
    text = pdf.extract_text()
    st.text_area("Visible Text", text if text else "(no visible text extracted)", height=200)
    
    # Create a dropdown for button field debug info
    with st.expander("🔍 Found Button Fields"):
        # Get all buttons from the PDF
        found_buttons = pdf.get_all_buttons()
        
        # Display the found buttons
        if found_buttons:
            for btn in found_buttons:
                with st.container():
                    status = "✅ CHECKED" if btn['is_checked'] else "❌ UNCHECKED"
                    st.markdown(f"**Button on Page {btn['page']}** - {status}")
                    
                    # Prepare the code block content
                    code_content = [
                        f"Name: {btn['name']}",
                        f"Title: {btn['title']}",
                        f"Value: {btn['value']}",
                        f"State: {btn['state']}"
                    ]
                    
                    # Add parent info if exists
                    if btn['parent']:
                        code_content.append(f"Parent: {btn['parent']}")
                        
                    st.code("\n".join(code_content))
        else:
            st.info("No button fields found in this PDF.")

    # Debug panel to show raw PDF data
    with st.expander("🔍 Debug Information (Raw PDF Data)"):
        # Display PDF metadata
        st.write("PDF Basic Info:")
        metadata = pdf.get_metadata()
        if metadata:
            st.json(metadata)
        else:
            st.info("No metadata found")
            
        # Display form fields
        st.write("Form Fields (Raw):")
        form_fields = pdf.get_form_fields()
        if form_fields:
            st.json(form_fields)
        else:
            st.info("No form fields found via get_fields()")
            
        # Display XFA check
        st.write("XFA Form Check:")
        if pdf.is_xfa_form():
            st.warning("⚠️ This appears to be an XFA form - different parsing may be needed")
        else:
            st.info("Not an XFA form")
            
    # Extract form fields (AcroForm/widget values)
    st.subheader("Form field values (if present)")
    
    # Add toggle for LLM-enhanced extraction
    use_llm = st.checkbox("Use AI-Enhanced Extraction", value=False,
                         help="Use AI to improve field extraction accuracy")
    
    # Get form fields with optional LLM enhancement
    fields, error_message = pdf.get_form_fields(use_llm=use_llm)
    
    # Display error message if AI extraction fails
    if use_llm and error_message:
        st.error(f"An error occurred during AI-enhanced extraction: {error_message}")

    if fields:
        try:
            # Create a clean list of field values
            field_data = []
            
            for field_name, field_info in fields.items():
                # Handle both old and new format
                if isinstance(field_info, dict):
                    # New LLM format
                    field_data.append({
                        "field": field_name,
                        "value": field_info["value"],
                        "type": field_info["type"],
                        "confidence": field_info['confidence']
                    })
                else:
                    # Old format
                    clean_value = str(field_info).strip('/')
                    if clean_value and clean_value.lower() not in ['off', 'null', '']:
                        field_data.append({
                            "field": field_name,
                            "value": clean_value,
                            "type": "auto",
                            "confidence": None
                        })
            
            # Convert to dataframe and sort
            if field_data:
                df = pd.DataFrame(field_data)
                df = df.sort_values('field')
                
                # Display the dataframe with conditional formatting
                st.dataframe(
                    df,
                    hide_index=True,
                    column_config={
                        "confidence": st.column_config.ProgressColumn(
                            "Confidence",
                            help="AI confidence in the extracted value",
                            format="%d%%",
                            min_value=0,
                            max_value=100,
                        ),
                        "type": st.column_config.SelectboxColumn(
                            "Field Type",
                            help="Type of form field",
                            options=["text", "checkbox", "radio", "date", "address", "auto"],
                            required=True,
                        )
                    }
                )
                
                # Show statistics if using LLM
                if use_llm:
                    st.subheader("Extraction Statistics")
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Total Fields", len(field_data))
                    with col2:
                        high_conf = sum(1 for f in field_data if isinstance(f["confidence"], int) and f["confidence"] >= 90)
                        st.metric("High Confidence Fields", high_conf)
                    with col3:
                        # Calculate average confidence only if we have valid confidence values
                        confidences = [f["confidence"] for f in field_data if isinstance(f["confidence"], int)]
                        if confidences:
                            avg_conf = np.mean(confidences)
                            st.metric("Average Confidence", f"{avg_conf:.1f}%")
                            # Display a warning if average confidence is low
                            if avg_conf < 70:
                                st.warning(f"The average AI confidence of {avg_conf:.1f}% is low. Please double-check the extracted values.")
                        else:
                            st.metric("Average Confidence", "N/A")
            else:
                st.info("No populated form fields found in this PDF.")
        except Exception as e:
            st.error(f"Error processing form fields: {str(e)}")
            st.error("Stack trace:", exception=e)
    else:
        st.info("No form fields detected in this PDF.")
    
    # OCR extraction section
    st.subheader("OCR Text Extraction (Tesseract)")
    if uploaded_file:
        try:
            ocr_extractor = PDFOCRExtractor(file_bytes)
            ocr_json = ocr_extractor.structure_as_json()
            st.json(ocr_json)
            # Optionally, allow user to download the JSON
            st.download_button(
                label="Download OCR JSON",
                data=json.dumps(ocr_json, ensure_ascii=False, indent=2),
                file_name="ocr_text.json",
                mime="application/json"
            )
        except Exception as e:
            st.warning(
                "⚠️ OCR feature is not available. Tesseract OCR is not installed.\n\n"
                "To enable OCR functionality:\n"
                "1. Download Tesseract from: https://github.com/UB-Mannheim/tesseract/wiki\n"
                "2. Install it and add to your system PATH\n"
                "3. Or set the path in your .env file\n\n"
                f"Error: {str(e)}"
            )
