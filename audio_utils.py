import shutil
import subprocess


FFMPEG_TIMEOUT_SECONDS = 5.0
MAX_AUDIO_INPUT_BYTES = 10 * 1024 * 1024

SUPPORTED_SOURCE_FORMATS = {
    "amr",
    "flac",
    "m4a",
    "mp3",
    "mp4",
    "mpeg",
    "mpga",
    "ogg",
    "speex",
    "spx",
    "wav",
    "webm",
}

FORCED_INPUT_FORMATS = {
    "amr": "amr",
    "speex": "spx",
    "spx": "spx",
}


class AudioConversionError(RuntimeError):
    """音频转换失败。"""


def convert_audio_to_wav(audio_bytes: bytes, source_format: str) -> bytes:
    if not audio_bytes:
        raise AudioConversionError("empty audio input")
    if len(audio_bytes) > MAX_AUDIO_INPUT_BYTES:
        raise AudioConversionError("audio input is too large")

    normalized_format = source_format.strip().lower().lstrip(".")
    if normalized_format not in SUPPORTED_SOURCE_FORMATS:
        raise AudioConversionError("unsupported audio format")

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise AudioConversionError("ffmpeg is unavailable")

    command = [ffmpeg_path, "-hide_banner", "-loglevel", "error"]
    forced_input_format = FORCED_INPUT_FORMATS.get(normalized_format)
    if forced_input_format:
        command.extend(["-f", forced_input_format])
    command.extend(
        [
            "-i",
            "pipe:0",
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            "pipe:1",
        ]
    )

    try:
        completed = subprocess.run(
            command,
            input=audio_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioConversionError("ffmpeg conversion timed out") from exc
    except OSError as exc:
        raise AudioConversionError("ffmpeg could not be started") from exc

    if completed.returncode != 0:
        raise AudioConversionError("ffmpeg conversion failed")

    wav_bytes = bytes(completed.stdout)
    if (
        len(wav_bytes) < 12
        or not wav_bytes.startswith(b"RIFF")
        or wav_bytes[8:12] != b"WAVE"
    ):
        raise AudioConversionError("ffmpeg returned invalid WAV audio")

    return wav_bytes
