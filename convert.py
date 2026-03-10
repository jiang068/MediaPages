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

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 常量定义
MB = 1024 * 1024
MAX_SIZE = 24 * MB  # 24MB

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
    try:
        img = Image.open(input_path)
        if img.mode != 'RGB': img = img.convert('RGB')

        ext = os.path.splitext(output_path)[1].lower()
        if ext not in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            output_path = os.path.splitext(output_path)[0] + '.webp'

        quality = 95
        while quality >= 20:
            img.save(output_path, 'WEBP', quality=quality)
            if os.path.getsize(output_path) <= MAX_SIZE:
                return
            quality -= 5

        scale = 0.9
        while scale > 0.3:
            new_size = (int(img.width * scale), int(img.height * scale))
            img_resized = img.resize(new_size, Image.LANCZOS)
            quality = 95
            while quality >= 20:
                img_resized.save(output_path, 'WEBP', quality=quality)
                if os.path.getsize(output_path) <= MAX_SIZE:
                    return
                quality -= 5
            scale -= 0.1

        img.save(output_path, 'WEBP', quality=20)
    except Exception as e:
        logging.error(f"Image compression error: {e}")
        shutil.copy2(input_path, output_path)

def compress_audio(input_path, output_path):
    logging.info(f"Starting precise audio compression: {input_path}")
    temp_output = output_path + '.tmp'

    try:
        duration = get_audio_duration(input_path)
        orig_bitrate = get_audio_bitrate(input_path)
        if duration <= 0: duration = 60

        safe_target_bytes = 23.5 * MB
        calculated_kbps = int((safe_target_bytes * 8) / (duration * 1000))

        target_kbps = calculated_kbps
        if orig_bitrate > 0:
            target_kbps = min(target_kbps, orig_bitrate)
        target_kbps = min(target_kbps, 320)
        target_kbps = max(target_kbps, 32)

        while True:
            cmd = [
                'ffmpeg', '-y', '-i', input_path,
                '-c:a', 'libmp3lame', '-b:a', f'{target_kbps}k',
                '-f', 'mp3', temp_output
            ]
            subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)

            final_size = os.path.getsize(temp_output)
            if final_size <= MAX_SIZE or target_kbps <= 32:
                shutil.move(temp_output, output_path)
                break

            target_kbps = int(target_kbps * 0.8)
            if target_kbps < 32: target_kbps = 32

    except Exception as e:
        logging.error(f"Error compressing audio {input_path}: {e}")
        shutil.copy2(input_path, output_path)
    finally:
        if os.path.exists(temp_output):
            os.remove(temp_output)

