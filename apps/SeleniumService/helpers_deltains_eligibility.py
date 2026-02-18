import os
import time
import asyncio
from typing import Dict, Any
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException

from selenium_DeltaIns_eligibilityCheckWorker import AutomationDeltaInsEligibilityCheck
from deltains_browser_manager import get_browser_manager

# In-memory session store
sessions: Dict[str, Dict[str, Any]] = {}

SESSION_OTP_TIMEOUT = int(os.getenv("SESSION_OTP_TIMEOUT", "240"))


def make_session_entry() -> str:
    import uuid
    sid = str(uuid.uuid4())
    sessions[sid] = {
        "status": "created",
        "created_at": time.time(),
        "last_activity": time.time(),
        "bot": None,
        "driver": None,
        "otp_event": asyncio.Event(),
        "otp_value": None,
        "result": None,
        "message": None,
        "type": None,
    }
    return sid


async def cleanup_session(sid: str, message: str | None = None):
    s = sessions.get(sid)
    if not s:
        return
    try:
        try:
            if s.get("status") not in ("completed", "error", "not_found"):
                s["status"] = "error"
            if message:
                s["message"] = message
        except Exception:
            pass
        try:
            ev = s.get("otp_event")
            if ev and not ev.is_set():
                ev.set()
        except Exception:
            pass
    finally:
        sessions.pop(sid, None)


async def _remove_session_later(sid: str, delay: int = 30):
    await asyncio.sleep(delay)
    await cleanup_session(sid)


def _close_browser(bot):
    """Save cookies and close the browser after task completion."""
    try:
        bm = get_browser_manager()
        try:
            bm.save_cookies()
        except Exception:
            pass
        try:
            bm.quit_driver()
            print("[DeltaIns] Browser closed")
        except Exception:
            pass
    except Exception as e:
        print(f"[DeltaIns] Could not close browser: {e}")


