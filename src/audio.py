import subprocess
import logging

logger = logging.getLogger(__name__)

def extract_audio(video_path: str, audio_path: str):
    """
    Extracts the audio from a video file using ffmpeg to 16kHz mono WAV format.
    """
    logger.info(f"Extracting audio from {video_path} to {audio_path}...")
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        audio_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    logger.info("Audio extraction complete.")

def replace_audio_in_video(video_path: str, new_audio_path: str, output_path: str, mix_background: bool = False, bg_volume: float = 0.12):
    """
    Replaces the audio track of a video with a new audio file.
    By default (mix_background=False), completely removes the original foreign language audio track
    so there is zero collision with the original speech.
    If mix_background is True, ducks original audio underneath the dubbed speech.
    """
    logger.info(f"Muxing audio into video (mix_background={mix_background}, bg_volume={bg_volume})...")
    if mix_background:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", new_audio_path,
            "-filter_complex",
            f"[0:a]volume={bg_volume}[bg];[1:a]volume=1.0[voice];[bg][voice]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "0:v:0",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", new_audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-map", "0:v:0",
            "-map", "1:a:0",
            output_path
        ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    logger.info(f"Final video saved to {output_path}")
