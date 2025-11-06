# Quick Start Guide

## First Time Setup

1. **Set up your environment file**
   ```bash
   # Copy the example file
   copy .env.example .env
   
   # Edit .env and add your OpenAI API key
   notepad .env
   ```

2. **Activate your virtual environment**
   ```bash
   .\venv\Scripts\activate
   ```

3. **Install/Update dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

From the project root directory:

```bash
# Make sure virtual environment is activated
.\venv\Scripts\activate

# Run the Streamlit app
streamlit run src/app.py
```

The application will open in your browser at `http://localhost:8501`

## Common Issues

### Import Errors
If you see import errors, make sure:
- Virtual environment is activated
- All dependencies are installed: `pip install -r requirements.txt`
- You're running from the project root directory

### Module Not Found
If Python can't find the modules, you have two options:

**Option 1: Run from project root (recommended)**
```bash
cd c:\Users\moham\Rami\Ai-Form-Agent
streamlit run src/app.py
```

**Option 2: Add src to PYTHONPATH**
```bash
$env:PYTHONPATH = "c:\Users\moham\Rami\Ai-Form-Agent\src"
streamlit run src/app.py
```

### OpenAI API Errors
Make sure:
- `.env` file exists in the project root
- `OPENAI_API_KEY` is set correctly in `.env`
- No quotes around the API key value

## Development Workflow

1. Always activate the virtual environment first
2. Make changes to files in `src/` directory
3. Test your changes
4. Commit your changes (venv/ is excluded via .gitignore)

## Git Commands

```bash
# Check status
git status

# Add changes
git add .

# Commit
git commit -m "Your message"

# Push to remote
git push origin feat/extraction-rami
```
