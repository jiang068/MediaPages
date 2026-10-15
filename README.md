# MediaPages

利用 Cloudflare Pages 搭建个人流媒体库的自动化工具套件。将大型视频自动 HLS 切片、字幕提取、图片/音频压缩，并一键部署到 Cloudflare Pages。

## 特性

- **自动转码切片** — 大于 25MB 的视频自动 HLS 切片（支持 CUDA 加速），小视频转标准 MP4
- **HLS 切片容器可选** — `mpegts`（默认）或 `fmp4`（CMAF，`.m4s` + `init.mp4`），fMP4 附带生成带 `CODECS` 的 `master.m3u8`
- **HEVC/AV1 支持** — fMP4 路径支持 HEVC/AV1 流复制，高码率 HEVC 可按 `moof`/`mdat` 边界重排切片以规避 25MB 单文件上限
- **静态 Range 流** — 不适合切片的原始容器（如 MKV，含内挂 ASS/章节）可按固定大小分块，由 Pages Function 以单个可 Range 的 URL 提供
- **字幕提取** — 侧车与容器内挂（MKV 内嵌）ASS/SRT 自动转 VTT（Web 原生字幕），智能过滤日文等多余字幕；`keep_ass = true` 时额外保留 ASS 侧车供 libass 渲染
- **图音压缩兜底** — 超限图片/音频自动降质压缩，硬塞进 25MB 限制
- **ArtPlayer 可选播放器** — 主题提供 `#artplayer-container` 即启用 ArtPlayer，否则自动回退原生 `<video>` + hls.js
- **模块化前端** — player/（不变内核）与 theme/（可变皮囊）分离，可直接改 CSS/JS 自定义主题
- **增量部署** — 依赖 wrangler 自动跳过未变更文件，二次部署秒级完成

## 快速开始

```bash
pip install Pillow
npm install -g wrangler
export CLOUDFLARE_API_TOKEN="你的_API_TOKEN"
export CLOUDFLARE_ACCOUNT_ID="你的_ACCOUNT_ID"

python main.py \
  -s "/原始媒体/目录" \
  -w "/临时工作区" \
  -p "pages项目名" \
  -t "网站标题"
```

## 命令行参数

| 参数 | 说明 |
|------|------|
| `-s` | 原始媒体库目录 |
| `-w` | 临时工作区（自动创建 dist/ 和 tmp/） |
| `-p` | Cloudflare Pages 项目名 |
| `-t` | 网页标题（可选，默认取自 config.ini） |
| `--threshold` | 每批上传大小阈值 MB（默认 512） |
| `--skip-convert` | 跳过格式转换，只重新部署（改前端样式时用） |
| `--skip-deploy` | 只处理到 dist 目录，不部署（调试用） |

所有配置也可在 `config.ini` 中预设，CLI 参数优先级更高。

## 项目结构

```
MediaPages/
├── main.py                 ← 全流程编排入口
├── convert.py               ← 媒体转码切片模块
├── upload.py                ← 分批部署模块（增量模式走 wrangler）
├── config.py                ← 配置读写
├── config.ini               ← 用户配置
├── config.example.ini       ← 配置示例
├── codec_string.py          ← 从 fMP4 init segment 解析 RFC 6381 codec 字符串
├── fragment_mp4.py          ← 按 moof/mdat 边界重排 fMP4 切片（HEVC 高码率用）
├── static_stream.py         ← 原始容器按固定大小分块 + 生成 stream manifest
├── THEME-API.md             ← 播放内核与主题的稳定接口契约
├── functions/               ← Cloudflare Pages Functions
│   ├── stream/[file].js     ← 静态 Range 流入口
│   └── watch/[[path]].js    ← 多级路径的网页/媒体响应
├── range_stream.js         ← 两个入口共用的分块 Range 读取实现
├── static/                  ← 前端静态文件
│   ├── player/              ← 【绝对不动产】内核，换主题也不动
│   │   ├── hls.js           ← 第三方解码库
│   │   ├── artplayer/       ← 可选 ArtPlayer 播放器（含 UPSTREAM.txt 记录版本/许可）
│   │   └── core.js          ← MediaPages 播放内核 + 数据获取（fetch index.json）
│   └── theme/
│       ├── default/         ← 【完全可变皮囊】默认 auto，可通过 [player].engine 切换
│       ├── bg-theme/        ← Tailwind 皮肤，已迁移到新内核接口
│       └── artplayer/       ← ArtPlayer + ASS 优先（libass）参考主题
└── README.md
```

