import os
import sys
import shutil
import subprocess
import argparse
import json
from PIL import Image
import math
import re
import logging
import configparser
from pathlib import Path
from urllib.parse import quote

import config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 常量定义
MB = 1024 * 1024
MAX_SIZE = config.int_("media", "max_file_size", 24 * MB)

# 支持的媒体类型
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}
VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.webm'}
SUBTITLE_EXTENSIONS = {'.ass', '.srt', '.vtt'}

def get_audio_duration(file_path):
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', file_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        return float(result.stdout.strip())
    return 60

def get_audio_bitrate(file_path):
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries', 'stream=bit_rate',
        '-of', 'default=noprint_wrappers=1:nokey=1', file_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        bitrate_str = result.stdout.strip().split('\n')[0]
        if bitrate_str and bitrate_str != 'N/A':
            return int(float(bitrate_str) / 1000)
    return 0

def compress_image(input_path, output_path):
    logging.info(f"Starting image compression: {input_path}")
    q_start = config.int_("image", "quality_start", 95)
    q_min = config.int_("image", "quality_min", 20)
    q_step = config.int_("image", "quality_step", 5)
    scale_start = config.float_("image", "scale_start", 0.9)
    scale_min = config.float_("image", "scale_min", 0.3)
    scale_step = config.float_("image", "scale_step", 0.1)
    try:
        img = Image.open(input_path)
        if img.mode != 'RGB': img = img.convert('RGB')

        ext = os.path.splitext(output_path)[1].lower()
        if ext not in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            output_path = os.path.splitext(output_path)[0] + '.webp'

        quality = q_start
        while quality >= q_min:
            img.save(output_path, 'WEBP', quality=quality)
            if os.path.getsize(output_path) <= MAX_SIZE:
                return
            quality -= q_step

        scale = scale_start
        while scale > scale_min:
            new_size = (int(img.width * scale), int(img.height * scale))
            img_resized = img.resize(new_size, Image.LANCZOS)
            quality = q_start
            while quality >= q_min:
                img_resized.save(output_path, 'WEBP', quality=quality)
                if os.path.getsize(output_path) <= MAX_SIZE:
                    return
                quality -= q_step
            scale -= scale_step

        img.save(output_path, 'WEBP', quality=q_min)
    except Exception as e:
        logging.error(f"Image compression error: {e}")
        shutil.copy2(input_path, output_path)

def compress_audio(input_path, output_path):
    logging.info(f"Starting precise audio compression: {input_path}")

    # 复制模式：直接复制，不重新编码
    if config.str_("audio", "mode", "encode") == "copy":
        logging.info(f"Audio copy mode: directly copying {input_path}")
        shutil.copy2(input_path, output_path)
        return
    temp_output = output_path + '.tmp'
    safe_target = config.int_("audio", "safe_target_bytes", 24641536)  # 23.5 * MB
    bitrate_max = config.int_("audio", "bitrate_max", 320)
    bitrate_min = config.int_("audio", "bitrate_min", 32)
    reduction = config.float_("audio", "bitrate_reduction_factor", 0.8)

    try:
        duration = get_audio_duration(input_path)
        orig_bitrate = get_audio_bitrate(input_path)
        if duration <= 0: duration = 60

        calculated_kbps = int((safe_target * 8) / (duration * 1000))

        target_kbps = calculated_kbps
        if orig_bitrate > 0:
            target_kbps = min(target_kbps, orig_bitrate)
        target_kbps = min(target_kbps, bitrate_max)
        target_kbps = max(target_kbps, bitrate_min)

        while True:
            cmd = [
                'ffmpeg', '-y', '-i', input_path,
                '-c:a', 'libmp3lame', '-b:a', f'{target_kbps}k',
                '-f', 'mp3', temp_output
            ]
            subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)

            final_size = os.path.getsize(temp_output)
            if final_size <= MAX_SIZE or target_kbps <= bitrate_min:
                shutil.move(temp_output, output_path)
                break

            target_kbps = int(target_kbps * reduction)
            if target_kbps < bitrate_min: target_kbps = bitrate_min

    except Exception as e:
        logging.error(f"Error compressing audio {input_path}: {e}")
        shutil.copy2(input_path, output_path)
    finally:
        if os.path.exists(temp_output):
            os.remove(temp_output)

