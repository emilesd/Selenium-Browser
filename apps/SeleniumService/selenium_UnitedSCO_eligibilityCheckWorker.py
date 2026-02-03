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

from unitedsco_browser_manager import get_browser_manager

class AutomationUnitedSCOEligibilityCheck:    
    def __init__(self, data):
        self.headless = False
        self.driver = None

        self.data = data.get("data", {}) if isinstance(data, dict) else {}

        # Flatten values for convenience
        self.memberId = self.data.get("memberId", "")
        self.dateOfBirth = self.data.get("dateOfBirth", "")
        self.firstName = self.data.get("firstName", "")
        self.lastName = self.data.get("lastName", "")
        self.unitedsco_username = self.data.get("unitedscoUsername", "")
        self.unitedsco_password = self.data.get("unitedscoPassword", "")

        # Use browser manager's download dir
        self.download_dir = get_browser_manager().download_dir
        os.makedirs(self.download_dir, exist_ok=True)

    def config_driver(self):
        # Use persistent browser from manager (keeps device trust tokens)
        self.driver = get_browser_manager().get_driver(self.headless)

    def _force_logout(self):
        """Force logout by clearing cookies for United SCO domain."""
        try:
            print("[UnitedSCO login] Forcing logout due to credential change...")
            browser_manager = get_browser_manager()
            
            # First try to click logout button if visible
            try:
                self.driver.get("https://app.dentalhub.com/app/dashboard")
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
                        print("[UnitedSCO login] Clicked logout button")
                        time.sleep(2)
                        break
                    except TimeoutException:
                        continue
            except Exception as e:
                print(f"[UnitedSCO login] Could not click logout button: {e}")
            
            # Clear cookies as backup
            try:
                self.driver.delete_all_cookies()
                print("[UnitedSCO login] Cleared all cookies")
            except Exception as e:
                print(f"[UnitedSCO login] Error clearing cookies: {e}")
            
            browser_manager.clear_credentials_hash()
            print("[UnitedSCO login] Logout complete")
            return True
        except Exception as e:
            print(f"[UnitedSCO login] Error during forced logout: {e}")
            return False

    def login(self, url):
        wait = WebDriverWait(self.driver, 30)
        browser_manager = get_browser_manager()
        
        try:
            # Check if credentials have changed - if so, force logout first
            if self.unitedsco_username and browser_manager.credentials_changed(self.unitedsco_username):
                self._force_logout()
                self.driver.get(url)
                time.sleep(2)
            
            # First check if we're already on a logged-in page (from previous run)
            try:
                current_url = self.driver.current_url
                print(f"[UnitedSCO login] Current URL: {current_url}")
                
                # Check if we're already on dentalhub dashboard (not the login page)
                if "app.dentalhub.com" in current_url and "login" not in current_url.lower():
                    try:
                        # Look for dashboard element or member search
                        dashboard_elem = WebDriverWait(self.driver, 3).until(
                            EC.presence_of_element_located((By.XPATH, 
                                '//input[contains(@placeholder,"Search")] | //*[contains(@class,"dashboard")] | '
                                '//a[contains(@href,"member")] | //nav'))
                        )
                        print("[UnitedSCO login] Already logged in - on dashboard")
                        return "ALREADY_LOGGED_IN"
                    except TimeoutException:
                        pass
            except Exception as e:
                print(f"[UnitedSCO login] Error checking current state: {e}")
            
            # Navigate to login URL
            self.driver.get(url)
            time.sleep(3)
            
            current_url = self.driver.current_url
            print(f"[UnitedSCO login] After navigation URL: {current_url}")
            
            # If already on dentalhub dashboard (not login page), we're logged in
            if "app.dentalhub.com" in current_url and "login" not in current_url.lower():
                print("[UnitedSCO login] Already on dashboard")
                return "ALREADY_LOGGED_IN"
            
            # Check for OTP input first (in case we're on B2C OTP page)
            try:
                otp_input = WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, 
                        "//input[@type='tel' or contains(@placeholder,'code') or contains(@aria-label,'Verification')]"))
                )
                print("[UnitedSCO login] OTP input found")
                return "OTP_REQUIRED"
            except TimeoutException:
                pass
            
            # Step 1: Click the LOGIN button on the initial dentalhub page
            # This redirects to Azure B2C login
            if "app.dentalhub.com" in current_url:
                try:
                    login_btn = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, 
                            "//button[contains(text(),'LOGIN') or contains(text(),'Log In') or contains(text(),'Login')]"))
                    )
                    login_btn.click()
                    print("[UnitedSCO login] Clicked LOGIN button on dentalhub.com")
                    time.sleep(5)  # Wait for redirect to B2C login page
                except TimeoutException:
                    print("[UnitedSCO login] No LOGIN button found on dentalhub page, proceeding...")
            
            # Now we should be on the Azure B2C login page (dentalhubauth.b2clogin.com)
            current_url = self.driver.current_url
            print(f"[UnitedSCO login] After LOGIN click URL: {current_url}")
            
            # Step 2: Fill in credentials on B2C login page
            if "b2clogin.com" in current_url or "login" in current_url.lower():
                print("[UnitedSCO login] On B2C login page - filling credentials")
                
                try:
                    # Find email field by id="signInName" (Azure B2C specific)
                    email_field = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, 
                            "//input[@id='signInName' or @name='signInName' or @name='Email address' or @type='email']"))
                    )
                    email_field.clear()
                    email_field.send_keys(self.unitedsco_username)
                    print(f"[UnitedSCO login] Entered username: {self.unitedsco_username}")
                    
                    # Find password field by id="password"
                    password_field = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, 
                            "//input[@id='password' or @type='password']"))
                    )
                    password_field.clear()
                    password_field.send_keys(self.unitedsco_password)
                    print("[UnitedSCO login] Entered password")
                    
                    # Click "Sign in" button (id="next" on B2C page)
                    signin_button = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, 
                            "//button[@id='next'] | //button[@type='submit' and contains(text(),'Sign')]"))
                    )
                    signin_button.click()
                    print("[UnitedSCO login] Clicked Sign in button")
                    
                    # Save credentials hash after login attempt
                    if self.unitedsco_username:
                        browser_manager.save_credentials_hash(self.unitedsco_username)
                    
                    time.sleep(5)  # Wait for login to process
                    
                    # Check for OTP input after login
                    try:
                        otp_input = WebDriverWait(self.driver, 15).until(
                            EC.presence_of_element_located((By.XPATH, 
                                "//input[@type='tel' or contains(@placeholder,'code') or contains(@placeholder,'Code') or "
                                "contains(@aria-label,'Verification') or contains(@aria-label,'verification') or "
                                "contains(@aria-label,'Code') or contains(@aria-label,'code') or "
                                "contains(@placeholder,'verification') or contains(@placeholder,'Verification') or "
                                "contains(@name,'otp') or contains(@name,'code') or contains(@id,'otp') or contains(@id,'code')]"
                            ))
                        )
                        print("[UnitedSCO login] OTP input detected -> OTP_REQUIRED")
                        return "OTP_REQUIRED"
                    except TimeoutException:
                        print("[UnitedSCO login] No OTP input detected")
                    
                    # Check if login succeeded (redirected back to dentalhub dashboard)
                    current_url_after_login = self.driver.current_url.lower()
                    print(f"[UnitedSCO login] After login URL: {current_url_after_login}")
                    
                    if "app.dentalhub.com" in current_url_after_login and "login" not in current_url_after_login:
                        print("[UnitedSCO login] Login successful - redirected to dashboard")
                        return "SUCCESS"
                    
                    # Check for error messages on B2C page
                    try:
                        error_elem = self.driver.find_element(By.XPATH, 
                            "//*[contains(@class,'error') or contains(@class,'alert')]")
                        error_text = error_elem.text
                        if error_text:
                            print(f"[UnitedSCO login] Error on page: {error_text}")
                            return f"ERROR: {error_text}"
                    except:
                        pass
                    
                    # Still on B2C page - might need OTP or login failed
                    if "b2clogin.com" in current_url_after_login:
                        print("[UnitedSCO login] Still on B2C page - checking for OTP or error")
                        # Give it more time for OTP
                        try:
                            otp_input = WebDriverWait(self.driver, 10).until(
                                EC.presence_of_element_located((By.XPATH, 
                                    "//input[@type='tel' or contains(@id,'code') or contains(@name,'code')]"))
                            )
                            print("[UnitedSCO login] OTP input found on second check")
                            return "OTP_REQUIRED"
                        except TimeoutException:
                            return "ERROR: Login failed - still on B2C page"
                    
                except TimeoutException as te:
                    print(f"[UnitedSCO login] Login form elements not found: {te}")
                    return "ERROR: Login form not found"
                except Exception as form_err:
                    print(f"[UnitedSCO login] Error filling form: {form_err}")
                    return f"ERROR: {form_err}"
            
            # If we got here without going through login, we're already logged in
            return "SUCCESS"
                
        except Exception as e:
            print(f"[UnitedSCO login] Exception: {e}")
            return f"ERROR:LOGIN FAILED: {e}"

    def _format_dob(self, dob_str):
        """Convert DOB from YYYY-MM-DD to MM/DD/YYYY format"""
        if dob_str and "-" in dob_str:
            dob_parts = dob_str.split("-")
            if len(dob_parts) == 3:
                # YYYY-MM-DD -> MM/DD/YYYY
                return f"{dob_parts[1]}/{dob_parts[2]}/{dob_parts[0]}"
        return dob_str

    def step1(self):
        """
        Navigate to Eligibility page and fill the Patient Information form.
        
        FLEXIBLE INPUT SUPPORT:
        - If Member ID is provided: Fill Subscriber ID + DOB (+ optional First/Last Name)
        - If no Member ID but First/Last Name provided: Fill First Name + Last Name + DOB
        
        Workflow:
        1. Navigate directly to eligibility page
        2. Fill available fields based on input
        3. Select Payer: "UnitedHealthcare Massachusetts" from ng-select dropdown
        4. Click Continue
        5. Handle Practitioner & Location page - click paymentGroupId dropdown, select Summit Dental Care
        6. Click Continue again
        """
        from selenium.webdriver.common.action_chains import ActionChains
        
        try:
            # Determine which input mode to use
            has_member_id = bool(self.memberId and self.memberId.strip())
            has_name = bool(self.firstName and self.firstName.strip() and self.lastName and self.lastName.strip())
            
            if has_member_id:
                print(f"[UnitedSCO step1] Using Member ID mode: ID={self.memberId}, DOB={self.dateOfBirth}")
            elif has_name:
                print(f"[UnitedSCO step1] Using Name mode: {self.firstName} {self.lastName}, DOB={self.dateOfBirth}")
            else:
                print("[UnitedSCO step1] ERROR: Need either Member ID or First Name + Last Name")
                return "ERROR: Missing required input (Member ID or Name)"
            
            # Navigate directly to eligibility page
            print("[UnitedSCO step1] Navigating to eligibility page...")
            self.driver.get("https://app.dentalhub.com/app/patient/eligibility")
            time.sleep(3)
            
            current_url = self.driver.current_url
            print(f"[UnitedSCO step1] Current URL: {current_url}")
            
            # Step 1.1: Fill the Patient Information form
            print("[UnitedSCO step1] Filling Patient Information form...")
            
            # Wait for form to load
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "subscriberId_Front"))
                )
                print("[UnitedSCO step1] Patient Information form loaded")
            except TimeoutException:
                print("[UnitedSCO step1] Patient Information form not found")
                return "ERROR: Patient Information form not found"
            
            # Fill Subscriber ID if provided (id='subscriberId_Front')
            if has_member_id:
                try:
                    subscriber_id_input = self.driver.find_element(By.ID, "subscriberId_Front")
                    subscriber_id_input.clear()
                    subscriber_id_input.send_keys(self.memberId)
                    print(f"[UnitedSCO step1] Entered Subscriber ID: {self.memberId}")
                except Exception as e:
                    print(f"[UnitedSCO step1] Error entering Subscriber ID: {e}")
            
            # Fill First Name if provided (id='firstName_Back')
            if self.firstName and self.firstName.strip():
                try:
                    first_name_input = self.driver.find_element(By.ID, "firstName_Back")
                    first_name_input.clear()
                    first_name_input.send_keys(self.firstName)
                    print(f"[UnitedSCO step1] Entered First Name: {self.firstName}")
                except Exception as e:
                    print(f"[UnitedSCO step1] Error entering First Name: {e}")
                    if not has_member_id:  # Only fail if we're relying on name
                        return "ERROR: Could not enter First Name"
            
            # Fill Last Name if provided (id='lastName_Back')
            if self.lastName and self.lastName.strip():
                try:
                    last_name_input = self.driver.find_element(By.ID, "lastName_Back")
                    last_name_input.clear()
                    last_name_input.send_keys(self.lastName)
                    print(f"[UnitedSCO step1] Entered Last Name: {self.lastName}")
                except Exception as e:
                    print(f"[UnitedSCO step1] Error entering Last Name: {e}")
                    if not has_member_id:  # Only fail if we're relying on name
                        return "ERROR: Could not enter Last Name"
            
            # Fill Date of Birth (id='dateOfBirth_Back', format: MM/DD/YYYY) - always required
            try:
                dob_input = self.driver.find_element(By.ID, "dateOfBirth_Back")
                dob_input.clear()
                dob_formatted = self._format_dob(self.dateOfBirth)
                dob_input.send_keys(dob_formatted)
                print(f"[UnitedSCO step1] Entered DOB: {dob_formatted}")
            except Exception as e:
                print(f"[UnitedSCO step1] Error entering DOB: {e}")
                return "ERROR: Could not enter Date of Birth"
            
            time.sleep(1)
            
            # Step 1.2: Select Payer - UnitedHealthcare Massachusetts
            print("[UnitedSCO step1] Selecting Payer...")
            try:
                # Click the Payer ng-select dropdown
                payer_ng_select = self.driver.find_element(By.XPATH, 
                    "//label[contains(text(),'Payer')]/following-sibling::ng-select"
                )
                payer_ng_select.click()
                time.sleep(1)
                
                # Find and click "UnitedHealthcare Massachusetts" option
                payer_options = self.driver.find_elements(By.XPATH, 
                    "//ng-dropdown-panel//div[contains(@class,'ng-option')]"
                )
                for opt in payer_options:
                    if "UnitedHealthcare Massachusetts" in opt.text:
                        opt.click()
                        print("[UnitedSCO step1] Selected Payer: UnitedHealthcare Massachusetts")
                        break
                
                # Press Escape to close any dropdown
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(1)
                
            except Exception as e:
                print(f"[UnitedSCO step1] Error selecting Payer: {e}")
                # Try to continue anyway - payer might be pre-selected
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            
            # Step 1.3: Click Continue button (Step 1 - Patient Info)
            try:
                continue_btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Continue')]"))
                )
                continue_btn.click()
                print("[UnitedSCO step1] Clicked Continue button (Patient Info)")
                time.sleep(4)
            except Exception as e:
                print(f"[UnitedSCO step1] Error clicking Continue: {e}")
                return "ERROR: Could not click Continue button"
            
            # Step 1.4: Handle Practitioner & Location page
            print("[UnitedSCO step1] Handling Practitioner & Location page...")
            try:
                # Click Practitioner Taxonomy dropdown (id='paymentGroupId')
                taxonomy_input = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "paymentGroupId"))
                )
                taxonomy_input.click()
                print("[UnitedSCO step1] Clicked Practitioner Taxonomy dropdown")
                time.sleep(1)
                
                # Select "Summit Dental Care" option
                summit_option = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, 
                        "//ng-dropdown-panel//div[contains(@class,'ng-option') and contains(.,'Summit Dental Care')]"
                    ))
                )
                summit_option.click()
                print("[UnitedSCO step1] Selected: Summit Dental Care")
                
                # Press Escape to close dropdown
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(1)
                
            except TimeoutException:
                print("[UnitedSCO step1] Practitioner Taxonomy not found or already selected")
            except Exception as e:
                print(f"[UnitedSCO step1] Practitioner Taxonomy handling: {e}")
            
            # Step 1.5: Click Continue button (Step 2 - Practitioner)
            try:
                continue_btn2 = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Continue')]"))
                )
                continue_btn2.click()
                print("[UnitedSCO step1] Clicked Continue button (Practitioner)")
                time.sleep(5)
            except Exception as e:
                print(f"[UnitedSCO step1] Error clicking Continue on Practitioner page: {e}")
            
            # Check for errors
            try:
                error_selectors = [
                    "//*[contains(text(),'No results')]",
                    "//*[contains(text(),'not found')]",
                    "//*[contains(text(),'Invalid')]",
                ]
                for sel in error_selectors:
                    try:
                        error_elem = self.driver.find_element(By.XPATH, sel)
                        if error_elem and error_elem.is_displayed():
                            error_text = error_elem.text
                            print(f"[UnitedSCO step1] Error found: {error_text}")
                            return f"ERROR: {error_text}"
                    except:
                        continue
            except:
                pass
            
            print("[UnitedSCO step1] Patient search completed successfully")
            return "Success"

        except Exception as e: 
            print(f"[UnitedSCO step1] Exception: {e}")
            return f"ERROR:STEP1 - {e}"

    
    def step2(self):
        """
        Navigate to eligibility detail page and capture PDF.
        
        At this point we should be on the "Selected Patient" page after step1.
        Workflow based on actual DOM testing:
        1. Extract eligibility status and Member ID from the page
        2. Click the "Eligibility" button (id='eligibility-link')
        3. Generate PDF using Chrome DevTools Protocol (same as other insurances)
        """
        try:
            print("[UnitedSCO step2] Starting eligibility capture")
            
            # Wait for page to load
            time.sleep(3)
            
            current_url = self.driver.current_url
            print(f"[UnitedSCO step2] Current URL: {current_url}")
            
            # 1) Extract eligibility status and Member ID from the Selected Patient page
            eligibilityText = "unknown"
            patientName = f"{self.firstName} {self.lastName}".strip()
            foundMemberId = self.memberId  # Use provided memberId as default
            
            # Extract eligibility status
            try:
                status_elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH,
                        "//*[contains(text(),'Member Eligible')]"
                    ))
                )
                status_text = status_elem.text.strip().lower()
                print(f"[UnitedSCO step2] Found status: {status_text}")
                
                if "eligible" in status_text:
                    eligibilityText = "active"
                elif "ineligible" in status_text or "not eligible" in status_text:
                    eligibilityText = "inactive"
                    
            except TimeoutException:
                print("[UnitedSCO step2] Eligibility status badge not found")
            except Exception as e:
                print(f"[UnitedSCO step2] Error extracting status: {e}")
            
            print(f"[UnitedSCO step2] Eligibility status: {eligibilityText}")
            
            # Extract Member ID from the page (for database storage)
            try:
                # Look for Member ID on the page
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                import re
                # Look for "Member ID" followed by a number
                member_id_match = re.search(r'Member ID\s*[\n:]\s*(\d+)', page_text)
                if member_id_match:
                    foundMemberId = member_id_match.group(1)
                    print(f"[UnitedSCO step2] Extracted Member ID from page: {foundMemberId}")
            except Exception as e:
                print(f"[UnitedSCO step2] Could not extract Member ID: {e}")
            
            # 2) Click the "Eligibility" button (id='eligibility-link')
            print("[UnitedSCO step2] Looking for 'Eligibility' button...")
            
            try:
                eligibility_btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "eligibility-link"))
                )
                eligibility_btn.click()
                print("[UnitedSCO step2] Clicked 'Eligibility' button")
                time.sleep(5)
            except TimeoutException:
                print("[UnitedSCO step2] Eligibility button not found, trying alternative selectors...")
                try:
                    # Alternative: find button with text "Eligibility"
                    eligibility_btn = self.driver.find_element(By.XPATH,
                        "//button[normalize-space(text())='Eligibility']"
                    )
                    eligibility_btn.click()
                    print("[UnitedSCO step2] Clicked 'Eligibility' button (alternative)")
                    time.sleep(5)
                except Exception as e:
                    print(f"[UnitedSCO step2] Could not click Eligibility button: {e}")
            
            # Wait for page to fully load
            try:
                WebDriverWait(self.driver, 30).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception:
                pass
            
            time.sleep(2)
            
            print(f"[UnitedSCO step2] Final URL: {self.driver.current_url}")

            # 3) Generate PDF using Chrome DevTools Protocol (same as other insurances)
            print("[UnitedSCO step2] Generating PDF...")
            
            pdf_options = {
                "landscape": False,
                "displayHeaderFooter": False,
                "printBackground": True,
                "preferCSSPageSize": True,
                "paperWidth": 8.5,
                "paperHeight": 11,
                "marginTop": 0.4,
                "marginBottom": 0.4,
                "marginLeft": 0.4,
                "marginRight": 0.4,
                "scale": 0.9,
            }
            
            # Use foundMemberId for filename
            file_identifier = foundMemberId if foundMemberId else f"{self.firstName}_{self.lastName}"
            
            result = self.driver.execute_cdp_cmd("Page.printToPDF", pdf_options)
            pdf_data = base64.b64decode(result.get('data', ''))
            pdf_path = os.path.join(self.download_dir, f"unitedsco_eligibility_{file_identifier}_{int(time.time())}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(pdf_data)
            print(f"[UnitedSCO step2] PDF saved: {pdf_path}")

            # Keep browser alive for next patient
            print("[UnitedSCO step2] Eligibility capture complete - session preserved")

            return {
                "status": "success",
                "eligibility": eligibilityText,
                "ss_path": pdf_path,
                "pdf_path": pdf_path,
                "patientName": patientName,
                "memberId": foundMemberId  # Return the Member ID found on the page
            }
            
        except Exception as e:
            print(f"[UnitedSCO step2] Exception: {e}")
            return {"status": "error", "message": f"STEP2 FAILED: {str(e)}"}


    def main_workflow(self, url):
        """Main workflow that runs all steps."""
        try:
            self.config_driver()
            
            login_result = self.login(url)
            print(f"[main_workflow] Login result: {login_result}")
            
            if login_result == "OTP_REQUIRED":
                return {"status": "otp_required", "message": "OTP required after login"}
            
            if isinstance(login_result, str) and login_result.startswith("ERROR"):
                return {"status": "error", "message": login_result}
            
            step1_result = self.step1()
            print(f"[main_workflow] Step1 result: {step1_result}")
            
            if isinstance(step1_result, str) and step1_result.startswith("ERROR"):
                return {"status": "error", "message": step1_result}
            
            step2_result = self.step2()
            print(f"[main_workflow] Step2 result: {step2_result}")
            
            return step2_result
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