**架构哲学**：只有两个核心概念。

- **`player/`（不动产）** — 控制视频/音频/图片播放、hls.js 生命周期、字幕注入、index.json 数据获取。任何主题都不能改动这里。
- **`theme/`（皮囊）** — 完整的主题包，包含样式（style.css）和全部 UI 行为 JS（theme.js）。换主题就是整个目录替换。

**切换主题**：复制 `theme/default/` → `theme/新主题/`，修改 style.css 和 theme.js，再更新 `index.html` 引用路径即可。`player/` 完全不需要动。

## 配置文件 config.ini

`config.ini` 集中管理所有参数，详细注释见 `config.example.ini`。关键配置项：

```ini
[video]
mode = copy    ; copy = 原画流复制 | encode = H.264 重编码
size_priority_mode = false  ; true=切片大小优先（目标切片大小由 video.size_priority_target 决定）

[auth]
enabled = false  ; 启用密码鉴权
password =       ; 密码（SHA256 前端校验，仅供参考）

[cloudflare]
api_token =
account_id =
upload_threshold_mb = 512
```

完整配置说明见 `config.example.ini`。

## 切片大小优先模式

默认 HLS 切片按固定时长（`hls_time=6` 秒）切割，每个 `.ts` 文件大小取决于视频码率。码率低的视频会产生很小的切片，上传到 Cloudflare Pages 时数量多、效率低。

启用 `size_priority_mode = true` 后，程序会**自动计算切片时长**，使每个切片大小尽可能接近目标值（由 `size_priority_target` 控制），从而减少切片数量：

| 视频模式 | 计算方法 |
|---------|---------|
| `mode=copy`（复制） | ffprobe 探测源文件码率 → `hls_time = target_size / (bitrate/8)` |
| `mode=encode`（编码） | 直接用配置中的 `bitrate`（如 `18M`）计算 |

配置示例：

```ini
[video]
mode = copy
size_priority_mode = true
size_priority_target = 24641536   ; 目标切片大小 23.5MB，默认与 [audio].safe_target_bytes 相同
```

目标大小不要超过 `[media].max_file_size`（25MB），否则部署到 Cloudflare Pages 时会超限。

## HLS 切片容器：mpegts 与 fmp4

```ini
[video]
mode = copy                  ; 流复制，不重新编码
hls_segment_type = fmp4      ; mpegts（默认） | fmp4

; ── fMP4 相关（hls_segment_type = fmp4 时生效）──
fmp4_segment_pattern = segment_%05d.m4s
fmp4_init_filename = init.mp4
write_master_playlist = true ; 生成带 CODECS 的 master.m3u8
hevc_repartition = true      ; 高码率 HEVC 按 moof/mdat 边界重排切片
hevc_fragment_bytes = 18874368
; max_segment_bytes = 25165824   ; 默认沿用 [media].max_file_size
fail_on_oversize = false        ; true = 切片超限直接失败
```

- `mpegts` 兼容性最好，切片为 `.ts`。
- `fmp4` 使用 `.m4s` 媒体切片 + `init.mp4` 初始化片段，可承载 HEVC/AV1，并生成带 `CODECS` 的 `master.m3u8`，供 `MediaSource.isTypeSupported` 预判。
- 高码率 4K HEVC 的单个关键帧区间可能超过 25MB；`hevc_repartition = true` 时会在不改变码流字节的前提下按 `moof`/`mdat` 边界重新分配切片。

## 静态 Range 流（原样发布 MKV 等容器）

```ini
[video]
static_range_mode = true
static_range_extensions = .mkv          ; 逗号分隔，命中的后缀不再 HLS 切片
static_range_part_bytes = 25165824      ; 每块字节数，不得超过 [media].max_file_size
static_range_url_prefix = /stream
```

