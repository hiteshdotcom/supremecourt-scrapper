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
            config.captcha.ocr_confidence_threshold,
            config.captcha.use_openai,
            config.captcha.openai_api_key,
            config.captcha.openai_model,
            config.captcha.openai_max_tokens,
            config.captcha.openai_temperature
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
    
    def _refresh_captcha_and_wait(self):
        """Trigger the site's CAPTCHA refresh and wait for the new image to load.

        On a wrong CAPTCHA the site itself clicks .captcha-refresh-btn, which loads a
        fresh image and updates the hidden `scid` field. We replicate that and wait so
        the next attempt reads a CAPTCHA whose id matches what the server expects.
        """
        try:
            self.page.evaluate(
                "() => { const b = document.querySelector('.captcha-refresh-btn'); if (b) b.click(); }"
            )
            time.sleep(2)
        except Exception as e:
            logger.debug(f"CAPTCHA refresh failed: {e}")

    def _submit_search_ajax(self) -> Optional[dict]:
        """Submit the search via the site's own AJAX endpoint and return the result.

        The browser form-submit path is unreliable (jQuery-validate's submitHandler
        does not reliably fire under automation), so we replicate exactly what
        ajax_call_services_form() does: serialize the form and GET /wp-admin/admin-ajax.php
        with action=get_judgements_judgement_date. Returns a dict with keys
        {success, resultsHtml, message} or None on transport failure.
        """
        try:
            result = self.page.evaluate(
                """async () => {
                    const $ = window.jQuery;
                    const f = document.querySelector('#sciapi-services-judgements-judgement-date');
                    if (!f || !$) return {ok:false, err:'form or jQuery missing'};
                    const data = {};
                    $(f).serializeArray().forEach(n => { data[n.name] = n.value; });
                    data.action = 'get_judgements_judgement_date';
                    data.es_ajax_request = 1;
                    data.language = (window.ecourtServicesData && window.ecourtServicesData.currentLang) || 'en';
                    try {
                        const resp = await $.ajax({ method:'GET', dataType:'json', url:'/wp-admin/admin-ajax.php', data });
                        let html = '', msg = '';
                        if (resp && resp.success) {
                            html = (resp.data && typeof resp.data.resultsHtml !== 'undefined') ? resp.data.resultsHtml : resp.data;
                        } else {
                            try { const d = JSON.parse(resp.data); msg = d.message || ''; }
                            catch(e) { msg = String((resp && resp.data) || 'request failed'); }
                        }
                        return {ok:true, success: !!(resp && resp.success), resultsHtml: html || '', message: msg};
                    } catch(e) {
                        return {ok:false, err: 'ajax error ' + (e && e.status)};
                    }
                }"""
            )
            if not result or not result.get("ok"):
                logger.warning(f"AJAX submit transport error: {result.get('err') if result else 'no result'}")
                return None
            return result
        except Exception as e:
            logger.error(f"_submit_search_ajax failed: {e}")
            return None

    def solve_and_submit_captcha(self) -> bool:
        """Solve the CAPTCHA and run the search via the site's AJAX endpoint.

        Retries the whole solve+submit cycle (with a fresh CAPTCHA each time) because
        a wrong CAPTCHA is only detectable from the server response.
        """
        max_attempts = max(1, self.config.captcha.max_captcha_attempts)

        # Make sure the auto-refreshed CAPTCHA has settled before the first read.
        try:
            self.page.wait_for_selector("#siwp_captcha_image_0", state="visible", timeout=15000)
        except Exception:
            time.sleep(2)

        for attempt in range(1, max_attempts + 1):
            try:
                # Solve the currently displayed CAPTCHA (single shot; we manage retries here)
                captcha_text = self.captcha_solver.solve_captcha(self.page, 1)
                if not captcha_text:
                    logger.warning(f"[SEARCH] CAPTCHA unsolved (attempt {attempt}/{max_attempts})")
                    self._refresh_captcha_and_wait()
                    continue

                if not self.captcha_solver.enter_captcha_text(self.page, captcha_text):
                    logger.error("[SEARCH] Failed to enter CAPTCHA text")
                    self._refresh_captcha_and_wait()
                    continue

                response = self._submit_search_ajax()
                if response is None:
                    self._refresh_captcha_and_wait()
                    continue

                if not response.get("success"):
                    logger.warning(
                        f"[SEARCH] Rejected (likely wrong CAPTCHA): "
                        f"{response.get('message') or 'no message'} (attempt {attempt}/{max_attempts})"
                    )
                    self._refresh_captcha_and_wait()
                    continue

                results_html = response.get("resultsHtml") or ""
                # Inject the results into the page exactly like the site does, so the
                # existing DOM-based parser can read them.
                self.page.evaluate(
                    "html => { const el = document.querySelector('#cnrResults');"
                    " if (el) { el.innerHTML = html; el.classList.remove('hide'); } }",
                    results_html,
                )
                logger.info(f"[SEARCH] ✓ Results loaded via AJAX ({len(results_html)} bytes)")
                return True

            except Exception as e:
                logger.error(f"[SEARCH] Attempt {attempt} failed: {e}")
                self._refresh_captcha_and_wait()

        logger.error("[SEARCH] Failed to submit search after all CAPTCHA attempts")
        self.stats["captcha_failures"] += 1
        return False

    def _solve_and_submit_captcha_legacy(self) -> bool:
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
                
                # Wait a bit for any error messages to appear
                time.sleep(1)
                
                # Get page content for validation
                page_content = self.page.content().lower()
                
                # Log detailed debugging information
                logger.info(f"[CAPTCHA VALIDATION] Page title: {self.page.title()}")
                logger.info(f"[CAPTCHA VALIDATION] Current URL: {self.page.url}")
                
                # Check for specific CAPTCHA error messages (more precise validation)
                specific_error_patterns = [
                    "captcha code is invalid",
                    "captcha code is incorrect", 
                    "invalid captcha",
                    "incorrect captcha",
                    "wrong captcha",
                    "captcha verification failed",
                    "please enter the captcha correctly",
                    "captcha does not match",
                    "captcha mismatch"
                ]
                
                # Check each pattern
                captcha_error_found = False
                for pattern in specific_error_patterns:
                    if pattern in page_content:
                        logger.warning(f"[CAPTCHA VALIDATION] ✗ FAILED - Found error pattern: '{pattern}'")
                        captcha_error_found = True
                        break
                
                if captcha_error_found:
                    logger.warning("[CAPTCHA VALIDATION] ✗ CAPTCHA validation failed - specific error message detected")
                    return False
                
                # Look for error messages in visible elements
                error_selectors = [
                    "div.alert-danger",
                    "div.error",
                    "span.error",
                    "div[class*='error']",
                    "span[class*='error']",
                    ".error-message",
                    "#error",
                    "[role='alert']"
                ]
                
                error_found = False
                for selector in error_selectors:
                    try:
                        error_elements = self.page.locator(selector)
                        count = error_elements.count()
                        if count > 0:
                            for i in range(count):
                                try:
                                    error_elem = error_elements.nth(i)
                                    if error_elem.is_visible():
                                        error_text = error_elem.text_content()
                                        if error_text and error_text.strip():
                                            error_text_lower = error_text.lower()
                                            logger.info(f"[CAPTCHA VALIDATION] Error element found: {error_text.strip()}")
                                            # Check if error is actually about CAPTCHA
                                            if "captcha" in error_text_lower:
                                                logger.warning(f"[CAPTCHA VALIDATION] ✗ CAPTCHA error in element: {error_text.strip()}")
                                                error_found = True
                                                break
                                except:
                                    continue
                        if error_found:
                            break
                    except:
                        continue
                
                if error_found:
                    logger.warning("[CAPTCHA VALIDATION] ✗ CAPTCHA validation failed - error element with CAPTCHA text found")
                    return False
                
                # Check if CAPTCHA input field still exists and is empty (might indicate failed validation)
                try:
                    captcha_input = self.page.locator("input[name*='captcha'], input[id*='captcha']").first
                    if captcha_input.is_visible():
                        captcha_value = captcha_input.input_value()
                        if not captcha_value or captcha_value.strip() == "":
                            logger.warning("[CAPTCHA VALIDATION] ⚠ CAPTCHA input field is empty after submission - possible validation failure")
                            # This alone is not enough to fail, but it's a warning sign
                except:
                    pass
                
                # Check for positive indicators of success
                success_indicators = [
                    # Table with results
                    ("table tbody tr", "Results table with data rows"),
                    ("table tr td", "Table cells with data"),
                    ("#cnrresults table", "CNR results table"),
                    (".distTableContent table", "Results table in container"),
                ]
                
                success_found = False
                for selector, description in success_indicators:
                    try:
                        elements = self.page.locator(selector)
                        if elements.count() > 0:
                            logger.info(f"[CAPTCHA VALIDATION] ✓ Found success indicator: {description}")
                            success_found = True
                            break
                    except:
                        continue
                
                if success_found:
                    logger.info("[CAPTCHA VALIDATION] ✓ SUCCESS - Form submitted successfully and results found")
                    return True
                
                # If no clear success indicators but also no errors, check if we're still on search page
                if self.page.url == "https://www.sci.gov.in/judgements-judgement-date/":
                    # Check for generic content indicators
                    has_content = (
                        "table" in page_content or
                        "tbody" in page_content or
                        "judgment" in page_content or
                        "diary" in page_content
                    )
                    
                    if has_content:
                        logger.info("[CAPTCHA VALIDATION] ✓ SUCCESS - Page has judgment-related content")
                        return True
                    else:
                        logger.warning("[CAPTCHA VALIDATION] ⚠ AMBIGUOUS - Still on search page with no clear results")
                        # Not definitively a failure, but proceed with caution
                        return True
                else:
                    # URL changed, likely successful
                    logger.info("[CAPTCHA VALIDATION] ✓ SUCCESS - URL changed, likely successful submission")
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
            
            # Look for the results table structure. IMPORTANT: the page also
            # contains a datepicker calendar <table> (id="myDatepickerGrid") that
            # appears *before* the results in the DOM, so a naive soup.find('table')
            # grabs the calendar. Always look inside the AJAX results container first.
            table = None
            results_div = (soup.find('div', id='cnrResults') or
                           soup.find('div', id='cnrresults'))
            if results_div:
                table = results_div.find('table')
                if table:
                    logger.info("Found table in cnrResults div")

            # Next, try the distTableContent container.
            if not table:
                dist_div = soup.find('div', class_='distTableContent')
                if dist_div:
                    table = dist_div.find('table')
                    if table:
                        logger.info("Found table in distTableContent div")

            # Last resort: first <table> that is not the datepicker calendar.
            if not table:
                for candidate in soup.find_all('table'):
                    tid = (candidate.get('id') or '').lower()
                    tclass = ' '.join(candidate.get('class') or []).lower()
                    if 'datepicker' in tid or 'mydatepicker' in tid or 'dates' in tclass:
                        continue
                    table = candidate
                    break

            if not table:
                logger.error("No results table found in any expected location")
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
                    pdf_link_elements = judgment_cell.find_all('a', href=True)

                    logger.debug(f"Row {i+1}: Found {len(pdf_link_elements)} links in judgment cell")

                    # Collect ALL valid PDF links for this row into one judgment entry
                    import re
                    valid_pdf_links = []
                    judgment_date = ''

                    for j, link in enumerate(pdf_link_elements):
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

                            # Extract judgment date from the first valid link
                            if not judgment_date:
                                date_match = re.search(r'(\d{2}-\d{2}-\d{4})', link_text)
                                if date_match:
                                    judgment_date = date_match.group(1)

                            valid_pdf_links.append(href.strip())

                    # Deduplicate while preserving order
                    seen_urls = set()
                    deduped_pdf_links = []
                    for url in valid_pdf_links:
                        if url not in seen_urls:
                            seen_urls.add(url)
                            deduped_pdf_links.append(url)
                    valid_pdf_links = deduped_pdf_links

                    # Create ONE judgment entry per row with all its PDF links
                    if valid_pdf_links:
                        judgment_data = {
                            'serial_no': serial_no,
                            'diary_no': diary_no,
                            'case_number': case_number,
                            'title': petitioner_respondent,
                            'advocate': advocate,
                            'bench': bench,
                            'judge': judgment_by,
                            'judgment_date': judgment_date,
                            'file_url': valid_pdf_links[0],      # Primary link (legacy)
                            'pdf_link': valid_pdf_links[0],      # Primary link (legacy)
                            'pdf_links': valid_pdf_links,         # All links
                            'judgment_links': valid_pdf_links,    # All links
                        }

                        logger.info(f"Found judgment: {case_number} - {judgment_date} - {len(valid_pdf_links)} file(s)")
                        judgments.append(judgment_data)
                            
                except Exception as e:
                    logger.warning(f"Failed to parse table row: {e}")
                    continue
            
            # Remove duplicates based on case_number (each row is now one judgment entry)
            seen_cases = set()
            unique_judgments = []
            for judgment in judgments:
                key = (judgment.get('case_number', ''), judgment.get('diary_no', ''))
                if key not in seen_cases:
                    seen_cases.add(key)
                    unique_judgments.append(judgment)

            logger.info(f"Found {len(unique_judgments)} unique judgments")
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
                
                # Deduplicate links while preserving order
                seen = set()
                unique_pdf_links = []
                for url in pdf_links:
                    if url not in seen:
                        seen.add(url)
                        unique_pdf_links.append(url)
                pdf_links = unique_pdf_links
                judgment_links = unique_pdf_links

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
                        # Merge any new PDF links into the existing record
                        new_pdf_links = cleaned_judgment.get('pdf_links') or []
                        if new_pdf_links:
                            existing_record = self.mongo_client.get_judgment(existing_id)
                            if existing_record:
                                existing_links = set(existing_record.pdf_links or [])
                                additional_links = [l for l in new_pdf_links if l not in existing_links]
                                if additional_links:
                                    merged = list(existing_links) + additional_links
                                    self.mongo_client.update_judgment(existing_id, {
                                        'pdf_links': merged,
                                        'judgment_links': merged
                                    })
                                    logger.info(f"Merged {len(additional_links)} new PDF link(s) into existing judgment: {existing_id}")
                        logger.info(f"Duplicate judgment found, skipping insert: {case_number} (existing ID: {existing_id})")
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
                        # Multiple PDF links support (deduplicated)
                        pdf_links=list(dict.fromkeys(cleaned_judgment.get('pdf_links', []))),
                        judgment_links=list(dict.fromkeys(cleaned_judgment.get('judgment_links', []))),
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
                # Remove the empty/orphaned file so it doesn't pile up in downloads/
                try:
                    if file_path.exists():
                        file_path.unlink()
                except Exception:
                    pass
                return None

        except Exception as e:
            logger.error(f"Failed to download {judgment_data.get('file_url', 'unknown')}: {e}")
            # Clean up any partial file left behind by a failed download
            try:
                if 'file_path' in locals() and file_path.exists():
                    file_path.unlink()
            except Exception:
                pass
            return None
    
    def process_judgment_with_multiple_files(self, judgment_data: Dict[str, str], date_range: DateRange) -> bool:
        """Process a single judgment with multiple PDF files: download, store metadata, upload to S3"""
        try:
            logger.info(f"[FILE UPLOAD] Processing judgment: {judgment_data.get('case_number', 'Unknown')}")
            
            # Create judgment metadata
            judgment = JudgmentMetadata(
                judgment_id="",  # Will be generated
                # Court hierarchy information
                court_type="supreme_court",
                court_level=1,
                court_name="Supreme Court of India",
                jurisdiction="India",
                # New schema fields
                serial_number=judgment_data.get('serial_number', ''),
                diary_number=judgment_data.get('diary_number') or judgment_data.get('diary_no', ''),
                case_number=judgment_data.get('case_number', ''),
                petitioner_respondent=judgment_data.get('petitioner_respondent') or judgment_data.get('title', ''),
                advocate=judgment_data.get('advocate', ''),
                bench=judgment_data.get('bench', ''),
                judgment_by=judgment_data.get('judgment_by') or judgment_data.get('judge', ''),
                judgment_date=judgment_data.get('judgment_date', ''),
                # Legacy fields for backward compatibility
                diary_no=judgment_data.get('diary_number') or judgment_data.get('diary_no', ''),
                title=judgment_data.get('petitioner_respondent') or judgment_data.get('title', ''),
                judge=judgment_data.get('judgment_by') or judgment_data.get('judge', ''),
                # Source URLs
                file_url=judgment_data.get('pdf_link') or judgment_data.get('file_url'),
                pdf_link=judgment_data.get('pdf_link') or judgment_data.get('file_url'),
                pdf_links=judgment_data.get('pdf_links', []),
                judgment_links=judgment_data.get('judgment_links', []),
                # Initialize files array
                files=[],
                # Search date range
                search_from_date=date_range.to_string_format()[0],
                search_to_date=date_range.to_string_format()[1]
            )
            
            # Get all PDF links to download
            pdf_urls = judgment_data.get('pdf_links', []) or judgment_data.get('judgment_links', [])
            if not pdf_urls:
                # Fallback to single URL
                single_url = judgment_data.get('pdf_link') or judgment_data.get('file_url')
                if single_url:
                    pdf_urls = [single_url]

            # Check if already processed
            existing = self.mongo_client.get_judgment(judgment.judgment_id)
            if existing and existing.processing_status in ("completed", "uploaded"):
                # Only skip if every PDF URL has already been uploaded
                existing_source_urls = {f.get('source_url') for f in (existing.files or [])}
                new_urls = [u for u in pdf_urls if u not in existing_source_urls]
                if not new_urls:
                    logger.info(f"[FILE UPLOAD] Judgment already fully processed: {judgment.judgment_id}")
                    return True
                logger.info(f"[FILE UPLOAD] Found {len(new_urls)} new file(s) to add to existing judgment: {judgment.judgment_id}")
                pdf_urls = new_urls

            # Insert initial record in database
            if not existing:
                self.mongo_client.insert_judgment(judgment)
                logger.info(f"[FILE UPLOAD] Created judgment record: {judgment.judgment_id}")
            
            if not pdf_urls:
                logger.warning(f"[FILE UPLOAD] No PDF URLs found for judgment: {judgment.judgment_id}")
                self.mongo_client.mark_as_completed(judgment.judgment_id)
                return True
            
            # Deduplicate pdf_urls by URL, preserving order
            seen_pdf_urls = set()
            unique_pdf_urls = []
            for u in pdf_urls:
                if u not in seen_pdf_urls:
                    seen_pdf_urls.add(u)
                    unique_pdf_urls.append(u)
            pdf_urls = unique_pdf_urls

            logger.info(f"[FILE UPLOAD] Found {len(pdf_urls)} unique PDF file(s) to download")

            # Build a set of already-uploaded file hashes to catch content-level duplicates
            existing_record = self.mongo_client.get_judgment(judgment.judgment_id)
            uploaded_hashes = {
                f.get('file_hash') for f in (existing_record.files if existing_record else []) or []
                if f.get('file_hash')
            }

            # Process each PDF file
            files_processed = 0
            files_skipped_duplicate = 0
            for i, pdf_url in enumerate(pdf_urls, 1):
                try:
                    logger.info(f"[FILE UPLOAD] Processing file {i}/{len(pdf_urls)}: {pdf_url}")

                    # Download file
                    file_path = self.download_judgment_file({'file_url': pdf_url})
                    if not file_path:
                        logger.warning(f"[FILE UPLOAD] Failed to download file {i}: {pdf_url}")
                        continue

                    # Compute file hash before uploading to detect content duplicates
                    import hashlib
                    with open(file_path, 'rb') as fh:
                        file_hash = hashlib.md5(fh.read()).hexdigest()

                    if file_hash in uploaded_hashes:
                        logger.info(f"[FILE UPLOAD] Skipping file {i} — identical content already uploaded (hash: {file_hash})")
                        files_skipped_duplicate += 1
                        try:
                            os.remove(file_path)
                        except Exception:
                            pass
                        continue

                    # Prepare metadata for S3
                    s3_metadata = {
                        "petitioner_respondent": judgment.petitioner_respondent or "Unknown",
                        "judge": judgment.judgment_by or "Unknown",
                        "bench": judgment.bench or "Unknown",
                        "diary_number": judgment.diary_number or "Unknown"
                    }

                    # Upload to S3
                    s3_result = self.s3_client.upload_file(
                        file_path,
                        judgment.judgment_date,
                        judgment.case_number,
                        s3_metadata,
                        court_type="supreme_court"
                    )

                    if s3_result:
                        # Track hash so subsequent files in this batch are also checked
                        uploaded_hashes.add(file_hash)

                        # Prepare file info for MongoDB
                        file_info = {
                            "source_url": pdf_url,
                            "file_name": os.path.basename(file_path),
                            "file_size": os.path.getsize(file_path),
                            "file_type": "pdf",
                            "s3_bucket": s3_result.get("bucket"),
                            "s3_key": s3_result.get("key"),
                            "s3_url": s3_result.get("url"),
                            "s3_metadata": s3_result.get("metadata", {}),
                            "uploaded_date": datetime.utcnow().isoformat(),
                            "file_hash": file_hash,
                            "document_type": f"judgment_{i}" if len(pdf_urls) > 1 else "judgment"
                        }
                        
                        # Add file to judgment's files array
                        self.mongo_client.add_file_to_judgment(judgment.judgment_id, file_info)
                        
                        # Update legacy fields for first file
                        if i == 1:
                            self.mongo_client.mark_as_uploaded(judgment.judgment_id, s3_result)
                        
                        logger.info(f"[FILE UPLOAD] ✓ Successfully uploaded file {i}/{len(pdf_urls)} to S3: {s3_result.get('key')}")
                        files_processed += 1
                    else:
                        logger.warning(f"[FILE UPLOAD] ✗ Failed to upload file {i} to S3")
                    
                    # Clean up local file
                    try:
                        os.remove(file_path)
                        logger.debug(f"[FILE UPLOAD] Cleaned up local file: {file_path}")
                    except Exception as e:
                        logger.warning(f"[FILE UPLOAD] Failed to delete local file: {e}")
                        
                except Exception as e:
                    logger.error(f"[FILE UPLOAD] Error processing file {i}: {e}")
                    # Clean up local file even on exception to prevent disk fill
                    if 'file_path' in locals() and file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            logger.debug(f"[FILE UPLOAD] Cleaned up local file after error: {file_path}")
                        except Exception:
                            pass
                    continue
            
            # Mark as completed
            if files_processed > 0:
                self.mongo_client.mark_as_completed(judgment.judgment_id)
                logger.info(f"[FILE UPLOAD] ✓ Completed: {files_processed} uploaded, {files_skipped_duplicate} skipped (duplicate content)")
                self.stats["successful_downloads"] += 1
                return True
            elif files_skipped_duplicate == len(pdf_urls):
                # All files were content-duplicates already on S3 — still a success
                self.mongo_client.mark_as_completed(judgment.judgment_id)
                logger.info(f"[FILE UPLOAD] ✓ All {files_skipped_duplicate} file(s) already uploaded (duplicate content), marking complete")
                self.stats["successful_downloads"] += 1
                return True
            else:
                self.mongo_client.mark_as_failed(judgment.judgment_id, "No files uploaded successfully")
                logger.error(f"[FILE UPLOAD] ✗ Failed to upload any files for judgment")
                self.stats["upload_failures"] += 1
                return False
                
        except Exception as e:
            logger.error(f"[FILE UPLOAD] Failed to process judgment: {e}")
            import traceback
            logger.error(f"[FILE UPLOAD] Traceback: {traceback.format_exc()}")
            if 'judgment' in locals():
                self.mongo_client.mark_as_failed(judgment.judgment_id, str(e))
            self.stats["failed_downloads"] += 1
            return False
    
    def process_judgment(self, judgment_data: Dict[str, str], date_range: DateRange) -> bool:
        """Backward compatible wrapper - routes to multiple files handler"""
        return self.process_judgment_with_multiple_files(judgment_data, date_range)
    
    def process_date_range(self, date_range: DateRange) -> bool:
        """Process all judgments for a specific date range"""
        try:
            logger.info(f"Processing date range: {date_range}")

            # Reset per-range network capture state so responses/endpoints from a
            # previous range don't leak into this one (and don't grow unbounded).
            self.captured_responses = []
            self.api_endpoints = []

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
            
            # Process each judgment: download PDFs and upload to S3
            if judgments:
                logger.info(f"Found {len(judgments)} judgments to process for date range: {date_range}")
                
                successful = 0
                failed = 0
                
                for i, judgment_data in enumerate(judgments, 1):
                    try:
                        logger.info(f"Processing judgment {i}/{len(judgments)}")
                        
                        # Process judgment with file download and S3 upload
                        if self.process_judgment_with_multiple_files(judgment_data, date_range):
                            successful += 1
                        else:
                            failed += 1
                            
                    except Exception as e:
                        logger.error(f"Error processing judgment {i}: {e}")
                        failed += 1
                    
                    # Small delay between processing judgments
                    time.sleep(1)
                
                self.stats["total_processed"] += len(judgments)
                logger.info(f"Completed processing {len(judgments)} judgments: {successful} successful, {failed} failed")
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
