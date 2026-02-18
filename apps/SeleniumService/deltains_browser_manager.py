"""
Browser manager for Delta Dental Ins - handles persistent profile, cookie
save/restore (for Okta session-only cookies), and keeping browser alive.
Tracks credentials to detect changes mid-session.
"""
import os
import json
import shutil
import hashlib
import threading
import subprocess
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

if not os.environ.get("DISPLAY"):
    os.environ["DISPLAY"] = ":0"

DELTAINS_DOMAIN = ".deltadentalins.com"
OKTA_DOMAINS = [".okta.com", ".oktacdn.com"]


class DeltaInsBrowserManager:
    """
    Singleton that manages a persistent Chrome browser instance for Delta Dental Ins.
    - Uses --user-data-dir for persistent profile
    - Saves/restores Okta session cookies to survive browser restarts
    - Tracks credentials to detect changes mid-session
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._driver = None
                cls._instance.profile_dir = os.path.abspath("chrome_profile_deltains")
                cls._instance.download_dir = os.path.abspath("seleniumDownloads")
                cls._instance._credentials_file = os.path.join(cls._instance.profile_dir, ".last_credentials")
                cls._instance._cookies_file = os.path.join(cls._instance.profile_dir, ".saved_cookies.json")
                cls._instance._needs_session_clear = False
                os.makedirs(cls._instance.profile_dir, exist_ok=True)
                os.makedirs(cls._instance.download_dir, exist_ok=True)
        return cls._instance

    # ── Cookie save / restore ──────────────────────────────────────────

    def save_cookies(self):
        """Save all browser cookies to a JSON file so they survive browser restart."""
        try:
            if not self._driver:
                return
            cookies = self._driver.get_cookies()
            if not cookies:
                return
            with open(self._cookies_file, "w") as f:
                json.dump(cookies, f)
            print(f"[DeltaIns BrowserManager] Saved {len(cookies)} cookies to disk")
        except Exception as e:
            print(f"[DeltaIns BrowserManager] Failed to save cookies: {e}")

    def restore_cookies(self):
        """Restore saved cookies into the current browser session."""
        if not os.path.exists(self._cookies_file):
            print("[DeltaIns BrowserManager] No saved cookies file found")
            return False

        try:
            with open(self._cookies_file, "r") as f:
                cookies = json.load(f)

            if not cookies:
                print("[DeltaIns BrowserManager] Saved cookies file is empty")
                return False

            # Navigate to the DeltaIns domain first so we can set cookies for it
            try:
                self._driver.get("https://www.deltadentalins.com/favicon.ico")
                time.sleep(2)
            except Exception:
                self._driver.get("https://www.deltadentalins.com")
                time.sleep(3)

            restored = 0
            for cookie in cookies:
                try:
                    # Remove problematic fields that Selenium doesn't accept
                    for key in ["sameSite", "storeId", "hostOnly", "session"]:
                        cookie.pop(key, None)
                    # sameSite must be one of: Strict, Lax, None
                    cookie["sameSite"] = "None"
                    self._driver.add_cookie(cookie)
                    restored += 1
                except Exception:
                    pass

            print(f"[DeltaIns BrowserManager] Restored {restored}/{len(cookies)} cookies")
            return restored > 0

        except Exception as e:
            print(f"[DeltaIns BrowserManager] Failed to restore cookies: {e}")
            return False

    def clear_saved_cookies(self):
        """Delete the saved cookies file."""
        try:
            if os.path.exists(self._cookies_file):
                os.remove(self._cookies_file)
                print("[DeltaIns BrowserManager] Cleared saved cookies file")
        except Exception as e:
            print(f"[DeltaIns BrowserManager] Failed to clear saved cookies: {e}")

    # ── Session clear ──────────────────────────────────────────────────

    def clear_session_on_startup(self):
        """
        Clear session cookies from Chrome profile on startup.
        This forces a fresh login after PC restart.
        """
        print("[DeltaIns BrowserManager] Clearing session on startup...")

        try:
            if os.path.exists(self._credentials_file):
                os.remove(self._credentials_file)
                print("[DeltaIns BrowserManager] Cleared credentials tracking file")

            # Also clear saved cookies
            self.clear_saved_cookies()

            session_files = [
                "Cookies",
                "Cookies-journal",
                "Login Data",
                "Login Data-journal",
                "Web Data",
                "Web Data-journal",
            ]

            for filename in session_files:
                filepath = os.path.join(self.profile_dir, "Default", filename)
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        print(f"[DeltaIns BrowserManager] Removed {filename}")
                    except Exception as e:
                        print(f"[DeltaIns BrowserManager] Could not remove {filename}: {e}")

            for filename in session_files:
                filepath = os.path.join(self.profile_dir, filename)
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        print(f"[DeltaIns BrowserManager] Removed root {filename}")
                    except Exception as e:
                        print(f"[DeltaIns BrowserManager] Could not remove root {filename}: {e}")

            session_storage_dir = os.path.join(self.profile_dir, "Default", "Session Storage")
            if os.path.exists(session_storage_dir):
                try:
                    shutil.rmtree(session_storage_dir)
                    print("[DeltaIns BrowserManager] Cleared Session Storage")
                except Exception as e:
                    print(f"[DeltaIns BrowserManager] Could not clear Session Storage: {e}")

            local_storage_dir = os.path.join(self.profile_dir, "Default", "Local Storage")
            if os.path.exists(local_storage_dir):
                try:
                    shutil.rmtree(local_storage_dir)
                    print("[DeltaIns BrowserManager] Cleared Local Storage")
                except Exception as e:
                    print(f"[DeltaIns BrowserManager] Could not clear Local Storage: {e}")

            indexeddb_dir = os.path.join(self.profile_dir, "Default", "IndexedDB")
            if os.path.exists(indexeddb_dir):
                try:
                    shutil.rmtree(indexeddb_dir)
                    print("[DeltaIns BrowserManager] Cleared IndexedDB")
                except Exception as e:
                    print(f"[DeltaIns BrowserManager] Could not clear IndexedDB: {e}")

            cache_dirs = [
                os.path.join(self.profile_dir, "Default", "Cache"),
                os.path.join(self.profile_dir, "Default", "Code Cache"),
                os.path.join(self.profile_dir, "Default", "GPUCache"),
                os.path.join(self.profile_dir, "Default", "Service Worker"),
                os.path.join(self.profile_dir, "Cache"),
                os.path.join(self.profile_dir, "Code Cache"),
                os.path.join(self.profile_dir, "GPUCache"),
                os.path.join(self.profile_dir, "Service Worker"),
                os.path.join(self.profile_dir, "ShaderCache"),
            ]
            for cache_dir in cache_dirs:
                if os.path.exists(cache_dir):
                    try:
                        shutil.rmtree(cache_dir)
                        print(f"[DeltaIns BrowserManager] Cleared {os.path.basename(cache_dir)}")
                    except Exception as e:
                        print(f"[DeltaIns BrowserManager] Could not clear {os.path.basename(cache_dir)}: {e}")

            self._needs_session_clear = True
            print("[DeltaIns BrowserManager] Session cleared - will require fresh login")

        except Exception as e:
            print(f"[DeltaIns BrowserManager] Error clearing session: {e}")

    # ── Credential tracking ────────────────────────────────────────────

    def _hash_credentials(self, username: str) -> str:
        return hashlib.sha256(username.encode()).hexdigest()[:16]

    def get_last_credentials_hash(self) -> str | None:
        try:
            if os.path.exists(self._credentials_file):
                with open(self._credentials_file, 'r') as f:
                    return f.read().strip()
        except Exception:
            pass
        return None

    def save_credentials_hash(self, username: str):
        try:
            cred_hash = self._hash_credentials(username)
            with open(self._credentials_file, 'w') as f:
                f.write(cred_hash)
        except Exception as e:
            print(f"[DeltaIns BrowserManager] Failed to save credentials hash: {e}")

    def credentials_changed(self, username: str) -> bool:
        last_hash = self.get_last_credentials_hash()
        if last_hash is None:
            return False
        current_hash = self._hash_credentials(username)
        changed = last_hash != current_hash
        if changed:
            print("[DeltaIns BrowserManager] Credentials changed - logout required")
        return changed

    def clear_credentials_hash(self):
        try:
            if os.path.exists(self._credentials_file):
                os.remove(self._credentials_file)
        except Exception as e:
            print(f"[DeltaIns BrowserManager] Failed to clear credentials hash: {e}")

    # ── Chrome process management ──────────────────────────────────────

    def _kill_existing_chrome_for_profile(self):
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"user-data-dir={self.profile_dir}"],
                capture_output=True, text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        subprocess.run(["kill", "-9", pid], check=False)
                    except:
                        pass
                time.sleep(1)
        except Exception:
            pass

        for lock_file in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
            lock_path = os.path.join(self.profile_dir, lock_file)
            try:
                if os.path.islink(lock_path) or os.path.exists(lock_path):
                    os.remove(lock_path)
            except:
                pass

    # ── Driver lifecycle ───────────────────────────────────────────────

    def get_driver(self, headless=False):
        with self._lock:
            need_cookie_restore = False

            if self._driver is None:
                print("[DeltaIns BrowserManager] Driver is None, creating new driver")
                self._kill_existing_chrome_for_profile()
                self._create_driver(headless)
                need_cookie_restore = True
            elif not self._is_alive():
                print("[DeltaIns BrowserManager] Driver not alive, recreating")
                # Save cookies from the dead session if possible (usually can't)
                self._kill_existing_chrome_for_profile()
                self._create_driver(headless)
                need_cookie_restore = True
            else:
                print("[DeltaIns BrowserManager] Reusing existing driver")

            if need_cookie_restore and os.path.exists(self._cookies_file):
                print("[DeltaIns BrowserManager] Restoring saved cookies into new browser...")
                self.restore_cookies()

            return self._driver

    def _is_alive(self):
        try:
            if self._driver is None:
                return False
            _ = self._driver.current_url
            return True
        except Exception:
            return False

    def _create_driver(self, headless=False):
        if self._driver:
            try:
                self._driver.quit()
            except:
                pass
            self._driver = None
            time.sleep(1)

        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("--headless")

        options.add_argument(f"--user-data-dir={self.profile_dir}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--disable-infobars")

        prefs = {
            "download.default_directory": self.download_dir,
            "plugins.always_open_pdf_externally": True,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.password_manager_leak_detection": False,
        }
        options.add_experimental_option("prefs", prefs)

        service = Service(ChromeDriverManager().install())
        self._driver = webdriver.Chrome(service=service, options=options)
        self._driver.maximize_window()

        try:
            self._driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except Exception:
            pass

        self._needs_session_clear = False

    def quit_driver(self):
        with self._lock:
            if self._driver:
                try:
                    self._driver.quit()
                except:
                    pass
                self._driver = None
            self._kill_existing_chrome_for_profile()


_manager = None

def get_browser_manager():
    global _manager
    if _manager is None:
        _manager = DeltaInsBrowserManager()
    return _manager


def clear_deltains_session_on_startup():
    """Called by agent.py on startup to clear session."""
    manager = get_browser_manager()
    manager.clear_session_on_startup()
