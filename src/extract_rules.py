import streamlit as st
import json
from pypdf import PdfReader
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
from typing import List

# --- 1. CONFIGURATION (Local vLLM) ---
VLLM_URL = "http://localhost:8000/v1"
MODEL_NAME = "google/gemma-2-9b-it"

# --- 2. DEFINE OUTPUT STRUCTURE ---
class Rule(BaseModel):
    id: str = Field(description="A unique ID like R1, R2")
    category: str = Field(description="Category: financial, temporal, eligibility, or verification")
    description: str = Field(description="A short human-readable summary of the rule")
    logic_hint: str = Field(description="A hint for the validator agent, e.g., 'requested_amount < total * 0.66'")

class PolicySchema(BaseModel):
    policy_name: str = Field(description="Name of the guideline")
    rules: List[Rule] = Field(description="List of extracted rules")

# --- 3. HELPER: EXTRACT TEXT FROM PDF ---
def get_pdf_text(uploaded_file):
    reader = PdfReader(uploaded_file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

# --- 4. THE EXTRACTION AGENT (With Gemma Fix) ---
def extract_rules_from_text(raw_text):
    # Initialize Local Model
    llm = ChatOpenAI(
        model=MODEL_NAME,
        openai_api_key="EMPTY",
        openai_api_base=VLLM_URL,
        temperature=0,
        max_tokens=4000
    )

    parser = JsonOutputParser(pydantic_object=PolicySchema)

    # --- PROMPT FIX FOR GEMMA-2 ---
    # We merge system instructions into the Human message to avoid 
    # "System role not supported" errors.
    instruction_text = """
    You are an Expert Legal Analyst. 
    Your task is to extract actionable rules from University Guidelines.
    
    Identify the following types of rules:
    1. Financial Limits (e.g., "max 2/3 coverage", "max 500 euros").
    2. Temporal Rules (e.g., "submit before travel", "reimbursement within 6 months").
    3. Eligibility (e.g., "active participation required", "students only").
    
    You must convert German phrases into logical hints.
    Example: "bis zu 2/3" -> "limit = total_cost * 0.66"
    Example: "vor Reiseantritt" -> "application_date < travel_start_date"
    
    {format_instructions}
    """

    prompt = ChatPromptTemplate.from_messages([
        ("human", instruction_text + "\n\nHere is the guideline text:\n\n{text}")
    ])

    chain = prompt | llm | parser

    # Invoke chain
    result = chain.invoke({
        "text": raw_text,
        "format_instructions": parser.get_format_instructions()
    })
    return result

# --- 5. STREAMLIT APP UI ---
def main():
    st.set_page_config(page_title="AI Policy Extractor", layout="wide")
    st.title("📄 AI Policy Rule Extractor")
    st.write(f"Connected to: `{MODEL_NAME}` at `{VLLM_URL}`")

    # File Uploader
    uploaded_file = st.file_uploader("Upload a Guideline PDF", type=["pdf"])

    if uploaded_file is not None:
        # Show file details
        st.info(f"File uploaded: {uploaded_file.name}")
        
        # Read PDF content
        with st.spinner("Reading PDF..."):
            pdf_text = get_pdf_text(uploaded_file)
            
        # Optional: Show a preview of extracted text
        with st.expander("View extracted raw text"):
            st.text(pdf_text[:1000] + "...")  # Show first 1000 chars

        # Button to Trigger AI
        if st.button("Extract Rules via AI"):
            try:
                with st.spinner("⏳ AI is analyzing and extracting rules..."):
                    extracted_data = extract_rules_from_text(pdf_text)
                
                # Success Message
                st.success("Analysis Complete!")
                
                # Display Results
                st.subheader("Extracted Rules JSON")
                st.json(extracted_data)

                # Option to download JSON
                json_str = json.dumps(extracted_data, indent=2, ensure_ascii=False)
                st.download_button(
                    label="Download JSON",
                    data=json_str,
                    file_name="extracted_rules.json",
                    mime="application/json"
                )

            except Exception as e:
                st.error(f"❌ Error during extraction: {e}")

if __name__ == "__main__":
    main()