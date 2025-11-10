import streamlit as st
import io
import pandas as pd
import numpy as np
import json
from pdf_processor import PDFProcessor
from pdf_ocr_extractor import PDFOCRExtractor
import os
import hashlib
from datetime import datetime

st.set_page_config(page_title="AI Form Agent", page_icon="📄", layout="wide")

st.title("📄 AI Form Agent")
st.markdown("Upload a PDF form to extract and validate field information with AI assistance.")

uploaded_file = st.file_uploader("Upload a PDF form", type=["pdf"])

if uploaded_file:
    # Read bytes once and reuse for both text extraction and field extraction
    file_bytes = uploaded_file.read()
    
    # Create PDF processor instance
    pdf = PDFProcessor(file_bytes)
    # Compute a simple identifier for this document (for feedback)
    doc_hash = hashlib.md5(file_bytes).hexdigest() if file_bytes else None
    # Initialize session state for manual approvals/corrections
    if 'overrides' not in st.session_state:
        st.session_state['overrides'] = {}
    st.session_state['current_doc'] = doc_hash
    
    # Auto-load previous feedback on startup
    feedback_dir = os.path.join("data")
    feedback_path = os.path.join(feedback_dir, "feedback.csv")
    if 'feedback_loaded' not in st.session_state:
        st.session_state['feedback_loaded'] = False
    
    if not st.session_state['feedback_loaded'] and os.path.exists(feedback_path):
        try:
            hist = pd.read_csv(feedback_path)
            if not hist.empty:
                # Get latest correction for each field
                latest = hist.sort_values('timestamp').drop_duplicates(subset=['field'], keep='last')
                for _, rec in latest.iterrows():
                    fname = str(rec['field'])
                    st.session_state['overrides'][fname] = {
                        'value': rec['final_value'],
                        'approved': True,
                        'source': 'auto-loaded'
                    }
                st.session_state['feedback_loaded'] = True
        except Exception:
            pass

    # Removed: Visible text preview, Found Button Fields, and Debug Information panels
            
    # Extraction Settings
    with st.expander("⚙️ Extraction Settings", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            use_llm = st.checkbox("🤖 Use AI-Enhanced Extraction", value=False,
                                 help="Use GPT-4o to improve field extraction accuracy")
        with col2:
            use_validation = st.checkbox("✅ Use Multi-Source Validation", value=True,
                                       help="Cross-validate fields from multiple sources")
        with col3:
            validation_threshold = st.slider(
                "Validation threshold (%)",
                min_value=50,
                max_value=99,
                value=85,
                help="Fields at or above this confidence count as validated in the UI"
            )
    
    # Extract form fields
    st.subheader("📝 Form Fields")
    
    # Get form fields with optional LLM enhancement and validation
    try:
        fields, error_message = pdf.get_form_fields(use_llm=use_llm, use_validation=use_validation)
        
        # Display error/warning messages
        if error_message:
            if "⚠️" in error_message:
                st.warning(error_message)
            else:
                st.error(error_message)
    except Exception as e:
        st.error(f"Error getting form fields: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
        fields = None

    if fields:
        try:
            # Create a clean list of field values
            field_data = []
            
            for field_name, field_info in fields.items():
                # Handle both old and new format
                if isinstance(field_info, dict):
                    # New validated format
                    field_data.append({
                        "field": field_name,
                        "value": field_info.get("value"),
                        "type": field_info.get("type", "text"),
                        "confidence": field_info.get('confidence'),
                        "status": field_info.get('status', 'unknown'),
                        "sources": field_info.get('sources', 1),
                        "conflicts": len(field_info.get('conflicts', [])),
                        "notes": field_info.get('notes', [])
                    })
                else:
                    # Old format
                    clean_value = str(field_info).strip('/')
                    if clean_value and clean_value.lower() not in ['off', 'null', '']:
                        field_data.append({
                            "field": field_name,
                            "value": clean_value,
                            "type": "auto",
                            "confidence": None,
                            "status": "unknown",
                            "sources": 1,
                            "conflicts": 0,
                            "notes": []
                        })
            
            # Convert to dataframe and sort
            if field_data:
                df = pd.DataFrame(field_data)
                df = df.sort_values('field')
                
                # Apply saved corrections/approvals to the dataframe BEFORE displaying
                if st.session_state.get('overrides'):
                    for i, r in df.iterrows():
                        fname = str(r['field'])
                        if fname in st.session_state['overrides']:
                            df.at[i, 'value'] = st.session_state['overrides'][fname]['value']
                            df.at[i, 'status'] = 'validated'
                            df.at[i, 'confidence'] = 100  # High confidence for manual overrides
                
                # Compute UI status using threshold (without changing backend statuses)
                conf_series = pd.to_numeric(df['confidence'], errors='coerce').fillna(0)
                df['ui_status'] = np.where(
                    df['status'] == 'missing',
                    'missing',
                    np.where(conf_series >= validation_threshold, 'validated', 'needs_review')
                )

                # Separate fields by status if using validation
                if use_validation:
                    validated = df[df['ui_status'] == 'validated']
                    needs_review = df[df['ui_status'] == 'needs_review']
                    missing = df[df['ui_status'] == 'missing']
                    
                    # Show summary metrics
                    st.subheader("📊 Validation Summary")
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric("✅ Validated", len(validated))
                    with col2:
                        st.metric("⚠️ Needs Review", len(needs_review))
                    with col3:
                        st.metric("❌ Missing", len(missing))
                    with col4:
                        # Average confidence of validated fields only (meets threshold)
                        validated_confidences = validated['confidence'].dropna()
                        validated_confidences = pd.to_numeric(validated_confidences, errors='coerce').dropna()
                        if len(validated_confidences) > 0:
                            avg_conf = validated_confidences.mean()
                            st.metric("Avg Confidence (Validated)", f"{avg_conf:.1f}%")
                        else:
                            st.metric("Avg Confidence (Validated)", "N/A")
                    
                    # Display validated fields
                    if not validated.empty:
                        st.subheader("✅ Validated Fields")
                        st.dataframe(
                            validated[['field', 'value', 'type', 'confidence', 'sources']],
                            hide_index=True,
                            column_config={
                                "confidence": st.column_config.ProgressColumn(
                                    "Confidence",
                                    help="Confidence in the extracted value",
                                    format="%d%%",
                                    min_value=0,
                                    max_value=100,
                                ),
                                "sources": st.column_config.NumberColumn(
                                    "Sources",
                                    help="Number of extraction sources that provided this value",
                                    format="%d"
                                )
                            }
                        )
                    
                    # Display fields needing review
                    if not needs_review.empty:
                        st.subheader("⚠️ Fields Needing Review")
                        for idx, row in needs_review.iterrows():
                            field_name = str(row['field'])
                            field_key = ''.join(ch if ch.isalnum() else '_' for ch in field_name)
                            with st.expander(f"🔍 {field_name} = {row['value']} (Confidence: {row['confidence']}%)"):
                                st.write("**Status:**", row['status'])
                                st.write("**Sources:**", row['sources'])
                                # Show per-source values if available
                                details = fields.get(field_name, {}) if isinstance(fields, dict) else {}
                                source_details = details.get('source_details') if isinstance(details, dict) else None
                                if source_details:
                                    st.caption("Source details:")
                                    st.dataframe(
                                        pd.DataFrame(source_details),
                                        hide_index=True,
                                    )
                                if row['conflicts'] > 0:
                                    st.warning(f"⚠️ {row['conflicts']} conflict(s) detected")
                                if row['notes']:
                                    st.info("**Validation Notes:**")
                                    for note in row['notes']:
                                        st.write(f"• {note}")

                                # Show current override (if any)
                                if field_name in st.session_state['overrides']:
                                    ov = st.session_state['overrides'][field_name]
                                    st.success(f"Approved value: {ov.get('value')} (manual)")

                                # Allow manual correction or approval
                                corrected_value = st.text_input(
                                    f"Correct value for {field_name}", 
                                    value=str(row['value']) if row['value'] else "",
                                    key=f"correct_{field_key}"
                                )
                                col_appr, col_save = st.columns(2)
                                with col_appr:
                                    if st.button("Approve as-is", key=f"approve_{field_key}"):
                                        st.session_state['overrides'][field_name] = {
                                            'value': str(row['value']) if row['value'] is not None else "",
                                            'approved': True,
                                            'source': 'manual-approve'
                                        }
                                        # Auto-save to feedback immediately
                                        try:
                                            os.makedirs(feedback_dir, exist_ok=True)
                                            now = datetime.utcnow().isoformat()
                                            orig = df[df['field'] == field_name]
                                            orig_val = orig.iloc[0]['value'] if not orig.empty else None
                                            orig_status = orig.iloc[0]['status'] if ('status' in orig.columns and not orig.empty) else None
                                            orig_conf = orig.iloc[0]['confidence'] if ('confidence' in orig.columns and not orig.empty) else None
                                            fb_row = pd.DataFrame([{
                                                'doc_hash': doc_hash,
                                                'field': field_name,
                                                'original_value': orig_val,
                                                'final_value': str(row['value']) if row['value'] is not None else "",
                                                'approved': True,
                                                'status_before': orig_status,
                                                'confidence': orig_conf,
                                                'timestamp': now
                                            }])
                                            fb_row.to_csv(feedback_path, mode='a', header=not os.path.exists(feedback_path), index=False)
                                        except Exception:
                                            pass
                                        st.toast(f"✅ Approved and saved {field_name}")
                                        st.rerun()
                                with col_save:
                                    if st.button("Save correction", key=f"save_{field_key}"):
                                        st.session_state['overrides'][field_name] = {
                                            'value': corrected_value,
                                            'approved': True,
                                            'source': 'manual-correct'
                                        }
                                        # Auto-save to feedback immediately
                                        try:
                                            os.makedirs(feedback_dir, exist_ok=True)
                                            now = datetime.utcnow().isoformat()
                                            orig = df[df['field'] == field_name]
                                            orig_val = orig.iloc[0]['value'] if not orig.empty else None
                                            orig_status = orig.iloc[0]['status'] if ('status' in orig.columns and not orig.empty) else None
                                            orig_conf = orig.iloc[0]['confidence'] if ('confidence' in orig.columns and not orig.empty) else None
                                            fb_row = pd.DataFrame([{
                                                'doc_hash': doc_hash,
                                                'field': field_name,
                                                'original_value': orig_val,
                                                'final_value': corrected_value,
                                                'approved': True,
                                                'status_before': orig_status,
                                                'confidence': orig_conf,
                                                'timestamp': now
                                            }])
                                            fb_row.to_csv(feedback_path, mode='a', header=not os.path.exists(feedback_path), index=False)
                                        except Exception:
                                            pass
                                        st.toast(f"✅ Saved correction for {field_name}")
                                        st.rerun()
                    
                    # Display missing fields
                    if not missing.empty:
                        st.subheader("❌ Missing Required Fields")
                        st.error("The following required fields were not found:")
                        for idx, row in missing.iterrows():
                            st.write(f"• **{row['field']}** ({row['type']})")
                
                else:
                    # Display without validation status
                    st.dataframe(
                        df[['field', 'value', 'type', 'confidence']],
                        hide_index=True,
                        column_config={
                            "confidence": st.column_config.ProgressColumn(
                                "Confidence",
                                help="Confidence in the extracted value",
                                format="%d%%",
                                min_value=0,
                                max_value=100,
                            )
                        }
                    )
                
                # Build final output by applying overrides (approvals/corrections)
                st.subheader("✅ Final Output (with approvals/corrections)")
                final_df = df.copy()
                if st.session_state.get('overrides'):
                    for i, r in final_df.iterrows():
                        fname = str(r['field'])
                        if fname in st.session_state['overrides']:
                            final_df.at[i, 'value'] = st.session_state['overrides'][fname]['value']
                            final_df.at[i, 'status'] = 'validated'
                            final_df.at[i, 'ui_status'] = 'validated'
                final_json = {str(r['field']): r['value'] for _, r in final_df.iterrows()}
                st.json(final_json)

                # Feedback & learning status
                with st.expander("🧠 Feedback & Learning"):
                    st.caption("Corrections are automatically saved and applied on next upload.")
                    if os.path.exists(feedback_path):
                        try:
                            hist = pd.read_csv(feedback_path)
                            total_corrections = len(hist)
                            unique_fields = hist['field'].nunique()
                            st.info(f"📊 {total_corrections} total corrections saved for {unique_fields} unique field(s).")
                            
                            if st.button("Clear all saved feedback"):
                                os.remove(feedback_path)
                                st.session_state['overrides'] = {}
                                st.session_state['feedback_loaded'] = False
                                st.success("Cleared all feedback. Reload the page.")
                        except Exception as ex:
                            st.warning(f"Could not read feedback: {ex}")
                    else:
                        st.info("No saved feedback yet. Approve or correct fields above to start learning.")

                # Show statistics (threshold-aware)
                st.subheader("📊 Statistics")
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Total Extracted Fields", len(field_data))
                with col2:
                    # High confidence = fields meeting the validation threshold
                    st.metric("High Confidence (≥threshold)", len(validated))
                with col3:
                    # Average of validated fields (same as summary above)
                    validated_confidences = validated['confidence'].dropna()
                    validated_confidences = pd.to_numeric(validated_confidences, errors='coerce').dropna()
                    if len(validated_confidences) > 0:
                        avg_conf = validated_confidences.mean()
                        st.metric("Avg Confidence (Validated)", f"{avg_conf:.1f}%")
                    else:
                        st.metric("Avg Confidence (Validated)", "N/A")
                
                # Export options (use final values)
                st.subheader("💾 Export Data")
                col1, col2 = st.columns(2)
                with col1:
                    # Export as JSON
                    export_data = {str(r['field']): r['value'] for _, r in final_df.iterrows()}
                    st.download_button(
                        label="📥 Download as JSON",
                        data=json.dumps(export_data, ensure_ascii=False, indent=2),
                        file_name="extracted_fields.json",
                        mime="application/json"
                    )
                with col2:
                    # Export as CSV
                    csv = final_df[['field', 'value', 'type', 'confidence']].to_csv(index=False)
                    st.download_button(
                        label="📥 Download as CSV",
                        data=csv,
                        file_name="extracted_fields.csv",
                        mime="text/csv"
                    )
            else:
                st.info("No populated form fields found in this PDF.")
        except Exception as e:
            st.error(f"Error processing form fields: {str(e)}")
            import traceback
            st.error("Stack trace:")
            st.code(traceback.format_exc())
    else:
        st.info("No form fields detected in this PDF.")

    # OCR extraction section
    st.subheader("🔍 OCR Text Extraction (Tesseract)")
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
