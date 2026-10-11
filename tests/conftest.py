import os
import sys
import tempfile
from pathlib import Path

# Isolated data folder and no real AI keys for every test run.
os.environ["ATHARVA_DATA_DIR"] = tempfile.mkdtemp(prefix="atharva-test-")
for key in ("GROQ_API_KEY", "OPENAI_API_KEY", "MODEL"):
    os.environ[key] = ""
os.environ["TIMEZONE"] = "Asia/Kolkata"
os.environ["MONGODB_URI"] = "mongomock://tests"  # in-memory MongoDB, no server needed
os.environ["SECRET_KEY"] = "test-secret"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
