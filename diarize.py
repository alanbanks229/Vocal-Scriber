#!/usr/bin/env python3
"""
Speaker Diarization for Vocal-Scriber
Uses MLX-optimized VibeVoice-ASR for Apple Silicon acceleration.

This is a standalone script for processing audio files with speaker identification.
NOT for real-time push-to-talk (use vocal-scriber.py for that).

Usage:
    python diarize.py audio.wav
    python diarize.py meeting.mp3 --context "Claude, Anthropic, Docker"
    python diarize.py audio.wav --output transcript.txt

Environment Variables:
    DIARIZE_MODEL - Specify custom MLX-format speech model
                    Default: mlx-community/VibeVoice-ASR-bf16
                    Must be MLX format from https://huggingface.co/mlx-community
                    Example: export DIARIZE_MODEL=mlx-community/VibeVoice-ASR-int4
    HF_TOKEN      - Hugging Face token for faster downloads (optional)
"""

import argparse
import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path


def load_env_file():
    """Load environment variables from .env file if it exists."""
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            if os.getenv("HF_TOKEN"):
                print("Loaded HF_TOKEN from .env file (enables faster downloads)")
    except ImportError:
        # python-dotenv not installed, skip (not required)
        pass


def check_apple_silicon():
    """Verify running on Apple Silicon (required for MLX)."""
    if platform.machine() != "arm64":
        print("ERROR: This script requires Apple Silicon (M1/M2/M3/M4).")
        print(f"Current architecture: {platform.machine()}")
        print("\nMLX (Apple's ML framework) only runs on Apple Silicon Macs.")
        print("If you need speaker diarization on Intel/AMD, consider pyannote.audio (PyTorch-based).")
        sys.exit(1)


def get_audio_duration(audio_file):
    """Get audio duration in seconds.

    Tries soundfile first (fast, works for WAV), then falls back to
    ffprobe (works for M4A, MP3, FLAC).
    """
    # Try soundfile first (fast for WAV files)
    try:
        import soundfile as sf
        info = sf.info(audio_file)
        return info.duration
    except Exception:
        pass  # soundfile can't read this format, try ffprobe

    # Fall back to ffprobe (works for M4A, MP3, FLAC, etc.)
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_format', audio_file],
            capture_output=True,
            text=True,
            check=True
        )

        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])
        return duration

    except (subprocess.CalledProcessError, KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"WARNING: Could not determine audio duration: {e}")
        print("Using default max_tokens setting")
        return None
    except FileNotFoundError:
        print("WARNING: ffprobe not found. Install with: brew install ffmpeg")
        print("Using default max_tokens setting")
        return None


def calculate_optimal_max_tokens(duration_seconds, user_max_tokens=None):
    """Calculate optimal max_tokens based on audio duration.

    Formula: ⌈15D + 300⌉ where D = duration in seconds

    Based on audio engineering analysis of real diarization output:
    - Diarization produces timestamps, speaker labels, and transcribed text
    - Format: "[0.0-5.3] Speaker 0: Hello everyone..."
    - Observed output: ~5-6 tokens/second of audio
    - Formula uses 15 tokens/sec for 2.5-3x safety buffer
    - Base 300 tokens covers formatting overhead

    Examples:
    - 146s audio (2m26s): 2,490 tokens (actual need ~850)
    - 60s audio (1min): 1,200 tokens (actual need ~600)
    - 300s audio (5min): 4,800 tokens (actual need ~3,000)
    """
    if user_max_tokens:
        return user_max_tokens  # User override

    if duration_seconds is None:
        return 8192  # Safe fallback

    # Calculate: ⌈15D + 300⌉
    estimated = max(500, math.ceil(15 * duration_seconds + 300))

    # Cap at 16384 for very long audio (18+ minutes)
    return min(estimated, 16384)


