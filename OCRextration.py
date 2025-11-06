import cv2
import pytesseract
import numpy as np
import os
from pdf2image import convert_from_path
from pytesseract import Output
import json  
# --- CONFIGURATION (Change these paths) ---

# For Windows:
# 1. Set the path to your Tesseract executable (if not in system PATH)
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# 2. Set the path to the Poppler 'bin' folder you unzipped
poppler_bin_path = r"C:\Program Files\poppler\poppler-25.07.0\Library\bin"

# The PDF you want to process
pdf_file_path = r"C:\Users\MSI\Desktop\MSc CS\3rd semester MSc CS\Applied Artificial Intelligence Lab\FormValidation\u_kn_travel_expense_report_1.pdf"

def preprocess_image(image):
    """Converts a PIL Image to OpenCV, grayscales, and binarizes it."""
    img_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    img_gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    # Use adaptive thresholding for better results on varied lighting
    img_bin = cv2.adaptiveThreshold(img_gray, 255, 
                                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                    cv2.THRESH_BINARY, 11, 2)
    return img_bin, img_cv # Return binary and original color CV images

def find_key_value_pairs(ocr_data):
    """
    Tries to automatically pair keys (labels) with values
    based on horizontal proximity.
    """
    pairs = {}
    n_boxes = len(ocr_data['text'])
    
    for i in range(n_boxes):
        key_text = ocr_data['text'][i].strip()
        key_conf = int(ocr_data['conf'][i])
        
        # Skip empty strings or low-confidence words
        if not key_text or key_conf < 50:
            continue
            
        # Get key coordinates
        k_left = ocr_data['left'][i]
        k_top = ocr_data['top'][i]
        k_height = ocr_data['height'][i]
        k_width = ocr_data['width'][i]
        
        closest_value = None
        min_distance = float('inf')

        # Find the closest text block to the right on the same line
        for j in range(n_boxes):
            if i == j:
                continue # Don't compare with itself
            
            val_text = ocr_data['text'][j].strip()
            val_conf = int(ocr_data['conf'][j])
            
            if not val_text or val_conf < 50:
                continue

            v_left = ocr_data['left'][j]
            v_top = ocr_data['top'][j]
            v_height = ocr_data['height'][j]

            # Check for vertical alignment (on the same line)
            # A value is "on the same line" if its vertical center is
            # within the key's vertical span
            key_v_center = k_top + (k_height / 2)
            val_v_center = v_top + (v_height / 2)
            
            is_on_same_line = abs(key_v_center - val_v_center) < k_height

            # Check for horizontal position (to the right)
            is_to_the_right = v_left > (k_left + k_width)
            
            if is_on_same_line and is_to_the_right:
                distance = v_left - (k_left + k_width)
                if distance < min_distance:
                    min_distance = distance
                    closest_value = val_text
        
        # We found a potential pair
        if closest_value:
            # Clean up key (e.g., remove trailing colons)
            clean_key = key_text.strip(' :')
            
            # Avoid overwriting a key with a less-likely sub-part
            if clean_key not in pairs:
                pairs[clean_key] = closest_value
                
    return pairs

def find_checkboxes(binary_image, ocr_data):
    """
    Finds checkboxes (both ☐ and ☑) and determines if they are checked.
    It links them to the *closest* text found by Tesseract.
    """
    checked_items = []
    
    # 1. Find contours in the binary image
    contours, hierarchy = cv2.findContours(binary_image, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
    for i, cnt in enumerate(contours):
        # 2. Approximate the contour to a polygon
        perimeter = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.04 * perimeter, True)
        
        x, y, w, h = cv2.boundingRect(cnt)
        
        # 3. Filter for square-like shapes (checkboxes)
        aspect_ratio = w / float(h)
        is_square = 0.8 <= aspect_ratio <= 1.2
        is_right_size = 10 < w < 30 and 10 < h < 30 # pixel size
        is_not_nested = hierarchy[0][i][3] == -1 # Not a contour-inside-a-contour
        
        if len(approx) == 4 and is_square and is_right_size and is_not_nested:
            # 4. This is likely a checkbox. Now, see if it's checked.
            # Get the Region of Interest (ROI) from the binary image
            roi = binary_image[y:y+h, x:x+w]
            
            # Calculate the percentage of black pixels (the checkmark)
            # Note: In our binary image, text/marks are 0 (black), bg is 255 (white)
            total_pixels = w * h
            black_pixels = total_pixels - cv2.countNonZero(roi)
            fill_percentage = (black_pixels / total_pixels) * 100
            
            if fill_percentage > 20: # If > 20% filled, we'll call it "checked"
                
                # 5. Find the closest text to this checked box
                box_center_x = x + (w / 2)
                box_center_y = y + (h / 2)
                
                min_text_dist = float('inf')
                closest_text = "[CHECKBOX]"
                
                for j in range(len(ocr_data['text'])):
                    text = ocr_data['text'][j].strip()
                    if not text:
                        continue
                        
                    t_left = ocr_data['left'][j]
                    t_top = ocr_data['top'][j]
                    t_width = ocr_data['width'][j]
                    t_height = ocr_data['height'][j]
                    text_center_x = t_left + (t_width / 2)
                    text_center_y = t_top + (t_height / 2)
                    
                    # Euclidean distance
                    dist = np.sqrt((box_center_x - text_center_x)**2 + (box_center_y - text_center_y)**2)
                    
                    if dist < min_text_dist:
                        min_text_dist = dist
                        closest_text = text
                        
                checked_items.append(closest_text)
                
    return list(set(checked_items)) # Return unique text labels


# --- Main Execution ---

if not os.path.exists(pdf_file_path):
    print(f"Error: PDF file not found at {pdf_file_path}")
    exit()

print(f"Processing PDF: {pdf_file_path}\n")

try:
    if os.name == 'nt':
        images = convert_from_path(pdf_file_path, poppler_path=poppler_bin_path)
    else:
        images = convert_from_path(pdf_file_path)

    final_results = {}

    for i, page_image in enumerate(images):
        print(f"--- Processing Page {i + 1} ---")
        
        # 1. Pre-process image
        # We need the binary one for contours, and the color one for OCR
        binary_img, cv_img = preprocess_image(page_image)
        
        # 2. Perform OCR to get structured data
        ocr_data = pytesseract.image_to_data(cv_img, lang='eng+deu', output_type=Output.DICT)
        # Note: Added 'deu' (German) for better results on your form
        
        # 3. Find horizontal Key-Value Pairs
        kv_pairs = find_key_value_pairs(ocr_data)
        
        # 4. Find checked boxes
        # We use the *inverted* binary image because findContours looks for white objects
        checked_items = find_checkboxes(cv2.bitwise_not(binary_img), ocr_data)
        
        final_results[f"Page_{i+1}"] = {
            "key_value_pairs": kv_pairs,
            "checked_items": checked_items
        }

    # 5. Print the final JSON results
    print("\n--- EXTRACTION COMPLETE ---")
    print(json.dumps(final_results, indent=2, ensure_ascii=False))

except Exception as e:
    print(f"An error occurred: {e}")
    if "Poppler" in str(e):
        print("\n*** POLLER ERROR ***\nMake sure 'poppler_bin_path' is set correctly.")
    if "Tesseract" in str(e):
        print("\n*** TESSERACT ERROR ***\nMake sure Tesseract is installed and in your system PATH.")