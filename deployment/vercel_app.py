"""Cloud entrypoint; the application and calculation engine stay unchanged."""
import os
import tempfile
from pathlib import Path

from backend import power_client

# Serverless deployment files are read-only; weather downloads use temporary storage.
if os.environ.get("VERCEL"):
    power_client.CACHE_DIR = Path(tempfile.gettempdir()) / "yieldgenerator" / "power"

from backend.api import app  # noqa: E402,F401
