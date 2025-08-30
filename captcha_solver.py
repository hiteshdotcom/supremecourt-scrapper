import cv2
import numpy as np
import pytesseract
from PIL import Image
import io
import base64
from typing import Optional, Tuple
from playwright.sync_api import Page
import time
from loguru import logger
import openai
from openai import OpenAI

class CaptchaSolver:
    """Handles CAPTCHA solving using OCR, manual input, or OpenAI"""
    
    def __init__(self, use_manual_input: bool = True, confidence_threshold: float = 0.7, 
                 use_openai: bool = False, openai_api_key: str = "", 
                 openai_model: str = "gpt-4o-mini", openai_max_tokens: int = 100, 
                 openai_temperature: float = 0.1):
        self.use_manual_input = use_manual_input
        self.use_openai = use_openai
        self.confidence_threshold = confidence_threshold
        
        # Debug logging for initialization
        logger.info(f"CaptchaSolver initialized with: use_manual_input={use_manual_input}, use_openai={use_openai}, api_key_provided={bool(openai_api_key)}")
        
        # OCR configuration
        self.ocr_config = '--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
        
        # OpenAI configuration
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.openai_max_tokens = openai_max_tokens
        self.openai_temperature = openai_temperature
        self.openai_client = None
        
        # Initialize OpenAI client if enabled
        if self.use_openai and self.openai_api_key:
            try:
                self.openai_client = OpenAI(api_key=self.openai_api_key)
                logger.info("OpenAI client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                self.use_openai = False
        elif self.use_openai and not self.openai_api_key:
            logger.warning("OpenAI enabled but no API key provided")
            self.use_openai = False
        elif not self.use_openai:
            logger.info("OpenAI CAPTCHA solving is disabled")
        
    def preprocess_image(self, image_bytes: bytes) -> np.ndarray:
        """Preprocess CAPTCHA image for better OCR accuracy"""
        # Convert bytes to numpy array
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Apply threshold to get binary image
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Morphological operations to clean up the image
        kernel = np.ones((2, 2), np.uint8)
        cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        
        # Resize image for better OCR
        height, width = cleaned.shape
        if height < 50 or width < 150:
            scale_factor = max(50/height, 150/width)
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            cleaned = cv2.resize(cleaned, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
        
        return cleaned
    
    def extract_text_with_ocr(self, image_bytes: bytes) -> Tuple[str, float]:
        """Extract text from CAPTCHA image using OCR"""
        try:
            # Preprocess the image
            processed_img = self.preprocess_image(image_bytes)
            
            # Convert back to PIL Image for tesseract
            pil_img = Image.fromarray(processed_img)
            
            # Extract text with confidence scores
            data = pytesseract.image_to_data(pil_img, config=self.ocr_config, output_type=pytesseract.Output.DICT)
            
            # Filter out low confidence text
            confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
            texts = [data['text'][i] for i, conf in enumerate(data['conf']) if int(conf) > 0]
            
            if not confidences:
                return "", 0.0
            
            # Combine text and calculate average confidence
            extracted_text = ''.join(texts).strip()
            avg_confidence = sum(confidences) / len(confidences) / 100.0  # Convert to 0-1 scale
            
            # Clean up the extracted text
            extracted_text = ''.join(c for c in extracted_text if c.isalnum())
            
            logger.info(f"OCR extracted: '{extracted_text}' with confidence: {avg_confidence:.2f}")
            
            return extracted_text, avg_confidence
            
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return "", 0.0
    
    def solve_captcha_with_openai(self, image_bytes: bytes) -> Optional[str]:
        """Solve CAPTCHA using OpenAI Vision API"""
        try:
            if not self.openai_client:
                logger.error("OpenAI client not initialized")
                return None
            
            # Convert image bytes to base64
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            
            # Create the prompt for CAPTCHA solving with math OCR capabilities
            prompt = (
                "You are an advanced math image OCR and CAPTCHA solver. Look at this image carefully and:"
                "1. If it contains mathematical expressions, solve them and return the numerical result."
                "2. If it contains text/characters, extract them exactly as shown."
                "3. If it contains both math and text, prioritize solving the math."
                "Return ONLY the final answer/text you see, nothing else. "
                "Be very precise and only return the exact result you can clearly determine."
            )
            
            # Make API call to OpenAI
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=self.openai_max_tokens,
                temperature=self.openai_temperature
            )
            
            # Extract the response text
            captcha_text = response.choices[0].message.content.strip()
            
            # Clean up the response (remove any extra text)
            captcha_text = ''.join(c for c in captcha_text if c.isalnum())
            
            # For math CAPTCHAs, single digits are valid; for text CAPTCHAs, usually 3+ chars
            if len(captcha_text) < 1:  # At least one character/digit required
                logger.warning(f"OpenAI extracted text too short: '{captcha_text}'")
                return None
            
            # Log whether this looks like a math result or text
            if captcha_text.isdigit():
                logger.info(f"OpenAI detected math result: '{captcha_text}'")
            else:
                logger.info(f"OpenAI detected text: '{captcha_text}'")
            
            logger.info(f"OpenAI CAPTCHA solution: '{captcha_text}'")
            return captcha_text
            
        except Exception as e:
            logger.error(f"OpenAI CAPTCHA solving failed: {e}")
            return None
    
    def get_captcha_image(self, page: Page) -> Optional[bytes]:
        """Extract CAPTCHA image from the page"""
        try:
            # Wait for CAPTCHA image to load
            captcha_selector = "img[src*='captcha'], img[alt*='captcha'], img[id*='captcha'], .captcha img"
            page.wait_for_selector(captcha_selector, timeout=10000)
            
            # Get the CAPTCHA image element
            captcha_element = page.locator(captcha_selector).first
            
            if not captcha_element.is_visible():
                logger.warning("CAPTCHA image not visible")
                return None
            
            # Take screenshot of the CAPTCHA element
            image_bytes = captcha_element.screenshot()
            
            logger.info("CAPTCHA image captured successfully")
            return image_bytes
            
        except Exception as e:
            logger.error(f"Failed to capture CAPTCHA image: {e}")
            return None
    
    def solve_captcha_manual(self, page: Page) -> Optional[str]:
        """Solve CAPTCHA with manual user input"""
        try:
            # Get CAPTCHA image
            image_bytes = self.get_captcha_image(page)
            if not image_bytes:
                return None
            
            # Save image temporarily for user to see
            temp_image_path = "temp_captcha.png"
            with open(temp_image_path, "wb") as f:
                f.write(image_bytes)
            
            print(f"\n{'='*50}")
            print("CAPTCHA SOLVING REQUIRED")
            print(f"{'='*50}")
            print(f"A CAPTCHA image has been saved as: {temp_image_path}")
            print("Please open this image and enter the CAPTCHA text below.")
            print("\nTips for better accuracy:")
            print("- Enter exactly what you see (case-sensitive)")
            print("- Use only alphanumeric characters")
            print("- If unclear, try refreshing the page")
            
            # Get user input
            captcha_text = input("\nEnter CAPTCHA text: ").strip()
            
            if not captcha_text:
                logger.warning("No CAPTCHA text entered")
                return None
            
            logger.info(f"Manual CAPTCHA input: '{captcha_text}'")
            return captcha_text
            
        except Exception as e:
            logger.error(f"Manual CAPTCHA solving failed: {e}")
            return None
    
    def solve_captcha_ocr(self, page: Page) -> Optional[str]:
        """Solve CAPTCHA using OCR"""
        try:
            # Get CAPTCHA image
            image_bytes = self.get_captcha_image(page)
            if not image_bytes:
                return None
            
            # Extract text using OCR
            extracted_text, confidence = self.extract_text_with_ocr(image_bytes)
            
            if confidence < self.confidence_threshold:
                logger.warning(f"OCR confidence too low: {confidence:.2f} < {self.confidence_threshold}")
                return None
            
            if len(extracted_text) < 3:  # Most CAPTCHAs have at least 3 characters
                logger.warning(f"Extracted text too short: '{extracted_text}'")
                return None
            
            logger.info(f"OCR CAPTCHA solution: '{extracted_text}' (confidence: {confidence:.2f})")
            return extracted_text
            
        except Exception as e:
            logger.error(f"OCR CAPTCHA solving failed: {e}")
            return None
    
    def solve_captcha(self, page: Page, max_attempts: int = 3) -> Optional[str]:
        """Main method to solve CAPTCHA"""
        for attempt in range(max_attempts):
            logger.info(f"CAPTCHA solving attempt {attempt + 1}/{max_attempts}")
            
            # Debug logging for current configuration
            logger.info(f"Current config: use_openai={self.use_openai}, openai_client_available={self.openai_client is not None}, use_manual_input={self.use_manual_input}")
            
            try:
                captcha_text = None
                
                # Try OpenAI first if enabled
                if self.use_openai and self.openai_client:
                    logger.info("Attempting to solve CAPTCHA with OpenAI...")
                    image_bytes = self.get_captcha_image(page)
                    if image_bytes:
                        captcha_text = self.solve_captcha_with_openai(image_bytes)
                        if captcha_text:
                            logger.info(f"OpenAI successfully solved CAPTCHA: '{captcha_text}'")
                        else:
                            logger.warning("OpenAI failed to solve CAPTCHA")
                    else:
                        logger.error("Failed to get CAPTCHA image for OpenAI")
                elif self.use_openai and not self.openai_client:
                    logger.warning("OpenAI enabled but client not available")
                elif not self.use_openai:
                    logger.info("OpenAI CAPTCHA solving is disabled, skipping...")
                
                # Fallback to manual input if OpenAI fails or is disabled
                if not captcha_text and self.use_manual_input:
                    logger.info("Falling back to manual CAPTCHA input...")
                    captcha_text = self.solve_captcha_manual(page)
                
                # Fallback to OCR if both OpenAI and manual are disabled/failed
                if not captcha_text and not self.use_manual_input:
                    logger.info("Falling back to OCR CAPTCHA solving...")
                    captcha_text = self.solve_captcha_ocr(page)
                
                if captcha_text:
                    return captcha_text
                
                # If failed and not last attempt, refresh CAPTCHA
                if attempt < max_attempts - 1:
                    logger.info("Refreshing CAPTCHA for next attempt")
                    self.refresh_captcha(page)
                    time.sleep(2)
                    
            except Exception as e:
                logger.error(f"CAPTCHA solving attempt {attempt + 1} failed: {e}")
        
        logger.error(f"Failed to solve CAPTCHA after {max_attempts} attempts")
        return None
    
    def refresh_captcha(self, page: Page) -> bool:
        """Refresh CAPTCHA image"""
        try:
            # Look for refresh button or link
            refresh_selectors = [
                "a[href*='refresh'], button[onclick*='refresh'], .refresh-captcha",
                "img[onclick*='refresh'], [title*='refresh'], [alt*='refresh']"
            ]
            
            for selector in refresh_selectors:
                try:
                    refresh_element = page.locator(selector).first
                    if refresh_element.is_visible():
                        refresh_element.click()
                        logger.info("CAPTCHA refreshed")
                        return True
                except:
                    continue
            
            logger.warning("Could not find CAPTCHA refresh button")
            return False
            
        except Exception as e:
            logger.error(f"Failed to refresh CAPTCHA: {e}")
            return False
    
    def enter_captcha_text(self, page: Page, captcha_text: str) -> bool:
        """Enter CAPTCHA text into the input field"""
        try:
            # Common CAPTCHA input selectors
            input_selectors = [
                "input[name*='captcha']",
                "input[id*='captcha']",
                "input[placeholder*='captcha']",
                "input[class*='captcha']",
                "input[type='text'][name*='Captcha']"
            ]
            
            for selector in input_selectors:
                try:
                    captcha_input = page.locator(selector).first
                    if captcha_input.is_visible():
                        captcha_input.clear()
                        captcha_input.fill(captcha_text)
                        logger.info(f"CAPTCHA text entered: '{captcha_text}'")
                        return True
                except:
                    continue
            
            logger.error("Could not find CAPTCHA input field")
            return False
            
        except Exception as e:
            logger.error(f"Failed to enter CAPTCHA text: {e}")
            return False

# Example usage
if __name__ == "__main__":
    # This would be used within the main scraper
    print("CAPTCHA Solver module loaded successfully")
    print("Available methods:")
    print("- Manual input (recommended for accuracy)")
    print("- OCR-based solving (experimental)")
    print("- Image preprocessing and enhancement")
    print("- Automatic refresh and retry logic")