def convert_video_to_mp4(input_path, output_path):
    logging.info(f"Converting video to MP4: {input_path}")
    output_path = os.path.splitext(output_path)[0] + '.mp4'

    hw_cmd = [
        'ffmpeg', '-y',
        '-hwaccel', 'cuda',
        '-hwaccel_output_format', 'cuda',
        '-i', input_path,
        '-vf', 'scale_cuda=format=nv12',
        '-c:v', 'h264_nvenc',
        '-preset', 'p6',
        '-tune', 'hq',
        '-profile:v', 'high',
        '-cq', '22',
        '-c:a', 'aac', '-b:a', '192k',
        '-movflags', '+faststart',
        output_path
    ]

    try:
        subprocess.run(hw_cmd, check=True, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        sw_cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-c:v', 'libx264',
            '-preset', 'slow',
            '-crf', '22',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart',
            output_path
        ]
        try:
            subprocess.run(sw_cmd, check=True, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            if os.path.exists(output_path):
                os.remove(output_path)
            return False

def compress_video(input_path, output_dir):
    input_dir_path = os.path.dirname(input_path)
    base_name = os.path.splitext(os.path.basename(input_path))[0]

    video_folder = os.path.join(output_dir, base_name)
    os.makedirs(video_folder, exist_ok=True)
    logging.info(f"Starting HLS video processing for: {input_path}")

    output_playlist = os.path.join(video_folder, f"{base_name}-0.m3u8")
    hls_segments = os.path.join(video_folder, "chunk_%04d.ts")

    hw_cmd = [
        'ffmpeg', '-y', '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda',
        '-i', input_path,
        '-map', '0:v:0', '-map', '0:a:0',
        '-vf', 'scale_cuda=format=nv12',
        '-c:v', 'h264_nvenc', '-preset', 'p6', '-tune', 'hq',
        '-profile:v', 'high', '-level:v', '4.2',
        '-rc', 'vbr', '-cq', '22', '-b:v', '0', '-maxrate', '8M', '-bufsize', '16M',
        '-g', '90', '-keyint_min', '90', '-sc_threshold', '0',
        '-c:a', 'aac', '-b:a', '192k',
        '-hls_time', '6', '-hls_playlist_type', 'vod',
        '-hls_segment_filename', hls_segments,
        output_playlist
    ]

    try:
        subprocess.run(hw_cmd, check=True, stderr=subprocess.DEVNULL)
    except:
        sw_cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-map', '0:v:0', '-map', '0:a:0',
            '-vf', 'scale=format=yuv420p',
            '-c:v', 'libx264', '-preset', 'medium', '-tune', 'film',
            '-profile:v', 'high', '-level', '4.2',
            '-rc', 'vbr', '-crf', '22', '-b:v', '0', '-maxrate', '8M', '-bufsize', '16M',
            '-g', '90', '-keyint_min', '90', '-sc_threshold', '0',
            '-c:a', 'aac', '-b:a', '192k',
            '-hls_time', '6', '-hls_playlist_type', 'vod',
            '-hls_segment_filename', hls_segments,
            output_playlist
        ]
        subprocess.run(sw_cmd, check=True, stderr=subprocess.DEVNULL)

    # ---------------- 智能字幕处理部分 ----------------
    try:
        source_items = os.listdir(input_dir_path)
        for item in source_items:
            # 找到和视频同名开头，且属于字幕格式的文件
            if item.startswith(base_name) and item.lower().endswith(tuple(SUBTITLE_EXTENSIONS)):
                if item == os.path.basename(input_path):
                    continue

                subtitle_file = os.path.join(input_dir_path, item)

                # 提取文件的后缀部分作为字幕名 (例如 .JPSC.ass -> JPSC)
                sub_name_without_ext = os.path.splitext(item)[0]
                suffix = sub_name_without_ext[len(base_name):]
                # 利用正则抹掉开头的标点符号（如点或下划线）
                suffix = re.sub(r'^[\.\-\_]+', '', suffix)
                if not suffix:
                    suffix = "Default"

                # 拼接最终转换出来的 vtt 文件名
                vtt_filename = f"{base_name}_{suffix}.vtt"
                vtt_path = os.path.join(video_folder, vtt_filename)

                # 处理 ASS 格式，动态滤除日语双语行
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
                                        # 将样式名中的非字母/数字替换为空格，提取出独立的单词
                                        words = re.sub(r'[^a-z0-9]', ' ', style_lower).split()
                                        # 智能识别常见的日文字幕样式并丢弃 (过滤独立词汇 jp/jpn 或含有日/romaji 的轨道)
                                        if 'jp' in words or 'jpn' in words or '日' in style_lower or 'romaji' in style_lower:
                                            continue
                                f_out.write(line)
                        # 将过滤好日文的 ass 转换为 vtt
                        subprocess.run(['ffmpeg', '-y', '-i', filtered_subtitle, vtt_path], check=True, stderr=subprocess.DEVNULL)
                    finally:
                        if os.path.exists(filtered_subtitle):
                            os.remove(filtered_subtitle)
                else:
                    # 如果是 SRT 或已经是 VTT，直接转换过去
                    subprocess.run(['ffmpeg', '-y', '-i', subtitle_file, vtt_path], check=True, stderr=subprocess.DEVNULL)
    except Exception as e:
        logging.error(f"Error processing subtitles for {base_name}: {e}")

def build_index_tree(dir_path, output_root):
    children = []
    try:
        items = sorted(os.listdir(dir_path))
    except Exception:
        return children

    for item in items:
        full_path = os.path.join(dir_path, item)
        raw_rel_path = os.path.relpath(full_path, output_root).replace('\\', '/')
        web_src = f"./{raw_rel_path}"

        if os.path.isdir(full_path):
            try:
                folder_items = os.listdir(full_path)
            except:
                folder_items = []

            m3u8_files = [f for f in folder_items if f.lower().endswith('.m3u8')]
            if m3u8_files:
                m3u8_file = m3u8_files[0]
                m3u8_rel = os.path.relpath(os.path.join(full_path, m3u8_file), output_root).replace('\\', '/')

                subtitles = []
                vtt_files = [f for f in folder_items if f.lower().endswith('.vtt')]
                base_name = item # 文件夹名即为视频源文件名

                for vtt in vtt_files:
                    vtt_name_no_ext = os.path.splitext(vtt)[0]
                    # 解析在 compress_video 里拼上去的 _后缀
                    if vtt_name_no_ext.startswith(base_name + "_"):
                        suffix = vtt_name_no_ext[len(base_name)+1:]
                    else:
                        suffix = vtt_name_no_ext

                    label = suffix  # 直接把截取到的字符串（例如 JPSC）作为前端显示的标签
                    suffix_lower = suffix.lower()

                    # 为了兼容播放器，智能推断 srclang 和 是否设为默认轨道
                    if 'sc' in suffix_lower or 'chs' in suffix_lower or 'zh' in suffix_lower:
                        srclang, default = "zh", True
                    elif 'tc' in suffix_lower or 'cht' in suffix_lower or 'hant' in suffix_lower:
                        srclang, default = "zh-Hant", False
                    else:
                        srclang, default = "und", False

                    vtt_rel = os.path.relpath(os.path.join(full_path, vtt), output_root).replace('\\', '/')
                    subtitles.append({
                        "label": label,
                        "srclang": srclang,
                        "src": f"./{vtt_rel}",
                        "default": default
                    })

                video_node = {
                    "name": item,
                    "type": "video",
                    "src": f"./{m3u8_rel}"
                }
                if subtitles:
                    video_node["subtitles"] = subtitles

                children.append(video_node)
            else:
                folder_children = build_index_tree(full_path, output_root)
                if folder_children:
                    children.append({
                        "name": item,
                        "type": "folder",
                        "children": folder_children
                    })
        else:
            ext = os.path.splitext(item)[1].lower()
            if item == 'index.json':
                continue

            if ext in AUDIO_EXTENSIONS:
                children.append({"name": item, "type": "audio", "src": web_src})
            elif ext in IMAGE_EXTENSIONS:
                children.append({"name": item, "type": "image", "src": web_src})
            elif ext in VIDEO_EXTENSIONS:
                children.append({"name": item, "type": "video", "src": web_src})

    return children

