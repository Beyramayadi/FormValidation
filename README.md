# FormValidation — PDF extraction approaches

This repository contains two alternative approaches for extracting structured data from PDF forms:

- OCR-based extraction using Tesseract + OpenCV: `OCRextration.py`
- Vision-Language Model (VLM) extraction using a local Ollama VLM: `VLMextraction.py`

The README below explains how each approach works, required setup, how to run them, trade-offs, and troubleshooting tips.

## Quick summary

Both scripts take a PDF file (configuration via `pdf_file_path`) and attempt to produce:

{
"key_value_pairs": { "Label": "Value", ... },
"checked_items": ["Label for checked box", ...]
}

Choose the OCR approach for fully local, deterministic extraction where you control thresholds and post-processing. Choose the VLM approach when you have a capable local VLM (via Ollama) and want the model to infer layout/handwriting/semantic matches with fewer heuristics.

---

## 1) OCR-based extraction — `OCRextration.py`

What it does

- Converts PDF pages to images using `pdf2image` (Poppler required).
- Preprocesses images with OpenCV (grayscale + adaptive thresholding).
- Runs Tesseract OCR (`pytesseract.image_to_data`) to obtain word-level boxes and confidences.
- Attempts to pair labels and values by looking for words on the same horizontal line to the right (`find_key_value_pairs`).
- Detects square contours likely to be checkboxes and determines whether they are checked by computing the fill percentage inside the box; links checked boxes to the closest OCR text (`find_checkboxes`).
- Produces and prints a JSON object with `key_value_pairs` and `checked_items` for each page.

Contract

- Input: configured `pdf_file_path` (edit top of script). Also set `poppler_bin_path` and (optionally) `pytesseract.pytesseract.tesseract_cmd` on Windows.
- Output: Printed JSON structure (and accessible in the `final_results` dict inside the script). Format shown above.
- Error modes: File not found, Poppler missing/incorrect path, Tesseract not installed or not found.

Key implementation details

- `preprocess_image(image)` — converts PIL image to OpenCV format; returns adaptive-thresholded binary image (for contour detection) and color image (for OCR).
- `find_key_value_pairs(ocr_data)` — uses Tesseract's box coordinates and confidences to match keys and values by horizontal proximity (skips low-confidence words <50).
- `find_checkboxes(binary_image, ocr_data)` — finds square contours (approx poly with 4 vertices, near-square aspect ratio and within pixel size limits), computes fill percentage to decide if checked (>20%), then matches to nearest OCR text based on Euclidean distance.
- Language setting used: `lang='eng+deu'` (adjust as needed).

Dependencies and setup

- Python packages (install via pip):

  - pytesseract
  - opencv-python
  - numpy
  - pdf2image

- External dependencies:
  - Tesseract OCR installed and accessible (or set `pytesseract.pytesseract.tesseract_cmd` to its path).
  - Poppler binaries (set `poppler_bin_path` on Windows) for `pdf2image`.

Run (PowerShell)

```powershell
# Edit the top of OCRextration.py to set `pdf_file_path` and `poppler_bin_path` (and Tesseract path if needed)
python OCRextration.py
```

When to use

- When you need a fully local, deterministic pipeline.
- When you want control over heuristic thresholds and can tune for the specific form layout.

Strengths

- No ML model server required; deterministic and debuggable.
- Checkbox detection implemented with contour heuristics.

Limitations

- Heuristics can fail for unusual layouts, rotated text, complex tables, or handwritten fields.
- Key/value pairing only looks for horizontal proximity by default; vertical-label-above-value patterns may be missed.
- Sensitive to OCR quality; requires tuning confidence thresholds and preprocessing.

Suggested improvements

- Merge OCR words into line-level or block-level boxes (to handle multi-word labels/values).
- Use layout-aware models (LayoutLM, Donut, or specialized table parsers) for complex forms.
- Add handwriting-specific OCR or a classifier to refine handwritten vs typed values.

---

## 2) VLM (Vision-Language Model) extraction — `VLMextraction.py`

What it does

