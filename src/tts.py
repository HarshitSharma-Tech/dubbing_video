import edge_tts
import asyncio
import os
import re
import logging
from pydub import AudioSegment

logger = logging.getLogger(__name__)

def _get_appropriate_voice(text: str, default_voice: str) -> str:
    """
    If the text contains Devanagari (Hindi) or Arabic/Urdu characters and default voice is English,
    use a voice capable of speaking that script to prevent TTS crashes.
    """
    has_devanagari = any('\u0900' <= c <= '\u097f' for c in text)
    has_arabic_urdu = any('\u0600' <= c <= '\u06ff' for c in text)
    
    if default_voice.startswith("en-"):
        if has_devanagari:
            return "hi-IN-SwaraNeural"
        elif has_arabic_urdu:
            return "ur-PK-UzmaNeural"
    return default_voice

async def generate_speech_async(text: str, voice: str, output_path: str):
    clean_text = text.strip()
    if not clean_text:
        silence = AudioSegment.silent(duration=500)
        silence.export(output_path, format="mp3")
        return
        
    actual_voice = _get_appropriate_voice(clean_text, voice)
    communicate = edge_tts.Communicate(clean_text, actual_voice)
    await communicate.save(output_path)

def generate_speech(text: str, voice: str, output_path: str):
    """
    Generates speech from text using edge-tts and saves to output_path.
    """
    try:
        asyncio.run(generate_speech_async(text, voice, output_path))
    except Exception as e:
        logger.error(f"TTS generation failed for text: '{text[:40]}...'. Error: {e}")
        silence = AudioSegment.silent(duration=500)
        silence.export(output_path, format="mp3")

async def generate_speech_batch_async(tasks: list, max_concurrency: int = 5, progress_callback=None):
    """
    Generates speech for a batch of tasks asynchronously with bounded concurrency,
    auto-retry, and fallback voice adaptation.
    Each task is a tuple of (text, voice, output_path).
    """
    semaphore = asyncio.Semaphore(max_concurrency)
    completed_count = 0
    total_count = len(tasks)

    async def worker(text: str, voice: str, output_path: str):
        nonlocal completed_count
        clean_text = text.strip()
        if not clean_text:
            silence = AudioSegment.silent(duration=500)
            silence.export(output_path, format="mp3")
            completed_count += 1
            return

        if os.path.exists(output_path) and os.path.getsize(output_path) > 200:
            completed_count += 1
            return

        actual_voice = _get_appropriate_voice(clean_text, voice)

        async with semaphore:
            for attempt in range(3):
                try:
                    communicate = edge_tts.Communicate(clean_text, actual_voice)
                    await asyncio.wait_for(communicate.save(output_path), timeout=15.0)
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 200:
                        break
                except Exception as e:
                    if attempt == 2:
                        logger.error(f"TTS generation permanently failed for: '{clean_text[:40]}...'. Error: {e}")
                        silence = AudioSegment.silent(duration=500)
                        silence.export(output_path, format="mp3")
                    else:
                        await asyncio.sleep(1.0 * (attempt + 1))
            
            completed_count += 1
            if progress_callback and (completed_count % 15 == 0 or completed_count == total_count):
                progress_callback({
                    "stage": "tts",
                    "status": "in_progress",
                    "message": f"Synthesized {completed_count}/{total_count} voice clips",
                    "progress": round((completed_count / total_count) * 100, 1),
                    "count": completed_count,
                    "total": total_count
                })

    await asyncio.gather(*(worker(t, v, o) for t, v, o in tasks))

def generate_speech_batch(tasks: list, max_concurrency: int = 5, progress_callback=None):
    """
    Synchronous wrapper for batch TTS generation.
    """
    asyncio.run(generate_speech_batch_async(tasks, max_concurrency=max_concurrency, progress_callback=progress_callback))