def show_progress_spinner(stop_event):
    """Show a progress spinner while processing."""
    spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    idx = 0
    while not stop_event.is_set():
        sys.stdout.write(f'\r{spinner[idx % len(spinner)]} Processing... ')
        sys.stdout.flush()
        idx += 1
        time.sleep(0.1)
    sys.stdout.write('\r')
    sys.stdout.flush()


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Speaker diarization using MLX-optimized VibeVoice-ASR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python diarize.py meeting.wav
  python diarize.py audio.mp3 --context "Claude, Anthropic, MLX, Docker"
  python diarize.py interview.wav --output transcript.txt
  python diarize.py audio.wav --output result.json
  python diarize.py audio.wav --verbose --debug
        """
    )
    parser.add_argument("audio_file", help="Audio file to process (WAV, MP3, M4A, FLAC)")
    parser.add_argument("--context", help="Vocabulary context to improve accuracy (comma-separated)")
    parser.add_argument("--output", "-o", help="Output file (.txt or .json - format inferred from extension)")
    parser.add_argument("--max-tokens", type=int, default=None,
                       help="Maximum tokens for generation (default: auto-calculated from audio duration)")
    parser.add_argument("--temperature", type=float, default=0.0,
                       help="Generation temperature (default: 0.0)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show detailed progress during processing")
    parser.add_argument("--debug", action="store_true",
                       help="Show memory usage and timing information")
    return parser.parse_args()


def load_model():
    """Load MLX-format speech model (downloads on first use).

    Model can be specified via DIARIZE_MODEL environment variable.
    Default: mlx-community/VibeVoice-ASR-bf16

    IMPORTANT: Model must be in MLX format (Apple Silicon optimized).
    Find compatible models at: https://huggingface.co/mlx-community
    Search for "VibeVoice" or "whisper mlx" models with "ASR" in the name.
    """
    try:
        from mlx_audio.stt.utils import load_model
    except ImportError:
        print("\nERROR: MLX-Audio not installed.")
        print("\nInstall with:")
        print("  pip install -r requirements-diarization.txt")
        print("\nThis will install:")
        print("  - mlx (Apple's ML framework)")
        print("  - mlx-audio (VibeVoice-ASR support)")
        print("  - soundfile (audio I/O)")
        sys.exit(1)

    # Check for custom model via environment variable
    model_name = os.getenv("DIARIZE_MODEL", "mlx-community/VibeVoice-ASR-bf16")

    print(f"Loading model: {model_name}")
    if model_name != "mlx-community/VibeVoice-ASR-bf16":
        print("(Using custom model from DIARIZE_MODEL environment variable)")
    print("(First run will download model - this may take several minutes)")
    print()

    try:
        # https://huggingface.co/mlx-community/VibeVoice-ASR-bf16
        model = load_model(model_name)
    except Exception as e:
        print(f"\nERROR: Failed to load model: {e}")
        print("\nTroubleshooting:")
        print("1. Check internet connection (first run downloads model)")
        print("2. Ensure sufficient disk space (~10GB free)")
        print("3. Verify model name is correct (e.g., 'mlx-community/VibeVoice-ASR-bf16')")
        print("4. Try running again (downloads may resume)")
        if model_name != "mlx-community/VibeVoice-ASR-bf16":
            print(f"\nCurrent DIARIZE_MODEL: {model_name}")
            print("To use default model, unset DIARIZE_MODEL or set to: mlx-community/VibeVoice-ASR-bf16")
        sys.exit(1)

    print("Model loaded successfully.")
    print()
    return model


def validate_audio_file(file_path):
    """Check if audio file exists and has valid extension."""
    path = Path(file_path)
    if not path.exists():
        print(f"ERROR: Audio file not found: {file_path}")
        sys.exit(1)

    valid_extensions = [".wav", ".mp3", ".m4a", ".flac"]
    if path.suffix.lower() not in valid_extensions:
        print(f"ERROR: Unsupported audio format: {path.suffix}")
        print(f"Supported formats: {', '.join(valid_extensions)}")
        sys.exit(1)

    return str(path.absolute())


def diarize_audio(model, audio_file, context=None, max_tokens=None, temperature=0.0, verbose=False, debug=False):
    """Run speaker diarization on audio file."""
    print(f"Processing: {audio_file}")
    print()

    # Get audio duration
    duration = get_audio_duration(audio_file)
    if duration:
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        print(f"Audio duration: {minutes}m {seconds}s ({duration:.1f}s)")

    # Calculate optimal max_tokens
    optimal_tokens = calculate_optimal_max_tokens(duration, max_tokens)
    if max_tokens:
        print(f"Using max_tokens: {max_tokens} (user specified)")
    else:
        print(f"Using max_tokens: {optimal_tokens} (auto-calculated)")

    # Estimate processing time (4-6x realtime for Apple Silicon)
    if duration:
        est_time = duration * 5  # Conservative 5x realtime
        est_min = int(est_time // 60)
        est_sec = int(est_time % 60)
        print(f"Estimated processing time: ~{est_min}m {est_sec}s")

    print()

    # Generate with optional context
    kwargs = {
        "audio": audio_file,
        "max_tokens": optimal_tokens,
        "temperature": temperature
    }
    if context:
        kwargs["context"] = context
        print(f"Using context: {context}")
        print()

    # Initialize debug tracking
    if debug:
        try:
            import psutil
            process = psutil.Process()
            mem_before = process.memory_info().rss / 1024 / 1024 / 1024  # GB
            print(f"Memory before: {mem_before:.1f} GB")
        except ImportError:
            print("WARNING: psutil not installed, cannot show memory usage")
            print("Install with: pip install psutil")
            debug = False
        start_time = time.time()

    # Start progress spinner if verbose
    stop_spinner = threading.Event()
    if verbose:
        print("Processing...")
        spinner_thread = threading.Thread(target=show_progress_spinner, args=(stop_spinner,))
        spinner_thread.start()

    try:
        result = model.generate(**kwargs)
    except Exception as e:
        if verbose:
            stop_spinner.set()
            spinner_thread.join()
        print(f"\nERROR: Transcription failed: {e}")
        print("\nTroubleshooting:")
        print("1. Check audio file is valid (play it in another app)")
        print("2. Try with a shorter audio file")
        print("3. Increase --max-tokens for long audio")
        sys.exit(1)
    finally:
        if verbose:
            stop_spinner.set()
            spinner_thread.join()

    # Show debug info
    if debug:
        elapsed = time.time() - start_time
        mem_after = process.memory_info().rss / 1024 / 1024 / 1024
        print(f"\nMemory after: {mem_after:.1f} GB (delta: +{mem_after - mem_before:.1f} GB)")
        print(f"Processing time: {elapsed:.1f}s", end="")
        if duration:
            realtime_factor = elapsed / duration
            print(f" ({realtime_factor:.1f}x realtime)")
        else:
            print()

    if verbose or debug:
        print()

    return result


def format_text_output(result):
    """Format diarization result as readable text."""
    lines = []

    # Check if result has segments attribute
    if not hasattr(result, 'segments'):
        print("WARNING: Result has no segments. The model may not have detected any speech.")
        return "No speech segments detected."

    for seg in result.segments:
        # Handle different possible segment formats
        if isinstance(seg, dict):
            speaker = seg.get('speaker_id', seg.get('speaker', 'Unknown'))
            start = seg.get('start_time', seg.get('start', 0.0))
            end = seg.get('end_time', seg.get('end', 0.0))
            text = seg.get('text', '').strip()
        else:
            # If segment is an object, try accessing as attributes
            speaker = getattr(seg, 'speaker_id', getattr(seg, 'speaker', 'Unknown'))
            start = getattr(seg, 'start_time', getattr(seg, 'start', 0.0))
            end = getattr(seg, 'end_time', getattr(seg, 'end', 0.0))
            text = getattr(seg, 'text', '').strip()

        if text:  # Only add non-empty segments
            lines.append(f"[{start:.1f}-{end:.1f}] Speaker {speaker}: {text}")

    if not lines:
        return "No speech segments with text found."

    return "\n".join(lines)


def format_json_output(result):
    """Format diarization result as JSON."""
    segments = []

    # Check if result has segments attribute
    if not hasattr(result, 'segments'):
        return json.dumps({"segments": [], "warning": "No speech segments detected"}, indent=2)

    for seg in result.segments:
        # Handle different possible segment formats
        if isinstance(seg, dict):
            segment_data = {
                "start_time": seg.get('start_time', seg.get('start', 0.0)),
                "end_time": seg.get('end_time', seg.get('end', 0.0)),
                "speaker_id": seg.get('speaker_id', seg.get('speaker', 'Unknown')),
                "text": seg.get('text', '').strip()
            }
        else:
            # If segment is an object, try accessing as attributes
            segment_data = {
                "start_time": getattr(seg, 'start_time', getattr(seg, 'start', 0.0)),
                "end_time": getattr(seg, 'end_time', getattr(seg, 'end', 0.0)),
                "speaker_id": getattr(seg, 'speaker_id', getattr(seg, 'speaker', 'Unknown')),
                "text": getattr(seg, 'text', '').strip()
            }

        if segment_data["text"]:  # Only add non-empty segments
            segments.append(segment_data)

    output = {"segments": segments}
    return json.dumps(output, indent=2)


def main():
    # Load environment variables from .env file
    load_env_file()

    # Check platform
    check_apple_silicon()

    # Parse arguments
    args = parse_args()

    # Validate audio file
    audio_file = validate_audio_file(args.audio_file)

    # Load model
    model = load_model()

    # Run diarization
    result = diarize_audio(
        model,
        audio_file,
        context=args.context,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        verbose=args.verbose,
        debug=args.debug
    )

    # Determine output format from file extension (if output specified)
    output_format = "text"  # default
    if args.output:
        output_path = Path(args.output)
        if output_path.suffix.lower() == ".json":
            output_format = "json"
        elif output_path.suffix.lower() not in [".txt", ""]:
            print(f"WARNING: Unrecognized output extension '{output_path.suffix}', using text format")
            print("Supported extensions: .txt (text), .json (JSON)")
            print()

    # Format output
    if output_format == "json":
        output = format_json_output(result)
    else:
        output = format_text_output(result)

    # Write or print output
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"\nTranscript saved to: {args.output}")
    else:
        print("\n" + "="*60)
        print("TRANSCRIPT")
        print("="*60)
        print(output)


if __name__ == "__main__":
    main()
