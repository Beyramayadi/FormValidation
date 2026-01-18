import streamlit as st
import io
import pandas as pd
import numpy as np
import json
from typing import Dict, Any
from pdf_processor import PDFProcessor
from pdf_ocr_extractor import PDFOCRExtractor
import os
import hashlib
from datetime import datetime
from form_rules_validator import FormRulesValidator
from flag_manager import FlagManager
from web_verifier import WebVerifier

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
                    
                    # Build overridden field set for validation/web checks
                    fields_for_validation: Dict[str, Any] = {}
                    for k, v in fields.items():
                        fields_for_validation[k] = dict(v) if isinstance(v, dict) else v
                    if st.session_state.get('overrides'):
                        for fname, ov in st.session_state['overrides'].items():
                            if fname in fields_for_validation and isinstance(fields_for_validation[fname], dict):
                                fields_for_validation[fname]['value'] = ov['value']
                            else:
                                fields_for_validation[fname] = {'value': ov['value']}

                    # Run validation early to get missing field count (using overrides)
                    validator = FormRulesValidator()
                    validation_result = validator.validate(fields_for_validation)
                    flag_manager = FlagManager()

                    # Count missing fields from both df and validation flags
                    missing_field_flags = [f for f in validation_result.flags if f.flag_type.value == 'MISSING_FIELD']
                    total_missing = len(missing) + len(missing_field_flags)

                    # Section 1: Overview & KPIs
                    st.subheader("1) Overview & KPIs")
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("✅ Validated", len(validated))
                    with col2:
                        st.metric("⚠️ Needs Review", len(needs_review))
                    with col3:
                        st.metric("❌ Missing", total_missing)
                    with col4:
                        total_fields = len(df) + len(missing_field_flags)
                        validation_rate = (len(validated) / total_fields * 100) if total_fields else 0
                        st.metric("Validation Rate", f"{validation_rate:.1f}%")

                    col5, col6, col7, col8 = st.columns(4)
                    with col5:
                        validated_confidences = pd.to_numeric(validated['confidence'], errors='coerce').dropna()
                        avg_conf = validated_confidences.mean() if len(validated_confidences) > 0 else None
                        st.metric("Avg Confidence (Validated)", f"{avg_conf:.1f}%" if avg_conf is not None else "N/A")
                    with col6:
                        st.metric("Manual Overrides", len(st.session_state.get('overrides', {})))
                    with col7:
                        st.metric("Conflicts", int(df['conflicts'].sum()))
                    with col8:
                        st.metric("Threshold", f"{validation_threshold}%")

                    # Prepare status distribution for charts
                    status_counts = df['ui_status'].value_counts().reset_index()
                    status_counts.columns = ['status', 'count']

                    # PART 2b: Web search / plausibility validation (reuse overridden fields)
                    web_verifier = WebVerifier()
                    web_result = web_verifier.validate(fields_for_validation)

                    # Section 2: Visual Insights
                    st.subheader("2) Visual Insights")
                    try:
                        import altair as alt

                        col_chart_1, col_chart_2 = st.columns(2)
                        with col_chart_1:
                            if not status_counts.empty:
                                status_chart = alt.Chart(status_counts).mark_bar().encode(
                                    x=alt.X('status', sort=['validated', 'needs_review', 'missing']),
                                    y='count',
                                    color=alt.Color('status', legend=None)
                                ).properties(title='Field Status Distribution')
                                st.altair_chart(status_chart, use_container_width=True)
                        with col_chart_2:
                            combined_flags = validation_result.flags + web_result.flags
                            if combined_flags:
                                flag_df = pd.DataFrame([
                                    {
                                        'severity': f.severity.value,
                                        'origin': getattr(f, 'origin', 'rules')
                                    } for f in combined_flags
                                ])
                                severity_counts = flag_df.groupby('severity').size().reset_index(name='count')
                                pie = alt.Chart(severity_counts).mark_arc().encode(
                                    theta='count',
                                    color='severity',
                                    tooltip=['severity', 'count']
                                ).properties(title='Flags by Severity')
                                st.altair_chart(pie, use_container_width=True)

                        with st.expander("📋 Field Table (sortable)", expanded=False):
                            display_cols = ['field', 'value', 'ui_status', 'confidence', 'sources', 'conflicts']
                            st.dataframe(df[display_cols], use_container_width=True)
                    except Exception:
                        st.info("Charts unavailable (Altair not installed). Data table shown below.")
                        with st.expander("📋 Field Table (sortable)", expanded=False):
                            display_cols = ['field', 'value', 'ui_status', 'confidence', 'sources', 'conflicts']
                            st.dataframe(df[display_cols], use_container_width=True)

                    # Section 3: Correction Workbench
                    st.subheader("3) Correction Workbench")

                    # Business rules summary
                    if validation_result.error_count > 0 or validation_result.warning_count > 0:
                        st.warning(f"**{validation_result.summary}**")
                    else:
                        st.success(f"**{validation_result.summary}**")

                    # Display flags grouped by severity (business rules)
                    if validation_result.flags:
                        st.markdown("#### 🎯 Business Rules")
                        # Errors (highest priority)
                        error_flags = [f for f in validation_result.flags if f.severity.value == 'ERROR']
                        if error_flags:
                            st.subheader("🔴 Errors (Must Fix)")
                            for flag in error_flags:
                                with st.expander(f"❌ {flag.field_name or flag.related_fields}: {flag.issue}", expanded=True):
                                    col1, col2 = st.columns([3, 1])
                                    
                                    with col1:
                                        st.write(f"**Rule:** `{flag.rule}`")
                                        st.write(f"**Issue:** {flag.issue}")
                                        st.write(f"**Expected:** {flag.expected}")
                                        if flag.current_value:
                                            st.write(f"**Current Value:** `{flag.current_value}`")
                                        elif flag.current_values:
                                            for k, v in flag.current_values.items():
                                                st.write(f"**{k}:** `{v}`")
                                        
                                        if flag.suggested_fix:
                                            st.info(f"💡 **Suggested Fix:** {flag.suggested_fix}")
                                    
                                    with col2:
                                        # User action buttons for errors
                                        if flag.suggested_fix:
                                            if st.button("✅ Apply Fix", key=f"autofix_{flag.flag_id}"):
                                                flag_manager.process_user_action(flag, 'auto_fix', doc_hash=doc_hash)
                                                if flag.field_name:
                                                    st.session_state['overrides'][flag.field_name] = {
                                                        'value': flag.suggested_fix,
                                                        'approved': True,
                                                        'source': 'auto-fix-rule'
                                                    }
                                                st.toast(f"✅ Applied fix for {flag.field_name}")
                                                st.rerun()
                                        
                                        if st.button("✏️ Manual Fix", key=f"manual_{flag.flag_id}"):
                                            st.session_state[f'manual_edit_{flag.flag_id}'] = True
                                    
                                    # Manual edit input if selected
                                    if st.session_state.get(f'manual_edit_{flag.flag_id}'):
                                        new_val = st.text_input(
                                            f"Enter corrected value for {flag.field_name}:",
                                            key=f"input_{flag.flag_id}"
                                        )
                                        if st.button("Save Correction", key=f"save_manual_{flag.flag_id}"):
                                            flag_manager.process_user_action(
                                                flag, 'manual_correct', user_value=new_val, doc_hash=doc_hash
                                            )
                                            if flag.field_name:
                                                st.session_state['overrides'][flag.field_name] = {
                                                    'value': new_val,
                                                    'approved': True,
                                                    'source': 'manual-correct-rule'
                                                }
                                            st.toast(f"✅ Saved correction for {flag.field_name}")
                                            st.session_state[f'manual_edit_{flag.flag_id}'] = False
                                            st.rerun()
                        
                        # Warnings
                        warning_flags = [f for f in validation_result.flags if f.severity.value == 'WARNING']
                        if warning_flags:
                            st.subheader("🟡 Warnings (Should Review)")
                            for flag in warning_flags:
                                with st.expander(f"⚠️ {flag.field_name or flag.related_fields}: {flag.issue}"):
                                    st.write(f"**Rule:** `{flag.rule}`")
                                    st.write(f"**Issue:** {flag.issue}")
                                    st.write(f"**Expected:** {flag.expected}")
                                    if flag.current_value:
                                        st.write(f"**Current Value:** `{flag.current_value}`")
                                    
                                    col1, col2, col3 = st.columns(3)
                                    with col1:
                                        if st.button("✅ Accept", key=f"accept_{flag.flag_id}"):
                                            flag_manager.process_user_action(flag, 'accept', doc_hash=doc_hash)
                                            st.toast(f"✅ Accepted {flag.field_name}")
                                            st.rerun()
                                    with col2:
                                        if st.button("👁️ Dismiss", key=f"dismiss_{flag.flag_id}"):
                                            flag_manager.mark_as_dismissed(flag, doc_hash=doc_hash)
                                            st.toast(f"👁️ Dismissed flag for {flag.field_name}")
                                            st.rerun()
                                    with col3:
                                        if st.button("✏️ Correct", key=f"correct_{flag.flag_id}"):
                                            st.session_state[f'manual_edit_{flag.flag_id}'] = True
                                    
                                    if st.session_state.get(f'manual_edit_{flag.flag_id}'):
                                        new_val = st.text_input(
                                            f"Corrected value:",
                                            key=f"input_warn_{flag.flag_id}"
                                        )
                                        if st.button("Save", key=f"save_warn_{flag.flag_id}"):
                                            flag_manager.process_user_action(
                                                flag, 'manual_correct', user_value=new_val, doc_hash=doc_hash
                                            )
                                            if flag.field_name:
                                                st.session_state['overrides'][flag.field_name] = {
                                                    'value': new_val,
                                                    'approved': True,
                                                    'source': 'manual-correct-rule'
                                                }
                                            st.rerun()
                        
                        # Info flags
                        info_flags = [f for f in validation_result.flags if f.severity.value == 'INFO']
                        if info_flags:
                            st.subheader("🔵 Info (FYI)")
                            for flag in info_flags:
                                with st.expander(f"ℹ️ {flag.field_name}: {flag.issue}"):
                                    st.write(f"**Issue:** {flag.issue}")
                                    st.write(f"**Confidence:** {flag.confidence:.1%}")
                                    
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        if st.button("✅ OK", key=f"info_accept_{flag.flag_id}"):
                                            flag_manager.process_user_action(flag, 'accept', doc_hash=doc_hash)
                                            st.rerun()
                                    with col2:
                                        if st.button("👁️ Dismiss", key=f"info_dismiss_{flag.flag_id}"):
                                            flag_manager.mark_as_dismissed(flag, doc_hash=doc_hash)
                                            st.rerun()

                    # Web summary
                    if web_result.error_count > 0 or web_result.warning_count > 0:
                        st.warning(f"**{web_result.summary}**")
                    else:
                        st.success(f"**{web_result.summary}**")

                    # Display web flags grouped by severity
                    if web_result.flags:
                        st.markdown("#### 🌐 Web Search Results")
                        # Errors
                        web_errors = [f for f in web_result.flags if f.severity.value == 'ERROR']
                        if web_errors:
                            st.subheader("🔴 Web Errors (Must Fix)")
                            for flag in web_errors:
                                with st.expander(f"❌ {flag.field_name or flag.related_fields}: {flag.issue}", expanded=True):
                                    st.write(f"**Rule:** `{flag.rule}`")
                                    st.write(f"**Issue:** {flag.issue}")
                                    st.write(f"**Expected:** {flag.expected}")
                                    if flag.current_value:
                                        st.write(f"**Current Value:** `{flag.current_value}`")
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        if flag.suggested_fix and st.button("✅ Apply Fix", key=f"web_autofix_{flag.flag_id}"):
                                            flag_manager.process_user_action(flag, 'auto_fix', doc_hash=doc_hash)
                                            if flag.field_name:
                                                st.session_state['overrides'][flag.field_name] = {
                                                    'value': flag.suggested_fix,
                                                    'approved': True,
                                                    'source': 'auto-fix-web'
                                                }
                                            st.toast(f"✅ Applied fix for {flag.field_name}")
                                            st.rerun()
                                    with col2:
                                        if st.button("✏️ Manual Fix", key=f"web_manual_{flag.flag_id}"):
                                            st.session_state[f'web_manual_edit_{flag.flag_id}'] = True
                                    if st.session_state.get(f'web_manual_edit_{flag.flag_id}'):
                                        new_val = st.text_input(
                                            f"Enter corrected value for {flag.field_name}:",
                                            key=f"web_input_{flag.flag_id}"
                                        )
                                        if st.button("Save Correction", key=f"web_save_manual_{flag.flag_id}"):
                                            flag_manager.process_user_action(flag, 'manual_correct', user_value=new_val, doc_hash=doc_hash)
                                            if flag.field_name:
                                                st.session_state['overrides'][flag.field_name] = {
                                                    'value': new_val,
                                                    'approved': True,
                                                    'source': 'manual-correct-web'
                                                }
                                            st.toast(f"✅ Saved correction for {flag.field_name}")
                                            st.session_state[f'web_manual_edit_{flag.flag_id}'] = False
                                            st.rerun()

                        # Warnings
                        web_warnings = [f for f in web_result.flags if f.severity.value == 'WARNING']
                        if web_warnings:
                            st.subheader("🟡 Web Warnings (Review)")
                            for flag in web_warnings:
                                with st.expander(f"⚠️ {flag.field_name or flag.related_fields}: {flag.issue}"):
                                    st.write(f"**Rule:** `{flag.rule}`")
                                    st.write(f"**Issue:** {flag.issue}")
                                    st.write(f"**Expected:** {flag.expected}")
                                    if flag.current_value:
                                        st.write(f"**Current Value:** `{flag.current_value}`")
                                    col1, col2, col3 = st.columns(3)
                                    with col1:
                                        if st.button("✅ Accept", key=f"web_accept_{flag.flag_id}"):
                                            flag_manager.process_user_action(flag, 'accept', doc_hash=doc_hash)
                                            st.rerun()
                                    with col2:
                                        if st.button("👁️ Dismiss", key=f"web_dismiss_{flag.flag_id}"):
                                            flag_manager.mark_as_dismissed(flag, doc_hash=doc_hash)
                                            st.rerun()
                                    with col3:
                                        if st.button("✏️ Correct", key=f"web_correct_{flag.flag_id}"):
                                            st.session_state[f'web_manual_edit_{flag.flag_id}'] = True
                                    if st.session_state.get(f'web_manual_edit_{flag.flag_id}'):
                                        new_val = st.text_input("Corrected value:", key=f"web_input_warn_{flag.flag_id}")
                                        if st.button("Save", key=f"web_save_warn_{flag.flag_id}"):
                                            flag_manager.process_user_action(flag, 'manual_correct', user_value=new_val, doc_hash=doc_hash)
                                            if flag.field_name:
                                                st.session_state['overrides'][flag.field_name] = {
                                                    'value': new_val,
                                                    'approved': True,
                                                    'source': 'manual-correct-web'
                                                }
                                            st.rerun()

                        # Info
                        web_infos = [f for f in web_result.flags if f.severity.value == 'INFO']
                        if web_infos:
                            st.subheader("🔵 Web Info (FYI)")
                            for flag in web_infos:
                                with st.expander(f"ℹ️ {flag.field_name}: {flag.issue}"):
                                    st.write(f"**Issue:** {flag.issue}")
                                    st.write(f"**Confidence:** {flag.confidence:.1%}")
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        if st.button("✅ OK", key=f"web_info_ok_{flag.flag_id}"):
                                            flag_manager.process_user_action(flag, 'accept', doc_hash=doc_hash)
                                            st.rerun()
                                    with col2:
                                        if st.button("👁️ Dismiss", key=f"web_info_dismiss_{flag.flag_id}"):
                                            flag_manager.mark_as_dismissed(flag, doc_hash=doc_hash)
                                            st.rerun()
                    
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
                
                # Include ALL fields from the original extraction, including empty/missing ones
                final_json = {}
                if isinstance(fields, dict):
                    # Add all fields from the extraction (including those with None/empty values)
                    for field_name, field_info in fields.items():
                        if isinstance(field_info, dict):
                            value = field_info.get('value')
                            # Convert None to empty string
                            final_json[field_name] = "" if value is None else value
                        else:
                            # Convert None to empty string
                            final_json[field_name] = "" if field_info is None else field_info
                    
                    # Apply overrides from corrections/approvals
                    if st.session_state.get('overrides'):
                        for fname, override in st.session_state['overrides'].items():
                            final_json[fname] = override['value']
                else:
                    # Fallback to dataframe-based approach
                    final_json = {str(r['field']): ("" if r['value'] is None else r['value']) for _, r in final_df.iterrows()}
                
                st.json(final_json)

                # Auto-save corrected PDF with overrides applied (server copy)
                corrected_pdf = None
                if st.session_state.get('overrides'):
                    corrected_pdf = pdf.save_with_overrides(st.session_state['overrides'])
                    if corrected_pdf and doc_hash:
                        os.makedirs("data/corrected", exist_ok=True)
                        corrected_path = os.path.join("data", "corrected", f"{doc_hash}_corrected.pdf")
                        try:
                            with open(corrected_path, "wb") as f_out:
                                f_out.write(corrected_pdf)
                            st.success(f"💾 Corrected PDF saved to {corrected_path}")
                        except Exception as ex:
                            st.warning(f"Could not save corrected PDF: {ex}")
                    else:
                        st.caption("PDF save unavailable (no overrides or writer missing).")

                # Download corrected PDF
                if corrected_pdf:
                    st.download_button(
                        label="💾 Download corrected PDF",
                        data=corrected_pdf,
                        file_name="corrected.pdf",
                        mime="application/pdf"
                    )
                else:
                    st.info("Download appears after you apply a correction/override (PDF writer must be available).")

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
                
                # Export options (use final values with all fields)
                st.subheader("💾 Export Data")
                col1, col2 = st.columns(2)
                with col1:
                    # Export as JSON (use the same final_json that includes all fields)
                    st.download_button(
                        label="📥 Download as JSON",
                        data=json.dumps(final_json, ensure_ascii=False, indent=2),
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