async def start_deltains_run(sid: str, data: dict, url: str):
    """
    Run the DeltaIns eligibility check workflow:
    1. Login (with OTP if needed)
    2. Search patient by Member ID + DOB
    3. Extract eligibility info + PDF
    """
    s = sessions.get(sid)
    if not s:
        return {"status": "error", "message": "session not found"}

    s["status"] = "running"
    s["last_activity"] = time.time()
    bot = None

    try:
        bot = AutomationDeltaInsEligibilityCheck({"data": data})
        bot.config_driver()

        s["bot"] = bot
        s["driver"] = bot.driver
        s["last_activity"] = time.time()

        # Maximize window and login (bot.login handles navigation itself,
        # checking provider-tools URL first to preserve existing sessions)
        try:
            bot.driver.maximize_window()
        except Exception:
            pass

        try:
            login_result = bot.login(url)
        except WebDriverException as wde:
            s["status"] = "error"
            s["message"] = f"Selenium driver error during login: {wde}"
            s["result"] = {"status": "error", "message": s["message"]}
            _close_browser(bot)
            asyncio.create_task(_remove_session_later(sid, 30))
            return {"status": "error", "message": s["message"]}
        except Exception as e:
            s["status"] = "error"
            s["message"] = f"Unexpected error during login: {e}"
            s["result"] = {"status": "error", "message": s["message"]}
            _close_browser(bot)
            asyncio.create_task(_remove_session_later(sid, 30))
            return {"status": "error", "message": s["message"]}

        # Handle login result
        if isinstance(login_result, str) and login_result == "ALREADY_LOGGED_IN":
            s["status"] = "running"
            s["message"] = "Session persisted"
            print("[DeltaIns] Session persisted - skipping OTP")
            # Re-save cookies to keep them fresh on disk
            get_browser_manager().save_cookies()

        elif isinstance(login_result, str) and login_result == "OTP_REQUIRED":
            s["status"] = "waiting_for_otp"
            s["message"] = "OTP required - please enter the code sent to your email"
            s["last_activity"] = time.time()

            driver = s["driver"]
            max_polls = SESSION_OTP_TIMEOUT
            login_success = False

            print(f"[DeltaIns OTP] Waiting for OTP (polling for {SESSION_OTP_TIMEOUT}s)...")

            for poll in range(max_polls):
                await asyncio.sleep(1)
                s["last_activity"] = time.time()

                try:
                    otp_value = s.get("otp_value")
                    if otp_value:
                        print(f"[DeltaIns OTP] OTP received from app: {otp_value}")
                        try:
                            otp_input = driver.find_element(By.XPATH,
                                "//input[@name='credentials.passcode' and @type='text'] | "
                                "//input[contains(@name,'passcode')]")
                            otp_input.clear()
                            otp_input.send_keys(otp_value)

                            try:
                                verify_btn = driver.find_element(By.XPATH,
                                    "//input[@type='submit'] | "
                                    "//button[@type='submit']")
                                verify_btn.click()
                                print("[DeltaIns OTP] Clicked verify button")
                            except Exception:
                                otp_input.send_keys(Keys.RETURN)
                                print("[DeltaIns OTP] Pressed Enter as fallback")

                            s["otp_value"] = None
                            await asyncio.sleep(8)
                        except Exception as type_err:
                            print(f"[DeltaIns OTP] Failed to type OTP: {type_err}")

                    current_url = driver.current_url.lower()
                    if poll % 10 == 0:
                        print(f"[DeltaIns OTP Poll {poll+1}/{max_polls}] URL: {current_url[:80]}")

                    if "provider-tools" in current_url and "login" not in current_url and "ciam" not in current_url:
                        print("[DeltaIns OTP] Login successful!")
                        login_success = True
                        break

                except Exception as poll_err:
                    if poll % 10 == 0:
                        print(f"[DeltaIns OTP Poll {poll+1}] Error: {poll_err}")

            if not login_success:
                try:
                    current_url = driver.current_url.lower()
                    if "provider-tools" in current_url and "login" not in current_url and "ciam" not in current_url:
                        login_success = True
                    else:
                        s["status"] = "error"
                        s["message"] = "OTP timeout - login not completed"
                        s["result"] = {"status": "error", "message": "OTP not completed in time"}
                        _close_browser(bot)
                        asyncio.create_task(_remove_session_later(sid, 30))
                        return {"status": "error", "message": "OTP not completed in time"}
                except Exception as final_err:
                    s["status"] = "error"
                    s["message"] = f"OTP verification failed: {final_err}"
                    s["result"] = {"status": "error", "message": s["message"]}
                    _close_browser(bot)
                    asyncio.create_task(_remove_session_later(sid, 30))
                    return {"status": "error", "message": s["message"]}

            if login_success:
                s["status"] = "running"
                s["message"] = "Login successful after OTP"
                print("[DeltaIns OTP] Proceeding to step1...")
                # Save cookies to disk so session survives browser restart
                get_browser_manager().save_cookies()

        elif isinstance(login_result, str) and login_result.startswith("ERROR"):
            s["status"] = "error"
            s["message"] = login_result
            s["result"] = {"status": "error", "message": login_result}
            _close_browser(bot)
            asyncio.create_task(_remove_session_later(sid, 30))
            return {"status": "error", "message": login_result}

        elif isinstance(login_result, str) and login_result == "SUCCESS":
            print("[DeltaIns] Login succeeded without OTP")
            s["status"] = "running"
            s["message"] = "Login succeeded"
            # Save cookies to disk so session survives browser restart
            get_browser_manager().save_cookies()

        # Step 1 - search patient
        step1_result = bot.step1()
        print(f"[DeltaIns] step1 result: {step1_result}")

        if isinstance(step1_result, str) and step1_result.startswith("ERROR"):
            s["status"] = "error"
            s["message"] = step1_result
            s["result"] = {"status": "error", "message": step1_result}
            _close_browser(bot)
            asyncio.create_task(_remove_session_later(sid, 30))
            return {"status": "error", "message": step1_result}

        # Step 2 - extract eligibility info + PDF
        step2_result = bot.step2()
        print(f"[DeltaIns] step2 result: {step2_result.get('status') if isinstance(step2_result, dict) else step2_result}")

        if isinstance(step2_result, dict):
            s["status"] = "completed"
            s["result"] = step2_result
            s["message"] = "completed"
            asyncio.create_task(_remove_session_later(sid, 60))
            return step2_result
        else:
            s["status"] = "error"
            s["message"] = f"step2 returned unexpected result: {step2_result}"
            s["result"] = {"status": "error", "message": s["message"]}
            _close_browser(bot)
            asyncio.create_task(_remove_session_later(sid, 30))
            return {"status": "error", "message": s["message"]}

    except Exception as e:
        if s:
            s["status"] = "error"
            s["message"] = f"worker exception: {e}"
            s["result"] = {"status": "error", "message": s["message"]}
        if bot:
            _close_browser(bot)
        asyncio.create_task(_remove_session_later(sid, 30))
        return {"status": "error", "message": f"worker exception: {e}"}


def submit_otp(sid: str, otp: str) -> Dict[str, Any]:
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
