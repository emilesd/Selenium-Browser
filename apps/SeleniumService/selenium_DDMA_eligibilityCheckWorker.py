from selenium import webdriver
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import os
import base64

from ddma_browser_manager import get_browser_manager

class AutomationDeltaDentalMAEligibilityCheck:    
    def __init__(self, data):
        self.headless = False
        self.driver = None

        self.data = data.get("data", {}) if isinstance(data, dict) else {}


        # Flatten values for convenience
        self.memberId = self.data.get("memberId", "")
        self.dateOfBirth = self.data.get("dateOfBirth", "")
        self.firstName = self.data.get("firstName", "")
        self.lastName = self.data.get("lastName", "")
        self.massddma_username = self.data.get("massddmaUsername", "")
        self.massddma_password = self.data.get("massddmaPassword", "")

        # Use browser manager's download dir
        self.download_dir = get_browser_manager().download_dir
        os.makedirs(self.download_dir, exist_ok=True)

    def config_driver(self):
        # Use persistent browser from manager (keeps device trust tokens)
        self.driver = get_browser_manager().get_driver(self.headless)

    def _force_logout(self):
        """Force logout by clearing cookies for Delta Dental domain."""
        try:
            print("[DDMA login] Forcing logout due to credential change...")
            browser_manager = get_browser_manager()
            
            # First try to click logout button if visible
            try:
                self.driver.get("https://providers.deltadentalma.com/")
                time.sleep(2)
                
                logout_selectors = [
                    "//button[contains(text(), 'Log out') or contains(text(), 'Logout') or contains(text(), 'Sign out')]",
                    "//a[contains(text(), 'Log out') or contains(text(), 'Logout') or contains(text(), 'Sign out')]",
                    "//button[@aria-label='Log out' or @aria-label='Logout' or @aria-label='Sign out']",
                    "//*[contains(@class, 'logout') or contains(@class, 'signout')]"
                ]
                
                for selector in logout_selectors:
                    try:
                        logout_btn = WebDriverWait(self.driver, 3).until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                        logout_btn.click()
                        print("[DDMA login] Clicked logout button")
                        time.sleep(2)
                        break
                    except TimeoutException:
                        continue
            except Exception as e:
                print(f"[DDMA login] Could not click logout button: {e}")
            
            # Clear cookies as backup
            try:
                self.driver.delete_all_cookies()
                print("[DDMA login] Cleared all cookies")
            except Exception as e:
                print(f"[DDMA login] Error clearing cookies: {e}")
            
            browser_manager.clear_credentials_hash()
            print("[DDMA login] Logout complete")
            return True
        except Exception as e:
            print(f"[DDMA login] Error during forced logout: {e}")
            return False

    def login(self, url):
        wait = WebDriverWait(self.driver, 30)
        browser_manager = get_browser_manager()
        
        try:
            # Check if credentials have changed - if so, force logout first
            if self.massddma_username and browser_manager.credentials_changed(self.massddma_username):
                self._force_logout()
                self.driver.get(url)
                time.sleep(2)
            
            # First check if we're already on a logged-in page (from previous run)
            try:
                current_url = self.driver.current_url
                print(f"[login] Current URL: {current_url}")
                
                # Check if we're on any logged-in page (dashboard, member pages, etc.)
                logged_in_patterns = ["member", "dashboard", "eligibility", "search", "patients"]
                is_logged_in_url = any(pattern in current_url.lower() for pattern in logged_in_patterns)
                
                if is_logged_in_url and "onboarding" not in current_url.lower():
                    print(f"[login] Already on logged-in page - skipping login entirely")
                    # Navigate directly to member search if not already there
                    if "member" not in current_url.lower():
                        # Try to find a link to member search or just check for search input
                        try:
                            member_search = WebDriverWait(self.driver, 5).until(
                                EC.presence_of_element_located((By.XPATH, '//input[@placeholder="Search by member ID"]'))
                            )
                            print("[login] Found member search input - returning ALREADY_LOGGED_IN")
                            return "ALREADY_LOGGED_IN"
                        except TimeoutException:
                            # Try navigating to members page
                            members_url = "https://providers.deltadentalma.com/members"
                            print(f"[login] Navigating to members page: {members_url}")
                            self.driver.get(members_url)
                            time.sleep(2)
                    
                    # Verify we have the member search input
                    try:
                        member_search = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.XPATH, '//input[@placeholder="Search by member ID"]'))
                        )
                        print("[login] Member search found - ALREADY_LOGGED_IN")
                        return "ALREADY_LOGGED_IN"
                    except TimeoutException:
                        print("[login] Could not find member search, will try login")
            except Exception as e:
                print(f"[login] Error checking current state: {e}")
            
            # Navigate to login URL
            self.driver.get(url)
            time.sleep(2)  # Wait for page to load and any redirects
            
            # Check if we got redirected to member search (session still valid)
            try:
                current_url = self.driver.current_url
                print(f"[login] URL after navigation: {current_url}")
                
                if "onboarding" not in current_url.lower():
                    member_search = WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.XPATH, '//input[@placeholder="Search by member ID"]'))
                    )
                    if member_search:
                        print("[login] Session valid - skipping login")
                        return "ALREADY_LOGGED_IN"
            except TimeoutException:
                print("[login] Proceeding with login")
            
            # Dismiss any "Authentication flow continued in another tab" modal
            modal_dismissed = False
            try:
                ok_button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[normalize-space(text())='Ok' or normalize-space(text())='OK']"))
                )
                ok_button.click()
                print("[login] Dismissed authentication modal")
                modal_dismissed = True
                time.sleep(2)
                
                # Check if a popup window opened for authentication
                all_windows = self.driver.window_handles
                print(f"[login] Windows after modal dismiss: {len(all_windows)}")
                
                if len(all_windows) > 1:
                    # Switch to the auth popup
                    original_window = self.driver.current_window_handle
                    for window in all_windows:
                        if window != original_window:
                            self.driver.switch_to.window(window)
                            print(f"[login] Switched to auth popup window")
                            break
                    
                    # Look for OTP input in the popup
                    try:
                        otp_candidate = WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located(
                                (By.XPATH, "//input[contains(@aria-lable,'Verification code') or contains(@placeholder,'Enter your verification code') or contains(@aria-label,'Verification code')]")
                            )
                        )
                        if otp_candidate:
                            print("[login] OTP input found in popup -> OTP_REQUIRED")
                            return "OTP_REQUIRED"
                    except TimeoutException:
                        print("[login] No OTP in popup, checking main window")
                        self.driver.switch_to.window(original_window)
                        
            except TimeoutException:
                pass  # No modal present
            
            # If modal was dismissed but no popup, page might have changed - wait and check
            if modal_dismissed:
                time.sleep(2)
                # Check if we're now on member search page (already authenticated)
                try:
                    member_search = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, '//input[@placeholder="Search by member ID"]'))
                    )
                    if member_search:
                        print("[login] Already authenticated after modal dismiss")
                        return "ALREADY_LOGGED_IN"
                except TimeoutException:
                    pass
            
            # Try to fill login form
            try:
                email_field = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@name='username' and @type='text']"))
                )
            except TimeoutException:
                print("[login] Could not find login form - page may have changed")
                return "ERROR: Login form not found"
            
            email_field = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@name='username' and @type='text']")))
            email_field.clear()
            email_field.send_keys(self.massddma_username)

            password_field = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@name='password' and @type='password']")))
            password_field.clear()
            password_field.send_keys(self.massddma_password)

            # remember me
            try:
                remember_me_checkbox = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//label[.//span[contains(text(),'Remember me')]]")
                ))
                remember_me_checkbox.click()
            except:
                print("[login] Remember me checkbox not found (continuing).")

            login_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and @aria-label='Sign in']")))
            login_button.click()
            
            # Save credentials hash after login attempt
            if self.massddma_username:
                browser_manager.save_credentials_hash(self.massddma_username)

            # OTP detection - wait up to 30 seconds for OTP input to appear
            try:
                otp_candidate = WebDriverWait(self.driver, 30).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//input[contains(@aria-lable,'Verification code') or contains(@placeholder,'Enter your verification code')]")
                    )
                )
                if otp_candidate:
                    print("[login] OTP input detected -> OTP_REQUIRED")
                    return "OTP_REQUIRED"
            except TimeoutException:
                print("[login] No OTP input detected in allowed time.")
                # Check if we're now on the member search page (login succeeded without OTP)
                try:
                    current_url = self.driver.current_url.lower()
                    if "member" in current_url or "dashboard" in current_url:
                        member_search = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.XPATH, '//input[@placeholder="Search by member ID"]'))
                        )
                        print("[login] Login successful - now on member search page")
                        return "SUCCESS"
                except TimeoutException:
                    pass
                
                # Check for error messages on page
                try:
                    error_elem = WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.XPATH, "//*[contains(@class,'error') or contains(text(),'invalid') or contains(text(),'failed')]"))
                    )
                    print(f"[login] Login failed - error detected: {error_elem.text}")
                    return f"ERROR:LOGIN FAILED: {error_elem.text}"
                except TimeoutException:
                    pass
                
                # If still on login page, login failed
                if "onboarding" in self.driver.current_url.lower() or "login" in self.driver.current_url.lower():
                    print("[login] Login failed - still on login page")
                    return "ERROR:LOGIN FAILED: Still on login page"
                
                # Otherwise assume success (might be on an intermediate page)
                print("[login] Assuming login succeeded (no errors detected)")
                return "SUCCESS"
        except Exception as e:
            print("[login] Exception during login:", e)
            return f"ERROR:LOGIN FAILED: {e}"

    def step1(self):
        """Fill search form with all available fields (flexible search)"""
        wait = WebDriverWait(self.driver, 30)

        try:
            # Log what fields are available
            fields = []
            if self.memberId:
                fields.append(f"ID: {self.memberId}")
            if self.firstName:
                fields.append(f"FirstName: {self.firstName}")
            if self.lastName:
                fields.append(f"LastName: {self.lastName}")
            if self.dateOfBirth:
                fields.append(f"DOB: {self.dateOfBirth}")
            print(f"[DDMA step1] Starting search with: {', '.join(fields)}")

            # Helper to click, select-all and type
            def replace_with_sendkeys(el, value):
                el.click()
                el.send_keys(Keys.CONTROL, "a")
                el.send_keys(Keys.BACKSPACE)
                el.send_keys(value)

            # 1. Fill Member ID if provided
            if self.memberId:
                try:
                    member_id_input = wait.until(EC.presence_of_element_located(
                        (By.XPATH, '//input[@placeholder="Search by member ID"]')
                    ))
                    member_id_input.clear()
                    member_id_input.send_keys(self.memberId)
                    print(f"[DDMA step1] Entered Member ID: {self.memberId}")
                    time.sleep(0.2)
                except Exception as e:
                    print(f"[DDMA step1] Warning: Could not fill Member ID: {e}")

            # 2. Fill DOB if provided
            if self.dateOfBirth:
                try:
                    dob_parts = self.dateOfBirth.split("-")
                    year = dob_parts[0]
                    month = dob_parts[1].zfill(2)
                    day = dob_parts[2].zfill(2)

                    dob_container = wait.until(
                        EC.presence_of_element_located(
                            (By.XPATH, "//div[@data-testid='member-search_date-of-birth']")
                        )
                    )

                    month_elem = dob_container.find_element(By.XPATH, ".//span[@data-type='month' and @contenteditable='true']")
                    day_elem = dob_container.find_element(By.XPATH, ".//span[@data-type='day' and @contenteditable='true']")
                    year_elem = dob_container.find_element(By.XPATH, ".//span[@data-type='year' and @contenteditable='true']")

                    replace_with_sendkeys(month_elem, month)
                    time.sleep(0.05)
                    replace_with_sendkeys(day_elem, day)
                    time.sleep(0.05)
                    replace_with_sendkeys(year_elem, year)
                    print(f"[DDMA step1] Filled DOB: {month}/{day}/{year}")
                except Exception as e:
                    print(f"[DDMA step1] Warning: Could not fill DOB: {e}")

            # 3. Fill First Name if provided
            if self.firstName:
                try:
                    first_name_input = wait.until(EC.presence_of_element_located(
                        (By.XPATH, '//input[@placeholder="First name - 1 char minimum" or contains(@placeholder,"first name") or contains(@name,"firstName")]')
                    ))
                    first_name_input.clear()
                    first_name_input.send_keys(self.firstName)
                    print(f"[DDMA step1] Entered First Name: {self.firstName}")
                    time.sleep(0.2)
                except Exception as e:
                    print(f"[DDMA step1] Warning: Could not fill First Name: {e}")

            # 4. Fill Last Name if provided
            if self.lastName:
                try:
                    last_name_input = wait.until(EC.presence_of_element_located(
                        (By.XPATH, '//input[@placeholder="Last name - 2 char minimum" or contains(@placeholder,"last name") or contains(@name,"lastName")]')
                    ))
                    last_name_input.clear()
                    last_name_input.send_keys(self.lastName)
                    print(f"[DDMA step1] Entered Last Name: {self.lastName}")
                    time.sleep(0.2)
                except Exception as e:
                    print(f"[DDMA step1] Warning: Could not fill Last Name: {e}")

            time.sleep(0.3)

            # Click Search button
            continue_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, '//button[@data-testid="member-search_search-button"]')
            ))
            continue_btn.click()
            print("[DDMA step1] Clicked Search button")
            
            time.sleep(5)
            
            # Check for error message
            try:
                error_msg = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located(
                    (By.XPATH, '//div[@data-testid="member-search-result-no-results"]')
                ))
                if error_msg:
                    print("[DDMA step1] Error: No results found")
                    return "ERROR: INVALID SEARCH CRITERIA"
            except TimeoutException:
                pass

            print("[DDMA step1] Search completed successfully")
            return "Success"

        except Exception as e: 
            print(f"[DDMA step1] Exception: {e}")
            return f"ERROR:STEP1 - {e}"

    
    def step2(self):
        wait = WebDriverWait(self.driver, 90)

        try:
            # Wait for results table to load
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//tbody//tr"))
                )
            except TimeoutException:
                print("[DDMA step2] Warning: Results table not found within timeout")
            
            # 1) Extract eligibility status and Member ID from search results
            eligibilityText = "unknown"
            foundMemberId = ""
            patientName = ""
            
            # Extract data from first row
            import re
            try:
                first_row = self.driver.find_element(By.XPATH, "(//tbody//tr)[1]")
                row_text = first_row.text.strip()
                print(f"[DDMA step2] First row text: {row_text[:150]}...")
                
                if row_text:
                    lines = row_text.split('\n')
                    
                    # Extract patient name (first line, before "DOB:")
                    if lines:
                        potential_name = lines[0].strip()
                        # Remove DOB if included in the name
                        potential_name = re.sub(r'\s*DOB[:\s]*\d{1,2}/\d{1,2}/\d{2,4}\s*', '', potential_name, flags=re.IGNORECASE).strip()
                        if potential_name and not potential_name.startswith('DOB') and not potential_name.isdigit():
                            patientName = potential_name
                            print(f"[DDMA step2] Extracted patient name from row: '{patientName}'")
                    
                    # Extract Member ID (usually a numeric/alphanumeric ID on its own line)
                    for line in lines:
                        line = line.strip()
                        if line and re.match(r'^[A-Z0-9]{5,}$', line) and not line.startswith('DOB'):
                            foundMemberId = line
                            print(f"[DDMA step2] Extracted Member ID from row: {foundMemberId}")
                            break
                    
                    # Fallback: use input memberId if not found
                    if not foundMemberId and self.memberId:
                        foundMemberId = self.memberId
                        print(f"[DDMA step2] Using input Member ID: {foundMemberId}")
                        
            except Exception as e:
                print(f"[DDMA step2] Error extracting data from row: {e}")
                if self.memberId:
                    foundMemberId = self.memberId
            
            # Extract eligibility status
            try:
                short_wait = WebDriverWait(self.driver, 3)
                status_link = short_wait.until(EC.presence_of_element_located((
                    By.XPATH,
                    "(//tbody//tr)[1]//a[contains(@href, 'member-eligibility-search')]"
                )))
                eligibilityText = status_link.text.strip().lower()
                print(f"[DDMA step2] Found eligibility status: {eligibilityText}")
            except Exception as e:
                print(f"[DDMA step2] Eligibility link not found, trying alternative...")
                try:
                    alt_status = self.driver.find_element(By.XPATH, "//*[contains(text(),'Active') or contains(text(),'Inactive') or contains(text(),'Eligible')]")
                    eligibilityText = alt_status.text.strip().lower()
                    if "active" in eligibilityText or "eligible" in eligibilityText:
                        eligibilityText = "active"
                    elif "inactive" in eligibilityText:
                        eligibilityText = "inactive"
                    print(f"[DDMA step2] Found eligibility via alternative: {eligibilityText}")
                except:
                    pass

            # 2) Click on patient name to navigate to detailed patient page
            print("[DDMA step2] Clicking on patient name to open detailed page...")
            patient_name_clicked = False
            # Note: Don't reset patientName here - preserve the name extracted from row above
            
            # First, let's print what we see on the page for debugging
            current_url_before = self.driver.current_url
            print(f"[DDMA step2] Current URL before click: {current_url_before}")
            
            # Try to find all links in the first row and print them for debugging
            try:
                all_links = self.driver.find_elements(By.XPATH, "(//tbody//tr)[1]//a")
                print(f"[DDMA step2] Found {len(all_links)} links in first row:")
                for i, link in enumerate(all_links):
                    href = link.get_attribute("href") or "no-href"
                    text = link.text.strip() or "(empty text)"
                    print(f"  Link {i}: href={href[:80]}..., text={text}")
            except Exception as e:
                print(f"[DDMA step2] Error listing links: {e}")
            
            # Find the patient detail link and navigate DIRECTLY to it
            detail_url = None
            patient_link_selectors = [
                "(//table//tbody//tr)[1]//td[1]//a",  # First column link
                "(//tbody//tr)[1]//a[contains(@href, 'member-details')]",  # member-details link
                "(//tbody//tr)[1]//a[contains(@href, 'member')]",  # Any member link
            ]
            
            for selector in patient_link_selectors:
                try:
                    patient_link = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, selector))
                    )
                    link_text = patient_link.text.strip()
                    href = patient_link.get_attribute("href")
                    print(f"[DDMA step2] Found patient link: text='{link_text}', href={href}")
                    
                    # Only update patientName if link has text (preserve previously extracted name)
                    if link_text and not patientName:
                        patientName = link_text
                    
                    if href and "member-details" in href:
                        detail_url = href
                        patient_name_clicked = True
                        print(f"[DDMA step2] Will navigate directly to: {detail_url}")
                        break
                except Exception as e:
                    print(f"[DDMA step2] Selector '{selector}' failed: {e}")
                    continue
            
            if not detail_url:
                # Fallback: Try to find ANY link to member-details
                try:
                    all_links = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'member-details')]")
                    if all_links:
                        detail_url = all_links[0].get_attribute("href")
                        patient_name_clicked = True
                        print(f"[DDMA step2] Found member-details link: {detail_url}")
                except Exception as e:
                    print(f"[DDMA step2] Could not find member-details link: {e}")
            
            # Navigate to detail page DIRECTLY instead of clicking (which may open new tab/fail)
            if patient_name_clicked and detail_url:
                print(f"[DDMA step2] Navigating directly to detail page: {detail_url}")
                self.driver.get(detail_url)
                time.sleep(3)  # Wait for page to load
                
                current_url_after = self.driver.current_url
                print(f"[DDMA step2] Current URL after navigation: {current_url_after}")
                
                if "member-details" in current_url_after:
                    print("[DDMA step2] Successfully navigated to member details page!")
                else:
                    print(f"[DDMA step2] WARNING: Navigation might have redirected. Current URL: {current_url_after}")
                
                # Wait for page to be ready
                try:
                    WebDriverWait(self.driver, 30).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                except Exception:
                    print("[DDMA step2] Warning: document.readyState did not become 'complete'")
                
                # Wait for member details content to load (wait for specific elements)
                print("[DDMA step2] Waiting for member details content to fully load...")
                content_loaded = False
                content_selectors = [
                    "//div[contains(@class,'member') or contains(@class,'detail') or contains(@class,'patient')]",
                    "//h1",
                    "//h2",
                    "//table",
                    "//*[contains(text(),'Member ID') or contains(text(),'Name') or contains(text(),'Date of Birth')]",
                ]
                for selector in content_selectors:
                    try:
                        WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, selector))
                        )
                        content_loaded = True
                        print(f"[DDMA step2] Content element found: {selector}")
                        break
                    except:
                        continue
                
                if not content_loaded:
                    print("[DDMA step2] Warning: Could not verify content loaded, waiting extra time...")
                
                # Additional wait for dynamic content and animations
                time.sleep(5)  # Increased from 2 to 5 seconds
                
                # Print page title for debugging
                try:
                    page_title = self.driver.title
                    print(f"[DDMA step2] Page title: {page_title}")
                except:
                    pass
                
                # Try to extract patient name from detailed page if not already found
                if not patientName:
                    detail_name_selectors = [
                        "//h1",
                        "//h2",
                        "//*[contains(@class,'patient-name') or contains(@class,'member-name')]",
                        "//div[contains(@class,'header')]//span",
                    ]
                    for selector in detail_name_selectors:
                        try:
                            name_elem = self.driver.find_element(By.XPATH, selector)
                            name_text = name_elem.text.strip()
                            if name_text and len(name_text) > 1:
                                if not any(x in name_text.lower() for x in ['active', 'inactive', 'eligible', 'search', 'date', 'print']):
                                    patientName = name_text
                                    print(f"[DDMA step2] Found patient name on detail page: {patientName}")
                                    break
                        except:
                            continue
            else:
                print("[DDMA step2] Warning: Could not click on patient, capturing search results page")
                # Still try to get patient name from search results if not already found
                if not patientName:
                    try:
                        name_elem = self.driver.find_element(By.XPATH, "(//tbody//tr)[1]//td[1]")
                        patientName = name_elem.text.strip()
                    except:
                        pass

            if not patientName:
                print("[DDMA step2] Could not extract patient name")
            else:
                print(f"[DDMA step2] Patient name: {patientName}")

            # Wait for page to fully load before generating PDF
            try:
                WebDriverWait(self.driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception:
                pass
            
            time.sleep(1)

            # Generate PDF of the detailed patient page using Chrome DevTools Protocol
            print("[DDMA step2] Generating PDF of patient detail page...")
            
            pdf_options = {
                "landscape": False,
                "displayHeaderFooter": False,
                "printBackground": True,
                "preferCSSPageSize": True,
                "paperWidth": 8.5,  # Letter size in inches
                "paperHeight": 11,
                "marginTop": 0.4,
                "marginBottom": 0.4,
                "marginLeft": 0.4,
                "marginRight": 0.4,
                "scale": 0.9,  # Slightly scale down to fit content
            }
            
            result = self.driver.execute_cdp_cmd("Page.printToPDF", pdf_options)
            pdf_data = base64.b64decode(result.get('data', ''))
            # Use foundMemberId for filename if available, otherwise fall back to input memberId
            pdf_id = foundMemberId or self.memberId or "unknown"
            pdf_path = os.path.join(self.download_dir, f"eligibility_{pdf_id}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(pdf_data)

            print(f"[DDMA step2] PDF saved at: {pdf_path}")
            
            # Close the browser window after PDF generation (session preserved in profile)
            try:
                from ddma_browser_manager import get_browser_manager
                get_browser_manager().quit_driver()
                print("[step2] Browser closed - session preserved in profile")
            except Exception as e:
                print(f"[step2] Error closing browser: {e}")
            
            # Clean patient name - remove DOB if it was included (already cleaned above but double check)
            if patientName:
                # Remove "DOB: MM/DD/YYYY" or similar patterns from the name
                cleaned_name = re.sub(r'\s*DOB[:\s]*\d{1,2}/\d{1,2}/\d{2,4}\s*', '', patientName, flags=re.IGNORECASE).strip()
                if cleaned_name:
                    patientName = cleaned_name
                    print(f"[DDMA step2] Cleaned patient name: {patientName}")
            
            print(f"[DDMA step2] Final data - PatientName: '{patientName}', MemberID: '{foundMemberId}'")
            
            output = {
                    "status": "success",
                    "eligibility": eligibilityText,
                    "ss_path": pdf_path,  # Keep key as ss_path for backward compatibility
                    "pdf_path": pdf_path,  # Also add explicit pdf_path
                    "patientName": patientName,
                    "memberId": foundMemberId  # Include extracted Member ID
                }
            return output
        except Exception as e:
            print("ERROR in step2:", e)
            # Empty the download folder (remove files / symlinks only)
            try:
                dl = os.path.abspath(self.download_dir)
                if os.path.isdir(dl):
                    for name in os.listdir(dl):
                        item = os.path.join(dl, name)
                        try:
                            if os.path.isfile(item) or os.path.islink(item):
                                os.remove(item)
                                print(f"[cleanup] removed: {item}")
                        except Exception as rm_err:
                            print(f"[cleanup] failed to remove {item}: {rm_err}")
                    print(f"[cleanup] emptied download dir: {dl}")
                else:
                    print(f"[cleanup] download dir does not exist: {dl}")
            except Exception as cleanup_exc:
                print(f"[cleanup] unexpected error while cleaning downloads dir: {cleanup_exc}")
            return {"status": "error", "message": str(e)}

        # NOTE: Do NOT quit driver here - keep browser alive for next patient

    def main_workflow(self, url):
        try: 
            self.config_driver()
            self.driver.maximize_window()
            time.sleep(3)

            login_result = self.login(url)
            if login_result.startswith("ERROR"):
                return {"status": "error", "message": login_result}
            if login_result == "OTP_REQUIRED":
                return {"status": "otp_required", "message": "OTP required after login"}

            step1_result = self.step1()
            if step1_result.startswith("ERROR"):
                return {"status": "error", "message": step1_result}

            step2_result = self.step2()
            if step2_result.get("status") == "error":
                return {"status": "error", "message": step2_result.get("message")}

            return step2_result
        except Exception as e: 
            return {
                "status": "error",
                "message": e
            }
        # NOTE: Do NOT quit driver - keep browser alive for next patient
