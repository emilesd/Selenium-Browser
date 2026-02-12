import os
import time
import asyncio
from typing import Dict, Any
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException

from selenium_UnitedSCO_eligibilityCheckWorker import AutomationUnitedSCOEligibilityCheck

# In-memory session store
sessions: Dict[str, Dict[str, Any]] = {}

SESSION_OTP_TIMEOUT = int(os.getenv("SESSION_OTP_TIMEOUT", "120"))  # seconds


def make_session_entry() -> str:
    """Create a new session entry and return its ID."""
    import uuid
    sid = str(uuid.uuid4())
    sessions[sid] = {
        "status": "created",     # created -> running -> waiting_for_otp -> otp_submitted -> completed / error
        "created_at": time.time(),
        "last_activity": time.time(),
        "bot": None,             # worker instance
        "driver": None,          # selenium webdriver
        "otp_event": asyncio.Event(),
        "otp_value": None,
        "result": None,
        "message": None,
        "type": None,
    }
    return sid


async def cleanup_session(sid: str, message: str | None = None):
    """
    Close driver (if any), wake OTP waiter, set final state, and remove session entry.
    Idempotent: safe to call multiple times.
    """
    s = sessions.get(sid)
    if not s:
        return
    try:
        # Ensure final state
        try:
            if s.get("status") not in ("completed", "error", "not_found"):
                s["status"] = "error"
            if message:
                s["message"] = message
        except Exception:
            pass

        # Wake any OTP waiter (so awaiting coroutines don't hang)
        try:
            ev = s.get("otp_event")
            if ev and not ev.is_set():
                ev.set()
        except Exception:
            pass

        # NOTE: Do NOT quit driver - keep browser alive for next patient
        # Browser manager handles the persistent browser instance

    finally:
        # Remove session entry from map
        sessions.pop(sid, None)


async def _remove_session_later(sid: str, delay: int = 20):
    await asyncio.sleep(delay)
    await cleanup_session(sid)


def _minimize_browser(bot):
    """Hide the browser window so it doesn't stay in the user's way."""
    try:
        if bot and bot.driver:
            # Navigate to blank page first
            try:
                bot.driver.get("about:blank")
            except Exception:
                pass
            # Try minimize
            try:
                bot.driver.minimize_window()
                print("[UnitedSCO] Browser minimized after error")
                return
            except Exception:
                pass
            # Fallback: move off-screen
            try:
                bot.driver.set_window_position(-10000, -10000)
                print("[UnitedSCO] Browser moved off-screen after error")
            except Exception:
                pass
    except Exception as e:
        print(f"[UnitedSCO] Could not hide browser: {e}")


