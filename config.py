import configparser
from pathlib import Path

_config = None
_CONFIG_PATH = None


def _find_config():
    """查找配置，优先使用 config.ini，不存在则用 config.example.ini。"""
    script_dir = Path(__file__).parent
    for name in ["config.ini", "config.example.ini"]:
        path = script_dir / name
        if path.exists():
            return path
    return script_dir / "config.ini"


def load(path=None):
    global _config, _CONFIG_PATH
    if path:
        _CONFIG_PATH = Path(path)
    else:
        _CONFIG_PATH = _find_config()
    _config = configparser.ConfigParser()
    _config.read(_CONFIG_PATH, encoding="utf-8")
    return _config


def get():
    if _config is None:
        load()
    return _config


# ── 便捷读取方法 ──────────────────────────────────────────────────


def str_(section, key, fallback=None):
    return get().get(section, key, fallback=fallback)


def int_(section, key, fallback=0):
    return get().getint(section, key, fallback=fallback)


def float_(section, key, fallback=0.0):
    return get().getfloat(section, key, fallback=fallback)


def bool_(section, key, fallback=False):
    return get().getboolean(section, key, fallback=fallback)


def list_(section, key, fallback=None):
    """返回逗号分隔的列表，去掉空白。"""
    raw = get().get(section, key, fallback=None)
    if raw is None:
        return fallback or []
    return [x.strip() for x in raw.split(",") if x.strip()]


# ── FFmpeg 命令构建 ──────────────────────────────────────────────


def _populate(cmd, mapping):
    """按顺序向 cmd 添加 ``-key value`` 对（跳过 None 和空值）。"""
    for key, val in mapping:
        if val is None or val == "":
            continue
        cmd.extend([key, str(val)])


def build_hls_hw_cmd(input_path, output_playlist, hls_segments):
    """构建 HLS 硬件编码 ffmpeg 命令。"""
    s = "video.hw"
    cmd = ["ffmpeg", "-y"]
    hwaccel = str_(s, "hwaccel")
    hwfmt = str_(s, "hwaccel_output_format")
    if hwaccel:
        cmd += ["-hwaccel", hwaccel]
        if hwfmt:
            cmd += ["-hwaccel_output_format", hwfmt]
    cmd += ["-i", input_path,
            "-map", "0:v:0", "-map", "0:a:0"]
    _populate(cmd, [
        ("-vf", str_(s, "filter")),
        ("-c:v", str_(s, "codec")),
        ("-preset", str_(s, "preset")),
        ("-profile:v", str_(s, "profile")),
        ("-level:v", str_(s, "level")),
        ("-rc", str_(s, "rc")),
        ("-b:v", str_(s, "bitrate")),
        ("-maxrate", str_(s, "maxrate")),
        ("-bufsize", str_(s, "bufsize")),
        ("-g", str_(s, "gop_size")),
        ("-keyint_min", str_(s, "keyint_min")),
        ("-sc_threshold", str_(s, "sc_threshold")),
        ("-c:a", str_(s, "audio_codec")),
        ("-b:a", str_(s, "audio_bitrate")),
        ("-hls_time", str_(s, "hls_time")),
        ("-hls_playlist_type", str_(s, "hls_playlist_type")),
        ("-hls_segment_filename", hls_segments),
    ])
    cmd.append(output_playlist)
    return cmd


def build_hls_sw_cmd(input_path, output_playlist, hls_segments):
    """构建 HLS 软件编码 ffmpeg 命令（回退方案）。"""
    s = "video.sw"
    cmd = ["ffmpeg", "-y", "-i", input_path,
           "-map", "0:v:0", "-map", "0:a:0"]
    _populate(cmd, [
        ("-vf", str_(s, "filter")),
        ("-c:v", str_(s, "codec")),
        ("-preset", str_(s, "preset")),
        ("-crf", str_(s, "crf")),
        ("-g", str_(s, "gop_size")),
        ("-keyint_min", str_(s, "keyint_min")),
        ("-sc_threshold", str_(s, "sc_threshold")),
        ("-c:a", str_(s, "audio_codec")),
        ("-b:a", str_(s, "audio_bitrate")),
        ("-hls_time", str_(s, "hls_time")),
        ("-hls_playlist_type", str_(s, "hls_playlist_type")),
        ("-hls_segment_filename", hls_segments),
    ])
    cmd.append(output_playlist)
    return cmd