- Converts the target PDF page to an image (PNG) using `pdf2image`.
- Encodes the image as base64.
- Sends the image plus a carefully-crafted prompt to a local Ollama VLM (e.g., `llava-phi3:3.8b`) via the `ollama` Python client.
- Requests the VLM to return ONLY a JSON object containing `key_value_pairs` and `checked_items`.
- Parses and prints the returned JSON.

Contract

- Input: configured `pdf_file_path`, `poppler_bin_path`, and `model` name in the call to `ollama.chat`.
- Output: printed JSON as described earlier.
- Error modes: failure to convert PDF, Ollama not running, model not loaded, or VLM returning invalid/non-JSON text.

Key implementation details

- `pdf_page_to_base64(pdf_path, page_num=0, poppler_path=None)` — converts one page to PNG and base64-encodes it for the Ollama API.
- The prompt instructs the VLM to extract both key/value pairs and checked boxes and to respond only with a strict JSON object. The code attempts to `json.loads` the response and prints it; otherwise it prints raw output for debugging.
- Uses `ollama.chat(..., format='json')` and passes image data in `messages[0]['images']`.

Dependencies and setup

- Python packages (install via pip):

  - `ollama` (the Ollama Python client)
  - `pdf2image`

- External dependencies:
  - Poppler (set `poppler_bin_path` on Windows).
  - Ollama application installed and running locally with a VLM model that supports images (e.g., an Llava-type model). Ensure the model name used in the script (e.g., `llava-phi3:3.8b`) is installed/available.

Run (PowerShell)

```powershell
# Make sure Ollama is installed and running with the required model
# Edit `pdf_file_path` and `poppler_bin_path` at the top of VLMextraction.py
python VLMextraction.py
```

When to use

- When you have a capable local VLM and want the model to do semantic interpretation, handle handwriting, or infer labels that are not strictly horizontally aligned.

Strengths

- Can handle complex layouts, vertical label/value pairs, handwriting, and semantic inference.
- Fewer hand-coded heuristics; the model uses learned knowledge.

Limitations

- Requires a local VLM runtime (Ollama) and the model — non-trivial to set up.
- Outputs can be non-deterministic; you must validate the returned JSON and possibly add retries or post-processing.
- Larger resource requirements (GPU/CPU, memory) depending on the model.

Suggested improvements

- Add an automated JSON validator and fallback to OCR heuristics if the VLM returns invalid output.
- Use multiple prompts or chain-of-thought / few-shot examples to improve extraction reliability.

---

## Comparison (short)

- Setup: OCR approach needs Tesseract + Poppler; VLM needs Poppler + Ollama + model.
- Reliability: OCR deterministic but brittle to layout; VLM flexible but non-deterministic.
- Accuracy: VLM can be better for handwriting and odd layouts; OCR is better for fully local, controlled pipelines.
- Cost/Resources: OCR is lightweight; VLM can be heavy (model downloads, GPU/large CPU usage).

---

## Troubleshooting

- "PDF file not found": set `pdf_file_path` correctly.
- "Poppler" errors: ensure `poppler_bin_path` points to Poppler's `bin` folder (Windows) and that Poppler is installed.
- "Tesseract" errors in OCR script: install Tesseract and either add it to PATH or set `pytesseract.pytesseract.tesseract_cmd` to its executable.
- "Ollama" or "model not found": make sure the Ollama application/service is running and the named model is installed.
- VLM returned non-JSON: inspect `json_string` printed in the script; consider adding heuristics to extract JSON substring or adjusting the prompt.

---

## Example output (JSON)

{
"Page_1": {
"key_value_pairs": {
"Name": "John Doe",
"Date": "2025-10-01"
},
"checked_items": ["Business travel", "Mileage reimb."]
}
}

---

## Next steps / Improvements you might want to add

- Add command-line arguments (argparse) to choose file, page, and method.
- Save output to a file instead of printing.
- Add more robust line/box grouping for OCR words.
- Add unit tests for the small helper functions (e.g., `find_key_value_pairs`) using synthetic OCR boxes.
- Implement a validator that checks the VLM output shape and falls back to the OCR pipeline if confidence is low.

---

## Author / Maintainer

This README was generated to document the two extraction approaches implemented in this repo. Edit the top-of-script configuration variables to use each script on your PDFs.
