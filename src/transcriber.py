from faster_whisper import WhisperModel
import logging

logger = logging.getLogger(__name__)

def transcribe_audio(audio_path: str, model_size: str = "base", device: str = "cpu", language: str = None, beam_size: int = 1, task: str = "translate", progress_callback=None) -> list:
    """
    Transcribes/translates audio using faster-whisper with VAD filtering and efficient beam size.
    When task="translate", Whisper directly translates foreign speech into fluent English without external API calls.
    Returns a list of dictionaries with 'start', 'end', 'text', 'language'.
    """
    logger.info(f"Loading faster-whisper model '{model_size}' on {device} (task={task})...")
    compute_type = "int8" if device == "cpu" else "float16"
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    logger.info(f"Processing {audio_path} (beam_size={beam_size}, vad_filter=True, task={task})...")
    segments, info = model.transcribe(
        audio_path,
        language=language,
        task=task,
        beam_size=beam_size,
        vad_filter=True,
    )
    
    logger.info(f"Detected language '{info.language}' with probability {info.language_probability:.2f}")
    if progress_callback:
        progress_callback({
            "stage": "transcribe",
            "status": "in_progress",
            "message": f"Detected language: {info.language.upper()} ({int(info.language_probability*100)}% confidence)",
            "progress": 5
        })
    
    result = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            result.append({
                'start': segment.start,
                'end': segment.end,
                'text': text,
                'language': info.language
            })
            if len(result) % 25 == 0:
                logger.info(f"Processed {len(result)} segments (current timestamp: {segment.end:.1f}s)...")
                if progress_callback:
                    progress_callback({
                        "stage": "transcribe",
                        "status": "in_progress",
                        "message": f"Processed {len(result)} segments (audio time: {int(segment.end // 60):02d}:{int(segment.end % 60):02d})",
                        "count": len(result),
                        "timestamp": segment.end
                    })
        
    logger.info(f"Transcription/Translation complete. Found {len(result)} segments.")
    return result
