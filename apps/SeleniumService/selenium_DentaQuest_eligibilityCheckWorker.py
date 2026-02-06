from selenium import webdriver
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import os
import base64

from dentaquest_browser_manager import get_browser_manager

class AutomationDentaQuestEligibilityCheck:    
    def __init__(self, data):
        self.headless = False
        self.driver = None

        self.data = data.get("data", {}) if isinstance(data, dict) else {}

        # Flatten values for convenience
        self.memberId = self.data.get("memberId", "")
        self.dateOfBirth = self.data.get("dateOfBirth", "")
        self.firstName = self.data.get("firstName", "")
        self.lastName = self.data.get("lastName", "")
        self.dentaquest_username = self.data.get("dentaquestUsername", "")
        self.dentaquest_password = self.data.get("dentaquestPassword", "")

        # Use browser manager's download dir
        self.download_dir = get_browser_manager().download_dir
        os.makedirs(self.download_dir, exist_ok=True)

    def config_driver(self):
        # Use persistent browser from manager (keeps device trust tokens)
        self.driver = get_browser_manager().get_driver(self.headless)

    def _force_logout(self):
        """Force logout by clearing cookies for DentaQuest domain."""
        try:
            print("[DentaQuest login] Forcing logout due to credential change...")
            browser_manager = get_browser_manager()
            
            # First try to click logout button if visible
            try:
                self.driver.get("https://providers.dentaquest.com/")
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
                        print("[DentaQuest login] Clicked logout button")
                        time.sleep(2)
                        break
                    except TimeoutException:
                        continue
            except Exception as e:
                print(f"[DentaQuest login] Could not click logout button: {e}")
            
            # Clear cookies as backup
            try:
                self.driver.delete_all_cookies()
                print("[DentaQuest login] Cleared all cookies")
            except Exception as e:
                print(f"[DentaQuest login] Error clearing cookies: {e}")
            
            browser_manager.clear_credentials_hash()
            print("[DentaQuest login] Logout complete")
            return True
        except Exception as e:
            print(f"[DentaQuest login] Error during forced logout: {e}")
            return False

    def login(self, url):
        wait = WebDriverWait(self.driver, 30)
        browser_manager = get_browser_manager()
        
        try:
            # Check if credentials have changed - if so, force logout first
            if self.dentaquest_username and browser_manager.credentials_changed(self.dentaquest_username):
                self._force_logout()
                self.driver.get(url)
                time.sleep(2)
            
            # First check if we're already on a logged-in page (from previous run)
            try:
                current_url = self.driver.current_url
                print(f"[DentaQuest login] Current URL: {current_url}")
                
                # Check if we're already on dashboard with member search
                if "dashboard" in current_url.lower() or "member" in current_url.lower():
                    try:
                        member_search = WebDriverWait(self.driver, 3).until(
                            EC.presence_of_element_located((By.XPATH, '//input[@placeholder="Search by member ID"]'))
                        )
                        print("[DentaQuest login] Already on dashboard with member search")
                        return "ALREADY_LOGGED_IN"
                    except TimeoutException:
                        pass
            except Exception as e:
                print(f"[DentaQuest login] Error checking current state: {e}")
            
            # Navigate to login URL
            self.driver.get(url)
            time.sleep(3)
            
            current_url = self.driver.current_url
            print(f"[DentaQuest login] After navigation URL: {current_url}")
            
            # If already on dashboard, we're logged in
            if "dashboard" in current_url.lower():
                print("[DentaQuest login] Already on dashboard")
                return "ALREADY_LOGGED_IN"
            
            # Try to dismiss the modal by clicking OK
            try:
                ok_button = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[normalize-space(text())='Ok' or normalize-space(text())='OK' or normalize-space(text())='Continue']"))
                )
                ok_button.click()
                print("[DentaQuest login] Clicked OK modal button")
                time.sleep(3)
            except TimeoutException:
                print("[DentaQuest login] No OK modal button found")
            
            # Check if we're now on dashboard (session was valid)
            current_url = self.driver.current_url
            print(f"[DentaQuest login] After modal click URL: {current_url}")
            
            if "dashboard" in current_url.lower():
                # Check for member search input to confirm logged in
                try:
                    member_search = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, '//input[@placeholder="Search by member ID"]'))
                    )
                    print("[DentaQuest login] Session valid - on dashboard with member search")
                    return "ALREADY_LOGGED_IN"
                except TimeoutException:
                    pass
            
            # Check if OTP is required (popup window or OTP input)
            if len(self.driver.window_handles) > 1:
                original_window = self.driver.current_window_handle
                for window in self.driver.window_handles:
                    if window != original_window:
                        self.driver.switch_to.window(window)
                        print("[DentaQuest login] Switched to popup window")
                        break
                
                try:
                    otp_input = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, "//input[@type='tel' or contains(@placeholder,'code') or contains(@aria-label,'Verification')]"))
                    )
                    print("[DentaQuest login] OTP input found in popup")
                    return "OTP_REQUIRED"
                except TimeoutException:
                    self.driver.switch_to.window(original_window)
            
            # Check for OTP input on main page
            try:
                otp_input = WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@type='tel' or contains(@placeholder,'code') or contains(@aria-label,'Verification')]"))
                )
                print("[DentaQuest login] OTP input found")
                return "OTP_REQUIRED"
            except TimeoutException:
                pass
            
            # If still on login page, need to fill credentials
            if "onboarding" in current_url.lower() or "login" in current_url.lower():
                print("[DentaQuest login] Need to fill login credentials")
                
                try:
                    email_field = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//input[@name='username' or @type='text']"))
                    )
                    email_field.clear()
                    email_field.send_keys(self.dentaquest_username)
                    
                    password_field = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='password']")))
                    password_field.clear()
                    password_field.send_keys(self.dentaquest_password)
                    
                    # Click login button
                    login_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
                    login_button.click()
                    print("[DentaQuest login] Submitted login form")
                    
                    # Save credentials hash after login attempt
                    if self.dentaquest_username:
                        browser_manager.save_credentials_hash(self.dentaquest_username)
                    
                    # OTP detection - wait up to 30 seconds for OTP input to appear (like Delta MA)
                    # Use comprehensive XPath to detect various OTP input patterns
                    try:
                        otp_input = WebDriverWait(self.driver, 30).until(
                            EC.presence_of_element_located((By.XPATH, 
                                "//input[@type='tel' or contains(@placeholder,'code') or contains(@placeholder,'Code') or "
                                "contains(@aria-label,'Verification') or contains(@aria-label,'verification') or "
                                "contains(@aria-label,'Code') or contains(@aria-label,'code') or "
                                "contains(@placeholder,'verification') or contains(@placeholder,'Verification') or "
                                "contains(@name,'otp') or contains(@name,'code') or contains(@id,'otp') or contains(@id,'code')]"
                            ))
                        )
                        print("[DentaQuest login] OTP input detected -> OTP_REQUIRED")
                        return "OTP_REQUIRED"
                    except TimeoutException:
                        print("[DentaQuest login] No OTP input detected in 30 seconds")
                    
                    # Check if login succeeded (redirected to dashboard or member search)
                    current_url_after_login = self.driver.current_url.lower()
                    print(f"[DentaQuest login] After login URL: {current_url_after_login}")
                    
                    if "dashboard" in current_url_after_login or "member" in current_url_after_login:
                        # Verify by checking for member search input
                        try:
                            member_search = WebDriverWait(self.driver, 5).until(
                                EC.presence_of_element_located((By.XPATH, '//input[@placeholder="Search by member ID"]'))
                            )
                            print("[DentaQuest login] Login successful - now on member search page")
                            return "SUCCESS"
                        except TimeoutException:
                            pass
                    
                    # Still on login page - login failed
                    if "onboarding" in current_url_after_login or "login" in current_url_after_login:
                        print("[DentaQuest login] Login failed - still on login page")
                        return "ERROR: Login failed - check credentials"
                    
                except TimeoutException:
                    print("[DentaQuest login] Login form elements not found")
                    return "ERROR: Login form not found"
            
            # If we got here without going through login, we're already logged in
            return "SUCCESS"
                
        except Exception as e:
            print(f"[DentaQuest login] Exception: {e}")
            return f"ERROR:LOGIN FAILED: {e}"

    def step1(self):
        """Navigate to member search - fills all available fields (Member ID, First Name, Last Name, DOB)"""
        wait = WebDriverWait(self.driver, 30)

        try:
            # Log what fields are available for search
            fields = []
            if self.memberId:
                fields.append(f"ID: {self.memberId}")
            if self.firstName:
                fields.append(f"FirstName: {self.firstName}")
            if self.lastName:
                fields.append(f"LastName: {self.lastName}")
            fields.append(f"DOB: {self.dateOfBirth}")
            print(f"[DentaQuest step1] Starting member search with: {', '.join(fields)}")
            
            # Wait for page to be ready
            time.sleep(2)
            
            # Parse DOB - format: YYYY-MM-DD
            try:
                dob_parts = self.dateOfBirth.split("-")
                dob_year = dob_parts[0]
                dob_month = dob_parts[1].zfill(2)
                dob_day = dob_parts[2].zfill(2)
                print(f"[DentaQuest step1] Parsed DOB: {dob_month}/{dob_day}/{dob_year}")
            except Exception as e:
                print(f"[DentaQuest step1] Error parsing DOB: {e}")
                return "ERROR: PARSING DOB"

            # Helper function to fill contenteditable date spans within a specific container
            def fill_date_by_testid(testid, month_val, day_val, year_val, field_name):
                try:
                    container = self.driver.find_element(By.XPATH, f"//div[@data-testid='{testid}']")
                    month_elem = container.find_element(By.XPATH, ".//span[@data-type='month' and @contenteditable='true']")
                    day_elem = container.find_element(By.XPATH, ".//span[@data-type='day' and @contenteditable='true']")
                    year_elem = container.find_element(By.XPATH, ".//span[@data-type='year' and @contenteditable='true']")
                    
                    def replace_with_sendkeys(el, value):
                        el.click()
                        time.sleep(0.05)
                        el.send_keys(Keys.CONTROL, "a")
                        el.send_keys(Keys.BACKSPACE)
                        el.send_keys(value)

                    replace_with_sendkeys(month_elem, month_val)
                    time.sleep(0.1)
                    replace_with_sendkeys(day_elem, day_val)
                    time.sleep(0.1)
                    replace_with_sendkeys(year_elem, year_val)
                    print(f"[DentaQuest step1] Filled {field_name}: {month_val}/{day_val}/{year_val}")
                    return True
                except Exception as e:
                    print(f"[DentaQuest step1] Error filling {field_name}: {e}")
                    return False

            # 1. Select Provider from dropdown (required field)
            try:
                print("[DentaQuest step1] Selecting Provider...")
                # Try to find and click Provider dropdown
                provider_selectors = [
                    "//label[contains(text(),'Provider')]/following-sibling::*//div[contains(@class,'select')]",
                    "//div[contains(@data-testid,'provider')]//div[contains(@class,'select')]",
                    "//*[@aria-label='Provider']",
                    "//select[contains(@name,'provider') or contains(@id,'provider')]",
                    "//div[contains(@class,'provider')]//input",
                    "//label[contains(text(),'Provider')]/..//div[contains(@class,'control')]"
                ]
                
                provider_clicked = False
                for selector in provider_selectors:
                    try:
                        provider_dropdown = WebDriverWait(self.driver, 3).until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                        provider_dropdown.click()
                        print(f"[DentaQuest step1] Clicked provider dropdown with selector: {selector}")
                        time.sleep(0.5)
                        provider_clicked = True
                        break
                    except TimeoutException:
                        continue
                
                if provider_clicked:
                    # Select first available provider option
                    option_selectors = [
                        "//div[contains(@class,'option') and not(contains(@class,'disabled'))]",
                        "//li[contains(@class,'option')]",
                        "//option[not(@disabled)]",
                        "//*[@role='option']"
                    ]
                    
                    for opt_selector in option_selectors:
                        try:
                            options = self.driver.find_elements(By.XPATH, opt_selector)
                            if options:
                                # Select first non-placeholder option
                                for opt in options:
                                    opt_text = opt.text.strip()
                                    if opt_text and "select" not in opt_text.lower():
                                        opt.click()
                                        print(f"[DentaQuest step1] Selected provider: {opt_text}")
                                        break
                                break
                        except:
                            continue
                    
                    # Close dropdown if still open
                    ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(0.3)
                else:
                    print("[DentaQuest step1] Warning: Could not find Provider dropdown")
                    
            except Exception as e:
                print(f"[DentaQuest step1] Error selecting provider: {e}")
            
            time.sleep(0.3)

            # 2. Fill Date of Birth with patient's DOB using specific data-testid
            fill_date_by_testid("member-search_date-of-birth", dob_month, dob_day, dob_year, "Date of Birth")
            time.sleep(0.3)

            # 3. Fill ALL available search fields (flexible search)
            # Fill Member ID if provided
            if self.memberId:
                try:
                    member_id_input = wait.until(EC.presence_of_element_located(
                        (By.XPATH, '//input[@placeholder="Search by member ID"]')
                    ))
                    member_id_input.clear()
                    member_id_input.send_keys(self.memberId)
                    print(f"[DentaQuest step1] Entered member ID: {self.memberId}")
                    time.sleep(0.2)
                except Exception as e:
                    print(f"[DentaQuest step1] Warning: Could not fill member ID: {e}")
            
            # Fill First Name if provided
            if self.firstName:
                try:
                    first_name_input = wait.until(EC.presence_of_element_located(
                        (By.XPATH, '//input[@placeholder="First name - 1 char minimum" or contains(@placeholder,"first name") or contains(@name,"firstName") or contains(@id,"firstName")]')
                    ))
                    first_name_input.clear()
                    first_name_input.send_keys(self.firstName)
                    print(f"[DentaQuest step1] Entered first name: {self.firstName}")
                    time.sleep(0.2)
                except Exception as e:
                    print(f"[DentaQuest step1] Warning: Could not fill first name: {e}")
            
            # Fill Last Name if provided
            if self.lastName:
                try:
                    last_name_input = wait.until(EC.presence_of_element_located(
                        (By.XPATH, '//input[@placeholder="Last name - 2 char minimum" or contains(@placeholder,"last name") or contains(@name,"lastName") or contains(@id,"lastName")]')
                    ))
                    last_name_input.clear()
                    last_name_input.send_keys(self.lastName)
                    print(f"[DentaQuest step1] Entered last name: {self.lastName}")
                    time.sleep(0.2)
                except Exception as e:
                    print(f"[DentaQuest step1] Warning: Could not fill last name: {e}")

            time.sleep(0.3)

            # 4. Click Search button
            try:
                search_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, '//button[@data-testid="member-search_search-button"]')
                ))
                search_btn.click()
                print("[DentaQuest step1] Clicked search button")
            except TimeoutException:
                # Fallback
                try:
                    search_btn = self.driver.find_element(By.XPATH, '//button[contains(text(),"Search")]')
                    search_btn.click()
                    print("[DentaQuest step1] Clicked search button (fallback)")
                except:
                    # Press Enter on the last input field
                    ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                    print("[DentaQuest step1] Pressed Enter to search")
            
            time.sleep(5)
            
            # Check for "no results" error
            try:
                error_msg = WebDriverWait(self.driver, 3).until(EC.presence_of_element_located(
                    (By.XPATH, '//*[contains(@data-testid,"no-results") or contains(@class,"no-results") or contains(text(),"No results") or contains(text(),"not found") or contains(text(),"No member found") or contains(text(),"Nothing was found")]')
                ))
                if error_msg and error_msg.is_displayed():
                    print("[DentaQuest step1] No results found")
                    return "ERROR: INVALID SEARCH CRITERIA"
            except TimeoutException:
                pass

            print("[DentaQuest step1] Search completed successfully")
            return "Success"

        except Exception as e: 
            print(f"[DentaQuest step1] Exception: {e}")
            return f"ERROR:STEP1 - {e}"

    
    def step2(self):
        """Get eligibility status, navigate to detail page, and capture PDF"""
        wait = WebDriverWait(self.driver, 90)

        try:
            print("[DentaQuest step2] Starting eligibility capture")
            
            # Wait for results table to load (use explicit wait instead of fixed sleep)
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//tbody//tr"))
                )
            except TimeoutException:
                print("[DentaQuest step2] Warning: Results table not found within timeout")
            
            # 1) Find and extract eligibility status and Member ID from search results
            eligibilityText = "unknown"
            foundMemberId = ""
            
            # Try to extract Member ID from the search results
            import re
            try:
                # Look for Member ID in various places
                member_id_selectors = [
                    "(//tbody//tr)[1]//td[contains(text(),'ID:') or contains(@data-testid,'member-id')]",
                    "//span[contains(text(),'Member ID')]/..//span",
                    "//div[contains(text(),'Member ID')]",
                    "(//tbody//tr)[1]//td[2]",  # Often Member ID is in second column
                ]
                
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                
                # Try regex patterns to find Member ID
                patterns = [
                    r'Member ID[:\s]+([A-Z0-9]+)',
                    r'ID[:\s]+([A-Z0-9]{5,})',
                    r'MemberID[:\s]+([A-Z0-9]+)',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, page_text, re.IGNORECASE)
                    if match:
                        foundMemberId = match.group(1).strip()
                        print(f"[DentaQuest step2] Extracted Member ID: {foundMemberId}")
                        break
                
                if not foundMemberId:
                    for selector in member_id_selectors:
                        try:
                            elem = self.driver.find_element(By.XPATH, selector)
                            text = elem.text.strip()
                            # Extract just the ID part
                            id_match = re.search(r'([A-Z0-9]{5,})', text)
                            if id_match:
                                foundMemberId = id_match.group(1)
                                print(f"[DentaQuest step2] Found Member ID via selector: {foundMemberId}")
                                break
                        except:
                            continue
            except Exception as e:
                print(f"[DentaQuest step2] Error extracting Member ID: {e}")
            
            # Extract eligibility status
            status_selectors = [
                "(//tbody//tr)[1]//a[contains(@href, 'eligibility')]",
                "//a[contains(@href,'eligibility')]",
                "//*[contains(@class,'status')]",
                "//*[contains(text(),'Active') or contains(text(),'Inactive') or contains(text(),'Eligible')]"
            ]
            
            for selector in status_selectors:
                try:
                    status_elem = self.driver.find_element(By.XPATH, selector)
                    status_text = status_elem.text.strip().lower()
                    if status_text:
                        print(f"[DentaQuest step2] Found status with selector '{selector}': {status_text}")
                        if "active" in status_text or "eligible" in status_text:
                            eligibilityText = "active"
                            break
                        elif "inactive" in status_text or "ineligible" in status_text:
                            eligibilityText = "inactive"
                            break
                except:
                    continue
            
            print(f"[DentaQuest step2] Final eligibility status: {eligibilityText}")

            # 2) Find the patient detail link and navigate DIRECTLY to it
            print("[DentaQuest step2] Looking for patient detail link...")
            patient_name_clicked = False
            patientName = ""
            detail_url = None
            current_url_before = self.driver.current_url
            print(f"[DentaQuest step2] Current URL before: {current_url_before}")
            
            # Find all links in first row and log them
            try:
                all_links = self.driver.find_elements(By.XPATH, "(//tbody//tr)[1]//a")
                print(f"[DentaQuest step2] Found {len(all_links)} links in first row:")
                for i, link in enumerate(all_links):
                    href = link.get_attribute("href") or "no-href"
                    text = link.text.strip() or "(empty text)"
                    print(f"  Link {i}: href={href[:80]}..., text={text}")
            except Exception as e:
                print(f"[DentaQuest step2] Error listing links: {e}")
            
            # Find the patient detail link
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
                    patientName = patient_link.text.strip()
                    href = patient_link.get_attribute("href")
                    print(f"[DentaQuest step2] Found patient link: text='{patientName}', href={href}")
                    
                    if href and ("member-details" in href or "member" in href):
                        detail_url = href
                        patient_name_clicked = True
                        print(f"[DentaQuest step2] Will navigate directly to: {detail_url}")
                        break
                except Exception as e:
                    print(f"[DentaQuest step2] Selector '{selector}' failed: {e}")
                    continue
            
            if not detail_url:
                # Fallback: Try to find ANY link to member-details
                try:
                    all_links = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'member')]")
                    if all_links:
                        detail_url = all_links[0].get_attribute("href")
                        patient_name_clicked = True
                        print(f"[DentaQuest step2] Found member link: {detail_url}")
                except Exception as e:
                    print(f"[DentaQuest step2] Could not find member link: {e}")
            
            # Navigate to detail page DIRECTLY
            if patient_name_clicked and detail_url:
                print(f"[DentaQuest step2] Navigating directly to detail page: {detail_url}")
                self.driver.get(detail_url)
                time.sleep(3)  # Wait for page to load
                
                current_url_after = self.driver.current_url
                print(f"[DentaQuest step2] Current URL after navigation: {current_url_after}")
                
                if "member-details" in current_url_after or "member" in current_url_after:
                    print("[DentaQuest step2] Successfully navigated to member details page!")
                else:
                    print(f"[DentaQuest step2] WARNING: Navigation might have redirected. Current URL: {current_url_after}")
                
                # Wait for page to be ready
                try:
                    WebDriverWait(self.driver, 30).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                except Exception:
                    print("[DentaQuest step2] Warning: document.readyState did not become 'complete'")
                
                # Wait for member details content to load
                print("[DentaQuest step2] Waiting for member details content to fully load...")
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
                        print(f"[DentaQuest step2] Content element found: {selector}")
                        break
                    except:
                        continue
                
                if not content_loaded:
                    print("[DentaQuest step2] Warning: Could not verify content loaded, waiting extra time...")
                
                # Additional wait for dynamic content
                time.sleep(5)
                
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
                                if not any(x in name_text.lower() for x in ['active', 'inactive', 'eligible', 'search', 'date', 'print', 'member id']):
                                    patientName = name_text
                                    print(f"[DentaQuest step2] Found patient name on detail page: {patientName}")
                                    break
                        except:
                            continue
            else:
                print("[DentaQuest step2] Warning: Could not find detail URL, capturing search results page")
                # Still try to get patient name from search results
                try:
                    name_elem = self.driver.find_element(By.XPATH, "(//tbody//tr)[1]//td[1]")
                    patientName = name_elem.text.strip()
                except:
                    pass

            if not patientName:
                print("[DentaQuest step2] Could not extract patient name")
            else:
                print(f"[DentaQuest step2] Patient name: {patientName}")

            # Wait for page to fully load before generating PDF
            try:
                WebDriverWait(self.driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception:
                pass

            time.sleep(1)

            # Generate PDF of the detailed patient page using Chrome DevTools Protocol
            print("[DentaQuest step2] Generating PDF of patient detail page...")
            
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
            pdf_path = os.path.join(self.download_dir, f"dentaquest_eligibility_{self.memberId}_{int(time.time())}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(pdf_data)
            print(f"[DentaQuest step2] PDF saved: {pdf_path}")

            # Close the browser window after PDF generation
            try:
                from dentaquest_browser_manager import get_browser_manager
                get_browser_manager().quit_driver()
                print("[DentaQuest step2] Browser closed")
            except Exception as e:
                print(f"[DentaQuest step2] Error closing browser: {e}")
            
            output = {
                "status": "success",
                "eligibility": eligibilityText,
                "ss_path": pdf_path,  # Keep key as ss_path for backward compatibility
                "pdf_path": pdf_path,  # Also add explicit pdf_path
                "patientName": patientName,
                "memberId": foundMemberId  # Member ID extracted from the page
            }
            print(f"[DentaQuest step2] Success: {output}")
            return output
            
        except Exception as e:
            print(f"[DentaQuest step2] Exception: {e}")
            # Cleanup download folder on error
            try:
                dl = os.path.abspath(self.download_dir)
                if os.path.isdir(dl):
                    for name in os.listdir(dl):
                        item = os.path.join(dl, name)
                        try:
                            if os.path.isfile(item) or os.path.islink(item):
                                os.remove(item)
                        except Exception:
                            pass
            except Exception:
                pass
            return {"status": "error", "message": str(e)}

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
                "message": str(e)
            }
