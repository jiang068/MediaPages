# MediaPages 🎬

一个利用 Cloudflare Pages 搭建几乎无限容量的个人流媒体库的工具套件

MediaPages 是一个自动化的多媒体处理与部署脚手架。它巧妙利用了现代浏览器的 HLS (`.m3u8`) 视频流切片技术，将大型视频文件切分为符合 Cloudflare Pages 免费版 **25MB 单文件大小限制** 的碎片。配合 Cloudflare Pages 单个项目 20,000 个文件的上限，理论上单个项目可容纳约 **488GB** 的媒体资产，且项目数量无限制！

本项目包含完整的自动化流程：从媒体转码切片、自动提取与转换字幕（支持 ASS/SRT 转 VTT）、**图片与音频智能压缩降级**、生成优雅的动态前端 Web 界面，到分批次防超时自动部署至 Cloudflare Pages，一气呵成。


部署示例实例： [极客湾2026年手机大横评](https://phone-2026.pages.dev)

## ⚠️ 重要警告与免责声明 (必读)

**1. 账号风控提示**

本工具的自动化分批上传机制属于对 Cloudflare Pages 免费层规则的极限利用。**存在触发风控导致账户封禁或限制使用的风险！**

强烈建议：**请务必使用新创建的独立 Cloudflare 账号进行操作**，切勿使用包含重要业务或域名的生产环境账号，以免造成不必要的连带损失。


**2. 用户内容免责声明**

本项目仅作为一个在本地运行的开源纯技术工具提供，核心目的为技术交流与个人媒体库的管理便利。

作者（开发者）对用户使用本工具处理、上传、分发或存储的**任何内容概不负责**。作为工具的开发者，作者**没有能力、没有义务，也无法审查或控制**任何人利用此工具从事的任何具体行为。

请使用者务必严格遵守所在国家/地区的法律法规，以及 Cloudflare 的服务条款 (ToS)。**严禁**使用本工具处理、传播任何违法违规、侵权（如盗版受版权保护的实体）或破坏公序良俗的内容。

因用户不当使用本工具（包括但不限于被不法分子利用）而引发的任何版权纠纷、账号封禁、数据丢失或法律责任，均由使用者自行承担，与本项目及原作者完全无关。


## ✨ 特性

* **全自动视频转码切片**：自动识别目录结构，大于 25MB 的视频自动进行 HLS 高性能切片（支持 CUDA 加速），小视频统一转标准 MP4 确保浏览器兼容性。
* **智能字幕处理**：自动扫描同名字幕文件，将 ASS/SRT 转换为 Web 原生支持的 VTT 格式（针对 ASS 还会智能过滤掉日文等双语多余字幕）。
* **图音极限压缩兜底**：超长无损 FLAC 播客？8K 超清扫图海报？遇到大于 25MB 的非视频媒体，脚本会自动触发极限压缩：音频动态计算码率进行转化，图片动态降低质量与分辨率转 WebP，死活也要帮你塞进 Pages！
* **优雅的 Web 播放器**：基于 `hls.js`，支持动态加载无限层级的嵌套目录，支持移动端自适应与原生字幕轨道切换。
* **分批防超时部署**：针对超大目录上传容易触发 Cloudflare API 403 错误的问题，内置分批次缓存搬运上传逻辑，并支持**断点续传**。

## 🛠️ 环境准备

在开始之前，请确保你的系统环境中已安装以下依赖：

1. **Python 3.x**（需安装 `Pillow` 库处理图片：`pip install Pillow`）
2. **FFmpeg**：用于媒体转码切片与音频压缩。必须配置在系统环境变量中。
3. **Node.js & npm**：用于安装 Cloudflare 官方部署工具 `wrangler`。
```bash
# 安装 wrangler
npm install -g wrangler

```

4. **Cloudflare API 令牌配置**：
你需要前往 Cloudflare 仪表盘创建一个 API 令牌（权限路径：`账户 > Cloudflare Pages > 编辑`），并在终端中配置环境变量：
```bash
export CLOUDFLARE_API_TOKEN="你的_API_TOKEN"
export CLOUDFLARE_ACCOUNT_ID="你的_ACCOUNT_ID"

```



## 🚀 快速开始 (一键运行)

`main.py` 是整个流程的编排入口，只需一条命令即可完成：格式转换 -> 网页生成 -> 创建远端项目 -> 自动分批部署。

```bash
python main.py -s "/你的/原始媒体/目录" -w "/你的/本地工作/缓存区" -p "cf-pages-项目名" -t "我的流媒体网站标题" --threshold 2048

```

**参数说明**：

* `-s, --source`：必填，原始媒体库目录。
* `-w, --workspace`：必填，临时工作区目录（程序会在其中创建 `dist` 和 `tmp` 用于处理和缓存文件，**运行结束后会清理 tmp**）。
* `-p, --project-name`：必填，Cloudflare Pages 的远端项目名称（英文/连字符）。
* `-t, --title`：可选，网页标题。不传则使用 `config.ini [site] → title`。
* `--threshold`：可选，单次上传阈值（MB）。不传则使用 `config.ini [cloudflare] → upload_threshold_mb`。

> [!TIP]
> 所有配置均可通过 `config.ini` 文件管理，无需改动源码。

### 批量处理多个媒体库

如果你有多个番剧或电影系列需要分别建站，可以写一个简单的 Bash 脚本顺序执行：

```bash
#!/bin/bash
python main.py -s "/Video/Railgun" -w "/tmp/work1" -p "railgun-t" -t "某科学的超电磁炮T" --threshold 2048
python main.py -s "/Video/Frieren" -w "/tmp/work2" -p "frieren-anime" -t "葬送的芙莉莲" --threshold 2048

```

## 🧩 独立模块进阶用法

你可以拆开单独使用转换模块或上传模块。

### 1. 仅转换媒体 (`convert.py`)

如果你只想把媒体库处理完毕并生成静态网站结构，不进行上传：

```bash
python convert.py "/输入目录" "/输出目录"

```

*(加上 `--no-default` 参数可以取消默认自动播放首个视频的行为)*

### 2. 仅分批上传 (`upload.py`)

如果你已经有了打包好的网页文件夹，想安全地传到 Cloudflare Pages（防 403）：

```bash
python upload.py -t "/包含网页的dist目录" -c "/用于搬运的空tmp目录" -p "项目名称" --threshold 1024

```

**断点续传**：如果上传因为网络波动意外中断，加上 `-r` 参数重新运行即可，它会优先上传目标目录内剩余的文件，继续未完成的任务。

## ⚙️ 配置文件 `config.ini` (必读)

`config.ini` 集中管理所有运行参数，修改后无需改动任何源码。你可以在 `MediaPages/config.ini` 中找到全部配置，以下逐一说明。

### `[main]` — 运行入口参数

在 `config.ini` 中设置后，`main.py` 可无参运行。CLI 参数优先级高于此配置：

```ini
[main]
source =                ; 原始媒体库目录（原 -s 参数）
workspace =             ; 工作区目录（原 -w 参数），程序会在此创建 dist 和 tmp
project_name =          ; Cloudflare Pages 项目名称（原 -p 参数）
```

### `[video]` — 视频处理模式切换

```ini
mode = copy     ; copy = 流复制（不重新编码，保留原始画质）
                ; encode = 硬件/软件编码（默认编码为 H.264）
```

这是最常用的开关。设 `copy` 则直接切片，画质零损失，速度极快；设 `encode` 则用 H.264 重新编码。

> **流复制模式**适用于你已有 HEVC (H.265) 等高效编码的视频源，只需切片无需降码率。
> **编码模式**适用于需要把所有视频统一输出为浏览器兼容性最好的 H.264 格式，或需要压小体积的场景。

### `[video.hw]` / `[video.sw]` — HLS 编码参数

这两个段控制 HLS 切片的硬件加速和 CPU 回退方案参数：

```ini
[video.hw]
hwaccel = cuda                    ; 硬件加速类型
hwaccel_output_format = cuda      ; 硬件输出格式
filter = scale_cuda=format=nv12   ; 视频滤镜
codec = h264_nvenc                ; 视频编码器（无 N 卡可改为 libx264）
preset = p6                       ; 编码预设（质量/速度权衡）
profile = high                    ; H.264 编码档次
level = 5.2                       ; H.264 编码等级
rc = vbr                          ; 码率控制模式
bitrate = 18M                     ; 平均码率
maxrate = 24M                     ; 最大码率
bufsize = 36M                     ; VBV 缓冲区
gop_size = 180                    ; 关键帧间隔，建议为 fps 的整数倍（60fps*3=180）
keyint_min = 180                  ; 最小关键帧间隔
sc_threshold = 0                  ; 场景切换阈值（0=关闭主动插入关键帧）
audio_codec = aac                 ; 音频编码器
audio_bitrate = 320k              ; 音频码率
hls_time = 3                      ; 切片时长（秒），关键！控制单个 .ts 文件大小
hls_playlist_type = vod           ; HLS 播放列表类型
```

**常见调优组合：**

| 视频类型 | 编码器 | 码率 | 切片时长 | GOP |
|---------|--------|------|---------|-----|
| 4K 60fps 真人视频 | `h264_nvenc` / `libx264` | `maxrate 24M` | `hls_time 3` | `gop_size 180` |
| 1080P 动漫/番剧 | `h264_nvenc` / `libx264` | `maxrate 8M` | `hls_time 6` | `gop_size 120` |
| 流复制（原画） | 无需编码，走 `[video] mode = copy` | — | `hls_time 6` | — |

**无 NVIDIA 显卡？** 改 `[video.hw]` 中的 `codec`：
- **macOS Apple Silicon**：`videotoolbox`
- **Intel 核显**：`h264_qsv`
- **通用 CPU**：`libx264`（并删掉 `hwaccel`、`hwaccel_output_format`、`filter`，改用 `scale=format=yuv420p`）

### `[video.mp4.hw]` / `[video.mp4.sw]` — 小视频 MP4 编码

处理小于 24MB 的小视频时使用这些参数，转换成通用 MP4（非 HLS 切片）。参数含义同上。

### `[image]` / `[audio]` — 图片与音频压缩

当图片/音频超过 24MB 时触发的极限压缩策略：

```ini
[image]
quality_start = 95           ; 初始画质，逐级降低至 20
scale_start = 0.9             ; 画质降到底后，再缩小分辨率（每次 10%）
scale_min = 0.3               ; 最多缩到 30%

[audio]
safe_target_bytes = 24641536  ; 目标 23.5MB，留余量
bitrate_max = 320             ; 初始码率上限 kbps
bitrate_min = 32              ; 最低码率 kbps
bitrate_reduction_factor = 0.8 ; 超标后每次砍掉 20% 码率重试
```

### `[site]` — 站点外观

```ini
[site]
title = MediaPages          ; 网站标题（可用 main.py -t 参数覆盖）
favicon =                   ; 网站图标（留空用默认，可填本地路径或 URL）
```

### `[cors]` — CORS 跨域配置

部署时自动生成 `_headers` 文件，允许跨域加载视频。如果需要把视频嵌入到其他网站，必须开启此功能：

```ini
[cors]
allow_origin = *             ; 允许所有来源，可改为特定域名如 https://mysite.com
allow_methods = GET, HEAD, OPTIONS
```

### `[cloudflare]` — API 凭证与部署

```ini
[cloudflare]
api_token =                  ; API 令牌（优先级：环境变量 > 此配置）
account_id =                 ; 账户 ID
deploy_cmd = ...             ; wrangler 部署命令，一般无需修改
upload_threshold_mb = 512    ; 单批次上传阈值（MB）
```

> API 凭证也可以设环境变量 `CLOUDFLARE_API_TOKEN` 和 `CLOUDFLARE_ACCOUNT_ID`，优先级高于 config.ini。

## 📄 许可证

本项目采用 **AGPLv3** 协议开源。
*注意：通过本程序处理生成的静态媒体网站内容不受此协议限制，你可以自由使用、部署和分发你生成的网站内容。*
