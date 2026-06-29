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

def compress_video(input_path, output_dir):
    """采用 HLS 切片方式处理视频，支持全格式和 CUDA 硬件加速"""
    input_dir_path = os.path.dirname(input_path)
    base_name = os.path.splitext(os.path.basename(input_path))[0]

    video_folder = os.path.join(output_dir, base_name)
    os.makedirs(video_folder, exist_ok=True)
    logging.info(f"Starting HLS processing: {input_path}")

    output_playlist = os.path.join(video_folder, f"{base_name}-0.m3u8")
    hls_segments = os.path.join(video_folder, "chunk_%04d.ts")

    # 复制模式：不重新编码，直接切片，保留原始画质
    if config.str_("video", "mode", "encode") == "copy":
        cmd = config.build_hls_copy_cmd(input_path, output_playlist, hls_segments)
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
        except Exception as e:
            logging.error(f"HLS copy failed for {base_name}: {e}")
            raise
    else:
        # 编码模式（默认）：硬件 + 软件回退
        hw_cmd = config.build_hls_hw_cmd(input_path, output_playlist, hls_segments)
        try:
            subprocess.run(hw_cmd, check=True, stderr=subprocess.DEVNULL)
        except Exception as e:
            logging.warning(f"CUDA failed, falling back to CPU for {base_name}. Error: {e}")
            sw_cmd = config.build_hls_sw_cmd(input_path, output_playlist, hls_segments)
            subprocess.run(sw_cmd, check=True, stderr=subprocess.DEVNULL)

    # 智能字幕处理
    process_subtitles(input_dir_path, base_name, video_folder, input_path)

def process_subtitles(input_dir_path, base_name, video_folder, input_video_path):
    """提取并转换关联字幕"""
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
                    finally:
                        if os.path.exists(filtered_subtitle): os.remove(filtered_subtitle)
                else:
                    subprocess.run(['ffmpeg', '-y', '-i', subtitle_file, vtt_path], check=True, stderr=subprocess.DEVNULL)
    except Exception as e:
        logging.error(f"Subtitle error for {base_name}: {e}")

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
                base_name = item

                for vtt in vtt_files:
                    vtt_name_no_ext = os.path.splitext(vtt)[0]
                    suffix = vtt_name_no_ext[len(base_name)+1:] if vtt_name_no_ext.startswith(base_name + "_") else vtt_name_no_ext
                    label = suffix
                    suffix_lower = suffix.lower()
                    lang_map = config.get_subtitle_lang_map()
                    matched = False
                    for lang_keyword, (lang_val, default_val) in lang_map.items():
                        if lang_keyword in suffix_lower:
                            srclang, default = lang_val, default_val
                            matched = True
                            break
                    if not matched:
                        srclang, default = "und", False

                    vtt_rel = os.path.relpath(os.path.join(full_path, vtt), output_root).replace('\\', '/')
                    subtitles.append({
                        "label": label, "srclang": srclang, "src": f"./{vtt_rel}", "default": default
                    })

                video_node = {"name": item, "type": "video", "src": f"./{m3u8_rel}"}
                if subtitles: video_node["subtitles"] = subtitles
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
                children.append({"name": item, "type": "video", "src": web_src})

    return children

def generate_index(output_dir, set_default=True):
    logging.info("Generating nested JSON index...")
    root_nodes = build_index_tree(output_dir, output_dir)
    if set_default:
        for node in root_nodes:
            if node.get("type") == "video":
                node["isDefault"] = True
                break
    index_path = os.path.join(output_dir, 'index.json')
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(root_nodes, f, indent=2, ensure_ascii=False)

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
            if ext in VIDEO_EXTENSIONS:
                base_name = os.path.splitext(file)[0]
                output_m3u8 = os.path.join(out_root, base_name, f"{base_name}-0.m3u8")
                # 如果 HLS 切片存在且比源文件更新，跳过
                if os.path.exists(output_m3u8) and is_output_newer(input_path, output_m3u8):
                    continue
                # 如果小 MP4 存在且比源文件更新，跳过
                if ext == '.mp4' and is_output_newer(input_path, output_path):
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
                if file_size <= MAX_SIZE: shutil.copy2(input_path, output_path)
                else: compress_audio(input_path, output_path)

            elif ext in VIDEO_EXTENSIONS:
                # 无论 MKV 还是 MP4，大于 MAX_SIZE 都进行 HLS 高性能切片
                if file_size > MAX_SIZE:
                    compress_video(input_path, out_root)
                else:
                    # 小视频统一转成兼容性好的 MP4
                    convert_video_to_mp4(input_path, output_path)

            elif ext in SUBTITLE_EXTENSIONS:
                if ext != '.ass': # .ass 由 compress_video 内部处理，此处仅复制 srt/vtt
                    shutil.copy2(input_path, output_path)

    # 清理残留 ass
    for root_dir, _, out_files in os.walk(args.output_dir):
        for f in out_files:
            if f.lower().endswith('.ass'):
                try: os.remove(os.path.join(root_dir, f))
                except: pass

    generate_index(args.output_dir, set_default=not args.no_default)
    logging.info("--- Processing Complete ---")

if __name__ == "__main__":
    main()
