import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CREDS_DIR = os.path.join(ROOT_DIR, "credentials")

for p in (ROOT_DIR, CREDS_DIR):
  if p not in sys.path:
    sys.path.insert(0, p)

from server import app  # noqa: E402, F401  # type: ignore[import-not-found]