开启后，命中的文件会被拆成 `part_XXXXX.bin`，并写入 `stream/manifest.json`；`functions/stream/[file].js` 把分块拼回一个支持 `GET`/`HEAD`/`OPTIONS` + `Range`/`If-Range`/`ETag` 的规范 URL：

- 原始字节、内挂字幕、章节、音轨全部保留；网页另外读取提取出的 ASS/VTT 侧车。
- ID 结合源文件相对路径生成，同名版本或中文文件名不会互相覆盖；媒体目录层级也保留。
- `static_range_url_prefix` 可改为 `/media-stream/files` 等路径，manifest、函数目录与路由随之生成。
- 构建用 Functions 放在 `<workspace>/.pages/functions/`，源码不会进入公开的 dist。
- 入口为 `/stream/<id>`（不带扩展名），避免 CDN 对 `.mkv` 的默认缓存策略剥掉 `Range`。
- 分块、字幕与 manifest 走静态资源直出，仅 `/stream/*` 交给 Function（见 `main.py` 自动生成的 `_routes.json`）。
- 对完整文件的 Range（例如 `bytes=0-`）保留完整 `200` 响应，局部 Range 返回 `206`；这是旧版 MPV/FFmpeg 扫描 MKV Cues 时的兼容要求，请勿改成全文件 `206`。
- 这是 Cloudflare Pages 特化能力，其它部署平台需要另行适配。

## 字幕与内挂 ASS

```ini
[subtitle]
keep_ass = true      ; true = 额外保留 .ass 侧车，供 libass/SubtitlesOctopus 主题渲染
filter_keywords = jp, jpn, 日, romaji
```

- HLS 与静态 Range 两种路径都会处理字幕。
- 除同目录的侧车字幕外，程序还会用 ffprobe 列出容器内的字幕流并用 ffmpeg 抽取，
  因此内嵌 ASS 的 MKV（没有独立 `.ass` 文件）也能生成可播放的 VTT 轨道。
- 生成的 `index.json` 会带上 `subtitles`（VTT 轨道）与 `ass`（ASS 侧车，`keep_ass = true` 时）字段，
  主题可直接消费，详见 [THEME-API.md](THEME-API.md)。

## 播放器与主题

播放内核（`static/player/core.js`）会在主题存在 `#artplayer-container` 且 ArtPlayer 可用时启用 ArtPlayer，否则回退到原生 `<video>` + hls.js。HLS 在 MSE 支持 `item.codecs` 时交给 hls.js；浏览器原生支持 HLS 时可在致命错误后回退原生播放并保留进度。

主题与内核通过一组稳定接口耦合，详见 **[THEME-API.md](THEME-API.md)**。

ArtPlayer 负责界面与播放控制，视频解码能力仍由浏览器和操作系统决定。建议为收藏库保留 H264/AAC 版本；HEVC/AV1 使用 fMP4 也不代表所有设备都能播放。需要将 Opus 转为 AAC 时，可设 `audio_copy_codec = aac` 与 `audio_copy_bitrate = 192k`，视频仍保持流复制，HEVC 重分片路径也遵循此配置。静态 Range 保留 MKV 原容器，不能通过更换播放器界面消除浏览器的容器限制。

```ini
[site]
theme = artplayer
[subtitle]
keep_ass = true
[player]
engine = auto          ; auto | artplayer | native
autoplay_default = true
```

ArtPlayer 参考主题默认选择 ASS，原字幕的字体、字号、描边、阴影、位置、旋转与动画由 libass 渲染。VTT 可手动选择，ASS 组件加载失败时才自动回退。`static/player/ass.js` 提供可复用的渲染控制器，`static/theme/artplayer/ass-config.js` 提供通用空配置；可在本机的 `ass-config.local.js` 配置自有字体与缺失字体别名，该文件与字体目录已从 Git 跟踪范围排除。字体名称只在内存中替换，源 ASS 文件保留。正的字幕延迟表示晚显示，范围 ±2 秒，每条 ASS 轨道的延迟会本地保存。字幕选择和 ASS 延迟均位于播放器的设置面板中；纯 VTT 视频使用 ArtPlayer 自带的字幕延迟设置。换视频、关闭字幕或改选 VTT 会销毁旧画布并清理监听器。

