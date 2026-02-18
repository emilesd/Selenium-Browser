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
import re
import glob

from deltains_browser_manager import get_browser_manager

LOGIN_URL = "https://www.deltadentalins.com/ciam/login?TARGET=%2Fprovider-tools%2Fv2"
PROVIDER_TOOLS_URL = "https://www.deltadentalins.com/provider-tools/v2"


class AutomationDeltaInsEligibilityCheck:
    def __init__(self, data):
        self.headless = False
        self.driver = None

        self.data = data.get("data", {}) if isinstance(data, dict) else {}

        self.memberId = self.data.get("memberId", "")
        self.dateOfBirth = self.data.get("dateOfBirth", "")
        self.firstName = self.data.get("firstName", "")
        self.lastName = self.data.get("lastName", "")
        self.deltains_username = self.data.get("deltains_username", "")
        self.deltains_password = self.data.get("deltains_password", "")

        self.download_dir = get_browser_manager().download_dir
        os.makedirs(self.download_dir, exist_ok=True)

    def config_driver(self):
        self.driver = get_browser_manager().get_driver(self.headless)

    def _dismiss_cookie_banner(self):
        try:
            accept_btn = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
            )
            accept_btn.click()
            print("[DeltaIns login] Dismissed cookie consent banner")
            time.sleep(1)
        except TimeoutException:
            print("[DeltaIns login] No cookie consent banner found")
        except Exception as e:
            print(f"[DeltaIns login] Error dismissing cookie banner: {e}")

    def _force_logout(self):
        try:
            print("[DeltaIns login] Forcing logout due to credential change...")
            browser_manager = get_browser_manager()
            try:
                self.driver.delete_all_cookies()
                print("[DeltaIns login] Cleared all cookies")
            except Exception as e:
                print(f"[DeltaIns login] Error clearing cookies: {e}")
            browser_manager.clear_credentials_hash()
            print("[DeltaIns login] Logout complete")
            return True
        except Exception as e:
            print(f"[DeltaIns login] Error during forced logout: {e}")
            return False

    def login(self, url):
        """
        Multi-step login flow for DeltaIns (Okta-based):
        1. Enter username (name='identifier') -> click Next
        2. Enter password (type='password') -> click Submit
        3. Handle MFA: click 'Send me an email' -> wait for OTP
        Returns: ALREADY_LOGGED_IN, SUCCESS, OTP_REQUIRED, or ERROR:...
        """
        wait = WebDriverWait(self.driver, 30)
        browser_manager = get_browser_manager()

        try:
            if self.deltains_username and browser_manager.credentials_changed(self.deltains_username):
                self._force_logout()
                self.driver.get(url)
                time.sleep(3)

            # First, try navigating to provider-tools directly (not login URL)
            # This avoids triggering Okta password re-verification when session is valid
            try:
                current_url = self.driver.current_url
                print(f"[DeltaIns login] Current URL: {current_url}")
                if "provider-tools" in current_url and "login" not in current_url.lower() and "ciam" not in current_url.lower():
                    print("[DeltaIns login] Already on provider tools page - logged in")
                    return "ALREADY_LOGGED_IN"
            except Exception as e:
                print(f"[DeltaIns login] Error checking current state: {e}")

            # Navigate to provider-tools URL first to check if session is still valid
            print("[DeltaIns login] Trying provider-tools URL to check session...")
            self.driver.get(PROVIDER_TOOLS_URL)
            time.sleep(5)

            current_url = self.driver.current_url
            print(f"[DeltaIns login] After provider-tools nav URL: {current_url}")

            if "provider-tools" in current_url and "login" not in current_url.lower() and "ciam" not in current_url.lower():
                print("[DeltaIns login] Session still valid - already logged in")
                return "ALREADY_LOGGED_IN"

            # Session expired or not logged in - navigate to login URL
            print("[DeltaIns login] Session not valid, navigating to login page...")
            self.driver.get(url)
            time.sleep(3)

            current_url = self.driver.current_url
            print(f"[DeltaIns login] After login nav URL: {current_url}")

            if "provider-tools" in current_url and "login" not in current_url.lower() and "ciam" not in current_url.lower():
                print("[DeltaIns login] Already logged in - on provider tools")
                return "ALREADY_LOGGED_IN"

            self._dismiss_cookie_banner()

            # Step 1: Username entry (name='identifier')
            print("[DeltaIns login] Looking for username field...")
            username_entered = False
            for sel in [
                (By.NAME, "identifier"),
                (By.ID, "okta-signin-username"),
                (By.XPATH, "//input[@type='text' and @autocomplete='username']"),
                (By.XPATH, "//input[@type='text']"),
            ]:
                try:
                    field = WebDriverWait(self.driver, 8).until(EC.presence_of_element_located(sel))
                    if field.is_displayed():
                        field.clear()
                        field.send_keys(self.deltains_username)
                        username_entered = True
                        print(f"[DeltaIns login] Username entered via {sel}")
                        break
                except Exception:
                    continue

            if not username_entered:
                return "ERROR: Could not find username field"

            # Click Next/Submit
            time.sleep(1)
            for sel in [
                (By.XPATH, "//input[@type='submit' and @value='Next']"),
                (By.XPATH, "//input[@type='submit']"),
                (By.XPATH, "//button[@type='submit']"),
            ]:
                try:
                    btn = self.driver.find_element(*sel)
                    if btn.is_displayed():
                        btn.click()
                        print(f"[DeltaIns login] Clicked Next via {sel}")
                        break
                except Exception:
                    continue

            time.sleep(4)

            current_url = self.driver.current_url
            if "provider-tools" in current_url and "login" not in current_url.lower() and "ciam" not in current_url.lower():
                return "ALREADY_LOGGED_IN"

            # Step 2: Password entry
            print("[DeltaIns login] Looking for password field...")
            pw_entered = False
            for sel in [
                (By.XPATH, "//input[@type='password']"),
                (By.ID, "okta-signin-password"),
                (By.NAME, "password"),
            ]:
                try:
                    field = WebDriverWait(self.driver, 10).until(EC.presence_of_element_located(sel))
                    if field.is_displayed():
                        field.clear()
                        field.send_keys(self.deltains_password)
                        pw_entered = True
                        print(f"[DeltaIns login] Password entered via {sel}")
                        break
                except Exception:
                    continue

            if not pw_entered:
                current_url = self.driver.current_url
                if "provider-tools" in current_url and "login" not in current_url.lower():
                    return "ALREADY_LOGGED_IN"
                return "ERROR: Password field not found"

            # Click Sign In
            time.sleep(1)
            for sel in [
                (By.ID, "okta-signin-submit"),
                (By.XPATH, "//input[@type='submit']"),
                (By.XPATH, "//button[@type='submit']"),
            ]:
                try:
                    btn = self.driver.find_element(*sel)
                    if btn.is_displayed():
                        btn.click()
                        print(f"[DeltaIns login] Clicked Sign In via {sel}")
                        break
                except Exception:
                    continue

            if self.deltains_username:
                browser_manager.save_credentials_hash(self.deltains_username)

            time.sleep(6)

            current_url = self.driver.current_url
            print(f"[DeltaIns login] After password submit URL: {current_url}")

            if "provider-tools" in current_url and "login" not in current_url.lower() and "ciam" not in current_url.lower():
                print("[DeltaIns login] Login successful - on provider tools")
                return "SUCCESS"

            # Step 3: MFA handling
            # There are two possible MFA pages:
            #   A) Method selection: "Verify it's you with a security method" with Email/Phone Select buttons
            #   B) Direct: "Send me an email" button
            print("[DeltaIns login] Handling MFA...")

            # Check for method selection page first (Email "Select" link)
            # The Okta MFA page uses <a> tags (not buttons/inputs) with class "select-factor"
            # inside <div data-se="okta_email"> for Email selection
            try:
                body_text = self.driver.find_element(By.TAG_NAME, "body").text
                if "security method" in body_text.lower() or "select from the following" in body_text.lower():
                    print("[DeltaIns login] MFA method selection page detected")
                    email_select = None
                    for sel in [
                        (By.CSS_SELECTOR, "div[data-se='okta_email'] a.select-factor"),
                        (By.XPATH, "//div[@data-se='okta_email']//a[contains(@class,'select-factor')]"),
                        (By.XPATH, "//a[contains(@aria-label,'Select Email')]"),
                        (By.XPATH, "//div[@data-se='okta_email']//a[@data-se='button']"),
                        (By.CSS_SELECTOR, "a.select-factor.link-button"),
                    ]:
                        try:
                            btn = self.driver.find_element(*sel)
                            if btn.is_displayed():
                                email_select = btn
                                print(f"[DeltaIns login] Found Email Select via {sel}")
                                break
                        except Exception:
                            continue

                    if email_select:
                        email_select.click()
                        print("[DeltaIns login] Clicked 'Select' for Email MFA")
                        time.sleep(5)
                    else:
                        print("[DeltaIns login] Could not find Email Select button")
            except Exception as e:
                print(f"[DeltaIns login] Error checking MFA method selection: {e}")

            # Now look for "Send me an email" button (may appear after method selection or directly)
            try:
                send_btn = WebDriverWait(self.driver, 8).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//input[@type='submit' and @value='Send me an email'] | "
                        "//input[@value='Send me an email'] | "
                        "//button[contains(text(),'Send me an email')]"))
                )
                send_btn.click()
                print("[DeltaIns login] Clicked 'Send me an email'")
                time.sleep(5)
            except TimeoutException:
                print("[DeltaIns login] No 'Send me an email' button, checking for OTP input...")

            # Step 4: OTP entry page
            try:
                otp_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH,
                        "//input[@name='credentials.passcode' and @type='text'] | "
                        "//input[contains(@name,'passcode')]"))
                )
                print("[DeltaIns login] OTP input found -> OTP_REQUIRED")
                return "OTP_REQUIRED"
            except TimeoutException:
                pass

            current_url = self.driver.current_url
            if "provider-tools" in current_url and "login" not in current_url.lower() and "ciam" not in current_url.lower():
                return "SUCCESS"

            try:
                error_elem = self.driver.find_element(By.XPATH,
                    "//*[contains(@class,'error') or contains(@class,'alert-error')]")
                error_text = error_elem.text.strip()[:200]
                if error_text:
                    return f"ERROR: {error_text}"
            except Exception:
                pass

            print("[DeltaIns login] Could not determine login state - returning OTP_REQUIRED as fallback")
            return "OTP_REQUIRED"

        except Exception as e:
            print(f"[DeltaIns login] Exception: {e}")
            return f"ERROR:LOGIN FAILED: {e}"

    def _format_dob(self, dob_str):
        """Convert DOB from YYYY-MM-DD to MM/DD/YYYY format."""
        if dob_str and "-" in dob_str:
            dob_parts = dob_str.split("-")
            if len(dob_parts) == 3:
                return f"{dob_parts[1]}/{dob_parts[2]}/{dob_parts[0]}"
        return dob_str

    def _close_browser(self):
        """Save cookies and close the browser after task completion."""
        browser_manager = get_browser_manager()
        try:
            browser_manager.save_cookies()
        except Exception as e:
            print(f"[DeltaIns] Failed to save cookies before close: {e}")
        try:
            browser_manager.quit_driver()
            print("[DeltaIns] Browser closed")
        except Exception as e:
            print(f"[DeltaIns] Could not close browser: {e}")

    def step1(self):
        """
        Navigate to Eligibility search, enter patient info, search, and
        click 'Check eligibility and benefits' on the result card.

        Search flow:
        1. Click 'Eligibility and benefits' link
        2. Click 'Search for a new patient' button
        3. Click 'Search by member ID' tab
        4. Enter Member ID in #memberId
        5. Enter DOB in #dob (MM/DD/YYYY)
        6. Click Search
        7. Extract patient info from result card
        8. Click 'Check eligibility and benefits'
        """
        try:
            formatted_dob = self._format_dob(self.dateOfBirth)
            print(f"[DeltaIns step1] Starting — memberId={self.memberId}, DOB={formatted_dob}")

            # 1. Click "Eligibility and benefits" link
            print("[DeltaIns step1] Clicking 'Eligibility and benefits'...")
            try:
                elig_link = WebDriverWait(self.driver, 15).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//a[contains(text(),'Eligibility and benefits')] | "
                        "//a[contains(text(),'Eligibility')]"))
                )
                elig_link.click()
                time.sleep(5)
                print("[DeltaIns step1] Clicked Eligibility link")
            except TimeoutException:
                print("[DeltaIns step1] No Eligibility link found, checking if already on page...")
                if "patient-search" not in self.driver.current_url and "eligibility" not in self.driver.current_url:
                    self.driver.get("https://www.deltadentalins.com/provider-tools/v2/patient-search")
                    time.sleep(5)

            # 2. Click "Search for a new patient" button
            print("[DeltaIns step1] Clicking 'Search for a new patient'...")
            try:
                new_patient_btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//button[contains(text(),'Search for a new patient')]"))
                )
                new_patient_btn.click()
                time.sleep(3)
                print("[DeltaIns step1] Clicked 'Search for a new patient'")
            except TimeoutException:
                print("[DeltaIns step1] 'Search for a new patient' button not found - may already be on search page")

            # 3. Click "Search by member ID" tab
            print("[DeltaIns step1] Clicking 'Search by member ID' tab...")
            try:
                member_id_tab = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//button[contains(text(),'Search by member ID')]"))
                )
                member_id_tab.click()
                time.sleep(2)
                print("[DeltaIns step1] Clicked 'Search by member ID' tab")
            except TimeoutException:
                print("[DeltaIns step1] 'Search by member ID' tab not found")
                return "ERROR: Could not find 'Search by member ID' tab"

            # 4. Enter Member ID
            print(f"[DeltaIns step1] Entering Member ID: {self.memberId}")
            try:
                mid_field = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "memberId"))
                )
                mid_field.click()
                mid_field.send_keys(Keys.CONTROL + "a")
                mid_field.send_keys(Keys.DELETE)
                time.sleep(0.3)
                mid_field.send_keys(self.memberId)
                time.sleep(0.5)
                print(f"[DeltaIns step1] Member ID entered: '{mid_field.get_attribute('value')}'")
            except TimeoutException:
                return "ERROR: Member ID field not found"

            # 5. Enter DOB
            print(f"[DeltaIns step1] Entering DOB: {formatted_dob}")
            try:
                dob_field = self.driver.find_element(By.ID, "dob")
                dob_field.click()
                dob_field.send_keys(Keys.CONTROL + "a")
                dob_field.send_keys(Keys.DELETE)
                time.sleep(0.3)
                dob_field.send_keys(formatted_dob)
                time.sleep(0.5)
                print(f"[DeltaIns step1] DOB entered: '{dob_field.get_attribute('value')}'")
            except Exception as e:
                return f"ERROR: DOB field not found: {e}"

            # 6. Click Search
            print("[DeltaIns step1] Clicking Search...")
            try:
                search_btn = self.driver.find_element(By.XPATH,
                    "//button[@type='submit'][contains(text(),'Search')] | "
                    "//button[@data-testid='searchButton']")
                search_btn.click()
                time.sleep(10)
                print("[DeltaIns step1] Search clicked")
            except Exception as e:
                return f"ERROR: Search button not found: {e}"

            # 7. Check for results - look for patient card
            print("[DeltaIns step1] Checking for results...")
            try:
                patient_card = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.XPATH,
                        "//div[contains(@class,'patient-card-root')] | "
                        "//div[@data-testid='patientCard'] | "
                        "//div[starts-with(@data-testid,'patientCard')]"))
                )
                print("[DeltaIns step1] Patient card found!")

                # Extract patient name
                try:
                    name_el = patient_card.find_element(By.XPATH, ".//h3")
                    patient_name = name_el.text.strip()
                    print(f"[DeltaIns step1] Patient name: {patient_name}")
                except Exception:
                    patient_name = ""

                # Extract eligibility dates
                try:
                    elig_el = patient_card.find_element(By.XPATH,
                        ".//*[@data-testid='patientCardMemberEligibility']//*[contains(@class,'pt-staticfield-text')]")
                    elig_text = elig_el.text.strip()
                    print(f"[DeltaIns step1] Eligibility: {elig_text}")
                except Exception:
                    elig_text = ""

                # Store for step2
                self._patient_name = patient_name
                self._eligibility_text = elig_text

            except TimeoutException:
                # Check for error messages
                try:
                    body_text = self.driver.find_element(By.TAG_NAME, "body").text
                    if "no results" in body_text.lower() or "not found" in body_text.lower() or "no patient" in body_text.lower():
                        return "ERROR: No patient found with the provided Member ID and DOB"
                    # Check for specific error alerts
                    alerts = self.driver.find_elements(By.XPATH, "//*[@role='alert']")
                    for alert in alerts:
                        if alert.is_displayed():
                            return f"ERROR: {alert.text.strip()[:200]}"
                except Exception:
                    pass
                return "ERROR: No patient results found within timeout"

            # 8. Click "Check eligibility and benefits"
            print("[DeltaIns step1] Clicking 'Check eligibility and benefits'...")
            try:
                check_btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//button[contains(text(),'Check eligibility and benefits')] | "
                        "//button[@data-testid='eligibilityBenefitsButton']"))
                )
                check_btn.click()
                time.sleep(10)
                print(f"[DeltaIns step1] Navigated to: {self.driver.current_url}")
            except TimeoutException:
                return "ERROR: 'Check eligibility and benefits' button not found"

            return "SUCCESS"

        except Exception as e:
            print(f"[DeltaIns step1] Exception: {e}")
            return f"ERROR: step1 failed: {e}"

    def step2(self):
        """
        Extract eligibility information and capture PDF from the
        Eligibility & Benefits detail page.

        URL: .../provider-tools/v2/eligibility-benefits

        Extracts:
        - Patient name from h3 in patient-card-header
        - DOB, Member ID, eligibility from data-testid fields
        - PDF via Page.printToPDF
        """
        try:
            print("[DeltaIns step2] Extracting eligibility data...")
            time.sleep(3)

            current_url = self.driver.current_url
            print(f"[DeltaIns step2] URL: {current_url}")

            if "eligibility-benefits" not in current_url:
                print("[DeltaIns step2] Not on eligibility page, checking body text...")

            # Extract patient name
            patientName = ""
            try:
                name_el = self.driver.find_element(By.XPATH,
                    "//div[contains(@class,'patient-card-header')]//h3 | "
                    "//div[starts-with(@data-testid,'patientCard')]//h3")
                patientName = name_el.text.strip()
                print(f"[DeltaIns step2] Patient name: {patientName}")
            except Exception:
                patientName = getattr(self, '_patient_name', '') or f"{self.firstName} {self.lastName}".strip()
                print(f"[DeltaIns step2] Using stored/fallback name: {patientName}")

            # Extract DOB from card
            extractedDob = ""
            try:
                dob_el = self.driver.find_element(By.XPATH,
                    "//*[@data-testid='patientCardDateOfBirth']//*[contains(@class,'pt-staticfield-text')]")
                extractedDob = dob_el.text.strip()
                print(f"[DeltaIns step2] DOB: {extractedDob}")
            except Exception:
                extractedDob = self._format_dob(self.dateOfBirth)

            # Extract Member ID from card
            foundMemberId = ""
            try:
                mid_el = self.driver.find_element(By.XPATH,
                    "//*[@data-testid='patientCardMemberId']//*[contains(@class,'pt-staticfield-text')]")
                foundMemberId = mid_el.text.strip()
                print(f"[DeltaIns step2] Member ID: {foundMemberId}")
            except Exception:
                foundMemberId = self.memberId

            # Extract eligibility status
            eligibility = "Unknown"
            try:
                elig_el = self.driver.find_element(By.XPATH,
                    "//*[@data-testid='patientCardMemberEligibility']//*[contains(@class,'pt-staticfield-text')]")
                elig_text = elig_el.text.strip()
                print(f"[DeltaIns step2] Eligibility text: {elig_text}")

                if "present" in elig_text.lower():
                    eligibility = "Eligible"
                elif elig_text:
                    eligibility = elig_text
            except Exception:
                elig_text = getattr(self, '_eligibility_text', '')
                if elig_text and "present" in elig_text.lower():
                    eligibility = "Eligible"
                elif elig_text:
                    eligibility = elig_text

            # Check page body for additional eligibility info
            try:
                body_text = self.driver.find_element(By.TAG_NAME, "body").text
                if "not eligible" in body_text.lower():
                    eligibility = "Not Eligible"
                elif "terminated" in body_text.lower():
                    eligibility = "Terminated"
            except Exception:
                pass

            # Capture PDF via "Download summary" -> "Download PDF" button
            pdfBase64 = ""
            try:
                existing_files = set(glob.glob(os.path.join(self.download_dir, "*")))

                dl_link = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//a[@data-testid='downloadBenefitSummaryLink']"))
                )
                dl_link.click()
                print("[DeltaIns step2] Clicked 'Download summary'")
                time.sleep(3)

                dl_btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//button[@data-testid='downloadPdfButton']"))
                )
                dl_btn.click()
                print("[DeltaIns step2] Clicked 'Download PDF'")

                pdf_path = None
                for i in range(30):
                    time.sleep(2)
                    current_files = set(glob.glob(os.path.join(self.download_dir, "*")))
                    new_files = current_files - existing_files
                    completed = [f for f in new_files
                                 if not f.endswith(".crdownload") and not f.endswith(".tmp")]
                    if completed:
                        pdf_path = completed[0]
                        break

                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        pdfBase64 = base64.b64encode(f.read()).decode()
                    print(f"[DeltaIns step2] PDF downloaded: {os.path.basename(pdf_path)} "
                          f"({os.path.getsize(pdf_path)} bytes), b64 len={len(pdfBase64)}")
                    try:
                        os.remove(pdf_path)
                    except Exception:
                        pass
                else:
                    print("[DeltaIns step2] Download PDF timed out, falling back to CDP")
                    cdp_result = self.driver.execute_cdp_cmd("Page.printToPDF", {
                        "printBackground": True,
                        "preferCSSPageSize": True,
                        "scale": 0.7,
                        "paperWidth": 11,
                        "paperHeight": 17,
                    })
                    pdfBase64 = cdp_result.get("data", "")
                    print(f"[DeltaIns step2] CDP fallback PDF, b64 len={len(pdfBase64)}")

                # Dismiss the download modal
                try:
                    self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(1)
                except Exception:
                    pass

            except Exception as e:
                print(f"[DeltaIns step2] PDF capture failed: {e}")
                try:
                    cdp_result = self.driver.execute_cdp_cmd("Page.printToPDF", {
                        "printBackground": True,
                        "preferCSSPageSize": True,
                        "scale": 0.7,
                        "paperWidth": 11,
                        "paperHeight": 17,
                    })
                    pdfBase64 = cdp_result.get("data", "")
                    print(f"[DeltaIns step2] CDP fallback PDF, b64 len={len(pdfBase64)}")
                except Exception as e2:
                    print(f"[DeltaIns step2] CDP fallback also failed: {e2}")

            # Hide browser after completion
            self._close_browser()

            result = {
                "status": "success",
                "patientName": patientName,
                "eligibility": eligibility,
                "pdfBase64": pdfBase64,
                "extractedDob": extractedDob,
                "memberId": foundMemberId,
            }

            print(f"[DeltaIns step2] Result: name={result['patientName']}, "
                  f"eligibility={result['eligibility']}, "
                  f"memberId={result['memberId']}")

            return result

        except Exception as e:
            print(f"[DeltaIns step2] Exception: {e}")
            self._close_browser()
            return {
                "status": "error",
                "patientName": getattr(self, '_patient_name', '') or f"{self.firstName} {self.lastName}".strip(),
                "eligibility": "Unknown",
                "pdfBase64": "",
                "extractedDob": self._format_dob(self.dateOfBirth),
                "memberId": self.memberId,
                "error": str(e),
            }
