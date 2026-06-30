# MediaPages

利用 Cloudflare Pages 搭建个人流媒体库的自动化工具套件。将大型视频自动 HLS 切片、字幕提取、图片/音频压缩，并一键部署到 Cloudflare Pages。

## 特性

- **自动转码切片** — 大于 25MB 的视频自动 HLS 切片（支持 CUDA 加速），小视频转标准 MP4
- **字幕提取** — ASS/SRT 自动转 VTT（Web 原生字幕），智能过滤日文等多余字幕
- **图音压缩兜底** — 超限图片/音频自动降质压缩，硬塞进 25MB 限制
- **hls.js 播放器** — 动态加载媒体树，支持移动端、字幕轨道切换、无限级嵌套目录
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
├── static/                  ← 前端静态文件
│   ├── player/              ← 【绝对不动产】内核，换主题也不动
│   │   ├── hls.js           ← 第三方解码库
│   │   └── core.js          ← MediaPlayer 类 + 数据获取（fetch index.json）
│   └── theme/
│       └── default/         ← 【完全可变皮囊】整个自包含主题包
│           ├── index.html   ← 纯骨架 DOM，引用 player/ 和 theme/
│           ├── favicon.png  ← 网站图标
│           ├── style.css    ← 全部样式
│           └── theme.js     ← 全部 JS 交互（侧边栏、UI 行为）
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

[auth]
enabled = false  ; 启用密码鉴权
password =       ; 密码（SHA256 前端校验，仅供参考）

[cloudflare]
api_token =
account_id =
upload_threshold_mb = 512
```

完整配置说明见 `config.example.ini`。

## 独立模块

```bash
# 仅转换
python convert.py /输入目录 /输出目录

# 仅部署
python upload.py -t /dist目录 -c /tmp缓存目录 -p 项目名
```

## 许可证

AGPLv3。生成的静态媒体网站不受此协议限制。