async def start_unitedsco_run(sid: str, data: dict, url: str):
    """
    Run the United SCO workflow for a session (WITHOUT managing semaphore/counters).
    Called by agent.py inside a wrapper that handles queue/counters.
    """
    s = sessions.get(sid)
    if not s:
        return {"status": "error", "message": "session not found"}

    s["status"] = "running"
    s["last_activity"] = time.time()

    try:
        bot = AutomationUnitedSCOEligibilityCheck({"data": data})
        bot.config_driver()

        s["bot"] = bot
        s["driver"] = bot.driver
        s["last_activity"] = time.time()

        # Navigate to login URL
        try:
            if not url:
                raise ValueError("URL not provided for United SCO run")
            bot.driver.maximize_window()
            bot.driver.get(url)
            await asyncio.sleep(1)
        except Exception as e:
            s["status"] = "error"
            s["message"] = f"Navigation failed: {e}"
            await cleanup_session(sid)
            return {"status": "error", "message": s["message"]}

        # Login
        try:
            login_result = bot.login(url)
        except WebDriverException as wde:
            s["status"] = "error"
            s["message"] = f"Selenium driver error during login: {wde}"
            await cleanup_session(sid, s["message"])
            return {"status": "error", "message": s["message"]}
        except Exception as e:
            s["status"] = "error"
            s["message"] = f"Unexpected error during login: {e}"
            await cleanup_session(sid, s["message"])
            return {"status": "error", "message": s["message"]}

        # Already logged in - session persisted from profile, skip to step1
        if isinstance(login_result, str) and login_result == "ALREADY_LOGGED_IN":
            s["status"] = "running"
            s["message"] = "Session persisted"
            print("[start_unitedsco_run] Session persisted - skipping OTP")
            # Continue to step1 below

        # OTP required path - POLL THE BROWSER to detect when user enters OTP
        elif isinstance(login_result, str) and login_result == "OTP_REQUIRED":
            s["status"] = "waiting_for_otp"
            s["message"] = "OTP required for login - please enter OTP in browser"
            s["last_activity"] = time.time()
            
            driver = s["driver"]
            
            # Poll the browser to detect when OTP is completed (user enters it directly)
            # We check every 1 second for up to SESSION_OTP_TIMEOUT seconds (faster response)
            max_polls = SESSION_OTP_TIMEOUT
            login_success = False
            
            print(f"[UnitedSCO OTP] Waiting for user to enter OTP (polling browser for {SESSION_OTP_TIMEOUT}s)...")
            
            for poll in range(max_polls):
                await asyncio.sleep(1)
                s["last_activity"] = time.time()
                
                try:
                    # Check if OTP was submitted via API (from app)
                    otp_value = s.get("otp_value")
                    if otp_value:
                        print(f"[UnitedSCO OTP] OTP received from app: {otp_value}")
                        try:
                            otp_input = driver.find_element(By.XPATH, 
                                "//input[contains(@name,'otp') or contains(@name,'code') or @type='tel' or contains(@aria-label,'Verification') or contains(@placeholder,'code')]"
                            )
                            otp_input.clear()
                            otp_input.send_keys(otp_value)
                            # Click verify button - use same pattern as Delta MA
                            try:
                                verify_btn = driver.find_element(By.XPATH, "//button[@type='button' and @aria-label='Verify']")
                                verify_btn.click()
                                print("[UnitedSCO OTP] Clicked verify button (aria-label)")
                            except:
                                try:
                                    # Fallback: try other button patterns
                                    verify_btn = driver.find_element(By.XPATH, "//button[contains(text(),'Verify') or contains(text(),'Submit') or @type='submit']")
                                    verify_btn.click()
                                    print("[UnitedSCO OTP] Clicked verify button (text/type)")
                                except:
                                    otp_input.send_keys("\n")  # Press Enter as fallback
                                    print("[UnitedSCO OTP] Pressed Enter as fallback")
                            print("[UnitedSCO OTP] OTP typed and submitted via app")
                            s["otp_value"] = None  # Clear so we don't submit again
                            await asyncio.sleep(3)  # Wait for verification
                        except Exception as type_err:
                            print(f"[UnitedSCO OTP] Failed to type OTP from app: {type_err}")
                    
                    # Check current URL - if we're on dashboard/member page, login succeeded
                    current_url = driver.current_url.lower()
                    print(f"[UnitedSCO OTP Poll {poll+1}/{max_polls}] URL: {current_url[:60]}...")
                    
                    # Check if we've navigated away from login/OTP pages
                    if "member" in current_url or "dashboard" in current_url or "eligibility" in current_url or "home" in current_url:
                        # Verify by checking for member search input or dashboard element
                        try:
                            # Try multiple selectors for logged-in state
                            dashboard_elem = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.XPATH, 
                                    '//input[@placeholder="Search by member ID"] | //input[contains(@placeholder,"Search")] | //*[contains(@class,"dashboard")]'
                                ))
                            )
                            print("[UnitedSCO OTP] Dashboard/search element found - login successful!")
                            login_success = True
                            break
                        except TimeoutException:
                            print("[UnitedSCO OTP] On member page but search input not found, continuing to poll...")
                    
                    # Also check if OTP input is still visible
                    try:
                        otp_input = driver.find_element(By.XPATH, 
                            "//input[contains(@name,'otp') or contains(@name,'code') or @type='tel' or contains(@aria-label,'Verification') or contains(@placeholder,'code') or contains(@placeholder,'Code')]"
                        )
                        # OTP input still visible - user hasn't entered OTP yet
                        print(f"[UnitedSCO OTP Poll {poll+1}] OTP input still visible - waiting...")
                    except:
                        # OTP input not found - might mean login is in progress or succeeded
                        # Try navigating to dashboard
                        if "login" in current_url or "app/login" in current_url:
                            print("[UnitedSCO OTP] OTP input gone, trying to navigate to dashboard...")
                            try:
                                driver.get("https://app.dentalhub.com/app/dashboard")
                                await asyncio.sleep(2)
                            except:
                                pass
                
                except Exception as poll_err:
                    print(f"[UnitedSCO OTP Poll {poll+1}] Error: {poll_err}")
            
            if not login_success:
                # Final attempt - navigate to dashboard and check
                try:
                    print("[UnitedSCO OTP] Final attempt - navigating to dashboard...")
                    driver.get("https://app.dentalhub.com/app/dashboard")
                    await asyncio.sleep(3)
                    
                    dashboard_elem = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, 
                            '//input[@placeholder="Search by member ID"] | //input[contains(@placeholder,"Search")] | //*[contains(@class,"dashboard")]'
                        ))
                    )
                    print("[UnitedSCO OTP] Dashboard element found - login successful!")
                    login_success = True
                except TimeoutException:
                    s["status"] = "error"
                    s["message"] = "OTP timeout - login not completed"
                    await cleanup_session(sid)
                    return {"status": "error", "message": "OTP not completed in time"}
                except Exception as final_err:
                    s["status"] = "error"
                    s["message"] = f"OTP verification failed: {final_err}"
                    await cleanup_session(sid)
                    return {"status": "error", "message": s["message"]}
            
            if login_success:
                s["status"] = "running"
                s["message"] = "Login successful after OTP"
                print("[UnitedSCO OTP] Proceeding to step1...")

        elif isinstance(login_result, str) and login_result.startswith("ERROR"):
            s["status"] = "error"
            s["message"] = login_result
            await cleanup_session(sid)
            return {"status": "error", "message": login_result}

        # Login succeeded without OTP (SUCCESS)
        elif isinstance(login_result, str) and login_result == "SUCCESS":
            print("[start_unitedsco_run] Login succeeded without OTP")
            s["status"] = "running"
            s["message"] = "Login succeeded"
            # Continue to step1 below

        # Step 1
        step1_result = bot.step1()
        if isinstance(step1_result, str) and step1_result.startswith("ERROR"):
            s["status"] = "error"
            s["message"] = step1_result
            s["result"] = {"status": "error", "message": step1_result}
            # Minimize browser on error
            _minimize_browser(bot)
            # Keep session alive for backend to poll, then clean up
            asyncio.create_task(_remove_session_later(sid, 30))
            return {"status": "error", "message": step1_result}

        # Step 2 (PDF)
        step2_result = bot.step2()
        if isinstance(step2_result, dict) and step2_result.get("status") == "success":
            s["status"] = "completed"
            s["result"] = step2_result
            s["message"] = "completed"
            asyncio.create_task(_remove_session_later(sid, 30))
            return step2_result
        else:
            s["status"] = "error"
            if isinstance(step2_result, dict):
                s["message"] = step2_result.get("message", "unknown error")
            else:
                s["message"] = str(step2_result)
            s["result"] = {"status": "error", "message": s["message"]}
            # Minimize browser on error
            _minimize_browser(bot)
            # Keep session alive for backend to poll, then clean up
            asyncio.create_task(_remove_session_later(sid, 30))
            return {"status": "error", "message": s["message"]}

    except Exception as e:
        s["status"] = "error"
        s["message"] = f"worker exception: {e}"
        # Minimize browser on exception
        try:
            if bot and bot.driver:
                bot.driver.minimize_window()
        except Exception:
            pass
        s["result"] = {"status": "error", "message": s["message"]}
        asyncio.create_task(_remove_session_later(sid, 30))
        return {"status": "error", "message": s["message"]}


def submit_otp(sid: str, otp: str) -> Dict[str, Any]:
    """Set OTP for a session and wake waiting runner."""
    s = sessions.get(sid)
    if not s:
        return {"status": "error", "message": "session not found"}
    if s.get("status") != "waiting_for_otp":
        return {"status": "error", "message": f"session not waiting for otp (state={s.get('status')})"}
    s["otp_value"] = otp
    s["last_activity"] = time.time()
    try:
        s["otp_event"].set()
    except Exception:
        pass
    return {"status": "ok", "message": "otp accepted"}


def get_session_status(sid: str) -> Dict[str, Any]:
    s = sessions.get(sid)
    if not s:
        return {"status": "not_found"}
    return {
        "session_id": sid,
        "status": s.get("status"),
        "message": s.get("message"),
        "created_at": s.get("created_at"),
        "last_activity": s.get("last_activity"),
        "result": s.get("result") if s.get("status") in ("completed", "error") else None,
    }
