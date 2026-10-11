"""Vercel entry point: Vercel looks for an `app` object in a root-level index.py.

The real application lives in app/main.py; this file only makes sure the project folder is
importable (so `import app...` works the same on Vercel as on your computer) and re-exports it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app  # noqa: E402,F401
