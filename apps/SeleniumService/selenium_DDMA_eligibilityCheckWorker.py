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

            # OTP detection
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
        except Exception as e:
            print("[login] Exception during login:", e)
            return f"ERROR:LOGIN FAILED: {e}"

    def step1(self):
        wait = WebDriverWait(self.driver, 30)

        try:
            # Fill Member ID
            member_id_input = wait.until(EC.presence_of_element_located((By.XPATH, '//input[@placeholder="Search by member ID"]')))
            member_id_input.clear()
            member_id_input.send_keys(self.memberId)

            # Fill DOB parts
            try:
                dob_parts = self.dateOfBirth.split("-")
                year = dob_parts[0]           # "1964"
                month = dob_parts[1].zfill(2) # "04"
                day = dob_parts[2].zfill(2)   # "17"
            except Exception as e:
                print(f"Error parsing DOB: {e}")
                return "ERROR: PARSING DOB"

             # 1) locate the specific member DOB container
            dob_container = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//div[@data-testid='member-search_date-of-birth']")
                )
            )

            # 2) find the editable spans *inside that container* using relative XPaths
            month_elem = dob_container.find_element(By.XPATH, ".//span[@data-type='month' and @contenteditable='true']")
            day_elem   = dob_container.find_element(By.XPATH, ".//span[@data-type='day'   and @contenteditable='true']")
            year_elem  = dob_container.find_element(By.XPATH, ".//span[@data-type='year'  and @contenteditable='true']")

            # Helper to click, select-all and type (pure send_keys approach)
            def replace_with_sendkeys(el, value):
                # focus (same as click)
                el.click()
                # select all (Ctrl+A) and delete (some apps pick up BACKSPACE better — we use BACKSPACE after select)
                el.send_keys(Keys.CONTROL, "a")
                el.send_keys(Keys.BACKSPACE)
                # type the value
                el.send_keys(value)
                # optionally blur or tab out if app expects it
                # el.send_keys(Keys.TAB)

            replace_with_sendkeys(month_elem, month)
            time.sleep(0.05)
            replace_with_sendkeys(day_elem, day)
            time.sleep(0.05)
            replace_with_sendkeys(year_elem, year)


            # Click Continue button
            continue_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[@data-testid="member-search_search-button"]')))
            continue_btn.click()
            
            # Check for error message
            try:
                error_msg = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located(
                    (By.XPATH, '//div[@data-testid="member-search-result-no-results"]')
                ))
                if error_msg:
                    print("Error: Invalid Member ID or Date of Birth.")
                    return  "ERROR: INVALID MEMBERID OR DOB"
            except TimeoutException:
                pass

            return "Success"

        except Exception as e: 
            print(f"Error while step1 i.e Cheking the MemberId and DOB in: {e}")
            return "ERROR:STEP1"

    
    def step2(self):
        wait = WebDriverWait(self.driver, 90)

        try:
            # 1) find the eligibility <a> inside the correct cell
            status_link = wait.until(EC.presence_of_element_located((
                By.XPATH,
                "(//tbody//tr)[1]//a[contains(@href, 'member-eligibility-search')]"
            )))

            eligibilityText = status_link.text.strip().lower()

            # 2) finding patient name. 
            patient_name_div = wait.until(EC.presence_of_element_located((
                By.XPATH,
                '//div[@class="flex flex-row w-full items-center"]'
            )))

            patientName = patient_name_div.text.strip().lower()



            try:
                WebDriverWait(self.driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception:
                print("Warning: document.readyState did not become 'complete' within timeout")

            # Give some time for lazy content to finish rendering (adjust if needed)
            time.sleep(0.6)

            # Get total page size and DPR
            total_width = int(self.driver.execute_script(
                "return Math.max(document.body.scrollWidth, document.documentElement.scrollWidth, document.documentElement.clientWidth);"
            ))
            total_height = int(self.driver.execute_script(
                "return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, document.documentElement.clientHeight);"
            ))
            dpr = float(self.driver.execute_script("return window.devicePixelRatio || 1;"))

            # Set device metrics to the full page size so Page.captureScreenshot captures everything
            # Note: Some pages are extremely tall; if you hit memory limits, you can capture in chunks.
            self.driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
                "mobile": False,
                "width": total_width,
                "height": total_height,
                "deviceScaleFactor": dpr,
                "screenOrientation": {"angle": 0, "type": "portraitPrimary"}
            })

            # Small pause for layout to settle after emulation change
            time.sleep(0.15)

            # Capture screenshot (base64 PNG)
            result = self.driver.execute_cdp_cmd("Page.captureScreenshot", {"format": "png", "fromSurface": True})
            image_data = base64.b64decode(result.get('data', ''))
            screenshot_path = os.path.join(self.download_dir, f"ss_{self.memberId}.png")
            with open(screenshot_path, "wb") as f:
                f.write(image_data)

            # Restore original metrics to avoid affecting further interactions
            try:
                self.driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
            except Exception:
                # non-fatal: continue
                pass

            print("Screenshot saved at:", screenshot_path)
            
            # Close the browser window after screenshot (session preserved in profile)
            try:
                from ddma_browser_manager import get_browser_manager
                get_browser_manager().quit_driver()
                print("[step2] Browser closed - session preserved in profile")
            except Exception as e:
                print(f"[step2] Error closing browser: {e}")
            
            output = {
                    "status": "success",
                    "eligibility": eligibilityText,
                    "ss_path": screenshot_path,
                    "patientName":patientName
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
