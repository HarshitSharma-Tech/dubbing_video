import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import argparse
import logging
from src.config import DEFAULT_MODEL, DEFAULT_VOICE, DEFAULT_DEVICE
from src.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Automated Video Dubbing System")
    parser.add_argument("url", nargs="?", default=None, help="YouTube video URL (optional, prompts interactively if omitted)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="faster-whisper model size (e.g. tiny, base, small)")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help="edge-tts voice (e.g. en-US-AriaNeural)")
    parser.add_argument("--output", default="output.mp4", help="Output filename in the outputs directory")
    parser.add_argument("--language", default=None, help="Source language code (auto-detect by default)")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary files after processing")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="Device for transcription (cpu or cuda)")
    parser.add_argument("--save-original", action="store_true", default=True, help="Save original downloaded video alongside dubbed video")
    parser.add_argument("--no-save-original", dest="save_original", action="store_false", help="Do not save original downloaded video")
    parser.add_argument("--whisper-task", default="translate", choices=["translate", "transcribe"], help="Whisper task: 'translate' directly produces fluent English; 'transcribe' keeps original language")
    parser.add_argument("--use-external-translator", action="store_true", help="Force using external Google/MyMemory translator instead of Whisper native translation")
    parser.add_argument("--mix-background", action="store_true", default=False, help="Mix original audio faintly in the background (default: False, pure clean dubbed audio)")
    parser.add_argument("--bg-volume", type=float, default=0.12, help="Background volume factor when mixing original audio (default: 0.12)")
    parser.add_argument("--resolution", default="480p", help="Target video download resolution (e.g. 480p, 360p, 720p)")
    
    args = parser.parse_args()
    
    video_url = args.url
    if not video_url:
        print("\n" + "="*60)
        print("  🎥 Automated Video Dubbing System (VS Code Launcher)  ")
        print("="*60)
        user_input = input("Enter YouTube video URL [Press Enter for 30-min test video]: ").strip()
        if user_input:
            video_url = user_input
        else:
            video_url = "https://www.youtube.com/watch?v=1EIbR0_z-y8"
            print(f"--> Using default 30-min test video: {video_url}")
            if args.output == "output.mp4":
                args.output = "test_30m.mp4"
        print("="*60 + "\n")

    logger.info("Starting Video Dubbing System...")
    try:
        final_file, benchmarks = run_pipeline(
            url=video_url,
            output_name=args.output,
            model_size=args.model,
            voice=args.voice,
            device=args.device,
            language=args.language,
            keep_temp=args.keep_temp,
            save_original=args.save_original,
            whisper_task=args.whisper_task,
            use_external_translator=args.use_external_translator,
            mix_background=args.mix_background,
            bg_volume=args.bg_volume,
            resolution=args.resolution
        )
        logger.info(f"Process completed successfully.")
        logger.info(f"Final dubbed video at: {final_file}")
        if "original_video_path" in benchmarks:
            logger.info(f"Original video saved at: {benchmarks['original_video_path']}")
        logger.info(f"Total time elapsed: {benchmarks['total_processing_time_s']}s")
    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)

if __name__ == "__main__":
    main()
