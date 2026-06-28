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


def _sha256(s):
    """返回 SHA256 十六进制字符串。"""
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def generate_auth(dist_path):
    """如果启用了密码鉴权，返回前端 auth 脚本片段。

    返回 dict: {"enabled": bool, "hash": str, "prompt": str, "error_tip": str,
                "script_before": str, "script_after": str}
    """
    if not bool_("auth", "enabled", False):
        return {"enabled": False, "hash": "", "prompt": "", "error_tip": "",
                "script_before": "", "script_after": ""}

    password = str_("auth", "password", "")
    if not password:
        return {"enabled": False, "hash": "", "prompt": "", "error_tip": "",
                "script_before": "", "script_after": ""}

    pw_hash = _sha256(password)
    prompt = str_("auth", "prompt", "请输入访问密码")
    error_tip = str_("auth", "error_tip", "密码错误")

    # 修复核心：将 display:flex 移入样式表通过 [open] 控制；明确 button 类型；安全处理 crypto 不支持的情况
    script_before = '''
<style>
  #auth-dialog {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0,0,0,0.85);
    z-index: 9999;
    border: none;
    margin: 0;
    max-width: 100vw;
    max-height: 100vh;
    padding: 0;
    display: none;
  }
  #auth-dialog[open] {
    display: flex !important;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
</style>
<dialog id="auth-dialog">
  <form onsubmit="return false;" style="background:#1a1a1a;padding:40px;border-radius:12px;text-align:center;max-width:360px;width:90%;">
    <h2 style="color:#fff;margin:0 0 8px;font-size:18px;">''' + prompt + '''</h2>
    <input id="auth-input" type="password" autofocus style="width:100%;padding:10px;margin:12px 0;background:#2a2a2a;border:1px solid #444;color:#fff;border-radius:6px;font-size:16px;box-sizing:border-box;">
    <div id="auth-error" style="color:#e74c3c;font-size:14px;display:none;margin-bottom:10px;">''' + error_tip + '''</div>
    <button id="auth-btn" type="button" style="width:100%;padding:10px;background:#00a1d6;color:#fff;border:none;border-radius:6px;font-size:16px;cursor:pointer;">确 认</button>
  </form>
</dialog>
<script>
function _sha256(str){
  if(!window.crypto||!window.crypto.subtle){
    var errEl = document.getElementById("auth-error");
    if(errEl) {
      errEl.textContent="环境安全限制，请使用 HTTPS 或 localhost 访问";
      errEl.style.display="block";
    }
    return Promise.reject("crypto.subtle not available");
  }
  return crypto.subtle.digest("SHA-256",new TextEncoder().encode(str)).then(function(b){
    return Array.from(new Uint8Array(b)).map(function(x){return x.toString(16).padStart(2,"0");}).join("");
  });
}
const AUTH_HASH = "''' + pw_hash + '''";
async function _authLogin(pw){
  try{
    var h=await _sha256(pw);
    if(h!==AUTH_HASH)return false;
    sessionStorage.setItem("mediapages_auth","1");
    return true;
  }catch(e){
    console.error("Auth error:",e);
    return false;
  }
}
function _authLogout(){
  sessionStorage.removeItem("mediapages_auth");
  var d=document.getElementById("auth-dialog");if(d)d.showModal();
  var i=document.getElementById("auth-input");if(i){i.value="";i.focus();}
  var e=document.getElementById("auth-error");if(e)e.style.display="none";
}
(function(){
  var p=new URLSearchParams(location.search).get("pw");
  if(p)_sha256(p).then(function(h){if(h===AUTH_HASH)sessionStorage.setItem("mediapages_auth","1");});
  if(sessionStorage.getItem("mediapages_auth")!=="1"){
    document.addEventListener("DOMContentLoaded",function(){
      var d=document.getElementById("auth-dialog"),
          b=document.getElementById("auth-btn"),
          i=document.getElementById("auth-input"),
          e=document.getElementById("auth-error");
      function s(){
        _authLogin(i.value).then(function(ok){
          if(ok){d.close();e.style.display="none";}
          else{
            e.textContent = "''' + error_tip + '''";
            e.style.display="block";
            setTimeout(function(){e.style.display="none";},2000);
          }
        });
      }
      if(b) b.onclick=s;
      if(i) i.onkeydown=function(ev){if(ev.key==="Enter")s();};
      if(d) d.showModal();
    });
  }
  window.authLogout=_authLogout;
})();
</script>
'''

    script_after = '''
<a id="auth-logout-btn" href="javascript:authLogout()" style="position:fixed;bottom:20px;right:20px;z-index:99;color:#666;font-size:11px;text-decoration:none;opacity:0.3;">退出登录</a>
'''

    return {"enabled": True, "hash": pw_hash, "prompt": prompt, "error_tip": error_tip,
            "script_before": script_before, "script_after": script_after}