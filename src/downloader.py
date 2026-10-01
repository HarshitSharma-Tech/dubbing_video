import yt_dlp
import os
import time
import shutil
import logging
from pathlib import Path
import subprocess

logger = logging.getLogger(__name__)

def is_valid_video_with_audio(file_path: str) -> bool:
    if not os.path.exists(file_path) or os.path.getsize(file_path) < 5 * 1024 * 1024:
        return False
    ffmpeg_bin = shutil.which("ffmpeg") or r"C:\Users\tarad\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe"
    test_wav = file_path + ".test.wav"
    cmd = [ffmpeg_bin, "-y", "-i", file_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "-t", "1", test_wav]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(test_wav):
        try: os.remove(test_wav)
        except Exception: pass
    return res.returncode == 0

def download_video(url: str, output_path: str, resolution: str = "480p") -> str:
    """
    Downloads the video from YouTube (or accepts a local file path) and returns the path to the downloaded file.
    Includes automatic browser cookie detection, cookies.txt detection, local file support, resolution limit, and Windows file-lock recovery.
    No extensions required!
    """
    # 1. Local file support: If user passed an existing local video path
    if os.path.exists(url) and os.path.isfile(url):
        logger.info(f"Local video file detected at {url}. Copying to {output_path}...")
        shutil.copy2(url, output_path)
        return output_path

    # 2. Reuse existing download if already present and valid with audio stream
    if is_valid_video_with_audio(output_path):
        logger.info(f"Valid video with audio track already exists at {output_path} ({round(os.path.getsize(output_path) / (1024*1024), 2)} MB). Reusing existing download.")
        return output_path
    elif os.path.exists(output_path):
        logger.warning(f"Existing file at {output_path} is invalid/missing audio track. Removing for fresh download...")
        try:
            os.remove(output_path)
        except Exception:
            pass

    max_height = 480
    if resolution:
        clean_res = str(resolution).lower().replace("p", "").strip()
        if clean_res.isdigit():
            max_height = int(clean_res)

    logger.info(f"Downloading video from {url} at resolution height <={max_height}p...")
    
    ffmpeg_path = shutil.which("ffmpeg") or r"C:\Users\tarad\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe"
    
    ydl_opts = {
        'format': f'bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best',
        'outtmpl': output_path,
        'quiet': False,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        'retries': 20,
        'fragment_retries': 20,
        'socket_timeout': 30,
        'file_access_retries': 5,
        'continuedl': True,
        'nopart': True,
        'js_runtimes': {'node': {}},
        'ffmpeg_location': ffmpeg_path,
    }
    
    # Check for optional cookies.txt if present
    cookie_candidates = [
        Path("cookies.txt"),
        Path(__file__).resolve().parent.parent / "cookies.txt",
        Path(__file__).resolve().parent.parent.parent / "cookies.txt"
    ]
    for candidate in cookie_candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            logger.info(f"Found YouTube cookies file at: {candidate}. Using for authenticated download.")
            ydl_opts['cookiefile'] = str(candidate)
            break

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        time.sleep(1)
        output_dir = os.path.dirname(os.path.abspath(output_path))
        target_name = os.path.basename(output_path).replace(".mp4", "")
        part_matches = [
            os.path.join(output_dir, f) for f in os.listdir(output_dir)
            if f.startswith(target_name) and (f.endswith(".part") or f.endswith(".ytdl"))
        ]
        if part_matches:
            best_part = max(part_matches, key=os.path.getsize)
            if os.path.getsize(best_part) > 1000000:
                logger.info(f"Recovering downloaded video file from {best_part} ({round(os.path.getsize(best_part)/(1024*1024),2)} MB)...")
                try:
                    shutil.copyfile(best_part, output_path)
                    logger.info(f"Successfully recovered {output_path} ({round(os.path.getsize(output_path)/(1024*1024),2)} MB)")
                    return output_path
                except Exception as move_err:
                    logger.warning(f"Could not copy {best_part}: {move_err}")

        temp_target = output_path.replace(".mp4", ".temp.mp4")
        if os.path.exists(temp_target):
            logger.info(f"Recovering merged file from {temp_target}...")
            shutil.move(temp_target, output_path)
            return output_path
        elif os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
            return output_path
        
        # If YouTube threw a bot-check or 403 error, try browser cookies automatically (Zero extension needed!)
        err_str = str(e)
        if "Sign in to confirm" in err_str or "403" in err_str or "Forbidden" in err_str:
            logger.info("YouTube bot check / 403 Forbidden detected. Trying automatic browser cookie authentication (no extension needed)...")
            for browser in ['chrome', 'edge', 'firefox', 'brave']:
                try:
                    logger.info(f"Trying to authenticate via {browser}...")
                    retry_opts = dict(ydl_opts)
                    retry_opts.pop('concurrent_fragment_downloads', None)
                    retry_opts['cookiesfrombrowser'] = (browser, None, None, None)
                    with yt_dlp.YoutubeDL(retry_opts) as ydl:
                        ydl.download([url])
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
                        logger.info(f"Successfully authenticated and downloaded using {browser} cookies!")
                        return output_path
                except Exception:
                    continue

            logger.error("\n" + "="*70)
            logger.error("🛑 YOUTUBE BOT VERIFICATION REQUIRED FOR THIS VIDEO")
            logger.error("YouTube blocked automated scraping for this specific video without authentication.")
            logger.error("Zero-Extension Solutions:")
            logger.error("1. Close your Chrome or Edge browser window for 10 seconds so the script can read your logged-in cookies.")
            logger.error("2. OR test any other video link (most videos on YouTube download directly without any bot checks).")
            logger.error("3. OR if you already downloaded the video, simply pass the local file path (e.g. temp/original_video.mp4).")
            logger.error("="*70 + "\n")
            raise e
        else:
            raise e
        
    logger.info(f"Downloaded video to {output_path}")
    return output_path