def convert_video_to_mp4(input_path, output_path):
    """用于处理小于 MAX_SIZE 的视频，仅进行标准 MP4 转码以确保浏览器兼容性"""
    logging.info(f"Standardizing small video to MP4: {input_path}")
    target_output = os.path.splitext(output_path)[0] + '.mp4'

    # 复制模式：直接封装，不重新编码
    if config.str_("video", "mode", "encode") == "copy":
        cmd = config.build_mp4_copy_cmd(input_path, target_output)
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            logging.error(f"Copy failed for {input_path}: {e}")
            if os.path.exists(target_output): os.remove(target_output)
            return False

    # 硬件编码模式
    hw_cmd = config.build_mp4_hw_cmd(input_path, target_output)
    try:
        subprocess.run(hw_cmd, check=True, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        sw_cmd = config.build_mp4_sw_cmd(input_path, target_output)
        try:
            subprocess.run(sw_cmd, check=True, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            logging.error(f"Failed to convert {input_path}: {e}")
            if os.path.exists(target_output): os.remove(target_output)
            return False

def build_static_range(input_path, output_dir, source_root=None):
    """把原始视频拆成静态分块，并写入 stream manifest 的骨架。"""
    import static_stream
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    part_bytes = config.static_range_part_bytes()
    url_prefix = config.static_range_url_prefix()
    chunks_root = os.path.join(output_dir, url_prefix.lstrip('/'), 'chunks')
    if not 0 < part_bytes <= MAX_SIZE:
        raise ValueError("static_range_part_bytes must be positive and <= media.max_file_size")
    source_path = Path(input_path).resolve()
    relative = source_path.relative_to(Path(source_root).resolve()).as_posix() if source_root else source_path.name
    stream_id = _safe_stream_id(relative)
    mime = {'.mkv': 'video/x-matroska', '.webm': 'video/webm', '.mov': 'video/quicktime',
            '.avi': 'video/x-msvideo', '.wmv': 'video/x-ms-wmv'}.get(source_path.suffix.lower(), 'video/mp4')
    entry = static_stream.split_file(
        input_path, chunks_root, stream_id,
        part_bytes=part_bytes,
        mime=mime,
        url_prefix=url_prefix + '/chunks',
    )
    subtitle_folder = Path(output_dir) / url_prefix.lstrip('/') / 'subtitles' / stream_id / entry.sha256[:16]
    subtitle_folder.mkdir(parents=True, exist_ok=True)
    process_subtitles(str(source_path.parent), base_name, str(subtitle_folder), str(source_path))
    entry.relative_path = relative
    entry.subtitles, entry.ass_tracks = subtitle_tracks(subtitle_folder, output_dir, base_name)
    _merge_stream_manifest(output_dir, entry)
    logging.info(f"Static range stream built for {relative}: {len(entry.chunks)} chunks")


def _safe_stream_id(name):
    """生成 URL 安全且稳定的 stream id。"""
    import re
    import hashlib
    relative = str(name).replace('\\', '/')
    slug = re.sub(r'[^A-Za-z0-9._-]+', '-', Path(relative).stem).strip('-').lower()[:40] or 'media'
    return slug + '-' + hashlib.sha256(relative.encode('utf-8')).hexdigest()[:16]


def _merge_stream_manifest(output_dir, entry):
    """把单个静态流合并进 dist/stream/manifest.json。"""
    import json
    manifest_path = os.path.join(output_dir, config.static_range_url_prefix().lstrip('/'), 'manifest.json')
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, 'r', encoding='utf-8') as handle:
                manifest = json.load(handle)
        except (OSError, ValueError):
            manifest = {'version': 1, 'files': {}}
    else:
        manifest = {'version': 1, 'files': {}}
    manifest.setdefault('files', {})[entry.id] = entry.to_manifest()
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)