def generate_index(output_dir, set_default=True):
    logging.info("Generating nested JSON index for frontend...")
    root_nodes = build_index_tree(output_dir, output_dir)

    if set_default:
        for node in root_nodes:
            if node.get("type") == "video":
                node["isDefault"] = True
                logging.info(f"Set default media to: {node['name']}")
                break

    index_path = os.path.join(output_dir, 'index.json')
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(root_nodes, f, indent=2, ensure_ascii=False)
    logging.info(f"Index successfully generated at: {index_path}")

def main():
    parser = argparse.ArgumentParser(description='Media file processing tool')
    parser.add_argument('input_dir', help='Input directory path')
    parser.add_argument('output_dir', help='Output directory path')
    parser.add_argument('--no-default', action='store_true', help='Disable automatically setting the first video in root as default')
    args = parser.parse_args()

    logging.info(f"--- Media Processing Tool Started ---")
    os.makedirs(args.output_dir, exist_ok=True)

    total_files = 0
    processed_files = 0
    for root, _, files in os.walk(args.input_dir):
        rel_path = os.path.relpath(root, args.input_dir)
        out_root = os.path.join(args.output_dir, rel_path)
        os.makedirs(out_root, exist_ok=True)

        for file in files:
            total_files += 1
            input_path = os.path.join(root, file)
            output_path = os.path.join(out_root, file)
            ext = os.path.splitext(file)[1].lower()

            if os.path.exists(output_path) or (ext == '.mkv' and os.path.exists(os.path.splitext(output_path)[0] + '.mp4')):
                continue

            file_size = os.path.getsize(input_path)

            if file_size <= MAX_SIZE and ext != '.mkv' and ext not in AUDIO_EXTENSIONS:
                # 提前拦截：如果是较小的常规文件，且是 ass 字幕，则跳过拷贝
                if ext == '.ass':
                    processed_files += 1
                    continue
                shutil.copy2(input_path, output_path)
                processed_files += 1
                continue

            if ext in IMAGE_EXTENSIONS:
                compress_image(input_path, output_path)
                processed_files += 1
            elif ext in AUDIO_EXTENSIONS:
                if file_size <= MAX_SIZE:
                    shutil.copy2(input_path, output_path)
                else:
                    compress_audio(input_path, output_path)
                processed_files += 1
            elif ext in VIDEO_EXTENSIONS:
                if ext == '.mkv':
                    if file_size <= MAX_SIZE:
                        convert_video_to_mp4(input_path, output_path)
                    else:
                        compress_video(input_path, out_root)
                    processed_files += 1
                else:
                    shutil.copy2(input_path, output_path)
                    processed_files += 1
            elif ext in SUBTITLE_EXTENSIONS:
                # 拦截点：如果是大于 MAX_SIZE 分支里的字幕，绝不复制原版 ass 过去
                if ext != '.ass':
                    shutil.copy2(input_path, output_path)
                processed_files += 1

    # ---------------- 清理阶段：彻底抹除输出目录残留的 ass 文件 ----------------
    logging.info("Cleaning up any remaining .ass files in output directory...")
    for root_dir, _, out_files in os.walk(args.output_dir):
        for f in out_files:
            if f.lower().endswith('.ass'):
                ass_path = os.path.join(root_dir, f)
                try:
                    os.remove(ass_path)
                    logging.info(f"Removed redundant subtitle: {ass_path}")
                except Exception as e:
                    logging.error(f"Failed to remove {ass_path}: {e}")

    generate_index(args.output_dir, set_default=not args.no_default)
    logging.info("--- Processing Complete ---")

if __name__ == "__main__":
    main()
