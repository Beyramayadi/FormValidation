# AI Form Agent 🤖📄

An intelligent PDF form extraction tool powered by AI that extracts text, form fields, checkboxes, and structured data from PDF documents.

## Features

- 📝 Extract visible text from PDFs
- ✅ Detect and extract checkbox/radio button states
- 🔍 OCR support for scanned documents (Tesseract)
- 🤖 AI-enhanced field extraction using OpenAI GPT-4
- 📊 Interactive web interface built with Streamlit
- 🎯 Confidence scoring for extracted values

## Project Structure

```
Ai-Form-Agent/
├── src/                    # Source code
│   ├── app.py              # Main Streamlit application
│   ├── pdf_processor.py    # PDF processing and field extraction
│   ├── pdf_ocr_extractor.py # OCR-based text extraction
│   └── llm_processor.py    # LLM-enhanced extraction
├── tests/                  # Unit tests
├── data/                   # Sample PDFs and test data
├── docs/                   # Additional documentation
├── venv/                   # Virtual environment (not committed)
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variables template
└── README.md              # This file
```

## Prerequisites

- Python 3.8 or higher
- Tesseract OCR (for OCR functionality)
- OpenAI API key (for AI-enhanced extraction)

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Beyramayadi/FormValidation.git
   cd Ai-Form-Agent
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   ```

3. **Activate the virtual environment**
   - Windows:
     ```bash
     .\venv\Scripts\activate
     ```
   - macOS/Linux:
     ```bash
     source venv/bin/activate
     ```

4. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Set up environment variables**
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` and add your OpenAI API key.

6. **Install Tesseract OCR** (Optional, for OCR features)
   - Windows: Download from [GitHub](https://github.com/UB-Mannheim/tesseract/wiki)
   - macOS: `brew install tesseract`
   - Linux: `sudo apt-get install tesseract-ocr`

## Usage

1. **Start the Streamlit application**
   ```bash
   streamlit run src/app.py
   ```

2. **Open your browser** and navigate to `http://localhost:8501`

3. **Upload a PDF** form and explore the extracted data

## Features in Detail

### Standard Extraction
- Extracts visible text using `pdfplumber`
- Identifies form fields and their values
- Detects checkbox and radio button states

### AI-Enhanced Extraction
Enable the "Use AI-Enhanced Extraction" checkbox to:
- Improve field detection accuracy
- Clean and normalize field values
- Assign confidence scores to extracted data
- Handle complex or poorly formatted forms

### OCR Extraction
Automatically extracts text from scanned PDFs or images within PDFs using Tesseract OCR.

## Development

### Running Tests
```bash
pytest tests/
```

### Code Style
This project follows PEP 8 guidelines. Format code with:
```bash
black src/
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built with [Streamlit](https://streamlit.io/)
- PDF processing with [pdfplumber](https://github.com/jsvine/pdfplumber) and [PyPDF](https://github.com/py-pdf/pypdf)
- OCR powered by [Tesseract](https://github.com/tesseract-ocr/tesseract)
- AI features powered by [OpenAI](https://openai.com/)

## Support

For issues, questions, or contributions, please open an issue on GitHub.
