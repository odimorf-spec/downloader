import os
import sys
import tempfile
import asyncio
import logging
import subprocess
import imageio_ffmpeg
import yt_dlp
from PIL import Image

logger = logging.getLogger(__name__)

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


class DownloadResult:
    def __init__(
        self,
        video_path: str,
        title: str,
        duration: int,
        width: int,
        height: int,
        thumb_path: str | None,
        is_compressed: bool = False
    ):
        self.video_path = video_path
        self.title = title
        self.duration = duration
        self.width = width
        self.height = height
        self.thumb_path = thumb_path
        self.is_compressed = is_compressed


def convert_image_to_jpg(input_path: str, output_path: str) -> bool:
    try:
        with Image.open(input_path) as img:
            rgb_img = img.convert('RGB')
            rgb_img.save(output_path, 'JPEG')
        return True
    except Exception as e:
        logger.error(f"Error converting thumbnail {input_path}: {e}")
        return False


def generate_video_thumbnail(video_path: str, thumb_path: str) -> bool:
    """Generate thumbnail from video using ffmpeg at 1 sec timestamp."""
    try:
        cmd = [
            FFMPEG_EXE,
            '-y',
            '-ss', '00:00:01',
            '-i', video_path,
            '-vframes', '1',
            '-q:v', '2',
            thumb_path
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0
    except Exception as e:
        logger.error(f"Error generating thumbnail with ffmpeg: {e}")
        return False


def get_video_duration(video_path: str) -> float:
    try:
        cmd = [FFMPEG_EXE, '-i', video_path]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in res.stderr.splitlines():
            if 'Duration:' in line:
                parts = line.split('Duration:')[1].split(',')[0].strip().split(':')
                hours, minutes, seconds = float(parts[0]), float(parts[1]), float(parts[2])
                return hours * 3600 + minutes * 60 + seconds
    except Exception as e:
        logger.error(f"Error parsing video duration: {e}")
    return 0.0


def compress_video_if_needed(video_path: str, max_size_mb: float = 49.0) -> str:
    """
    If file size > max_size_mb, compress video with ffmpeg to target size.
    Returns path to final video file.
    """
    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    if file_size_mb <= max_size_mb:
        return video_path

    logger.info(f"File size {file_size_mb:.2f}MB exceeds {max_size_mb}MB limit. Compressing...")

    duration = get_video_duration(video_path)
    if not duration or duration <= 0:
        duration = 60.0

    target_bytes = (max_size_mb - 2.0) * 1024 * 1024  # ~47MB target
    target_bitrate_bps = (target_bytes * 8) / duration
    audio_bitrate_bps = 128 * 1000
    video_bitrate_bps = max(int(target_bitrate_bps - audio_bitrate_bps), 100000)

    dir_name = os.path.dirname(video_path)
    compressed_path = os.path.join(dir_name, "compressed_" + os.path.basename(video_path))

    cmd = [
        FFMPEG_EXE,
        '-y',
        '-i', video_path,
        '-vf', "scale='min(720,iw)':-2",
        '-b:v', f"{video_bitrate_bps}",
        '-maxrate', f"{int(video_bitrate_bps * 1.5)}",
        '-bufsize', f"{int(video_bitrate_bps * 2)}",
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-c:a', 'aac',
        '-b:a', '128k',
        compressed_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if os.path.exists(compressed_path) and os.path.getsize(compressed_path) > 0:
            return compressed_path
    except Exception as e:
        logger.error(f"Compression failed: {e}")

    return video_path


def download_video_sync(url: str, output_dir: str) -> DownloadResult:
    out_tmpl = os.path.join(output_dir, '%(id)s.%(ext)s')

    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]/best',
        'outtmpl': out_tmpl,
        'merge_output_format': 'mp4',
        'ffmpeg_location': FFMPEG_EXE,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        },
        'quiet': True,
        'no_warnings': True,
        'writethumbnail': True,
        'js_runtimes': {'node': {}},
        'remote_components': {'ejs': 'github'},
        'nocheckcertificate': True,
        'ignoreerrors': False,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise ValueError("Не удалось получить информацию о видео.")

        if 'entries' in info and info['entries']:
            info = info['entries'][0]

        title = info.get('title', 'Video')
        duration = int(info.get('duration') or 0)
        width = int(info.get('width') or 0)
        height = int(info.get('height') or 0)

        filename = ydl.prepare_filename(info)
        base_name, _ = os.path.splitext(filename)
        video_path = base_name + '.mp4'

        if not os.path.exists(video_path):
            if os.path.exists(filename):
                video_path = filename
            else:
                candidates = [
                    os.path.join(output_dir, f)
                    for f in os.listdir(output_dir)
                    if f.endswith(('.mp4', '.mkv', '.webm', '.mov', '.avi'))
                ]
                if candidates:
                    video_path = candidates[0]
                else:
                    raise FileNotFoundError("Скачанный файл видео не найден.")

        thumb_path = None
        for ext in ['.jpg', '.jpeg', '.webp', '.png']:
            possible_thumb = base_name + ext
            if os.path.exists(possible_thumb):
                jpg_thumb = base_name + '_thumb.jpg'
                if convert_image_to_jpg(possible_thumb, jpg_thumb):
                    thumb_path = jpg_thumb
                break

        if not thumb_path or not os.path.exists(thumb_path):
            jpg_thumb = base_name + '_ffmpeg_thumb.jpg'
            if generate_video_thumbnail(video_path, jpg_thumb):
                thumb_path = jpg_thumb

        final_video_path = compress_video_if_needed(video_path, max_size_mb=49.0)
        is_compressed = (final_video_path != video_path)

        return DownloadResult(
            video_path=final_video_path,
            title=title,
            duration=duration,
            width=width,
            height=height,
            thumb_path=thumb_path if (thumb_path and os.path.exists(thumb_path)) else None,
            is_compressed=is_compressed
        )


async def download_video(url: str, output_dir: str) -> DownloadResult:
    return await asyncio.to_thread(download_video_sync, url, output_dir)
