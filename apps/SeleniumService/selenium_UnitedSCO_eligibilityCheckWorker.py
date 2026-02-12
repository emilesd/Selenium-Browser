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
                    
                    # Check for MFA method selection page
                    # DentalHub shows: "Phone" / "Authenticator App" radio buttons + "Continue" button
                    try:
                        continue_btn = self.driver.find_element(By.XPATH,
                            "//button[contains(text(),'Continue')]"
                        )
                        # Check if "Phone" radio is present (MFA selection page)
                        phone_elements = self.driver.find_elements(By.XPATH,
                            "//*[contains(text(),'Phone')]"
                        )
                        if continue_btn and phone_elements:
                            print("[UnitedSCO login] MFA method selection page detected")
                            # Select "Phone" radio button if not already selected
                            try:
                                phone_radio = self.driver.find_element(By.XPATH,
                                    "//input[@type='radio' and (contains(@value,'phone') or contains(@value,'Phone'))] | "
                                    "//label[contains(text(),'Phone')]/preceding-sibling::input[@type='radio'] | "
                                    "//label[contains(text(),'Phone')]//input[@type='radio'] | "
                                    "//input[@type='radio'][following-sibling::*[contains(text(),'Phone')]] | "
                                    "//input[@type='radio']"
                                )
                                if phone_radio and not phone_radio.is_selected():
                                    phone_radio.click()
                                    print("[UnitedSCO login] Selected 'Phone' radio button")
                                else:
                                    print("[UnitedSCO login] 'Phone' already selected")
                            except Exception as radio_err:
                                print(f"[UnitedSCO login] Could not click Phone radio (may already be selected): {radio_err}")
                                # Try clicking the label text instead
                                try:
                                    phone_label = self.driver.find_element(By.XPATH, "//*[contains(text(),'Phone') and not(contains(text(),'Authenticator'))]")
                                    phone_label.click()
                                    print("[UnitedSCO login] Clicked 'Phone' label")
                                except Exception:
                                    pass
                            
                            time.sleep(1)
                            # Click Continue
                            continue_btn.click()
                            print("[UnitedSCO login] Clicked 'Continue' on MFA selection page")
                            time.sleep(5)  # Wait for OTP to be sent
                    except Exception:
                        pass  # No MFA selection page - proceed normally
                    
                    # Check if login succeeded (redirected back to dentalhub dashboard)
                    current_url_after_login = self.driver.current_url.lower()
                    print(f"[UnitedSCO login] After login URL: {current_url_after_login}")
                    
                    if "app.dentalhub.com" in current_url_after_login and "login" not in current_url_after_login:
                        print("[UnitedSCO login] Login successful - redirected to dashboard")
                        return "SUCCESS"
                    
                    # Check for OTP input after login / after MFA selection
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
                    
                    # Re-check dashboard after waiting for OTP check
                    current_url_after_login = self.driver.current_url.lower()
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

    def _check_for_error_dialog(self):
        """Check for and dismiss common error dialogs. Returns error message string or None."""
        error_patterns = [
            ("Patient Not Found", "Patient Not Found - please check the Subscriber ID, DOB, and Payer selection"),
            ("Insufficient Information", "Insufficient Information - need Subscriber ID + DOB, or First Name + Last Name + DOB"),
            ("No Eligibility", "No eligibility information found for this patient"),
            ("Error", None),  # Generic error - will use the dialog text
        ]
        
        for pattern, default_msg in error_patterns:
            try:
                dialog_elem = self.driver.find_element(By.XPATH, 
                    f"//modal-container//*[contains(text(),'{pattern}')] | "
                    f"//div[contains(@class,'modal')]//*[contains(text(),'{pattern}')]"
                )
                if dialog_elem.is_displayed():
                    # Get the full dialog text for logging
                    try:
                        modal = self.driver.find_element(By.XPATH, "//modal-container | //div[contains(@class,'modal-dialog')]")
                        dialog_text = modal.text.strip()[:200]
                    except Exception:
                        dialog_text = dialog_elem.text.strip()[:200]
                    
                    print(f"[UnitedSCO step1] Error dialog detected: {dialog_text}")
                    
                    # Click OK/Close to dismiss
                    try:
                        dismiss_btn = self.driver.find_element(By.XPATH, 
                            "//modal-container//button[contains(text(),'Ok') or contains(text(),'OK') or contains(text(),'Close')] | "
                            "//div[contains(@class,'modal')]//button[contains(text(),'Ok') or contains(text(),'OK') or contains(text(),'Close')]"
                        )
                        dismiss_btn.click()
                        print("[UnitedSCO step1] Dismissed error dialog")
                        time.sleep(1)
                    except Exception:
                        # Try clicking the X button
                        try:
                            close_btn = self.driver.find_element(By.XPATH, "//modal-container//button[@class='close']")
                            close_btn.click()
                        except Exception:
                            pass
                    
                    error_msg = default_msg if default_msg else f"ERROR: {dialog_text}"
                    return f"ERROR: {error_msg}"
            except Exception:
                continue
        
        return None
    
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
        
        Workflow based on actual DOM testing:
        1. Navigate directly to eligibility page
        2. Fill First Name (id='firstName_Back'), Last Name (id='lastName_Back'), DOB (id='dateOfBirth_Back')
        3. Select Payer: "UnitedHealthcare Massachusetts" from ng-select dropdown
        4. Click Continue
        5. Handle Practitioner & Location page - click paymentGroupId dropdown, select Summit Dental Care
        6. Click Continue again
        """
        from selenium.webdriver.common.action_chains import ActionChains
        
        try:
            print(f"[UnitedSCO step1] Starting eligibility search for: {self.firstName} {self.lastName}, DOB: {self.dateOfBirth}")
            
            # Navigate directly to eligibility page
            print("[UnitedSCO step1] Navigating to eligibility page...")
            self.driver.get("https://app.dentalhub.com/app/patient/eligibility")
            time.sleep(3)
            
            current_url = self.driver.current_url
            print(f"[UnitedSCO step1] Current URL: {current_url}")
            
            # Step 1.1: Fill the Patient Information form
            print("[UnitedSCO step1] Filling Patient Information form...")
            
            # Wait for form to load - look for First Name field (id='firstName_Back')
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "firstName_Back"))
                )
                print("[UnitedSCO step1] Patient Information form loaded")
            except TimeoutException:
                print("[UnitedSCO step1] Patient Information form not found")
                return "ERROR: Patient Information form not found"
            
            # Fill Subscriber ID / Medicaid ID if memberId is provided
            # The field is labeled "Subscriber ID or Medicaid ID" on the DentalHub form
            # Actual DOM field id is 'subscriberId_Front' (not 'subscriberId_Back')
            if self.memberId:
                try:
                    subscriber_id_selectors = [
                        "//input[@id='subscriberId_Front']",
                        "//input[@id='subscriberId_Back' or @id='subscriberID_Back']",
                        "//input[@id='memberId_Back' or @id='memberid_Back']",
                        "//input[@id='medicaidId_Back']",
                        "//label[contains(text(),'Subscriber ID')]/..//input[not(@id='firstName_Back') and not(@id='lastName_Back') and not(@id='dateOfBirth_Back')]",
                        "//input[contains(@placeholder,'Subscriber') or contains(@placeholder,'subscriber')]",
                        "//input[contains(@placeholder,'Medicaid') or contains(@placeholder,'medicaid')]",
                        "//input[contains(@placeholder,'Member') or contains(@placeholder,'member')]",
                    ]
                    subscriber_filled = False
                    for sel in subscriber_id_selectors:
                        try:
                            sid_input = self.driver.find_element(By.XPATH, sel)
                            if sid_input.is_displayed():
                                sid_input.clear()
                                sid_input.send_keys(self.memberId)
                                field_id = sid_input.get_attribute("id") or "unknown"
                                print(f"[UnitedSCO step1] Entered Subscriber ID: {self.memberId} (field id='{field_id}')")
                                subscriber_filled = True
                                break
                        except Exception:
                            continue
                    
                    if not subscriber_filled:
                        # Fallback: find visible input that is NOT a known field
                        try:
                            all_inputs = self.driver.find_elements(By.XPATH, 
                                "//form//input[@type='text' or not(@type)]"
                            )
                            known_ids = {'firstName_Back', 'lastName_Back', 'dateOfBirth_Back', 'procedureDate_Back', 'insurerId'}
                            for inp in all_inputs:
                                inp_id = inp.get_attribute("id") or ""
                                if inp_id not in known_ids and inp.is_displayed():
                                    inp.clear()
                                    inp.send_keys(self.memberId)
                                    print(f"[UnitedSCO step1] Entered Subscriber ID in field id='{inp_id}': {self.memberId}")
                                    subscriber_filled = True
                                    break
                        except Exception as e2:
                            print(f"[UnitedSCO step1] Fallback subscriber field search error: {e2}")
                    
                    if not subscriber_filled:
                        print(f"[UnitedSCO step1] WARNING: Could not find Subscriber ID field (ID: {self.memberId})")
                except Exception as e:
                    print(f"[UnitedSCO step1] Error entering Subscriber ID: {e}")
            
            # Fill First Name (id='firstName_Back') - only if provided
            if self.firstName:
                try:
                    first_name_input = self.driver.find_element(By.ID, "firstName_Back")
                    first_name_input.clear()
                    first_name_input.send_keys(self.firstName)
                    print(f"[UnitedSCO step1] Entered First Name: {self.firstName}")
                except Exception as e:
                    print(f"[UnitedSCO step1] Error entering First Name: {e}")
            else:
                print("[UnitedSCO step1] No First Name provided, skipping")
            
            # Fill Last Name (id='lastName_Back') - only if provided
            if self.lastName:
                try:
                    last_name_input = self.driver.find_element(By.ID, "lastName_Back")
                    last_name_input.clear()
                    last_name_input.send_keys(self.lastName)
                    print(f"[UnitedSCO step1] Entered Last Name: {self.lastName}")
                except Exception as e:
                    print(f"[UnitedSCO step1] Error entering Last Name: {e}")
            else:
                print("[UnitedSCO step1] No Last Name provided, skipping")
            
            # Fill Date of Birth (id='dateOfBirth_Back', format: MM/DD/YYYY)
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
            
            # First dismiss any blocking dialogs (e.g. Chrome password save)
            try:
                self.driver.execute_script("""
                    // Dismiss Chrome password manager popup if present
                    var dialogs = document.querySelectorAll('[role="dialog"], .cdk-overlay-container');
                    dialogs.forEach(function(d) { d.style.display = 'none'; });
                """)
            except Exception:
                pass
            
            payer_selected = False
            
            # Strategy 1: Click the ng-select, type to search, and select the option
            try:
                # Find the Payer ng-select by multiple selectors
                payer_selectors = [
                    "//label[contains(text(),'Payer')]/following-sibling::ng-select",
                    "//label[contains(text(),'Payer')]/..//ng-select",
                    "//ng-select[contains(@placeholder,'Payer') or contains(@placeholder,'payer')]",
                    "//ng-select[.//input[contains(@placeholder,'Search by Payers')]]",
                ]
                payer_ng_select = None
                for sel in payer_selectors:
                    try:
                        payer_ng_select = self.driver.find_element(By.XPATH, sel)
                        if payer_ng_select.is_displayed():
                            break
                    except Exception:
                        continue
                
                if payer_ng_select:
                    # Scroll to it and click to open
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", payer_ng_select)
                    time.sleep(0.5)
                    payer_ng_select.click()
                    time.sleep(1)
                    
                    # Type into the search input inside ng-select to filter options
                    try:
                        search_input = payer_ng_select.find_element(By.XPATH, ".//input[contains(@type,'text') or contains(@role,'combobox')]")
                        search_input.clear()
                        search_input.send_keys("UnitedHealthcare Massachusetts")
                        print("[UnitedSCO step1] Typed payer search text")
                        time.sleep(2)
                    except Exception:
                        # If no search input, try sending keys directly to ng-select
                        try:
                            ActionChains(self.driver).send_keys("UnitedHealthcare Mass").perform()
                            print("[UnitedSCO step1] Typed payer search via ActionChains")
                            time.sleep(2)
                        except Exception:
                            pass
                    
                    # Find and click the matching option
                    payer_options = self.driver.find_elements(By.XPATH, 
                        "//ng-dropdown-panel//div[contains(@class,'ng-option')]"
                    )
                    for opt in payer_options:
                        opt_text = opt.text.strip()
                        if "UnitedHealthcare Massachusetts" in opt_text:
                            opt.click()
                            print(f"[UnitedSCO step1] Selected Payer: {opt_text}")
                            payer_selected = True
                            break
                    
                    if not payer_selected and payer_options:
                        # Select first visible option if it contains "United"
                        for opt in payer_options:
                            opt_text = opt.text.strip()
                            if "United" in opt_text and opt.is_displayed():
                                opt.click()
                                print(f"[UnitedSCO step1] Selected first matching Payer: {opt_text}")
                                payer_selected = True
                                break
                    
                    # Close dropdown
                    ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(0.5)
                else:
                    print("[UnitedSCO step1] Could not find Payer ng-select element")
                    
            except Exception as e:
                print(f"[UnitedSCO step1] Payer selection strategy 1 error: {e}")
                try:
                    ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                except Exception:
                    pass
            
            # Strategy 2: JavaScript direct selection if strategy 1 failed
            if not payer_selected:
                try:
                    # Try clicking via JavaScript
                    clicked = self.driver.execute_script("""
                        // Find ng-select near the Payer label
                        var labels = document.querySelectorAll('label');
                        for (var i = 0; i < labels.length; i++) {
                            if (labels[i].textContent.includes('Payer')) {
                                var parent = labels[i].parentElement;
                                var ngSelect = parent.querySelector('ng-select') || labels[i].nextElementSibling;
                                if (ngSelect) {
                                    ngSelect.click();
                                    return true;
                                }
                            }
                        }
                        return false;
                    """)
                    if clicked:
                        time.sleep(1)
                        ActionChains(self.driver).send_keys("UnitedHealthcare Mass").perform()
                        time.sleep(2)
                        payer_options = self.driver.find_elements(By.XPATH, 
                            "//ng-dropdown-panel//div[contains(@class,'ng-option')]"
                        )
                        for opt in payer_options:
                            if "UnitedHealthcare" in opt.text and "Massachusetts" in opt.text:
                                opt.click()
                                print(f"[UnitedSCO step1] Selected Payer via JS: {opt.text.strip()}")
                                payer_selected = True
                                break
                        ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                except Exception as e:
                    print(f"[UnitedSCO step1] Payer selection strategy 2 error: {e}")
            
            if not payer_selected:
                print("[UnitedSCO step1] WARNING: Could not select Payer - form may fail")
            
            time.sleep(1)
            
            # Step 1.3: Click Continue button (Step 1 - Patient Info)
            try:
                continue_btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Continue')]"))
                )
                continue_btn.click()
                print("[UnitedSCO step1] Clicked Continue button (Patient Info)")
                time.sleep(4)
                
                # Check for error dialogs (modal) after clicking Continue
                error_result = self._check_for_error_dialog()
                if error_result:
                    return error_result
                    
            except Exception as e:
                print(f"[UnitedSCO step1] Error clicking Continue: {e}")
                return "ERROR: Could not click Continue button"
            
            # Step 1.4: Handle Practitioner & Location page
            # First check if we actually moved to the Practitioner page
            # by looking for Practitioner-specific elements
            print("[UnitedSCO step1] Handling Practitioner & Location page...")
            
            on_practitioner_page = False
            try:
                # Check for Practitioner page elements (paymentGroupId or treatment location)
                WebDriverWait(self.driver, 8).until(
                    lambda d: d.find_element(By.ID, "paymentGroupId").is_displayed() or 
                              d.find_element(By.ID, "treatmentLocation").is_displayed()
                )
                on_practitioner_page = True
                print("[UnitedSCO step1] Practitioner & Location page loaded")
            except Exception:
                # Check if we're already on results page (3rd step) 
                try:
                    results_elem = self.driver.find_element(By.XPATH, 
                        "//*[contains(text(),'Selected Patient') or contains(@id,'patient-name') or contains(@id,'eligibility')]"
                    )
                    if results_elem.is_displayed():
                        print("[UnitedSCO step1] Already on Eligibility Results page (skipped Practitioner)")
                        return "Success"
                except Exception:
                    pass
                
                # Check for error dialog again
                error_result = self._check_for_error_dialog()
                if error_result:
                    return error_result
                
                print("[UnitedSCO step1] Practitioner page not detected, attempting to continue...")
            
            if on_practitioner_page:
                try:
                    # Click Practitioner Taxonomy dropdown (id='paymentGroupId')
                    taxonomy_input = self.driver.find_element(By.ID, "paymentGroupId")
                    if taxonomy_input.is_displayed():
                        taxonomy_input.click()
                        print("[UnitedSCO step1] Clicked Practitioner Taxonomy dropdown")
                        time.sleep(1)
                        
                        # Select "Summit Dental Care" option
                        try:
                            summit_option = WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, 
                                    "//ng-dropdown-panel//div[contains(@class,'ng-option') and contains(.,'Summit Dental Care')]"
                                ))
                            )
                            summit_option.click()
                            print("[UnitedSCO step1] Selected: Summit Dental Care")
                        except TimeoutException:
                            # Select first available option
                            try:
                                first_option = self.driver.find_element(By.XPATH, 
                                    "//ng-dropdown-panel//div[contains(@class,'ng-option')]"
                                )
                                option_text = first_option.text.strip()
                                first_option.click()
                                print(f"[UnitedSCO step1] Selected first available: {option_text}")
                            except Exception:
                                print("[UnitedSCO step1] No options available in Practitioner dropdown")
                        
                        # Press Escape to close dropdown
                        ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                        time.sleep(1)
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
                # Check for error dialog intercepting the click
                error_result = self._check_for_error_dialog()
                if error_result:
                    return error_result
            
            # Final check for error dialogs after the search
            error_result = self._check_for_error_dialog()
            if error_result:
                return error_result
            
            print("[UnitedSCO step1] Patient search completed successfully")
            return "Success"

        except Exception as e: 
            print(f"[UnitedSCO step1] Exception: {e}")
            return f"ERROR:STEP1 - {e}"

    
    def _get_existing_downloads(self):
        """Get set of existing PDF files in download dir before clicking."""
        import glob
        return set(glob.glob(os.path.join(self.download_dir, "*.pdf")))

    def _wait_for_new_download(self, existing_files, timeout=15):
        """Wait for a new PDF file to appear in the download dir."""
        import glob
        for _ in range(timeout * 2):  # check every 0.5s
            time.sleep(0.5)
            current = set(glob.glob(os.path.join(self.download_dir, "*.pdf")))
            new_files = current - existing_files
            if new_files:
                # Also wait for download to finish (no .crdownload files)
                crdownloads = glob.glob(os.path.join(self.download_dir, "*.crdownload"))
                if not crdownloads:
                    return list(new_files)[0]
        return None

    def step2(self):
        """
        Extract data from Selected Patient page, click the "Eligibility" tab
        to navigate to the eligibility details page, then capture PDF.
        
        The "Eligibility" tab at the bottom (next to "Benefit Summary" and
        "Service History") may:
          a) Open a new browser tab with eligibility details
          b) Download a PDF file
          c) Load content dynamically on the same page
        We handle all three cases.
        """
        import glob
        import re
        
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
                        "//*[contains(text(),'Member Eligible') or contains(text(),'member eligible')]"
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
            
            # Extract patient name from the page
            page_text = ""
            try:
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                pass
            
            # Log a snippet of page text around "Selected Patient" for debugging
            try:
                sp_idx = page_text.find("Selected Patient")
                if sp_idx >= 0:
                    snippet = page_text[sp_idx:sp_idx+300]
                    print(f"[UnitedSCO step2] Page text near 'Selected Patient': {repr(snippet[:200])}")
            except Exception:
                pass
            
            # Strategy 1: Try DOM element id="patient-name"
            name_extracted = False
            try:
                name_elem = self.driver.find_element(By.ID, "patient-name")
                extracted_name = name_elem.text.strip()
                if extracted_name:
                    patientName = extracted_name
                    name_extracted = True
                    print(f"[UnitedSCO step2] Extracted patient name from DOM (id=patient-name): {patientName}")
            except Exception:
                pass
            
            # Strategy 2: Try various DOM patterns for patient name
            if not name_extracted:
                name_selectors = [
                    "//*[contains(@class,'patient-name') or contains(@class,'patientName')]",
                    "//*[contains(@class,'selected-patient')]//h3 | //*[contains(@class,'selected-patient')]//h4 | //*[contains(@class,'selected-patient')]//strong",
                    "//div[contains(@class,'patient')]//h3 | //div[contains(@class,'patient')]//h4",
                    "//*[contains(@class,'eligibility__banner')]//h3 | //*[contains(@class,'eligibility__banner')]//h4",
                    "//*[contains(@class,'banner__patient')]",
                ]
                for sel in name_selectors:
                    try:
                        elems = self.driver.find_elements(By.XPATH, sel)
                        for elem in elems:
                            txt = elem.text.strip()
                            # Filter: must look like a name (2+ words, starts with uppercase)
                            if txt and len(txt.split()) >= 2 and txt[0].isupper() and len(txt) < 60:
                                patientName = txt
                                name_extracted = True
                                print(f"[UnitedSCO step2] Extracted patient name from DOM: {patientName}")
                                break
                        if name_extracted:
                            break
                    except Exception:
                        continue
            
            # Strategy 3: Regex from page text - multiple patterns
            # IMPORTANT: Use [^\n] to avoid matching across newlines (e.g. picking up "Member Eligible")
            if not name_extracted:
                name_patterns = [
                    # Name on the line right after "Selected Patient"
                    r'Selected Patient\s*\n\s*([A-Z][A-Za-z\-\']+(?: [A-Z][A-Za-z\-\']+)+)',
                    r'Patient Name\s*[\n:]\s*([A-Z][A-Za-z\-\']+(?: [A-Z][A-Za-z\-\']+)+)',
                    # "LASTNAME, FIRSTNAME" format
                    r'Selected Patient\s*\n\s*([A-Z][A-Za-z\-\']+,\s*[A-Z][A-Za-z\-\']+)',
                    # Name on the line right before "Member Eligible" or "Member ID"
                    r'\n([A-Z][A-Za-z\-\']+(?: [A-Z]\.?)? [A-Z][A-Za-z\-\']+)\n(?:Member|Date Of Birth|DOB)',
                ]
                for pattern in name_patterns:
                    try:
                        name_match = re.search(pattern, page_text)
                        if name_match:
                            candidate = name_match.group(1).strip()
                            # Validate: not too long, not a header/label, and doesn't contain "Eligible"/"Member"/"Patient"
                            skip_words = ("Selected Patient", "Patient Name", "Patient Information", 
                                         "Member Eligible", "Member ID", "Date Of Birth")
                            if (len(candidate) < 50 and candidate not in skip_words 
                                    and "Eligible" not in candidate and "Member" not in candidate):
                                patientName = candidate
                                name_extracted = True
                                print(f"[UnitedSCO step2] Extracted patient name from text: {patientName}")
                                break
                    except Exception:
                        continue
            
            if not name_extracted:
                print(f"[UnitedSCO step2] WARNING: Could not extract patient name from page")
            
            # Extract Member ID from the page (for database storage)
            try:
                member_id_match = re.search(r'Member ID\s*[\n:]\s*(\d+)', page_text)
                if member_id_match:
                    foundMemberId = member_id_match.group(1)
                    print(f"[UnitedSCO step2] Extracted Member ID from page: {foundMemberId}")
            except Exception as e:
                print(f"[UnitedSCO step2] Could not extract Member ID: {e}")
            
            # Extract Date of Birth from page if available (for patient creation)
            extractedDob = ""
            try:
                dob_match = re.search(r'Date Of Birth\s*[\n:]\s*(\d{2}/\d{2}/\d{4})', page_text)
                if dob_match:
                    extractedDob = dob_match.group(1)
                    print(f"[UnitedSCO step2] Extracted DOB from page: {extractedDob}")
            except Exception:
                pass
            
            # 2) Click the "Eligibility" button to navigate to eligibility details
            # The DOM has: <button id="eligibility-link" class="btn btn-link">Eligibility</button>
            # This is near "Benefit Summary" and "Service History" buttons.
            print("[UnitedSCO step2] Looking for 'Eligibility' button (id='eligibility-link')...")
            
            # Record existing downloads BEFORE clicking (to detect new downloads)
            existing_downloads = self._get_existing_downloads()
            
            # Record current window handles BEFORE clicking (to detect new tabs)
            original_window = self.driver.current_window_handle
            original_windows = set(self.driver.window_handles)
            
            eligibility_clicked = False
            
            # Strategy 1 (PRIMARY): Use the known button id="eligibility-link"
            try:
                # First check if the button exists and is visible
                elig_btn = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.ID, "eligibility-link"))
                )
                # Wait for it to become visible (it's hidden when no results)
                WebDriverWait(self.driver, 10).until(
                    EC.visibility_of(elig_btn)
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elig_btn)
                time.sleep(0.5)
                elig_btn.click()
                eligibility_clicked = True
                print("[UnitedSCO step2] Clicked 'Eligibility' button (id='eligibility-link')")
                time.sleep(5)
            except Exception as e:
                print(f"[UnitedSCO step2] Could not click by ID: {e}")
            
            # Strategy 2: Find the button with exact "Eligibility" text (not "Eligibility Check Results" etc.)
            if not eligibility_clicked:
                try:
                    buttons = self.driver.find_elements(By.XPATH, "//button")
                    for btn in buttons:
                        try:
                            text = btn.text.strip()
                            if re.match(r'^Eligibility\s*$', text, re.IGNORECASE) and btn.is_displayed():
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                                time.sleep(0.5)
                                btn.click()
                                eligibility_clicked = True
                                print(f"[UnitedSCO step2] Clicked button with text 'Eligibility'")
                                time.sleep(5)
                                break
                        except Exception:
                            continue
                except Exception as e:
                    print(f"[UnitedSCO step2] Button text search error: {e}")
            
            # Strategy 3: JavaScript click on #eligibility-link
            if not eligibility_clicked:
                try:
                    clicked = self.driver.execute_script("""
                        var btn = document.getElementById('eligibility-link');
                        if (btn) { btn.scrollIntoView({block: 'center'}); btn.click(); return true; }
                        // Fallback: find any button/a with exact "Eligibility" text
                        var all = document.querySelectorAll('button, a');
                        for (var i = 0; i < all.length; i++) {
                            if (/^\\s*Eligibility\\s*$/i.test(all[i].textContent)) {
                                all[i].scrollIntoView({block: 'center'});
                                all[i].click();
                                return true;
                            }
                        }
                        return false;
                    """)
                    if clicked:
                        eligibility_clicked = True
                        print("[UnitedSCO step2] Clicked via JavaScript")
                        time.sleep(5)
                except Exception as e:
                    print(f"[UnitedSCO step2] JS click error: {e}")
            
            if not eligibility_clicked:
                print("[UnitedSCO step2] WARNING: Could not click Eligibility button")
            
            # 3) Handle the result of clicking: new tab, download, or same-page content
            pdf_path = None
            
            # Check for new browser tab/window
            new_windows = set(self.driver.window_handles) - original_windows
            if new_windows:
                new_tab = list(new_windows)[0]
                print(f"[UnitedSCO step2] New tab opened! Switching to it...")
                self.driver.switch_to.window(new_tab)
                time.sleep(5)
                
                # Wait for the new page to load
                try:
                    WebDriverWait(self.driver, 30).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                except Exception:
                    pass
                time.sleep(2)
                
                print(f"[UnitedSCO step2] New tab URL: {self.driver.current_url}")
                
                # Capture PDF from the new tab
                pdf_path = self._capture_pdf(foundMemberId)
                
                # Close the new tab and switch back to original
                self.driver.close()
                self.driver.switch_to.window(original_window)
                print("[UnitedSCO step2] Closed new tab, switched back to original")
            
            # Check for downloaded file
            if not pdf_path:
                downloaded_file = self._wait_for_new_download(existing_downloads, timeout=10)
                if downloaded_file:
                    print(f"[UnitedSCO step2] File downloaded: {downloaded_file}")
                    pdf_path = downloaded_file
            
            # Fallback: capture current page as PDF
            if not pdf_path:
                print("[UnitedSCO step2] No new tab or download detected - capturing current page as PDF")
                
                # Wait for any dynamic content
                try:
                    WebDriverWait(self.driver, 15).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                except Exception:
                    pass
                time.sleep(3)
                
                print(f"[UnitedSCO step2] Capturing PDF from URL: {self.driver.current_url}")
                pdf_path = self._capture_pdf(foundMemberId)

            if not pdf_path:
                return {"status": "error", "message": "STEP2 FAILED: Could not generate PDF"}

            print(f"[UnitedSCO step2] PDF saved: {pdf_path}")

            # Hide browser window after completion
            self._hide_browser()

            print("[UnitedSCO step2] Eligibility capture complete")

            return {
                "status": "success",
                "eligibility": eligibilityText,
                "ss_path": pdf_path,
                "pdf_path": pdf_path,
                "patientName": patientName,
                "memberId": foundMemberId
            }
            
        except Exception as e:
            print(f"[UnitedSCO step2] Exception: {e}")
            return {"status": "error", "message": f"STEP2 FAILED: {str(e)}"}

    def _hide_browser(self):
        """Hide the browser window after task completion using multiple strategies."""
        try:
            # Strategy 1: Navigate to blank page first (clears sensitive data from view)
            try:
                self.driver.get("about:blank")
                time.sleep(0.5)
            except Exception:
                pass
            
            # Strategy 2: Minimize window
            try:
                self.driver.minimize_window()
                print("[UnitedSCO step2] Browser window minimized")
                return
            except Exception:
                pass
            
            # Strategy 3: Move window off-screen
            try:
                self.driver.set_window_position(-10000, -10000)
                print("[UnitedSCO step2] Browser window moved off-screen")
                return
            except Exception:
                pass
            
            # Strategy 4: Use xdotool to minimize (Linux)
            try:
                import subprocess
                subprocess.run(["xdotool", "getactivewindow", "windowminimize"], 
                             timeout=3, capture_output=True)
                print("[UnitedSCO step2] Browser minimized via xdotool")
            except Exception:
                pass
                
        except Exception as e:
            print(f"[UnitedSCO step2] Could not hide browser: {e}")

    def _capture_pdf(self, member_id):
        """Capture the current page as PDF using Chrome DevTools Protocol."""
        try:
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
            
            file_identifier = member_id if member_id else f"{self.firstName}_{self.lastName}"
            
            result = self.driver.execute_cdp_cmd("Page.printToPDF", pdf_options)
            pdf_data = base64.b64decode(result.get('data', ''))
            pdf_path = os.path.join(self.download_dir, f"unitedsco_eligibility_{file_identifier}_{int(time.time())}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(pdf_data)
            return pdf_path
        except Exception as e:
            print(f"[UnitedSCO _capture_pdf] Error: {e}")
            return None


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
