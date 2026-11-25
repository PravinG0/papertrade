"""Never let the test suite open a developer's actual trading DB or use live credentials."""
import os
import tempfile
from pathlib import Path
import atexit

_test_directory = tempfile.TemporaryDirectory(prefix="papertrade-test-")
atexit.register(_test_directory.cleanup)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_test_directory.name) / 'test.db'}"
for key in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET", "GEMINI_API_KEY", "GOOGLE_CLIENT_SECRET"):
    os.environ[key] = ""
os.environ["JWT_SECRET_KEY"] = "test-only-private-key-not-for-deployment"
os.environ["ENABLE_KEEP_ALIVE"] = "false"
os.environ["ALLOW_SIMULATED_TRADING"] = "true"
os.environ["ALLOW_OFFHOURS_TRADING"] = "true"
os.environ["SCRIP_CACHE_PATH"] = str(Path(_test_directory.name) / "scrip.json")
