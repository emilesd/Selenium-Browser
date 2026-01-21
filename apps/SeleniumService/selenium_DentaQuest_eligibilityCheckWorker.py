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

from dentaquest_browser_manager import get_browser_manager

class AutomationDentaQuestEligibilityCheck:    
    def __init__(self, data):
        self.headless = False
        self.driver = None

        self.data = data.get("data", {}) if isinstance(data, dict) else {}

        # Flatten values for convenience
        self.memberId = self.data.get("memberId", "")
        self.dateOfBirth = self.data.get("dateOfBirth", "")
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
                    
                    time.sleep(5)
                    
                    # Check for OTP after login
                    try:
                        otp_input = WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, "//input[@type='tel' or contains(@placeholder,'code') or contains(@aria-label,'Verification')]"))
                        )
                        return "OTP_REQUIRED"
                    except TimeoutException:
                        pass
                    
                    # Check if login succeeded
                    if "dashboard" in self.driver.current_url.lower():
                        return "SUCCESS"
                    
                except TimeoutException:
                    print("[DentaQuest login] Login form elements not found")
                    return "ERROR: Login form not found"
            
            return "SUCCESS"
                
        except Exception as e:
            print(f"[DentaQuest login] Exception: {e}")
            return f"ERROR:LOGIN FAILED: {e}"

    def step1(self):
        """Navigate to member search and enter member ID + DOB"""
        wait = WebDriverWait(self.driver, 30)

        try:
            print(f"[DentaQuest step1] Starting member search for ID: {self.memberId}, DOB: {self.dateOfBirth}")
            
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

            # Get today's date for Date of Service
            from datetime import datetime
            today = datetime.now()
            service_month = str(today.month).zfill(2)
            service_day = str(today.day).zfill(2)
            service_year = str(today.year)
            print(f"[DentaQuest step1] Service date: {service_month}/{service_day}/{service_year}")

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

            # 1. Fill Date of Service with TODAY's date using specific data-testid
            fill_date_by_testid("member-search_date-of-service", service_month, service_day, service_year, "Date of Service")
            time.sleep(0.3)

            # 2. Fill Date of Birth with patient's DOB using specific data-testid
            fill_date_by_testid("member-search_date-of-birth", dob_month, dob_day, dob_year, "Date of Birth")
            time.sleep(0.3)

            # 3. Fill Member ID
            member_id_input = wait.until(EC.presence_of_element_located(
                (By.XPATH, '//input[@placeholder="Search by member ID"]')
            ))
            member_id_input.clear()
            member_id_input.send_keys(self.memberId)
            print(f"[DentaQuest step1] Entered member ID: {self.memberId}")

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
                    member_id_input.send_keys(Keys.RETURN)
                    print("[DentaQuest step1] Pressed Enter to search")
            
            time.sleep(5)
            
            # Check for "no results" error
            try:
                error_msg = WebDriverWait(self.driver, 3).until(EC.presence_of_element_located(
                    (By.XPATH, '//*[contains(@data-testid,"no-results") or contains(@class,"no-results") or contains(text(),"No results") or contains(text(),"not found") or contains(text(),"No member found") or contains(text(),"Nothing was found")]')
                ))
                if error_msg and error_msg.is_displayed():
                    print("[DentaQuest step1] No results found")
                    return "ERROR: INVALID MEMBERID OR DOB"
            except TimeoutException:
                pass

            print("[DentaQuest step1] Search completed successfully")
            return "Success"

        except Exception as e: 
            print(f"[DentaQuest step1] Exception: {e}")
            return f"ERROR:STEP1 - {e}"

    
    def step2(self):
        """Get eligibility status and capture screenshot"""
        wait = WebDriverWait(self.driver, 90)

        try:
            print("[DentaQuest step2] Starting eligibility capture")
            
            # Wait for results to load
            time.sleep(3)
            
            # Try to find eligibility status from the results
            eligibilityText = "unknown"
            try:
                # Look for a link or element with eligibility status
                status_elem = wait.until(EC.presence_of_element_located((
                    By.XPATH,
                    "//a[contains(@href,'eligibility')] | //*[contains(@class,'status')] | //*[contains(text(),'Active') or contains(text(),'Inactive') or contains(text(),'Eligible')]"
                )))
                eligibilityText = status_elem.text.strip().lower()
                print(f"[DentaQuest step2] Found status element: {eligibilityText}")
                
                # Normalize status
                if "active" in eligibilityText or "eligible" in eligibilityText:
                    eligibilityText = "active"
                elif "inactive" in eligibilityText or "ineligible" in eligibilityText:
                    eligibilityText = "inactive"
            except TimeoutException:
                print("[DentaQuest step2] Could not find specific eligibility status")

            # Try to find patient name
            patientName = ""
            try:
                # Look for the patient name in the results
                name_elem = self.driver.find_element(By.XPATH, "//h1 | //div[contains(@class,'name')] | //*[contains(@class,'member-name') or contains(@class,'patient-name')]")
                patientName = name_elem.text.strip()
                print(f"[DentaQuest step2] Found patient name: {patientName}")
            except:
                pass

            # Wait for page to fully load
            try:
                WebDriverWait(self.driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception:
                pass

            time.sleep(1)

            # Capture full page screenshot
            print("[DentaQuest step2] Capturing screenshot")
            total_width = int(self.driver.execute_script(
                "return Math.max(document.body.scrollWidth, document.documentElement.scrollWidth, document.documentElement.clientWidth);"
            ))
            total_height = int(self.driver.execute_script(
                "return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, document.documentElement.clientHeight);"
            ))
            dpr = float(self.driver.execute_script("return window.devicePixelRatio || 1;"))

            self.driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
                "mobile": False,
                "width": total_width,
                "height": total_height,
                "deviceScaleFactor": dpr,
                "screenOrientation": {"angle": 0, "type": "portraitPrimary"}
            })

            time.sleep(0.2)

            # Capture screenshot
            result = self.driver.execute_cdp_cmd("Page.captureScreenshot", {"format": "png", "fromSurface": True})
            image_data = base64.b64decode(result.get('data', ''))
            screenshot_path = os.path.join(self.download_dir, f"dentaquest_ss_{self.memberId}_{int(time.time())}.png")
            with open(screenshot_path, "wb") as f:
                f.write(image_data)
            print(f"[DentaQuest step2] Screenshot saved: {screenshot_path}")

            # Restore original metrics
            try:
                self.driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
            except Exception:
                pass

            # Close the browser window after screenshot
            try:
                from dentaquest_browser_manager import get_browser_manager
                get_browser_manager().quit_driver()
                print("[DentaQuest step2] Browser closed")
            except Exception as e:
                print(f"[DentaQuest step2] Error closing browser: {e}")
            
            output = {
                "status": "success",
                "eligibility": eligibilityText,
                "ss_path": screenshot_path,
                "patientName": patientName
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