def build_mp4_hw_cmd(input_path, target_output):
    """构建 MP4 硬件编码 ffmpeg 命令。"""
    s = "video.mp4.hw"
    cmd = ["ffmpeg", "-y"]
    hwaccel = str_(s, "hwaccel")
    hwfmt = str_(s, "hwaccel_output_format")
    if hwaccel:
        cmd += ["-hwaccel", hwaccel]
        if hwfmt:
            cmd += ["-hwaccel_output_format", hwfmt]
    cmd += ["-i", input_path]
    _populate(cmd, [
        ("-vf", str_(s, "filter")),
        ("-c:v", str_(s, "codec")),
        ("-preset", str_(s, "preset")),
        ("-tune", str_(s, "tune")),
        ("-profile:v", str_(s, "profile")),
        ("-cq", str_(s, "cq")),
        ("-c:a", str_(s, "audio_codec")),
        ("-b:a", str_(s, "audio_bitrate")),
        ("-movflags", str_(s, "movflags")),
    ])
    cmd.append(target_output)
    return cmd


def build_mp4_sw_cmd(input_path, target_output):
    """构建 MP4 软件编码 ffmpeg 命令（回退方案）。"""
    s = "video.mp4.sw"
    cmd = ["ffmpeg", "-y", "-i", input_path]
    _populate(cmd, [
        ("-c:v", str_(s, "codec")),
        ("-preset", str_(s, "preset")),
        ("-crf", str_(s, "crf")),
        ("-pix_fmt", str_(s, "pix_fmt")),
        ("-c:a", str_(s, "audio_codec")),
        ("-b:a", str_(s, "audio_bitrate")),
        ("-movflags", str_(s, "movflags")),
    ])
    cmd.append(target_output)
    return cmd


def build_hls_copy_cmd(input_path, output_playlist, hls_segments):
    """构建 HLS 复制模式 ffmpeg 命令（不重新编码，直接切片）。"""
    cmd = ["ffmpeg", "-y", "-i", input_path,
           "-map", "0:v:0", "-map", "0:a:0",
           "-c:v", "copy",
           "-c:a", str_("video", "audio_copy_codec", "copy"),
           "-hls_time", str_("video.hw", "hls_time", "3"),
           "-hls_playlist_type", str_("video.hw", "hls_playlist_type", "vod"),
           "-hls_segment_filename", hls_segments,
           output_playlist]
    return cmd


def build_mp4_copy_cmd(input_path, target_output):
    """构建 MP4 复制模式 ffmpeg 命令（不重新编码，直接封装）。"""
    cmd = ["ffmpeg", "-y", "-i", input_path,
           "-c:v", "copy",
           "-c:a", "copy",
           "-movflags", "+faststart",
           target_output]
    return cmd


def get_subtitle_filter_keywords():
    return list_("subtitle", "filter_keywords", ["jp", "jpn", "日", "romaji"])


def get_subtitle_lang_map():
    """从 config.ini 读取字幕语言映射 {keyword: (srclang, default)}。

    [subtitle.lang] 节中，值格式为 'srclang,default_bool'。
    例如: sc = zh,True   → 匹配 'sc' 时 srclang='zh', default=True
    省略逗号部分: sc = zh  → srclang='zh', default=False
    """
    section = "subtitle.lang"
    cfg = get()
    lang_map = {}
    for key in cfg.options(section):
        val = cfg.get(section, key).strip()
        parts = [p.strip() for p in val.split(",")]
        srclang = parts[0] if parts else "und"
        default_flag = parts[1].lower() in ("1", "true", "yes") if len(parts) > 1 else False
        lang_map[key.strip()] = (srclang, default_flag)
    return lang_map


def generate_headers(dist_path):
    """在 dist 目录下生成 Cloudflare Pages _headers 文件。"""
    allow_origin = str_("cors", "allow_origin")
    allow_methods = str_("cors", "allow_methods", "GET, HEAD, OPTIONS")
    if not allow_origin:
        return
    lines = [
        "/*",
        f"  Access-Control-Allow-Origin: {allow_origin}",
        f"  Access-Control-Allow-Methods: {allow_methods}",
    ]
    header_path = dist_path / "_headers"
    header_path.write_text("\n".join(lines), encoding="utf-8")