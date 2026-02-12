"""
Minimal browser manager for United SCO - only handles persistent profile and keeping browser alive.
Clears session cookies on startup (after PC restart) to force fresh login.
Tracks credentials to detect changes mid-session.
"""
import os
import shutil
import hashlib
import threading
import subprocess
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Ensure DISPLAY is set for Chrome to work (needed when running from SSH/background)
if not os.environ.get("DISPLAY"):
    os.environ["DISPLAY"] = ":0"


class UnitedSCOBrowserManager:
    """
    Singleton that manages a persistent Chrome browser instance for United SCO.
    - Uses --user-data-dir for persistent profile (device trust tokens)
    - Clears session cookies on startup (after PC restart)
    - Tracks credentials to detect changes mid-session
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._driver = None
                cls._instance.profile_dir = os.path.abspath("chrome_profile_unitedsco")
                cls._instance.download_dir = os.path.abspath("seleniumDownloads")
                cls._instance._credentials_file = os.path.join(cls._instance.profile_dir, ".last_credentials")
                cls._instance._needs_session_clear = False  # Flag to clear session on next driver creation
                os.makedirs(cls._instance.profile_dir, exist_ok=True)
                os.makedirs(cls._instance.download_dir, exist_ok=True)
        return cls._instance

    def clear_session_on_startup(self):
        """
        Clear session cookies from Chrome profile on startup.
        This forces a fresh login after PC restart.
        Preserves device trust tokens (LocalStorage, IndexedDB) to avoid OTPs.
        """
        print("[UnitedSCO BrowserManager] Clearing session on startup...")
        
        try:
            # Clear the credentials tracking file
            if os.path.exists(self._credentials_file):
                os.remove(self._credentials_file)
                print("[UnitedSCO BrowserManager] Cleared credentials tracking file")
            
            # Clear session-related files from Chrome profile
            # These are the files that store login session cookies
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
                        print(f"[UnitedSCO BrowserManager] Removed {filename}")
                    except Exception as e:
                        print(f"[UnitedSCO BrowserManager] Could not remove {filename}: {e}")
            
            # Also try root level (some Chrome versions)
            for filename in session_files:
                filepath = os.path.join(self.profile_dir, filename)
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        print(f"[UnitedSCO BrowserManager] Removed root {filename}")
                    except Exception as e:
                        print(f"[UnitedSCO BrowserManager] Could not remove root {filename}: {e}")
            
            # Clear Session Storage (contains login state)
            session_storage_dir = os.path.join(self.profile_dir, "Default", "Session Storage")
            if os.path.exists(session_storage_dir):
                try:
                    shutil.rmtree(session_storage_dir)
                    print("[UnitedSCO BrowserManager] Cleared Session Storage")
                except Exception as e:
                    print(f"[UnitedSCO BrowserManager] Could not clear Session Storage: {e}")
            
            # Clear Local Storage (may contain auth tokens)
            local_storage_dir = os.path.join(self.profile_dir, "Default", "Local Storage")
            if os.path.exists(local_storage_dir):
                try:
                    shutil.rmtree(local_storage_dir)
                    print("[UnitedSCO BrowserManager] Cleared Local Storage")
                except Exception as e:
                    print(f"[UnitedSCO BrowserManager] Could not clear Local Storage: {e}")
            
            # Clear IndexedDB (may contain auth tokens)
            indexeddb_dir = os.path.join(self.profile_dir, "Default", "IndexedDB")
            if os.path.exists(indexeddb_dir):
                try:
                    shutil.rmtree(indexeddb_dir)
                    print("[UnitedSCO BrowserManager] Cleared IndexedDB")
                except Exception as e:
                    print(f"[UnitedSCO BrowserManager] Could not clear IndexedDB: {e}")
            
            # Clear browser cache (prevents corrupted cached responses)
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
                        print(f"[UnitedSCO BrowserManager] Cleared {os.path.basename(cache_dir)}")
                    except Exception as e:
                        print(f"[UnitedSCO BrowserManager] Could not clear {os.path.basename(cache_dir)}: {e}")
            
            # Set flag to clear session via JavaScript after browser opens
            self._needs_session_clear = True
            
            print("[UnitedSCO BrowserManager] Session cleared - will require fresh login")
            
        except Exception as e:
            print(f"[UnitedSCO BrowserManager] Error clearing session: {e}")

    def _hash_credentials(self, username: str) -> str:
        """Create a hash of the username to track credential changes."""
        return hashlib.sha256(username.encode()).hexdigest()[:16]
    
    def get_last_credentials_hash(self) -> str | None:
        """Get the hash of the last-used credentials."""
        try:
            if os.path.exists(self._credentials_file):
                with open(self._credentials_file, 'r') as f:
                    return f.read().strip()
        except Exception:
            pass
        return None
    
    def save_credentials_hash(self, username: str):
        """Save the hash of the current credentials."""
        try:
            cred_hash = self._hash_credentials(username)
            with open(self._credentials_file, 'w') as f:
                f.write(cred_hash)
        except Exception as e:
            print(f"[UnitedSCO BrowserManager] Failed to save credentials hash: {e}")
    
    def credentials_changed(self, username: str) -> bool:
        """Check if the credentials have changed since last login."""
        last_hash = self.get_last_credentials_hash()
        if last_hash is None:
            return False  # No previous credentials, not a change
        current_hash = self._hash_credentials(username)
        changed = last_hash != current_hash
        if changed:
            print(f"[UnitedSCO BrowserManager] Credentials changed - logout required")
        return changed
    
    def clear_credentials_hash(self):
        """Clear the saved credentials hash (used after logout)."""
        try:
            if os.path.exists(self._credentials_file):
                os.remove(self._credentials_file)
        except Exception as e:
            print(f"[UnitedSCO BrowserManager] Failed to clear credentials hash: {e}")

    def _kill_existing_chrome_for_profile(self):
        """Kill any existing Chrome processes using this profile."""
        try:
            # Find and kill Chrome processes using this profile
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
        except Exception as e:
            pass
        
        # Remove SingletonLock if exists
        lock_file = os.path.join(self.profile_dir, "SingletonLock")
        try:
            if os.path.islink(lock_file) or os.path.exists(lock_file):
                os.remove(lock_file)
        except:
            pass

    def get_driver(self, headless=False):
        """Get or create the persistent browser instance."""
        with self._lock:
            if self._driver is None:
                print("[UnitedSCO BrowserManager] Driver is None, creating new driver")
                self._kill_existing_chrome_for_profile()
                self._create_driver(headless)
            elif not self._is_alive():
                print("[UnitedSCO BrowserManager] Driver not alive, recreating")
                self._kill_existing_chrome_for_profile()
                self._create_driver(headless)
            else:
                print("[UnitedSCO BrowserManager] Reusing existing driver")
            return self._driver

    def _is_alive(self):
        """Check if browser is still responsive."""
        try:
            if self._driver is None:
                return False
            url = self._driver.current_url
            return True
        except Exception as e:
            return False

    def _create_driver(self, headless=False):
        """Create browser with persistent profile."""
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
        
        # Persistent profile - THIS IS THE KEY for device trust
        options.add_argument(f"--user-data-dir={self.profile_dir}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        # Anti-detection options (prevent bot detection)
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--disable-infobars")
        
        prefs = {
            "download.default_directory": self.download_dir,
            "plugins.always_open_pdf_externally": True,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            # Disable password save dialog that blocks page interactions
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.password_manager_leak_detection": False,
        }
        options.add_experimental_option("prefs", prefs)

        service = Service(ChromeDriverManager().install())
        self._driver = webdriver.Chrome(service=service, options=options)
        self._driver.maximize_window()
        
        # Remove webdriver property to avoid detection
        try:
            self._driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except Exception:
            pass
        
        # Reset the session clear flag (file-based clearing is done on startup)
        self._needs_session_clear = False

    def quit_driver(self):
        """Quit browser (only call on shutdown)."""
        with self._lock:
            if self._driver:
                try:
                    self._driver.quit()
                except:
                    pass
                self._driver = None
            # Also clean up any orphaned processes
            self._kill_existing_chrome_for_profile()


# Singleton accessor
_manager = None

def get_browser_manager():
    global _manager
    if _manager is None:
        _manager = UnitedSCOBrowserManager()
    return _manager


def clear_unitedsco_session_on_startup():
    """Called by agent.py on startup to clear session."""
    manager = get_browser_manager()
    manager.clear_session_on_startup()
