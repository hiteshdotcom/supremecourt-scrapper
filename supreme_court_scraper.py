from playwright.sync_api import sync_playwright, Page, Browser
from bs4 import BeautifulSoup
import requests
import time
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json
from urllib.parse import urljoin, urlparse
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

# Import our custom modules
from config import AppConfig
from date_manager import DateManager, DateRange
from captcha_solver import CaptchaSolver
from mongodb_client import MongoDBClient, JudgmentMetadata
from s3_client import S3Client

class SupremeCourtScraper:
    """Main scraper class for Supreme Court judgments"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.date_manager = DateManager(
            config.scraping.start_year,
            config.scraping.end_year,
            config.scraping.max_date_range_days
        )
        self.captcha_solver = CaptchaSolver(
            config.captcha.use_manual_input,
            config.captcha.ocr_confidence_threshold
        )
        self.mongo_client = MongoDBClient(config.mongo)
        self.s3_client = S3Client(config.s3)
        
        # Playwright objects
        self.playwright = None
        self.browser = None
        self.page = None
        
        # Network monitoring
        self.captured_responses = []
        self.api_endpoints = []
        
        # Download directory
        self.download_dir = Path("downloads")
        self.download_dir.mkdir(exist_ok=True)
        
        # Statistics
        self.stats = {
            "total_processed": 0,
            "successful_downloads": 0,
            "failed_downloads": 0,
            "captcha_failures": 0,
            "upload_failures": 0,
            "start_time": None,
            "end_time": None
        }
    
    def setup_browser(self):
        """Initialize Playwright browser with network monitoring"""
        try:
            self.playwright = sync_playwright().start()
            
            # Launch browser with configuration
            self.browser = self.playwright.firefox.launch(
                headless=self.config.scraping.headless,
                slow_mo=self.config.scraping.slow_mo
            )
            
            # Create browser context with download settings
            context = self.browser.new_context(
                accept_downloads=True
            )
            
            # Create new page
            self.page = context.new_page()
            
            # Set timeout
            self.page.set_default_timeout(self.config.scraping.timeout)
            
            # Setup network monitoring
            self.setup_network_monitoring()
            
            logger.info("Browser setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup browser: {e}")
            raise
    
    def setup_network_monitoring(self):
        """Setup network request/response monitoring"""
        try:
            # Monitor all network requests
            self.page.on("request", self._handle_request)
            self.page.on("response", self._handle_response)
            logger.info("Network monitoring setup completed")
        except Exception as e:
            logger.warning(f"Failed to setup network monitoring: {e}")
    
    def _handle_request(self, request):
        """Handle outgoing requests"""
        try:
            url = request.url
            method = request.method
            
            # Log interesting requests (API calls, AJAX, etc.)
            if any(keyword in url.lower() for keyword in ['api', 'ajax', 'search', 'judgment', 'result']):
                logger.info(f"Captured request: {method} {url}")
                
                # Store potential API endpoints
                if url not in self.api_endpoints:
                    self.api_endpoints.append(url)
                    
        except Exception as e:
            logger.debug(f"Error handling request: {e}")
    
    def _handle_response(self, response):
        """Handle incoming responses"""
        try:
            url = response.url
            status = response.status
            
            # Capture responses that might contain judgment data
            if (status == 200 and 
                any(keyword in url.lower() for keyword in ['api', 'ajax', 'search', 'judgment', 'result'])):
                
                logger.info(f"Captured response: {status} {url}")
                
                # Try to get response body for analysis
                try:
                    # Only capture text responses (not images, etc.)
                    content_type = response.headers.get('content-type', '')
                    if any(ct in content_type.lower() for ct in ['json', 'html', 'xml', 'text']):
                        response_data = {
                            'url': url,
                            'status': status,
                            'headers': dict(response.headers),
                            'timestamp': datetime.now().isoformat()
                        }
                        
                        # Try to get body (this might fail for some responses)
                        try:
                            body = response.body()
                            if body:
                                response_data['body'] = body.decode('utf-8', errors='ignore')
                                self.captured_responses.append(response_data)
                                logger.info(f"Captured response body from {url} ({len(body)} bytes)")
                        except Exception:
                            # Some responses can't be read, that's okay
                            pass
                            
                except Exception as e:
                    logger.debug(f"Error capturing response body: {e}")
                    
        except Exception as e:
            logger.debug(f"Error handling response: {e}")
    
    def cleanup_browser(self):
        """Clean up Playwright resources"""
        try:
            if self.page:
                self.page.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            logger.info("Browser cleanup completed")
        except Exception as e:
            logger.warning(f"Error during browser cleanup: {e}")
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def navigate_to_search_page(self) -> bool:
        """Navigate to the judgment search page"""
        try:
            logger.info(f"Navigating to: {self.config.scraping.base_url}")
            self.page.goto(self.config.scraping.base_url)
            
            # Wait for page to load
            self.page.wait_for_load_state("networkidle")
            
            # Check if we're on the right page
            if "judgement-date" in self.page.url:
                logger.info("Successfully navigated to search page")
                return True
            else:
                logger.error(f"Unexpected page URL: {self.page.url}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to navigate to search page: {e}")
            raise
    
    def fill_search_form(self, date_range: DateRange) -> bool:
        """Fill the search form with date range"""
        try:
            from_date, to_date = date_range.to_string_format()
            
            logger.info(f"Filling search form: {from_date} to {to_date}")
            
            # Fill from date
            from_date_input = self.page.locator("input[name*='from'], input[id*='from'], input[placeholder*='from']").first
            if from_date_input.is_visible():
                from_date_input.clear()
                from_date_input.fill(from_date)
            else:
                logger.error("From date input not found")
                return False
            
            # Fill to date
            to_date_input = self.page.locator("input[name*='to'], input[id*='to'], input[placeholder*='to']").first
            if to_date_input.is_visible():
                to_date_input.clear()
                to_date_input.fill(to_date)
            else:
                logger.error("To date input not found")
                return False
            
            logger.info("Search form filled successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to fill search form: {e}")
            return False
    
    def solve_and_submit_captcha(self) -> bool:
        """Solve CAPTCHA and submit the form"""
        try:
            # Solve CAPTCHA
            captcha_text = self.captcha_solver.solve_captcha(
                self.page, 
                self.config.captcha.max_captcha_attempts
            )
            
            if not captcha_text:
                logger.error("Failed to solve CAPTCHA")
                self.stats["captcha_failures"] += 1
                return False
            
            # Enter CAPTCHA text
            if not self.captcha_solver.enter_captcha_text(self.page, captcha_text):
                logger.error("Failed to enter CAPTCHA text")
                return False
            
            # Submit form
            search_button = self.page.locator('input[type="submit"][name="submit"][value="Search"]')
            if search_button.is_visible():
                # Use force click to bypass intercepting elements
                search_button.click(force=True)
                
                # Wait for results to load
                self.page.wait_for_load_state("networkidle")
                
                # Get page content for validation
                page_content = self.page.content().lower()
                print(page_content, "page_content")
                # Log detailed debugging information
                logger.info(f"Page title after submission: {self.page.title()}")
                logger.info(f"Current URL: {self.page.url}")
                
                # Log relevant page content snippets for debugging
                if "captcha" in page_content:
                    logger.info("CAPTCHA text found in page content")
                if "error" in page_content:
                    logger.info("Error text found in page content")
                if "invalid" in page_content:
                    logger.info("Invalid text found in page content")
                if "incorrect" in page_content:
                    logger.info("Incorrect text found in page content")
                
                # Look for specific error messages in the page
                error_selectors = [
                    "div.alert-danger",
                    "div.error",
                    "span.error",
                    "div[class*='error']",
                    "span[class*='error']"
                ]
                
                error_found = False
                for selector in error_selectors:
                    error_elements = self.page.locator(selector)
                    if error_elements.count() > 0:
                        for i in range(error_elements.count()):
                            error_text = error_elements.nth(i).text_content()
                            if error_text and error_text.strip():
                                logger.info(f"Error element found: {error_text.strip()}")
                                if "captcha" in error_text.lower():
                                    error_found = True
                
                # Check for specific CAPTCHA error messages (more precise validation)
                specific_error_patterns = [
                    "captcha code is invalid",
                    "captcha code is incorrect", 
                    "invalid captcha",
                    "incorrect captcha",
                    "captcha verification failed",
                    "please enter the captcha correctly",
                    "captcha does not match"
                ]
                
                captcha_error_found = any(pattern in page_content for pattern in specific_error_patterns)
                
                if captcha_error_found:
                    logger.warning("CAPTCHA validation failed - specific error message detected")
                    return False
                
                # Additional check: if error elements contain CAPTCHA-related errors
                if error_found:
                    logger.warning("CAPTCHA validation failed - error element with CAPTCHA text found")
                    return False
                
                # Check if we successfully moved away from the search page
                # Success usually redirects to results page or changes URL
                if self.page.url == "https://www.sci.gov.in/judgements-judgement-date/":
                    # Still on the same search page - check if there are results or if it's an error
                    results_indicators = [
                        "table",
                        "judgment",
                        "result",
                        "download",
                        "pdf"
                    ]
                    
                    has_results = any(indicator in page_content for indicator in results_indicators)
                    
                    if not has_results:
                        logger.warning("CAPTCHA validation failed - no results found on search page")
                        return False
                
                logger.info("Form submitted successfully")
                return True
            else:
                logger.error("Search button not found")
                return False
                
        except Exception as e:
            logger.error(f"Failed to solve and submit CAPTCHA: {e}")
            return False
    
    def extract_judgment_links(self) -> List[Dict[str, str]]:
        """Extract judgment download links from search results"""
        try:
            judgments = []
            
            # Prioritize network response data extraction
            judgment_data_from_api = self._extract_from_network_responses()
            print(judgment_data_from_api, "judgment_data_from_api")
            logger.info(f"Found {judgment_data_from_api} judgments from network responses")

            if judgment_data_from_api:
                logger.info(f"Found {len(judgment_data_from_api)} judgments from network responses")
                return judgment_data_from_api
            
            logger.info("No data found in network responses, attempting page parsing as fallback")
            
            # Wait for potential dynamic content loading
            self._wait_for_dynamic_content()
            
            # Parse page content with BeautifulSoup
            soup = BeautifulSoup(self.page.content(), 'html.parser')
            
            # Debug: Log page content structure
            logger.debug(f"Page content length: {len(self.page.content())}")
            
            # Look for the results table structure
            table = soup.find('table')
            if not table:
                logger.warning("No table found in search results")
                # Try alternative selectors - first check cnrresults div
                cnr_div = soup.find('div', id='cnrresults')
                if cnr_div:
                    table = cnr_div.find('table')
                    if table:
                        logger.info("Found table in cnrresults div")
                    else:
                        logger.warning("cnrresults div found but no table inside")
                
                # If still no table, try distTableContent
                if not table:
                    table = soup.find('div', class_='distTableContent')
                    if table:
                        table = table.find('table')
                        logger.info("Found table in distTableContent div")
                    else:
                        logger.error("No table found in any expected location")
                        return []
            
            # Find all table rows with judgment data
            tbody = table.find('tbody')
            if tbody:
                rows = tbody.find_all('tr')
                logger.info(f"Found {len(rows)} rows in tbody")
            else:
                all_rows = table.find_all('tr')
                rows = all_rows[1:] if len(all_rows) > 1 else all_rows  # Skip header if present
                logger.info(f"Found {len(rows)} rows (skipped header)")
            
            for i, row in enumerate(rows):
                try:
                    cells = row.find_all('td')
                    print(f"DEBUG: Row {i+1}: Found {len(cells)} cells")
                    
                    # Print cell contents for debugging
                    for j, cell in enumerate(cells):
                        print(f"DEBUG: Row {i+1}, Cell {j+1}: '{cell.get_text(strip=True)[:50]}'")
                    
                    if len(cells) < 7:  # Minimum expected columns
                        print(f"DEBUG: Row {i+1}: Skipping row with {len(cells)} cells (expected at least 7)")
                        continue
                    
                    # Extract data from table cells (adjust for actual structure)
                    serial_no = cells[0].get_text(strip=True)
                    diary_no = cells[1].get_text(strip=True)
                    case_number = cells[2].get_text(strip=True)
                    petitioner_respondent = cells[3].get_text(strip=True)
                    advocate = cells[4].get_text(strip=True)
                    bench = cells[5].get_text(strip=True)
                    print(serial_no, "serial no")
                    print(diary_no, "diary no")
                    print(case_number, "case number")
                    print(petitioner_respondent, "petitioner respondent")
                    print(advocate, "advocate")
                    print(bench, "bench")
                    # Handle different column structures
                    if len(cells) >= 8:
                        judgment_by = cells[6].get_text(strip=True)
                        judgment_cell = cells[7]
                    else:
                        # If only 7 cells, the last cell contains judgment info
                        judgment_by = cells[5].get_text(strip=True)  # Use bench as judgment_by
                        judgment_cell = cells[6]
                    
                    logger.debug(f"Row {i+1}: Case {case_number}, Diary {diary_no}, Cells: {len(cells)}")
                    pdf_links = judgment_cell.find_all('a', href=True)
                    
                    logger.debug(f"Row {i+1}: Found {len(pdf_links)} links in judgment cell")
                    
                    for j, link in enumerate(pdf_links):
                        href = link.get('href')
                        link_text = link.get_text(strip=True)
                        
                        logger.debug(f"Row {i+1}, Link {j+1}: href='{href}', text='{link_text}'")
                        
                        # Filter for valid PDF links (more permissive)
                        if href and (href.strip() != '' and 
                                   ('.pdf' in href.lower() or 
                                    'api.sci.gov.in' in href or 
                                    'supremecourt' in href.lower())):
                            
                            # Skip empty or placeholder links
                            if href.strip() == 'https://api.sci.gov.in/' or not link_text:
                                logger.debug(f"Row {i+1}, Link {j+1}: Skipping placeholder link")
                                continue
                            
                            # Extract judgment date from link text
                            judgment_date = ''
                            
                            # Try to extract date from link text (format: DD-MM-YYYY)
                            import re
                            date_match = re.search(r'(\d{2}-\d{2}-\d{4})', link_text)
                            if date_match:
                                judgment_date = date_match.group(1)
                            
                            judgment_data = {
                                'serial_no': serial_no,
                                'diary_no': diary_no,
                                'case_number': case_number,
                                'title': petitioner_respondent,
                                'advocate': advocate,
                                'bench': bench,
                                'judge': judgment_by,
                                'judgment_date': judgment_date,
                                'file_url': href.strip(),
                                'link_text': link_text
                            }
                            
                            logger.info(f"Found valid judgment: {case_number} - {judgment_date} - {href}")
                            judgments.append(judgment_data)
                            
                except Exception as e:
                    logger.warning(f"Failed to parse table row: {e}")
                    continue
            
            # Remove duplicates based on URL
            seen_urls = set()
            unique_judgments = []
            for judgment in judgments:
                if judgment['file_url'] not in seen_urls:
                    seen_urls.add(judgment['file_url'])
                    unique_judgments.append(judgment)
            
            logger.info(f"Found {len(unique_judgments)} unique judgment links")
            return unique_judgments
            
        except Exception as e:
            logger.error(f"Failed to extract judgment links: {e}")
            return []
    
    def try_direct_api_calls(self, date_range: DateRange) -> List[Dict[str, str]]:
        """Try to make direct API calls using captured endpoints"""
        judgments = []
        
        try:
            if not self.api_endpoints:
                logger.info("No API endpoints captured yet")
                return judgments
            
            logger.info(f"Attempting direct API calls to {len(self.api_endpoints)} endpoints")
            
            for endpoint in self.api_endpoints:
                try:
                    # Try to construct API request with date parameters
                    api_judgments = self._call_api_endpoint(endpoint, date_range)
                    if api_judgments:
                        judgments.extend(api_judgments)
                        logger.info(f"Successfully extracted {len(api_judgments)} judgments from API: {endpoint}")
                        
                except Exception as e:
                    logger.debug(f"Failed to call API endpoint {endpoint}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in direct API calls: {e}")
            
        return judgments
    
    def _call_api_endpoint(self, endpoint: str, date_range: DateRange) -> List[Dict[str, str]]:
        """Make a direct call to an API endpoint"""
        judgments = []
        
        try:
            import requests
            from urllib.parse import urljoin, urlparse, parse_qs, urlencode
            
            # Parse the endpoint URL
            parsed_url = urlparse(endpoint)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
            
            # Prepare parameters
            params = parse_qs(parsed_url.query)
            
            # Add date parameters if not present
            date_params = {
                'from_date': date_range.start_date.strftime('%d-%m-%Y'),
                'to_date': date_range.end_date.strftime('%d-%m-%Y'),
                'fromdate': date_range.start_date.strftime('%d-%m-%Y'),
                'todate': date_range.end_date.strftime('%d-%m-%Y'),
                'start_date': date_range.start_date.strftime('%Y-%m-%d'),
                'end_date': date_range.end_date.strftime('%Y-%m-%d')
            }
            
            # Try different parameter combinations
            for param_set in [date_params, {}]:  # Try with and without date params
                try:
                    # Merge parameters
                    final_params = {**params, **param_set}
                    
                    # Make the request
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'application/json, text/html, */*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Referer': 'https://www.sci.gov.in/judgements-judgement-date/',
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                    
                    response = requests.get(base_url, params=final_params, headers=headers, timeout=30)
                    
                    if response.status_code == 200:
                        # Try to parse response
                        try:
                            json_data = response.json()
                            parsed_judgments = self._parse_json_for_judgments(json_data)
                            if parsed_judgments:
                                judgments.extend(parsed_judgments)
                                break  # Success, no need to try other parameter sets
                        except:
                            # Try parsing as HTML
                            soup = BeautifulSoup(response.text, 'html.parser')
                            parsed_judgments = self._parse_table_from_soup(soup)
                            if parsed_judgments:
                                judgments.extend(parsed_judgments)
                                break
                                
                except Exception as e:
                    logger.debug(f"API call failed with params {param_set}: {e}")
                    continue
                    
        except Exception as e:
            logger.debug(f"Error calling API endpoint: {e}")
            
        return judgments
    
    def _extract_from_network_responses(self) -> List[Dict[str, str]]:
        """Extract judgment data from captured network responses"""
        judgments = []
        logger.info(f"Processing {len(self.captured_responses)} captured network responses")

        try:
            for response_data in self.captured_responses:
                if 'body' in response_data:
                    body = response_data['body']
                    url = response_data.get('url', '')
                    
                    # Target the specific Google Analytics API call that contains judgment data
                    is_target_api = ('google-analytics.com/g/collect' in url and 
                                   'en=user_engagement' in url and 
                                   len(body) > 1000)  # Has substantial content
                    
                    # Also process other known judgment APIs
                    is_judgment_api = ('admin-ajax.php' in url or 
                                     'action=get_judgements' in url or
                                     'judgement_date' in url)
                    
                    if is_target_api or is_judgment_api or len(body) > 10000:
                        logger.info(f"Processing API response from {url} ({len(body)} bytes)")
                        
                        # For Google Analytics API, extract embedded judgment data
                        if is_target_api:
                            extracted = self._parse_google_analytics_response(body, url)
                            if extracted:
                                judgments.extend(extracted)
                                logger.info(f"Extracted {len(extracted)} judgments from Google Analytics API")
                                # Save directly to MongoDB without S3 upload
                                self._save_judgments_to_mongodb(extracted)
                                continue
                        
                        # Try to parse as JSON first
                        try:
                            import json
                            json_data = json.loads(body)
                            
                            # Look for judgment data in JSON response
                            extracted = self._parse_json_for_judgments(json_data)
                            if extracted:
                                judgments.extend(extracted)
                                logger.info(f"Extracted {len(extracted)} judgments from JSON response")
                                continue
                                
                        except json.JSONDecodeError:
                            pass
                        
                        # Parse as HTML with enhanced detection
                        try:
                            soup = BeautifulSoup(body, 'html.parser')
                            
                            # Look for tables with judgment data
                            tables = soup.find_all('table')
                            logger.info(f"Found {len(tables)} tables in response")
                            
                            for table in tables:
                                rows = table.find_all('tr')
                                logger.info(f"Table has {len(rows)} rows")
                                
                                # Process table regardless of row count
                                extracted = self._parse_table_from_soup(soup)
                                if extracted:
                                    judgments.extend(extracted)
                                    logger.info(f"Extracted {len(extracted)} judgments from table")
                                    break  # Found data, no need to check other tables
                                else:
                                    logger.debug(f"No judgments extracted from table with {len(rows)} rows")
                                        
                        except Exception as e:
                            logger.debug(f"Error parsing HTML response: {e}")
                            
        except Exception as e:
            logger.error(f"Error extracting from network responses: {e}")
            
        return judgments
    
    def _parse_json_for_judgments(self, json_data) -> List[Dict[str, str]]:
        """Parse JSON data for judgment information"""
        judgments = []
        
        try:
            # Handle different JSON structures
            if isinstance(json_data, dict):
                # Check for Supreme Court API structure: data.resultsHtml
                if 'data' in json_data and isinstance(json_data['data'], dict):
                    data = json_data['data']
                    if 'resultsHtml' in data:
                        # Parse the HTML content within the JSON
                        html_content = data['resultsHtml']
                        logger.info(f"Found resultsHtml with {len(html_content)} characters")
                        
                        soup = BeautifulSoup(html_content, 'html.parser')
                        table_judgments = self._parse_table_from_soup(soup)
                        if table_judgments:
                            judgments.extend(table_judgments)
                            logger.info(f"Extracted {len(table_judgments)} judgments from resultsHtml")
                            return judgments
                
                # Look for common keys that might contain judgment data
                for key in ['data', 'results', 'judgments', 'records', 'items']:
                    if key in json_data and isinstance(json_data[key], list):
                        for item in json_data[key]:
                            if isinstance(item, dict):
                                judgment = self._extract_judgment_from_json_item(item)
                                if judgment:
                                    judgments.append(judgment)
                                    
            elif isinstance(json_data, list):
                # Direct list of judgment objects
                for item in json_data:
                    if isinstance(item, dict):
                        judgment = self._extract_judgment_from_json_item(item)
                        if judgment:
                            judgments.append(judgment)
                            
        except Exception as e:
            logger.debug(f"Error parsing JSON for judgments: {e}")
            
        return judgments
    
    def _extract_judgment_from_json_item(self, item: dict) -> Optional[Dict[str, str]]:
        """Extract judgment data from a JSON item"""
        try:
            judgment = {}
            
            # Map common JSON keys to our judgment fields
            key_mappings = {
                'serial_no': ['serial', 'sno', 'id', 'index'],
                'diary_no': ['diary', 'diary_no', 'diary_number'],
                'case_number': ['case', 'case_no', 'case_number', 'caseNumber'],
                'petitioner_respondent': ['parties', 'petitioner', 'respondent', 'case_title'],
                'advocate': ['advocate', 'lawyer', 'counsel'],
                'judgment_date': ['date', 'judgment_date', 'judgmentDate', 'decided_on'],
                'pdf_link': ['link', 'url', 'pdf', 'download', 'file_url']
            }
            
            for field, possible_keys in key_mappings.items():
                for key in possible_keys:
                    if key in item and item[key]:
                        judgment[field] = str(item[key]).strip()
                        break
            
            # Only return if we have essential fields
            if judgment.get('case_number') or judgment.get('pdf_link'):
                return judgment
                
        except Exception as e:
            logger.debug(f"Error extracting judgment from JSON item: {e}")
            
        return None
    
    def _parse_table_from_soup(self, soup) -> List[Dict[str, str]]:
        """Parse table data from BeautifulSoup object"""
        judgments = []
        
        try:
            table = soup.find('table')
            if not table:
                logger.debug("No table found in soup")
                return judgments
                
            # Find all table rows
            tbody = table.find('tbody')
            if tbody:
                rows = tbody.find_all('tr')
                logger.debug(f"Found {len(rows)} rows in tbody")
            else:
                all_rows = table.find_all('tr')
                rows = all_rows[1:] if len(all_rows) > 1 else all_rows  # Skip header if present
                logger.debug(f"Found {len(rows)} data rows (skipped header)")
            
            for i, row in enumerate(rows):
                cells = row.find_all('td')
                logger.debug(f"Row {i+1}: Found {len(cells)} cells")
                
                # Be more flexible with cell count - require at least 3 cells
                if len(cells) >= 3:
                    judgment = self._extract_judgment_from_cells(cells)
                    if judgment:
                        judgments.append(judgment)
                        logger.debug(f"Successfully extracted judgment from row {i+1}")
                else:
                    logger.debug(f"Row {i+1}: Not enough cells ({len(cells)} < 3)")
                        
        except Exception as e:
            logger.debug(f"Error parsing table from soup: {e}")
            
        return judgments
    
    def _extract_judgment_from_cells(self, cells) -> Optional[Dict[str, str]]:
        """Extract judgment data from table cells"""
        try:
            # Initialize judgment with available data
            judgment = {}
            
            # Extract text from cells based on Supreme Court table structure (8 columns):
            # Column 1: Serial Number
            # Column 2: Diary Number  
            # Column 3: Case Number
            # Column 4: Petitioner/Respondent
            # Column 5: Petitioner/Respondent Advocate
            # Column 6: Bench
            # Column 7: Judgment By
            # Column 8: Judgment (contains date and PDF links)
            
            if len(cells) >= 1:
                judgment['serial_number'] = cells[0].get_text(strip=True)
                judgment['serial_no'] = cells[0].get_text(strip=True)  # Legacy field
            if len(cells) >= 2:
                judgment['diary_number'] = cells[1].get_text(strip=True)
                judgment['diary_no'] = cells[1].get_text(strip=True)  # Legacy field
            if len(cells) >= 3:
                judgment['case_number'] = cells[2].get_text(strip=True)
            if len(cells) >= 4:
                judgment['petitioner_respondent'] = cells[3].get_text(strip=True)
                judgment['title'] = cells[3].get_text(strip=True)  # Legacy field
            if len(cells) >= 5:
                judgment['advocate'] = cells[4].get_text(strip=True)
            if len(cells) >= 6:
                judgment['bench'] = cells[5].get_text(strip=True)
            if len(cells) >= 7:
                judgment['judgment_by'] = cells[6].get_text(strip=True)
                judgment['judge'] = cells[6].get_text(strip=True)  # Legacy field
            if len(cells) >= 8:
                # Last column contains judgment date and PDF links
                judgment_cell = cells[7]
                
                # Extract judgment date from text (remove HTML tags)
                judgment_text = judgment_cell.get_text(strip=True)
                # Extract date from the first line/part before any links
                import re
                date_match = re.search(r'(\d{2}-\d{2}-\d{4})', judgment_text)
                if date_match:
                    judgment['judgment_date'] = date_match.group(1)
                else:
                    judgment['judgment_date'] = judgment_text.split('\n')[0].strip() if judgment_text else ''
                
                # Extract all PDF links from the judgment column
                links = judgment_cell.find_all('a')
                pdf_links = []
                judgment_links = []
                primary_pdf_link = None
                
                for link in links:
                    href = link.get('href', '').strip()
                    link_text = link.get_text(strip=True)
                    onclick = link.get('onclick', '')
                    
                    # Skip empty links or API base URL
                    if not href or href == 'https://api.sci.gov.in/' or href.strip() == '':
                        continue
                    
                    # Check for PDF links or download links
                    if href and ('.pdf' in href.lower() or 'download' in href.lower() or 'judgment' in href.lower()):
                        pdf_links.append(href)
                        judgment_links.append(href)  # Store as string instead of object
                        
                        # Set first valid PDF as primary link for legacy compatibility
                        if not primary_pdf_link:
                            primary_pdf_link = href
                    
                    # Check for JavaScript onclick handlers that might contain PDF URLs
                    elif onclick and ('pdf' in onclick.lower() or 'download' in onclick.lower()):
                        # Try to extract URL from onclick
                        url_match = re.search(r"['\"]([^'\"]*\.pdf[^'\"]*)['\"]|window\.open\(['\"]([^'\"]*)['\"])", onclick)
                        if url_match:
                            pdf_url = url_match.group(1) or url_match.group(2)
                            pdf_links.append(pdf_url)
                            judgment_links.append(pdf_url)  # Store as string instead of object
                            
                            if not primary_pdf_link:
                                primary_pdf_link = pdf_url
                
                # Store all links
                if pdf_links:
                    judgment['pdf_links'] = pdf_links
                    judgment['judgment_links'] = judgment_links
                    judgment['pdf_link'] = primary_pdf_link  # Legacy field
                    judgment['file_url'] = primary_pdf_link  # Legacy field
            
            # Extract PDF link from any cell (fallback)
            if not judgment.get('pdf_link'):
                pdf_link = None
                for i, cell in enumerate(cells):
                    # Look for links in this cell
                    links = cell.find_all('a')
                    for link in links:
                        href = link.get('href', '')
                        onclick = link.get('onclick', '')
                        
                        # Check for PDF links or download links
                        if href and ('.pdf' in href.lower() or 'download' in href.lower() or 'judgment' in href.lower()):
                            pdf_link = href
                            break
                        
                        # Check for JavaScript onclick handlers that might contain PDF URLs
                        if onclick and ('pdf' in onclick.lower() or 'download' in onclick.lower()):
                            # Try to extract URL from onclick
                            import re
                            url_match = re.search(r"['\"]([^'\"]*\.pdf[^'\"]*)['\"]|window\.open\(['\"]([^'\"]*)['\"])", onclick)
                            if url_match:
                                pdf_link = url_match.group(1) or url_match.group(2)
                                break
                    
                    if pdf_link:
                        break
                
                # Add PDF link if found
                if pdf_link:
                    judgment['pdf_link'] = pdf_link
                    judgment['file_url'] = pdf_link  # Legacy field
            
            # Return judgment if we have essential data (case number or PDF link)
            if judgment.get('case_number') or judgment.get('pdf_link'):
                logger.debug(f"Extracted judgment: {judgment}")
                return judgment
                
        except Exception as e:
            logger.debug(f"Error extracting judgment from cells: {e}")
            
        return None
    
    def _wait_for_dynamic_content(self):
        """Wait for dynamic content to load"""
        try:
            # Wait for various indicators that content might be loading
            wait_strategies = [
                # Wait for table to appear
                lambda: self.page.wait_for_selector('table', timeout=5000),
                # Wait for any content in cnrresults
                lambda: self.page.wait_for_selector('#cnrresults table', timeout=5000),
                # Wait for loading indicators to disappear
                lambda: self.page.wait_for_selector('.loading', state='hidden', timeout=5000),
                # Wait for network idle
                lambda: self.page.wait_for_load_state('networkidle', timeout=10000)
            ]
            
            for strategy in wait_strategies:
                try:
                    strategy()
                    logger.info("Dynamic content loading detected")
                    break
                except Exception:
                    continue
                    
            # Additional wait for any JavaScript execution
            time.sleep(2)
            
        except Exception as e:
            logger.debug(f"Error waiting for dynamic content: {e}")
    
    def _parse_google_analytics_response(self, body: str, url: str) -> List[Dict[str, str]]:
        """Parse Google Analytics response that contains embedded judgment data"""
        judgments = []
        
        try:
            # The Google Analytics response might contain HTML data in URL parameters
            # or as embedded content. Let's extract and parse it.
            from urllib.parse import unquote, parse_qs, urlparse
            
            # Parse URL parameters that might contain judgment data
            parsed_url = urlparse(url)
            params = parse_qs(parsed_url.query)
            
            # Look for HTML content in parameters
            for param_name, param_values in params.items():
                for param_value in param_values:
                    decoded_value = unquote(param_value)
                    
                    # Check if this contains HTML table data
                    if '<table' in decoded_value.lower() or '<tr' in decoded_value.lower():
                        logger.info(f"Found HTML table data in parameter: {param_name}")
                        
                        # Parse the HTML content
                        soup = BeautifulSoup(decoded_value, 'html.parser')
                        extracted = self._parse_table_from_soup(soup)
                        if extracted:
                            judgments.extend(extracted)
                            logger.info(f"Extracted {len(extracted)} judgments from GA parameter")
            
            # Also check the response body for any embedded HTML
            if '<table' in body.lower() or '<tr' in body.lower():
                logger.info("Found HTML table data in response body")
                soup = BeautifulSoup(body, 'html.parser')
                extracted = self._parse_table_from_soup(soup)
                if extracted:
                    judgments.extend(extracted)
                    logger.info(f"Extracted {len(extracted)} judgments from GA body")
                    
        except Exception as e:
            logger.error(f"Error parsing Google Analytics response: {e}")
            
        return judgments
    
    def _clean_html_content(self, text: str) -> str:
        """Remove HTML tags and clean text content"""
        if not text:
            return ""
        
        # Remove HTML tags using BeautifulSoup
        soup = BeautifulSoup(text, 'html.parser')
        cleaned_text = soup.get_text(separator=' ', strip=True)
        
        # Clean up extra whitespace
        cleaned_text = ' '.join(cleaned_text.split())
        
        return cleaned_text
    
    def _save_judgments_to_mongodb(self, judgments: List[Dict[str, str]]) -> bool:
        """Save judgment data directly to MongoDB without S3 upload with duplicate prevention"""
        try:
            if not judgments:
                return True
                
            saved_count = 0
            duplicate_count = 0
            
            for judgment in judgments:
                try:
                    # Clean HTML content from all fields, but preserve arrays
                    cleaned_judgment = {}
                    for key, value in judgment.items():
                        if isinstance(value, list):
                            # Keep arrays as arrays, don't convert to string
                            cleaned_judgment[key] = value
                        elif value:
                            # Clean HTML content for string values
                            cleaned_judgment[key] = self._clean_html_content(str(value))
                        else:
                            cleaned_judgment[key] = ""
                    
                    # Check for duplicates by content using both old and new field names
                    diary_no = cleaned_judgment.get('diary_number') or cleaned_judgment.get('diary_no', '')
                    case_number = cleaned_judgment.get('case_number', '')
                    judgment_date = cleaned_judgment.get('judgment_date', '')
                    
                    existing_id = self.mongo_client.find_duplicate_by_content(
                        diary_no, case_number, judgment_date
                    )
                    
                    if existing_id:
                        duplicate_count += 1
                        logger.info(f"Duplicate judgment found, skipping: {case_number} (existing ID: {existing_id})")
                        continue
                    
                    # Generate unique judgment ID
                    judgment_id = f"{diary_no}_{case_number}_{judgment_date}".replace('/', '_').replace(' ', '_').replace(':', '_')
                    
                    # Check if judgment ID already exists
                    if self.mongo_client.judgment_exists(judgment_id):
                        duplicate_count += 1
                        logger.info(f"Judgment ID already exists, skipping: {judgment_id}")
                        continue
                    
                    # Create metadata object with all available fields
                    metadata = JudgmentMetadata(
                        judgment_id=judgment_id,
                        # Court hierarchy information
                        court_type="supreme_court",
                        court_level=1,
                        court_name="Supreme Court of India",
                        jurisdiction="India",
                        # New schema fields
                        serial_number=cleaned_judgment.get('serial_number', ''),
                        diary_number=diary_no,
                        case_number=case_number,
                        petitioner_respondent=cleaned_judgment.get('petitioner_respondent', ''),
                        advocate=cleaned_judgment.get('advocate', ''),
                        bench=cleaned_judgment.get('bench', ''),
                        judgment_by=cleaned_judgment.get('judgment_by', ''),
                        judgment_date=judgment_date,
                        # Multiple PDF links support
                        pdf_links=cleaned_judgment.get('pdf_links', []),
                        judgment_links=cleaned_judgment.get('judgment_links', []),
                        # Legacy fields for backward compatibility
                        diary_no=diary_no,
                        title=cleaned_judgment.get('petitioner_respondent', ''),
                        judge=cleaned_judgment.get('judgment_by', ''),
                        # File information
                        file_url=cleaned_judgment.get('pdf_link', ''),
                        pdf_link=cleaned_judgment.get('pdf_link', ''),
                        file_size=0,  # No file downloaded yet
                        processing_status="completed"  # Mark as completed since we have the metadata and PDF link
                    )
                    
                    # Save to MongoDB
                    if self.mongo_client.insert_judgment(metadata):
                        saved_count += 1
                        logger.info(f"Saved new judgment to MongoDB: {cleaned_judgment.get('case_number', 'Unknown')}")
                    else:
                        logger.warning(f"Failed to save judgment: {cleaned_judgment.get('case_number', 'Unknown')}")
                        
                except Exception as e:
                    logger.error(f"Error saving individual judgment: {e}")
                    continue
            
            logger.info(f"Processing complete: {saved_count} new judgments saved, {duplicate_count} duplicates skipped out of {len(judgments)} total")
            return saved_count > 0
            
        except Exception as e:
            logger.error(f"Error saving judgments to MongoDB: {e}")
            return False
    
    def log_network_analysis(self):
        """Log analysis of captured network traffic"""
        try:
            logger.info("=== NETWORK TRAFFIC ANALYSIS ===")
            logger.info(f"Total API endpoints captured: {len(self.api_endpoints)}")
            logger.info(f"Total responses captured: {len(self.captured_responses)}")
            
            if self.api_endpoints:
                logger.info("Captured API endpoints:")
                for i, endpoint in enumerate(self.api_endpoints, 1):
                    logger.info(f"  {i}. {endpoint}")
            
            if self.captured_responses:
                logger.info("Captured responses summary:")
                for i, response in enumerate(self.captured_responses, 1):
                    url = response.get('url', 'Unknown')
                    status = response.get('status', 'Unknown')
                    body_size = len(response.get('body', '')) if 'body' in response else 0
                    logger.info(f"  {i}. {status} {url} ({body_size} bytes)")
                    
                    # Try to detect if response contains judgment data
                    if 'body' in response:
                        body = response['body'].lower()
                        indicators = ['judgment', 'case', 'petitioner', 'respondent', 'diary', 'pdf']
                        found_indicators = [ind for ind in indicators if ind in body]
                        if found_indicators:
                            logger.info(f"    -> Potential judgment data detected: {found_indicators}")
            
            logger.info("=== END NETWORK ANALYSIS ===")
            
        except Exception as e:
            logger.error(f"Error in network analysis: {e}")
    
    def save_network_debug_info(self, date_range: DateRange):
        """Save network debug information to file"""
        try:
            debug_file = f"network_debug_{date_range.start_date.strftime('%Y%m%d')}_{date_range.end_date.strftime('%Y%m%d')}.json"
            debug_data = {
                'date_range': {
                    'start': date_range.start_date.isoformat(),
                    'end': date_range.end_date.isoformat()
                },
                'api_endpoints': self.api_endpoints,
                'captured_responses': self.captured_responses,
                'timestamp': datetime.now().isoformat()
            }
            
            with open(debug_file, 'w', encoding='utf-8') as f:
                json.dump(debug_data, f, indent=2, ensure_ascii=False)
                
            logger.info(f"Network debug information saved to: {debug_file}")
            
        except Exception as e:
            logger.error(f"Error saving network debug info: {e}")
    
    def _extract_judgment_metadata(self, link_element) -> Dict[str, str]:
        """Extract metadata from judgment link context"""
        metadata = {
            'title': '',
            'case_number': '',
            'diary_no': '',
            'judge': '',
            'judgment_date': ''
        }
        
        try:
            # Get parent row or container
            parent = link_element.find_parent('tr') or link_element.find_parent('div')
            
            if parent:
                # Extract text content and try to parse
                text_content = parent.get_text(separator=' ', strip=True)
                
                # Try to extract case number (common patterns)
                import re
                case_patterns = [
                    r'(\d+/\d+)',
                    r'([A-Z]+\s*\d+\s*/\s*\d+)',
                    r'(Case\s*No[.:]*\s*[^\s]+)'
                ]
                
                for pattern in case_patterns:
                    match = re.search(pattern, text_content, re.IGNORECASE)
                    if match:
                        metadata['case_number'] = match.group(1).strip()
                        break
                
                # Try to extract date (dd-mm-yyyy or dd/mm/yyyy)
                date_pattern = r'(\d{1,2}[-/]\d{1,2}[-/]\d{4})'
                date_match = re.search(date_pattern, text_content)
                if date_match:
                    metadata['judgment_date'] = date_match.group(1).replace('/', '-')
                
                # Extract title (usually the link text or nearby text)
                metadata['title'] = link_element.get_text(strip=True) or text_content[:100]
            
        except Exception as e:
            logger.warning(f"Failed to extract metadata: {e}")
        
        return metadata
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
    def download_judgment_file(self, judgment_data: Dict[str, str]) -> Optional[str]:
        """Download judgment file"""
        try:
            file_url = judgment_data['file_url']
            logger.info(f"Downloading: {file_url}")
            
            # Generate filename
            parsed_url = urlparse(file_url)
            filename = os.path.basename(parsed_url.path)
            if not filename or not filename.endswith('.pdf'):
                filename = f"judgment_{int(time.time())}.pdf"
            
            # Download using requests for better control
            response = requests.get(file_url, stream=True, timeout=30)
            response.raise_for_status()
            
            # Save file
            file_path = self.download_dir / filename
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Verify file was downloaded
            if file_path.exists() and file_path.stat().st_size > 0:
                logger.info(f"Downloaded: {filename} ({file_path.stat().st_size} bytes)")
                return str(file_path)
            else:
                logger.error(f"Download failed or file is empty: {filename}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to download {judgment_data.get('file_url', 'unknown')}: {e}")
            return None
    
    def process_judgment(self, judgment_data: Dict[str, str], date_range: DateRange) -> bool:
        """Process a single judgment: download, store metadata, upload to S3"""
        try:
            # Create judgment metadata
            judgment = JudgmentMetadata(
                judgment_id="",  # Will be generated
                # Court hierarchy information
                court_type="supreme_court",
                court_level=1,
                court_name="Supreme Court of India",
                jurisdiction="India",
                # Legacy fields
                title=judgment_data.get('title'),
                case_number=judgment_data.get('case_number'),
                diary_no=judgment_data.get('diary_no'),
                judge=judgment_data.get('judge'),
                judgment_date=judgment_data.get('judgment_date'),
                file_url=judgment_data.get('file_url'),
                search_from_date=date_range.to_string_format()[0],
                search_to_date=date_range.to_string_format()[1]
            )
            
            # Check if already processed
            existing = self.mongo_client.get_judgment(judgment.judgment_id)
            if existing and existing.processing_status == "completed":
                logger.info(f"Judgment already processed: {judgment.judgment_id}")
                return True
            
            # Insert/update in database
            self.mongo_client.insert_judgment(judgment)
            
            # NOTE: S3 upload functionality commented out as PDF links are extracted directly
            # No need to download and upload files since we have direct PDF URLs
            
            # # Download file
            # file_path = self.download_judgment_file(judgment_data)
            # if not file_path:
            #     self.mongo_client.mark_as_failed(judgment.judgment_id, "Download failed")
            #     self.stats["failed_downloads"] += 1
            #     return False
            # 
            # # Update with file info
            # file_info = {
            #     "file_name": os.path.basename(file_path),
            #     "file_size": os.path.getsize(file_path),
            #     "file_type": "pdf"
            # }
            # self.mongo_client.mark_as_downloaded(judgment.judgment_id, file_info)
            # 
            # # Upload to S3
            # s3_result = self.s3_client.upload_file(
            #     file_path,
            #     judgment.judgment_date,
            #     judgment.case_number,
            #     {
            #         "judgment_id": judgment.judgment_id,
            #         "title": judgment.title or "Unknown",
            #         "case_number": judgment.case_number or "Unknown"
            #     }
            # )
            # 
            # if s3_result:
            #     # Mark as uploaded
            #     self.mongo_client.mark_as_uploaded(judgment.judgment_id, s3_result)
            #     
            #     # Clean up local file
            #     try:
            #         os.remove(file_path)
            #     except:
            #         pass
            #     
            #     logger.info(f"Successfully processed judgment: {judgment.judgment_id}")
            #     self.stats["successful_downloads"] += 1
            #     return True
            # else:
            #     self.mongo_client.mark_as_failed(judgment.judgment_id, "S3 upload failed")
            #     self.stats["upload_failures"] += 1
            #     return False
            
            # Mark as completed since we have the PDF URL
            # Note: Completion is handled in _save_judgments_to_mongodb method
            logger.info(f"Successfully processed judgment with PDF URL: {judgment.judgment_id}")
            self.stats["successful_downloads"] += 1
            return True
                
        except Exception as e:
            logger.error(f"Failed to process judgment: {e}")
            if 'judgment' in locals():
                self.mongo_client.mark_as_failed(judgment.judgment_id, str(e))
            return False
    
    def process_date_range(self, date_range: DateRange) -> bool:
        """Process all judgments for a specific date range"""
        try:
            logger.info(f"Processing date range: {date_range}")
            
            # Navigate to search page
            if not self.navigate_to_search_page():
                return False
            
            # Fill search form
            if not self.fill_search_form(date_range):
                return False
            
            # Solve CAPTCHA and submit
            if not self.solve_and_submit_captcha():
                return False
            
            # Extract judgment links from network responses (after CAPTCHA submission)
            judgments = self._extract_from_network_responses()
            
            # If no network responses captured, try traditional extraction
            if not judgments:
                logger.info("No judgments found in network responses, trying traditional extraction...")
                judgments = self.extract_judgment_links()
            
            # If still no links found, try direct API calls as fallback
            if not judgments:
                logger.warning(f"No judgment links found via web scraping for date range: {date_range}")
                logger.info("Attempting direct API calls as fallback...")
                
                judgments = self.try_direct_api_calls(date_range)
                
                if not judgments:
                    logger.info(f"No judgments found for date range: {date_range}")
                    return True
                else:
                    logger.info(f"Successfully found {len(judgments)} judgments via direct API calls")
            
            # Save all judgments to MongoDB with duplicate prevention and HTML cleaning
            if judgments:
                success = self._save_judgments_to_mongodb(judgments)
                if success:
                    self.stats["total_processed"] += len(judgments)
                    logger.info(f"Successfully processed {len(judgments)} judgments for date range: {date_range}")
                else:
                    logger.warning(f"Failed to save judgments for date range: {date_range}")
            else:
                logger.info(f"No judgments to process for date range: {date_range}")
            
            # Log network analysis for debugging
            self.log_network_analysis()
            
            # Save network debug info if enabled
            if hasattr(self.config, 'debug') and self.config.debug:
                self.save_network_debug_info(date_range)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to process date range {date_range}: {e}")
            
            # Log network analysis even on failure for debugging
            self.log_network_analysis()
            
            return False
    
    def run(self):
        """Main execution method"""
        try:
            self.stats["start_time"] = datetime.now()
            logger.info("Starting Supreme Court judgment scraper")
            
            # Setup browser
            self.setup_browser()
            
            # Get remaining date ranges
            remaining_ranges = self.date_manager.get_remaining_ranges()
            total_ranges = len(remaining_ranges)
            
            logger.info(f"Processing {total_ranges} date ranges")
            
            # Process each date range
            completed_ranges = []
            failed_ranges = []
            
            for i, date_range in enumerate(remaining_ranges, 1):
                logger.info(f"Progress: {i}/{total_ranges} - {date_range}")
                
                try:
                    if self.process_date_range(date_range):
                        completed_ranges.append(date_range)
                    else:
                        failed_ranges.append(date_range)
                        
                    # Save progress periodically
                    if i % 10 == 0:
                        self.date_manager.save_progress(completed_ranges, failed_ranges)
                        
                except Exception as e:
                    logger.error(f"Error processing date range {date_range}: {e}")
                    failed_ranges.append(date_range)
                
                # Delay between date ranges
                time.sleep(self.config.scraping.retry_delay)
            
            # Save final progress
            self.date_manager.save_progress(completed_ranges, failed_ranges)
            
            self.stats["end_time"] = datetime.now()
            self._print_final_statistics()
            
        except Exception as e:
            logger.error(f"Scraper execution failed: {e}")
            raise
        finally:
            self.cleanup_browser()
            self.mongo_client.close()
    
    def _print_final_statistics(self):
        """Print final execution statistics"""
        duration = self.stats["end_time"] - self.stats["start_time"]
        
        print("\n" + "="*60)
        print("SUPREME COURT SCRAPER - FINAL STATISTICS")
        print("="*60)
        print(f"Execution time: {duration}")
        print(f"Total judgments processed: {self.stats['total_processed']}")
        print(f"Successful downloads: {self.stats['successful_downloads']}")
        print(f"Failed downloads: {self.stats['failed_downloads']}")
        print(f"CAPTCHA failures: {self.stats['captcha_failures']}")
        print(f"Upload failures: {self.stats['upload_failures']}")
        
        if self.stats['total_processed'] > 0:
            success_rate = (self.stats['successful_downloads'] / self.stats['total_processed']) * 100
            print(f"Success rate: {success_rate:.1f}%")
        
        # Database statistics
        db_stats = self.mongo_client.get_statistics()
        print(f"\nDatabase statistics:")
        for key, value in db_stats.items():
            print(f"  {key}: {value}")
        
        # S3 statistics
        s3_stats = self.s3_client.get_storage_stats()
        print(f"\nS3 storage statistics:")
        for key, value in s3_stats.items():
            print(f"  {key}: {value}")
        
        print("="*60)

# Example usage
if __name__ == "__main__":
    from config import config
    
    # Validate configuration
    if not config.validate():
        print("Configuration validation failed. Please check your settings.")
        exit(1)
    
    # Create and run scraper
    scraper = SupremeCourtScraper(config)
    scraper.run()