主题可在自身目录提供 `_headers`，每次构建都会与 CORS 配置合并。参考主题包含 WASM MIME 与静态资源缓存头。主题接口、逐媒体字体覆盖和渲染参数见 THEME-API.md。

HLS 输出缓存包含源文件、关联字幕和配置签名；改变切片类型、字幕设置或编码参数后会重新生成该媒体。旧版本生成但没有签名的切片首次转换会重建；仅修改页面或渲染配置时可以使用 `--skip-convert` 复用已有切片。

## 独立模块

```bash
# 仅转换
python convert.py /输入目录 /输出目录

# 仅部署
python upload.py -t /dist目录 -c /tmp缓存目录 -p 项目名
```

## 许可证

AGPLv3。生成的静态媒体网站不受此协议限制。

## 播放器交互增强

ArtPlayer 参考主题的媒体库按钮和完整标题位于播放器顶栏。播放中闲置约 3 秒，顶栏与底部控件一起隐藏；鼠标移动或点击会重新显示。暂停、拖动进度、打开设置或媒体库时保留控件。媒体库可以用自身关闭按钮、顶栏按钮或 Esc 收回，选择条目后自动关闭，网页全屏中同样可用。音频、图片和原生播放器回退仍保留页面导航。

ASS／VTT／关闭字幕统一放在播放器设置里，ASS 延迟使用 ArtPlayer range 设置。渲染器和界面不依赖特定媒体 ID 或文件名，字幕标签与字体配置可由其他媒体库提供。`item.ass` 既接受轨道数组，也兼容单个 ASS URL；无字幕视频不会出现空的字幕设置。

## 媒体独立路径

每个媒体都有独立的页面地址，目录层级保留在 `/watch/` 后，例如 `/watch/电影/版本/视频.mp4`。音频和图片也使用相同规则。`index.json` 的 `path` 是页面地址，`src` 仍是实际视频、HLS 播放列表或静态 Range 地址，两者分开。

选片会更新浏览器地址，可以直接复制链接；直接访问、刷新和前进/后退会打开对应媒体。不同目录的同名视频保持不同路径；中文、空格、`#`、`%` 等会逐段编码。路径不存在时显示提示，不会误播默认视频。直接链接会加载媒体，自动播放仍受浏览器策略限制。

构建生成 `/watch/*` 的 Pages Function 路由，以及 `player/media-routes.json`。浏览器导航（`Accept: text/html`）收到网页；mpv 等媒体客户端、Range 请求或 `?raw=1` 收到媒体响应。静态 Range 媒体复用 `/stream/<id>` 的字节读取逻辑，MP4/WebM/HLS 则以 307 跳转到实际资源。响应设置 `Vary: Accept` 和 `no-store`，避免网页与媒体混用缓存。

入口使用 `<base href="/">`，保证脚本、字体、字幕和相对资源路径从根目录加载。`--skip-convert` 也会补齐旧索引的 `path` 并生成媒体路由，无需重新转码。需要使用 `main.py` 构建并从 `.pages` 部署 Functions；纯静态服务器的 SPA 重写只能打开网页，不能提供此媒体响应。重命名文件或移动目录后，对应页面地址会变化。

### 在 mpv 等外部播放器中打开

可以直接打开 `/watch/目录/版本`；为避免部分客户端声明接收 HTML，推荐明确使用 `/watch/目录/版本?raw=1`。原始 MKV 的内挂 ASS、音轨、章节和字体附件随虚拟文件原样保留，mpv 能识别它们。

ArtPlayer 底栏设置按钮左侧的分享图标会复制当前媒体的外部播放直链，优先使用媒体源地址：MKV 等虚拟分片资源是 `/stream/<id>`，MP4、WebM 和 HLS 是对应文件或播放列表地址。媒体没有源地址时，回退为带 `?raw=1` 的 `/watch/...` 地址。

网页额外提供的 ASS **侧车文件**不会被自动封装进原始 MKV。如果原文件没有内挂字幕，外部播放器需要另行加载侧车，例如 `mpv "媒体URL?raw=1" --sub-file="ASS侧车URL"`；网页仍由 libass 加载侧车。

```powershell
mpv "https://your-site.example/watch/电影/版本/视频.mkv?raw=1"
```
