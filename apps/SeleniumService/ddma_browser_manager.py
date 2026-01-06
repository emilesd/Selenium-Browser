"""
Minimal browser manager for DDMA - only handles persistent profile and keeping browser alive.
Does NOT modify any login/OTP logic.
"""
import os
import threading
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


class DDMABrowserManager:
    """
    Singleton that manages a persistent Chrome browser instance.
    - Uses --user-data-dir for persistent profile (device trust tokens, cookies)
    - Keeps browser alive between patient runs
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._driver = None
                cls._instance.profile_dir = os.path.abspath("chrome_profile_ddma")
                cls._instance.download_dir = os.path.abspath("seleniumDownloads")
                os.makedirs(cls._instance.profile_dir, exist_ok=True)
                os.makedirs(cls._instance.download_dir, exist_ok=True)
        return cls._instance

    def get_driver(self, headless=False):
        """Get or create the persistent browser instance."""
        with self._lock:
            if self._driver is None:
                print("[BrowserManager] Driver is None, creating new driver")
                self._create_driver(headless)
            elif not self._is_alive():
                print("[BrowserManager] Driver not alive, recreating")
                self._create_driver(headless)
            else:
                print("[BrowserManager] Reusing existing driver")
            return self._driver

    def _is_alive(self):
        """Check if browser is still responsive."""
        try:
            url = self._driver.current_url
            print(f"[BrowserManager] Driver alive, current URL: {url[:50]}...")
            return True
        except Exception as e:
            print(f"[BrowserManager] Driver not alive: {e}")
            return False

    def _create_driver(self, headless=False):
        """Create browser with persistent profile."""
        if self._driver:
            try:
                self._driver.quit()
            except:
                pass

        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("--headless")
        
        # Persistent profile - THIS IS THE KEY for device trust
        options.add_argument(f"--user-data-dir={self.profile_dir}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        prefs = {
            "download.default_directory": self.download_dir,
            "plugins.always_open_pdf_externally": True,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True
        }
        options.add_experimental_option("prefs", prefs)

        service = Service(ChromeDriverManager().install())
        self._driver = webdriver.Chrome(service=service, options=options)
        self._driver.maximize_window()

    def quit_driver(self):
        """Quit browser (only call on shutdown)."""
        with self._lock:
            if self._driver:
                try:
                    self._driver.quit()
                except:
                    pass
                self._driver = None


# Singleton accessor
_manager = None

def get_browser_manager():
    global _manager
    if _manager is None:
        _manager = DDMABrowserManager()
    return _manager
