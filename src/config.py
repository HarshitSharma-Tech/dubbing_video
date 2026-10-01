import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "outputs"

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Default configs
DEFAULT_MODEL = "base"
DEFAULT_VOICE = "en-US-AriaNeural"
DEFAULT_DEVICE = "cpu"

import shutil
if not shutil.which("ffmpeg"):
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        winget_bin = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
        ffmpeg_matches = list(winget_bin.glob("**/ffmpeg.exe"))
        if ffmpeg_matches:
            ffmpeg_dir = str(ffmpeg_matches[0].parent)
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
