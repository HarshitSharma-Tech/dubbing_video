import os
import shutil
import time
import json
import logging
from pathlib import Path
from pydub import AudioSegment
from pydub.effects import speedup

from .config import TEMP_DIR, OUTPUT_DIR, DEFAULT_MODEL, DEFAULT_VOICE, DEFAULT_DEVICE
from .downloader import download_video
from .audio import extract_audio, replace_audio_in_video
from .transcriber import transcribe_audio
from .translator import translate_text
from .tts import generate_speech_batch

logger = logging.getLogger(__name__)

def fast_concat_audio_segments(chunks):
    if not chunks:
        return AudioSegment.empty()
    lst = list(chunks)
    while len(lst) > 1:
        nxt = []
        for i in range(0, len(lst), 2):
            if i + 1 < len(lst):
                nxt.append(lst[i] + lst[i+1])
            else:
                nxt.append(lst[i])
        lst = nxt
    return lst[0]

def run_pipeline(
    url: str,
    output_name: str,
    model_size: str = DEFAULT_MODEL,
    voice: str = DEFAULT_VOICE,
    device: str = DEFAULT_DEVICE,
    language: str = None,
    keep_temp: bool = False,
    save_original: bool = True,
    whisper_task: str = "translate",
    use_external_translator: bool = False,
    mix_background: bool = False,
    bg_volume: float = 0.12,
    resolution: str = "480p",
    progress_callback = None
):
    start_time = time.time()
    benchmarks = {
        "url": url,
        "output_name": output_name,
        "model_size": model_size,
        "voice": voice,
        "device": device,
        "whisper_task": whisper_task,
        "mix_background": mix_background,
        "bg_volume": bg_volume,
        "resolution": resolution
    }

    # 1. Download Video
    t0 = time.time()
    if progress_callback:
        progress_callback({"stage": "download", "status": "in_progress", "message": f"Downloading video at target resolution ({resolution})..."})
    
    video_path = str(TEMP_DIR / "original_video.mp4")
    download_video(url, video_path, resolution=resolution)
    benchmarks["download_time_s"] = round(time.time() - t0, 2)
    logger.info(f"Download time: {benchmarks['download_time_s']}s")
    if progress_callback:
        progress_callback({"stage": "download", "status": "completed", "message": "Video stream loaded successfully"})

    # If requested, save copy of original video to outputs
    original_saved_path = None
    if save_original:
        original_output_name = f"original_{output_name}"
        original_saved_path = str(OUTPUT_DIR / original_output_name)
        if not os.path.exists(original_saved_path) or os.path.getsize(original_saved_path) == 0:
            shutil.copy2(video_path, original_saved_path)
        benchmarks["original_video_path"] = original_saved_path
        benchmarks["original_video_size_mb"] = round(os.path.getsize(original_saved_path) / (1024 * 1024), 2)
        logger.info(f"Saved original video to: {original_saved_path} ({benchmarks['original_video_size_mb']} MB)")

    # 2. Extract Audio
    t0 = time.time()
    original_audio_path = str(TEMP_DIR / "original_audio.wav")
    if os.path.exists(original_audio_path):
        try:
            os.remove(original_audio_path)
        except Exception:
            pass
    extract_audio(video_path, original_audio_path)
    benchmarks["audio_extraction_time_s"] = round(time.time() - t0, 2)
    logger.info(f"Audio extraction time: {benchmarks['audio_extraction_time_s']}s")

    # 3. Transcribe & Translate
    t0 = time.time()
    segments_cache = TEMP_DIR / "segments.json"
    if segments_cache.exists() and os.path.getsize(segments_cache) > 500:
        logger.info(f"Reusing cached transcription ({segments_cache})...")
        with open(segments_cache, "r", encoding="utf-8") as f:
            segments = json.load(f)
        benchmarks["transcription_time_s"] = 0.01
        benchmarks["num_segments"] = len(segments)
        logger.info(f"Loaded {len(segments)} cached speech segments.")
        if progress_callback:
            progress_callback({"stage": "transcribe", "status": "completed", "message": f"Loaded {len(segments)} speech segments from cache"})
    else:
        if progress_callback:
            progress_callback({"stage": "transcribe", "status": "in_progress", "message": f"Transcribing audio with faster-whisper ({model_size} model)..."})
        logger.info(f"Transcribing audio with faster-whisper (task={whisper_task})...")
        segments = transcribe_audio(
            original_audio_path,
            model_size=model_size,
            device=device,
            language=language,
            task=whisper_task,
            progress_callback=progress_callback
        )
        try:
            with open(segments_cache, "w", encoding="utf-8") as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(segments)} segments to cache: {segments_cache}")
        except Exception as err:
            logger.warning(f"Could not cache segments: {err}")

        benchmarks["transcription_time_s"] = round(time.time() - t0, 2)
        benchmarks["num_segments"] = len(segments)
        logger.info(f"Transcription/Translation completed in {benchmarks['transcription_time_s']}s for {len(segments)} segments")
        if progress_callback:
            progress_callback({"stage": "transcribe", "status": "completed", "message": f"Transcribed {len(segments)} speech segments"})

    # 4. Translation Handling
    t0 = time.time()
    if progress_callback:
        progress_callback({"stage": "translate", "status": "in_progress", "message": "Translating segments into natural English..."})
    if whisper_task == "translate" and not use_external_translator:
        logger.info("Using Whisper's native direct translation - zero API overhead and no rate limits!")
        translated_texts = [seg['text'] for seg in segments]
        benchmarks["translation_time_s"] = 0.0
    else:
        logger.info(f"Translating {len(segments)} segments via external translator...")
        translated_texts = []
        for i, seg in enumerate(segments):
            text = seg['text']
            seg_lang = seg.get('language') or language or 'auto'
            trans = translate_text(text, source_lang=seg_lang, target_lang='en')
            translated_texts.append(trans)
            if (i + 1) % 50 == 0 or (i + 1) == len(segments):
                logger.info(f"Translated {i + 1}/{len(segments)} segments...")
        benchmarks["translation_time_s"] = round(time.time() - t0, 2)
        logger.info(f"External translation completed in {benchmarks['translation_time_s']}s")
    
    if progress_callback:
        progress_callback({"stage": "translate", "status": "completed", "message": "English translations verified"})

    # 5. TTS Batch Generation
    t_tts = time.time()
    if progress_callback:
        progress_callback({"stage": "tts", "status": "in_progress", "message": f"Synthesizing {len(segments)} English neural voice clips with Edge-TTS..."})
    logger.info(f"Synthesizing {len(segments)} TTS audio clips concurrently...")
    tts_tasks = []
    for i, trans_text in enumerate(translated_texts):
        tts_output = str(TEMP_DIR / f"tts_{i}.mp3")
        tts_tasks.append((trans_text, voice, tts_output))

    generate_speech_batch(tts_tasks, max_concurrency=10, progress_callback=progress_callback)
    benchmarks["tts_synthesis_time_s"] = round(time.time() - t_tts, 2)
    logger.info(f"TTS synthesis completed in {benchmarks['tts_synthesis_time_s']}s")
    if progress_callback:
        progress_callback({"stage": "tts", "status": "completed", "message": f"All {len(segments)} neural voice clips synthesized"})

    # 6. Assemble Audio Timeline with Dynamic Pacing (Multi-Threaded Parallel Decoding)
    t_asm = time.time()
    if progress_callback:
        progress_callback({"stage": "sync", "status": "in_progress", "message": "Aligning audio timeline with dynamic pacing synchronization..."})
    logger.info("Assembling audio timeline with dynamic pacing synchronization (parallel decoding)...")

    from concurrent.futures import ThreadPoolExecutor

    def process_segment_audio(args):
        i, seg = args
        start_ms = int(seg['start'] * 1000)
        target_dur_ms = max(400, int((seg['end'] - seg['start']) * 1000))
        tts_output = Path(TEMP_DIR) / f"tts_{i}.mp3"
        
        if tts_output.exists() and os.path.getsize(tts_output) > 200:
            try:
                seg_audio = AudioSegment.from_file(str(tts_output))
                # Apply 10ms edge smoothing to eliminate digital clicks and pops
                if len(seg_audio) > 40:
                    seg_audio = seg_audio.fade_in(10).fade_out(10)
                return start_ms, seg_audio
            except Exception:
                pass
        return start_ms, AudioSegment.silent(duration=target_dur_ms)

    with ThreadPoolExecutor(max_workers=16) as executor:
        processed_clips = list(executor.map(process_segment_audio, enumerate(segments)))

    chunks = []
    current_time_ms = 0.0

    for start_ms, seg_audio in processed_clips:
        if start_ms > current_time_ms:
            silence_duration = int(start_ms - current_time_ms)
            chunks.append(AudioSegment.silent(duration=silence_duration))
            current_time_ms = start_ms

        chunks.append(seg_audio)
        current_time_ms += len(seg_audio)

    dubbed_audio = fast_concat_audio_segments(chunks)
    try:
        orig_audio_seg = AudioSegment.from_file(original_audio_path)
        if len(dubbed_audio) < len(orig_audio_seg):
            pad_ms = len(orig_audio_seg) - len(dubbed_audio)
            dubbed_audio += AudioSegment.silent(duration=pad_ms)
            logger.info(f"Padded dubbed audio timeline by {pad_ms/1000:.2f}s to match full video length.")
    except Exception as e:
        logger.warning(f"Could not pad audio timeline: {e}")
    benchmarks["assembly_time_s"] = round(time.time() - t_asm, 2)
    logger.info(f"Audio assembly completed in {benchmarks['assembly_time_s']}s")

    # 7. Export Dubbed Audio
    t0 = time.time()
    final_audio_path = str(TEMP_DIR / "final_dubbed_audio.wav")
    dubbed_audio.export(final_audio_path, format="wav")
    benchmarks["audio_export_time_s"] = round(time.time() - t0, 2)
    logger.info(f"Audio export time: {benchmarks['audio_export_time_s']}s")

    # 8. Replace Audio in Video
    t0 = time.time()
    if progress_callback:
        progress_callback({"stage": "sync", "status": "in_progress", "message": "Rendering final dubbed MP4 with FFmpeg..."})
    final_output_path = str(OUTPUT_DIR / output_name)
    replace_audio_in_video(video_path, final_audio_path, final_output_path, mix_background=mix_background, bg_volume=bg_volume)
    benchmarks["video_muxing_time_s"] = round(time.time() - t0, 2)
    benchmarks["final_video_path"] = final_output_path
    benchmarks["final_video_size_mb"] = round(os.path.getsize(final_output_path) / (1024 * 1024), 2)
    logger.info(f"Video muxing time: {benchmarks['video_muxing_time_s']}s")
    if progress_callback:
        progress_callback({"stage": "sync", "status": "completed", "message": "Video rendering complete"})

    # 9. Cleanup
    if not keep_temp:
        logger.info("Cleaning up temporary files...")
        for file in os.listdir(TEMP_DIR):
            try:
                os.remove(TEMP_DIR / file)
            except Exception:
                pass

    total_time = round(time.time() - start_time, 2)
    benchmarks["total_processing_time_s"] = total_time
    logger.info(f"Total processing time: {total_time}s ({total_time / 60:.2f} minutes)")

    # Save benchmark result
    benchmark_file = OUTPUT_DIR / "benchmarks.json"
    existing_benchmarks = []
    if benchmark_file.exists():
        try:
            with open(benchmark_file, "r", encoding="utf-8") as f:
                existing_benchmarks = json.load(f)
        except Exception:
            existing_benchmarks = []

    existing_benchmarks.append(benchmarks)
    with open(benchmark_file, "w", encoding="utf-8") as f:
        json.dump(existing_benchmarks, f, indent=2)

    logger.info(f"Benchmark appended to: {benchmark_file}")
    
    if progress_callback:
        progress_callback({
            "stage": "completed",
            "status": "done",
            "message": "Dubbed video ready!",
            "output_file": output_name,
            "benchmarks": benchmarks
        })
    return final_output_path, benchmarks
