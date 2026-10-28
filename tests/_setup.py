"""Import the project with every paid-API key blanked, so tests never call a model or spend credits."""
import os
import sys
from pathlib import Path

for k in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "NVIDIA_API_KEY", "SARVAM_API_KEY"):
    os.environ[k] = ""
PROJECT = str(Path(__file__).resolve().parent.parent)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
os.chdir(PROJECT)