def _is_hevc(input_path):
    """用 ffprobe 判断视频流是否为 HEVC。"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', input_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return result.returncode == 0 and result.stdout.strip().lower() in ('hevc', 'h265')
    except OSError:
        return False


def repartition_hevc(input_path, video_folder):
    """对 HEVC 源使用 moof/mdat 边界重分配，保证切片不超限。"""
    import fragment_mp4
    fragment_bytes = config.hevc_fragment_bytes()
    logging.info(f"HEVC repartition: {input_path} fragment={fragment_bytes} bytes")
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    segments = fragment_mp4.repartition(
        input_path, video_folder, fragment_bytes,
        audio_codec=config.str_('video', 'audio_copy_codec', 'copy'),
        audio_bitrate=config.str_('video', 'audio_copy_bitrate', '128k'),
        init_name=config.fmp4_init_filename(),
        segment_pattern=config.fmp4_filename_pattern(),
        playlist_name=f"{base_name}-0.m3u8",
    )
    logging.info(f"HEVC repartition produced {len(segments)} segments")


def check_segment_sizes(video_folder, base_name):
    """校验切片未超过部署单文件上限。"""
    limit = config.max_segment_bytes()
    oversized = [(name, os.path.getsize(os.path.join(video_folder, name)))
                 for name in os.listdir(video_folder)
                 if name.endswith(('.ts', '.m4s')) and os.path.getsize(os.path.join(video_folder, name)) > limit]
    if oversized:
        detail = ', '.join(f"{name}={size}" for name, size in oversized[:5])
        logging.warning(f"Segments above max_segment_bytes({limit}) for {base_name}: {detail}")
        if config.bool_("video", "fail_on_oversize", False):
            raise RuntimeError(f"oversized HLS segments for {base_name}: {detail}")


def run_hls_command(cmd, video_folder):
    """运行 HLS 命令。

    fMP4 模式下 ffmpeg 会把 ``-hls_fmp4_init_filename``、``-hls_segment_filename``
    等解析为相对 **当前工作目录** 的路径；因此在 fMP4 模式下以切片目录作为 cwd，
    并把命令行里所有可能为路径的参数先转成绝对路径再转成相对切片目录的相对路径，
    这样无论调用方传绝对路径还是相对路径（convert.py 独立使用时允许相对路径）都能正确落盘。
    """
    if config.hls_segment_type() != "fmp4":
        subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
        return
    folder = os.path.abspath(video_folder)
    os.makedirs(folder, exist_ok=True)
    resolved = []
    for token in cmd:
        if isinstance(token, str) and token and not token.startswith("-") and (
            os.path.isabs(token) or os.sep in token or "/" in token
        ):
            try:
                token = os.path.relpath(os.path.abspath(token), folder)
            except ValueError:
                pass
        resolved.append(token)
    subprocess.run(resolved, cwd=folder, check=True, stderr=subprocess.DEVNULL)


def compress_video(input_path, output_dir):
    """采用 HLS 切片方式处理视频，支持全格式和 CUDA 硬件加速"""
    input_dir_path = os.path.dirname(input_path)
    base_name = os.path.splitext(os.path.basename(input_path))[0]

    video_folder = os.path.join(output_dir, base_name)
    os.makedirs(video_folder, exist_ok=True)
    logging.info(f"Starting HLS processing: {input_path}")
    for generated in Path(video_folder).iterdir():
        if generated.is_file() and (generated.suffix.lower() in ('.m3u8', '.m4s', '.ts', '.vtt', '.ass') or generated.name == config.fmp4_init_filename()):
            generated.unlink()

    output_playlist = os.path.join(video_folder, f"{base_name}-0.m3u8")
    if config.hls_segment_type() == "fmp4":
        hls_segments = os.path.join(video_folder, config.fmp4_filename_pattern())
    else:
        hls_segments = os.path.join(video_folder, "chunk_%04d.ts")

    # 切片大小优先模式：计算最优 hls_time
    hls_time_override = None
    if config.size_priority_enabled():
        is_copy = config.str_("video", "mode", "encode") == "copy"
        if is_copy:
            v_bitrate = config.get_video_bitrate_kbps(input_path)
            a_bitrate = 0
        else:
            mode_section = "video.hw"
            v_bitrate = config._parse_bitrate_kbps(config.str_(mode_section, "bitrate", ""))
            if v_bitrate <= 0:
                v_bitrate = config.get_video_bitrate_kbps(input_path)
            a_bitrate = config._parse_bitrate_kbps(config.str_(mode_section, "audio_bitrate", ""))
        hls_time_override = config.calc_size_priority_hls_time(v_bitrate, a_bitrate)
        if hls_time_override:
            logging.info(f"Size priority mode: calculated hls_time={hls_time_override}s for bitrate={v_bitrate}+{a_bitrate}kbps")

    # 复制模式：不重新编码，直接切片，保留原始画质
    if config.str_("video", "mode", "encode") == "copy":
        if config.hls_segment_type() == "fmp4" and config.hevc_repartition_enabled() and _is_hevc(input_path):
            try:
                repartition_hevc(input_path, video_folder)
            except Exception as e:
                logging.warning(f"HEVC repartition failed for {base_name}, falling back to ffmpeg: {e}")
                cmd = config.build_hls_copy_cmd(input_path, output_playlist, hls_segments, hls_time_override)
                run_hls_command(cmd, video_folder)
        else:
            cmd = config.build_hls_copy_cmd(input_path, output_playlist, hls_segments, hls_time_override)
            try:
                run_hls_command(cmd, video_folder)
            except Exception as e:
                logging.error(f"HLS copy failed for {base_name}: {e}")
                raise
    else:
        # 编码模式（默认）：硬件 + 软件回退
        hw_cmd = config.build_hls_hw_cmd(input_path, output_playlist, hls_segments, hls_time_override)
        try:
            run_hls_command(hw_cmd, video_folder)
        except Exception as e:
            logging.warning(f"CUDA failed, falling back to CPU for {base_name}. Error: {e}")
            sw_cmd = config.build_hls_sw_cmd(input_path, output_playlist, hls_segments, hls_time_override)
            run_hls_command(sw_cmd, video_folder)

    if config.hls_segment_type() == "fmp4":
        write_fmp4_master(video_folder, output_playlist, input_path, base_name)

    check_segment_sizes(video_folder, base_name)

    # 智能字幕处理
    process_subtitles(input_dir_path, base_name, video_folder, input_path)


def write_fmp4_master(video_folder, media_playlist, input_path, base_name):
    """为 fMP4 切片生成带 CODECS 的 master.m3u8；失败时保留媒体播放列表。"""
    try:
        import codec_string
        init_segment = os.path.join(video_folder, config.fmp4_init_filename())
        codecs = codec_string.probe_codec_string(init_segment)
        width, height = codec_string.probe_dimensions(init_segment)
        durations = []
        sizes = []
        with open(media_playlist, 'r', encoding='utf-8') as handle:
            for line in handle:
                if line.startswith('#EXTINF:'):
                    durations.append(float(line.split(':', 1)[1].rstrip().rstrip(',')))
                elif line.strip() and not line.startswith('#'):
                    sizes.append(os.path.getsize(os.path.join(video_folder, line.strip())))
        bandwidth = 0
        if durations and sizes:
            rates = [size * 8 / duration for size, duration in zip(sizes, durations) if duration > 0]
            bandwidth = math.ceil(max(rates))
        master = [
            '#EXTM3U',
            '#EXT-X-VERSION:7',
            f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={width}x{height},CODECS="{codecs}"',
            quote(os.path.basename(media_playlist), safe='/'),
            '',
        ]
        with open(os.path.join(video_folder, 'master.m3u8'), 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(master))
        logging.info(f"fMP4 master written for {base_name}: {codecs}")
    except Exception as error:
        logging.warning(f"fMP4 master playlist skipped for {base_name}: {error}")

def _embedded_subtitle_language(stream):
    """把 ffprobe 的 tags 归一化成 srclang + 是否默认。"""
    tags = stream.get("tags") or {}
    raw = (tags.get("language") or "").lower()
    mapping = {
        "chi": ("zh", True), "zho": ("zh", True), "zh": ("zh", True),
        "chs": ("zh", True), "cht": ("zh-Hant", False), "chi-hant": ("zh-Hant", False),
        "jpn": ("ja", False), "jp": ("ja", False), "eng": ("en", False), "und": ("und", False),
    }
    return mapping.get(raw, (raw or "und", False))


def extract_embedded_subtitles(source_video, video_folder, base_name):
    """从容器（如 MKV）中提取内挂 ASS/字幕，产出 VTT，并按需保留 ASS 侧车。

    很多收藏级源（例如 Eva 的 AI-Raws 版本）把 ASS 内挂进 MKV，磁盘上没有独立的
    .ass 文件；只扫目录的话会漏掉字幕。这里用 ffprobe 列出字幕流、再用 ffmpeg 抽取。
    ``keep_ass=true`` 时额外保留 .ass 供 libass/SubtitlesOctopus 主题渲染。
    """
    import json
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "s",
             "-show_entries", "stream=index,codec_name:stream_tags=language,title",
             "-of", "json", source_video],
            check=True, capture_output=True, text=True)
        streams = json.loads(probe.stdout or "{}").get("streams") or []
    except Exception as error:
        logging.warning(f"embedded subtitle probe failed for {base_name}: {error}")
        return
    keep_ass = config.bool_("subtitle", "keep_ass", False)
    lang_map = config.get_subtitle_lang_map()
    for order, stream in enumerate(streams):
        index = stream.get("index")
        tags = stream.get("tags") or {}
        title = (tags.get("title") or "").strip()
        suffix = re.sub(r'[\\/:*?"<>|]+', "_", title) or f"s{order}"
        srclang, _default = _embedded_subtitle_language(stream)
        # MKV 常把语言标成 chi 而标题里写着“简体中文/繁體中文/日文”；标题更可靠，
        # 复用 [subtitle.lang] 关键字映射（与侧车字幕同一套规则）。
        if title:
            title_lower = title.lower()
            for keyword, (lang_val, default_val) in lang_map.items():
                if keyword and (keyword in title_lower or keyword in title):
                    srclang, _default = lang_val, default_val
                    break
        if srclang == "und" and any("\u4e00" <= ch <= "\u9fff" for ch in title):
            srclang = "zh"
        vtt_path = os.path.join(video_folder, f"{base_name}_{suffix}.vtt")
        try:
            if stream.get("codec_name") == "ass":
                ass_path = os.path.join(video_folder, f"{base_name}_{suffix}.ass")
                # -c:s ass 保留原始 ASS 样式
                subprocess.run(["ffmpeg", "-y", "-i", source_video, "-map", f"0:{index}",
                                "-c:s", "copy", ass_path], check=True, stderr=subprocess.DEVNULL)
                subprocess.run(["ffmpeg", "-y", "-i", ass_path, vtt_path],
                               check=True, stderr=subprocess.DEVNULL)
                if not keep_ass:
                    try: os.remove(ass_path)
                    except OSError: pass
            else:
                subprocess.run(["ffmpeg", "-y", "-i", source_video, "-map", f"0:{index}", vtt_path],
                               check=True, stderr=subprocess.DEVNULL)
            logging.info(f"embedded subtitle extracted for {base_name}: {suffix} ({srclang})")
        except Exception as error:
            logging.warning(f"embedded subtitle extract failed for {base_name} stream {index}: {error}")


def process_subtitles(input_dir_path, base_name, video_folder, input_video_path):
    """提取并转换关联字幕（侧车文件 + 容器内挂字幕）。"""
    extract_embedded_subtitles(input_video_path, video_folder, base_name)
    try:
        source_items = os.listdir(input_dir_path)
        for item in source_items:
            if item.startswith(base_name) and item.lower().endswith(tuple(SUBTITLE_EXTENSIONS)):
                if item == os.path.basename(input_video_path): continue

                subtitle_file = os.path.join(input_dir_path, item)
                sub_name_without_ext = os.path.splitext(item)[0]
                suffix = re.sub(r'^[\.\-\_]+', '', sub_name_without_ext[len(base_name):])
                if not suffix: suffix = "Default"

                vtt_filename = f"{base_name}_{suffix}.vtt"
                vtt_path = os.path.join(video_folder, vtt_filename)

                if item.lower().endswith('.ass'):
                    filtered_subtitle = os.path.join(video_folder, f"temp_{suffix}.ass")
                    try:
                        with open(subtitle_file, 'r', encoding='utf-8') as f_in:
                            lines = f_in.readlines()
                        with open(filtered_subtitle, 'w', encoding='utf-8') as f_out:
                            for line in lines:
                                if line.startswith('Dialogue:'):
                                    parts = line.split(',', 9)
                                    if len(parts) >= 4:
                                        style_lower = parts[3].lower()
                                        words = re.sub(r'[^a-z0-9]', ' ', style_lower).split()
                                        if any(x in words for x in ['jp', 'jpn']) or '日' in style_lower or 'romaji' in style_lower:
                                            continue
                                f_out.write(line)
                        subprocess.run(['ffmpeg', '-y', '-i', filtered_subtitle, vtt_path], check=True, stderr=subprocess.DEVNULL)
                        if config.bool_("subtitle", "keep_ass", False):
                            ass_name = f"{base_name}_{suffix}.ass"
                            shutil.copy2(subtitle_file, os.path.join(video_folder, ass_name))
                    finally:
                        if os.path.exists(filtered_subtitle): os.remove(filtered_subtitle)
                else:
                    subprocess.run(['ffmpeg', '-y', '-i', subtitle_file, vtt_path], check=True, stderr=subprocess.DEVNULL)
    except Exception as e:
        logging.error(f"Subtitle error for {base_name}: {e}")

def _static_range_nodes(output_dir):
    """Return (relative parent, media node) pairs for original containers."""
    manifest_path = Path(output_dir) / config.static_range_url_prefix().lstrip('/') / 'manifest.json'
    if not manifest_path.is_file():
        return []
    files = json.loads(manifest_path.read_text(encoding='utf-8')).get('files', {})
    nodes = []
    for stream_id, entry in sorted(files.items()):
        relative = Path(entry.get('relative_path') or entry.get('name', stream_id))
        node = {
            "name": relative.stem, "type": "video", "playbackType": "video",
            "src": f"{config.static_range_url_prefix()}/{stream_id}",
            "mime": entry.get("mime", "video/x-matroska"),
            "subtitle": "原始容器（含内挂字幕/章节）",
        }
        if entry.get('subtitles'): node['subtitles'] = entry['subtitles']
        if entry.get('ass'): node['ass'] = entry['ass']
        nodes.append((relative.parent.parts if relative.parent != Path('.') else (), node))
    return nodes


def subtitle_tracks(folder, output_root, base_name):
    """Use the same subtitle metadata for HLS, small MP4 and Range items."""
    from urllib.parse import quote
    subtitles, ass = [], []
    lang_map = config.get_subtitle_lang_map()
    for path in sorted(Path(folder).iterdir()):
        if path.suffix.lower() not in ('.vtt', '.ass') or path.name.startswith('temp_'):
            continue
        label = path.stem[len(base_name)+1:] if path.stem.startswith(base_name + '_') else path.stem
        if not path.stem.startswith(base_name + '_'):
            continue
        lower = label.lower()
        language, default = 'und', False
        if any(word in label for word in ('繁體', '繁体', '正體', '正体')):
            language = 'zh-Hant'
        elif any(word in label for word in ('简体', '簡體', '中文')):
            language, default = 'zh', True
        elif any(word in label for word in ('日文', '日语', '日語')):
            language = 'ja'
        else:
            for keyword, values in lang_map.items():
                if keyword != 'default' and keyword in lower:
                    language, default = values
                    break
        src = './' + quote(path.relative_to(Path(output_root)).as_posix(), safe='/')
        track = {"label": label, "src": src, "srclang": language, "default": default}
        (ass if path.suffix.lower() == '.ass' else subtitles).append(track)
    # Never enable multiple native text tracks at the same time.
    for collection in (subtitles, ass):
        selected = False
        for track in collection:
            track['default'] = bool(track['default'] and not selected)
            selected = selected or track['default']
    return subtitles, ass


def _read_master_codecs(master_path):
    """从 master.m3u8 的 EXT-X-STREAM-INF 读取 CODECS 值。"""
    try:
        with open(master_path, 'r', encoding='utf-8') as handle:
            for line in handle:
                if line.startswith('#EXT-X-STREAM-INF'):
                    match = re.search(r'CODECS="([^"]+)"', line)
                    if match:
                        return match.group(1)
    except OSError:
        pass
    return ""


def build_index_tree(dir_path, output_root):
    children = []
    try:
        items = sorted(os.listdir(dir_path))
    except Exception:
        return children

    stream_root = config.static_range_url_prefix().lstrip('/') or 'stream'
    for item in items:
        full_path = os.path.join(dir_path, item)
        raw_rel_path = os.path.relpath(full_path, output_root).replace('\\', '/')
        web_src = './' + quote(raw_rel_path, safe='/')

        # 静态 Range 分块与 manifest 属于发布基础设施，不进入媒体树
        if os.path.abspath(full_path) == os.path.abspath(os.path.join(output_root, stream_root)):
            continue

        if os.path.isdir(full_path):
            try:
                folder_items = os.listdir(full_path)
            except:
                folder_items = []

            m3u8_files = [f for f in folder_items if f.lower().endswith('.m3u8')]
            if m3u8_files:
                m3u8_file = 'master.m3u8' if 'master.m3u8' in m3u8_files else sorted(m3u8_files)[0]
                m3u8_rel = os.path.relpath(os.path.join(full_path, m3u8_file), output_root).replace('\\', '/')

                subtitles, ass_tracks = subtitle_tracks(full_path, output_root, item)

                video_node = {"name": item, "type": "video", "src": './' + quote(m3u8_rel, safe='/')}
                if subtitles: video_node["subtitles"] = subtitles
                if ass_tracks: video_node["ass"] = ass_tracks
                master_rel = os.path.join(os.path.dirname(m3u8_rel), 'master.m3u8').replace('\\', '/')
                if os.path.exists(os.path.join(output_root, master_rel)):
                    video_node["master"] = './' + quote(master_rel, safe='/')
                    video_node["codecs"] = _read_master_codecs(os.path.join(output_root, master_rel))
                children.append(video_node)
            else:
                folder_children = build_index_tree(full_path, output_root)
                if folder_children:
                    children.append({"name": item, "type": "folder", "children": folder_children})
        else:
            ext = os.path.splitext(item)[1].lower()
            if item == 'index.json' or item == '_headers' or item.startswith('favicon.'): continue
            if ext in AUDIO_EXTENSIONS:
                children.append({"name": item, "type": "audio", "src": web_src})
            elif ext in IMAGE_EXTENSIONS:
                children.append({"name": item, "type": "image", "src": web_src})
            elif ext in VIDEO_EXTENSIONS:
                # 注意：如果已经被 HLS 处理，它将作为文件夹存在，这里处理的是未被转码的小视频
                node = {"name": item, "type": "video", "src": web_src}
                subtitles, ass_tracks = subtitle_tracks(dir_path, output_root, Path(item).stem)
                if subtitles: node['subtitles'] = subtitles
                if ass_tracks: node['ass'] = ass_tracks
                children.append(node)

    return children

def generate_index(output_dir, set_default=True):
    from media_paths import assign_media_paths
    logging.info("Generating nested JSON index...")
    root_nodes = build_index_tree(output_dir, output_dir)
    for parents, node in _static_range_nodes(output_dir):
        children = root_nodes
        for name in parents:
            folder = next((n for n in children if n['type'] == 'folder' and n['name'] == name), None)
            if folder is None:
                folder = {'name': name, 'type': 'folder', 'children': []}
                children.append(folder)
            children = folder['children']
        # When switching from HLS to Range, prefer the newly selected mode.
        children[:] = [n for n in children if not (n['type'] == 'video' and n['name'] == node['name'])]
        children.append(node)
    if set_default:
        for node in root_nodes:
            if node.get("type") == "video":
                node["isDefault"] = True
                break
    assign_media_paths(root_nodes)
    index_path = os.path.join(output_dir, 'index.json')
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(root_nodes, f, indent=2, ensure_ascii=False)

def _conversion_signature(input_path):
    """Invalidate cached conversion when source/sidecar/config changes."""
    import hashlib
    source = Path(input_path)
    files = [source] + sorted(p for p in source.parent.iterdir()
                             if p.stem.startswith(source.stem) and p.suffix.lower() in SUBTITLE_EXTENSIONS)
    sections = [section for section in config.get().sections() if section.startswith(('video', 'subtitle', 'media'))]
    payload = {
        'version': 1,
        'files': [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in files],
        'config': {section: dict(config.get().items(section)) for section in sections},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def is_output_newer(input_path, output_path):
    """检查输出文件是否已存在且比输入文件更新（mtime 比较）。"""
    if not os.path.exists(output_path):
        return False
    return os.path.getmtime(output_path) >= os.path.getmtime(input_path)


def main():
    parser = argparse.ArgumentParser(description='Universal Media Processing Tool')
    parser.add_argument('input_dir', help='Input directory path')
    parser.add_argument('output_dir', help='Output directory path')
    parser.add_argument('--no-default', action='store_true')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    logging.info("--- Media Processing Tool Started ---")
    # Build a fresh catalog so deleted sources and changed modes cannot leave entries.
    manifest_path = Path(args.output_dir) / config.static_range_url_prefix().lstrip('/') / 'manifest.json'
    if config.static_range_enabled():
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text('{"version": 1, "files": {}}', encoding='utf-8')
    else:
        manifest_path.unlink(missing_ok=True)

    for root, _, files in os.walk(args.input_dir):
        rel_path = os.path.relpath(root, args.input_dir)
        out_root = os.path.join(args.output_dir, rel_path)
        os.makedirs(out_root, exist_ok=True)

        for file in files:
            input_path = os.path.join(root, file)
            output_path = os.path.join(out_root, file)
            ext = os.path.splitext(file)[1].lower()
            file_size = os.path.getsize(input_path)

            # 检查是否已处理过（HLS 切片或 MP4 转换）
            range_video = config.static_range_enabled() and ext in config.static_range_extensions()
            if ext in VIDEO_EXTENSIONS and not range_video:
                base_name = os.path.splitext(file)[0]
                output_m3u8 = os.path.join(out_root, base_name, f"{base_name}-0.m3u8")
                # 如果 HLS 切片存在且比源文件更新，跳过
                stamp = Path(out_root) / base_name / '.mediapages-conversion.json'
                signature = _conversion_signature(input_path)
                if os.path.exists(output_m3u8) and stamp.is_file() and stamp.read_text(encoding='utf-8') == signature:
                    continue
                # 如果小 MP4 存在且比源文件更新，跳过
                if ext == '.mp4' and file_size <= MAX_SIZE and is_output_newer(input_path, output_path):
                    process_subtitles(root, base_name, out_root, input_path)
                    continue

            # 如果音/图片的目标文件存在且比源文件更新，跳过
            if ext in AUDIO_EXTENSIONS and is_output_newer(input_path, output_path):
                continue
            if ext in IMAGE_EXTENSIONS and is_output_newer(input_path, output_path):
                continue
            # 字幕文件（非 .ass）存在且更新，跳过
            if ext in SUBTITLE_EXTENSIONS and ext != '.ass' and is_output_newer(input_path, output_path):
                continue

            # --- 核心处理逻辑 ---
            if ext in IMAGE_EXTENSIONS:
                if file_size <= MAX_SIZE: shutil.copy2(input_path, output_path)
                else: compress_image(input_path, output_path)

            elif ext in AUDIO_EXTENSIONS:
                if config.str_("audio", "mode", "encode") == "copy" or file_size <= MAX_SIZE:
                    shutil.copy2(input_path, output_path)
                else:
                    compress_audio(input_path, output_path)

            elif ext in VIDEO_EXTENSIONS:
                # static_range_mode 下，匹配后缀的视频保留原始字节，供 Pages Function 以 Range 流提供
                if config.static_range_enabled() and ext in config.static_range_extensions():
                    build_static_range(input_path, args.output_dir, args.input_dir)
                elif file_size > MAX_SIZE:
                    # 其余大视频继续 HLS 高性能切片
                    compress_video(input_path, out_root)
                    (Path(out_root) / base_name / '.mediapages-conversion.json').write_text(
                        _conversion_signature(input_path), encoding='utf-8')
                else:
                    # 小视频统一转成兼容性好的 MP4
                    if not convert_video_to_mp4(input_path, output_path):
                        raise RuntimeError(f"MP4 conversion failed: {input_path}")
                    process_subtitles(root, os.path.splitext(file)[0], out_root, input_path)

            elif ext in SUBTITLE_EXTENSIONS:
                if ext != '.ass': # .ass 由 compress_video 内部处理，此处仅复制 srt/vtt
                    shutil.copy2(input_path, output_path)

    # 清理残留 ass（keep_ass=true 时保留给 libass 主题使用）
    if not config.bool_("subtitle", "keep_ass", False):
        for root_dir, _, out_files in os.walk(args.output_dir):
            for f in out_files:
                if f.lower().endswith('.ass'):
                    try: os.remove(os.path.join(root_dir, f))
                    except: pass

    generate_index(args.output_dir, set_default=not args.no_default)
    logging.info("--- Processing Complete ---")

if __name__ == "__main__":
    main()
