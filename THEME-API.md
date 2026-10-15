# MediaPages 主题接口（THEME-API）

播放内核（`static/player/core.js`）与主题（`static/theme/<name>/`）通过一组稳定接口耦合。
主题可以完全替换风格与页面结构，但不需要也不应该直接操作 hls.js 实例或 `video.src`。

## 加载顺序

主题页面按以下顺序引入脚本：

```html
<script src="./player/hls.js"></script>
<script src="./player/artplayer/artplayer.js"></script>   <!-- 使用 ArtPlayer 时可选 -->
<script src="./player/core.js"></script>
<script src="./player/ass.js"></script>             <!-- 需要 ASS 时 -->
<script src="./ass-config.js"></script>             <!-- 通用配置，可填写用户自有字体 -->
<script src="./theme.js"></script>
```

`core.js` 会读取同目录的 `index.json`，构建播放器，并暴露以下对象。

## 稳定 API

| 成员 | 说明 |
|------|------|
| `window.MediaPages.config` | 合并后的运行配置（可由页面在加载 `core.js` 之前设置 `window.MEDIAPAGES_CONFIG` 覆盖） |
| `window.MediaPages.player` | 当前 `MediaPlayer` 实例 |
| `window.MediaPages.on(event, handler)` | 订阅内核事件，返回取消订阅函数 |
| `window.MediaPages.off(event, handler)` | 取消订阅 |
| `window.MediaPages.findDefaultMedia(data)` | 递归查找 `isDefault` 条目 |
| `window.__player` | 旧主题兼容别名，等价于 `MediaPages.player` |
| `window.__mediaData` | 解析后的 `index.json` 数据 |
| `window.updatePlayer(item)` | 旧主题兼容回调，内核播放后调用 |

### 播放器实例

| 成员 | 说明 |
|------|------|
| `player.play(item)` | 播放一条媒体记录（video / audio / image） |
| `player.stop()` | 停止并销毁当前引擎 |
| `player.setSubtitle(index, options?)` | 选择 VTT 轨道（从 0 起）；-1 关闭。主题处理 ASS 时传 `{silent:true}` 避免触发自身切换监听 |
| `player.engineName` | `artplayer`、`native` 或 `null` |
| `player.video` | 当前 `<video>` 元素 |
| `player.currentItem` | 当前媒体记录（兼容别名 `player._currentItem`） |
| `player.hls` / `player._hls` | HLS 控制器包装；仅在需要读取状态时使用 |

内核会自动选择引擎：

1. 主题存在 `#artplayer-container` 且 `Artplayer` 可用时，使用 ArtPlayer。
2. 否则回退到 `#video-viewer` 原生 `<video>`。
3. HLS 在 MSE 支持 `item.codecs` 时交给 hls.js；浏览器原生支持 HLS 时可在致命错误后回退到原生播放。

可通过 `window.MEDIAPAGES_CONFIG` 强制引擎：

```html
<script>
  window.MEDIAPAGES_CONFIG = { player: { engine: 'artplayer' } }; // 或 'native'
</script>
```

## 事件

| 事件名 | 触发时机 | `detail` |
|--------|----------|----------|
| `stop` | 停止旧媒体，释放主题资源 | `{ item, player }` |
| `beforeplay` | 播放新媒体之前 | `{ item, player }` |
| `subtitlechange` | VTT 选择或关闭 | `{ index, item }` |
| `subtitleerror` | ArtPlayer VTT 切换失败 | `{ error }` |
| `ready` | `index.json` 加载完成、播放器创建后 | `{ data, player }` |
| `play` | 每次开始播放条目后 | `{ item, player, engine }` |
| `error` | 引擎加载/播放失败 | `{ item?, error }` |

同时会派发对应的 DOM `CustomEvent`：

```js
window.addEventListener('mediapages:play', event => {
  console.log(event.detail.item, event.detail.engine);
});
```

## 媒体记录扩展字段

除基础 `name` / `type` / `src` 外，主题可以使用以下字段：

| 字段 | 说明 |
|------|------|
| `master` | fMP4 的 `master.m3u8` 地址（自动生成） |
| `codecs` | RFC 6381 codec 字符串，供 `MediaSource.isTypeSupported` 使用 |
| `subtitles` | WebVTT 字幕轨道数组（`label` / `srclang` / `src` / `default`） |
| `ass` | ASS 侧车字幕数组（`label` / `src`），配合 libass 渲染 |
| `mime` | 原始容器 MIME（静态 Range 流使用） |
| `settings` | 传给 ArtPlayer 的设置面板项 |

## 主题侧注意事项

- **不要**再直接给 `#video-viewer` 赋 `src`；内核负责媒体加载，主题只控制显隐和 UI。
- 需要在自定义容器里播放时，保留 `id="artplayer-container"` 即可自动启用 ArtPlayer。
- 需要 libass 渲染 ASS 时，使用 `item.ass`，并把
  `subtitles-octopus.js` 与 worker 放到主题自己的 `vendor/` 下；字体由部署者自行提供，不要把未获再分发授权的字体提交到仓库。
- 旧主题若仍引用 `window.__player._hls` 或自行设置 `video.src`，应改为
  `window.MediaPages.player` 与事件订阅。

## 参考实现

- `static/theme/default/`：默认 auto，提供 ArtPlayer 容器，可配置为 native。
- `static/theme/bg-theme/`：Tailwind 皮肤，已迁移到新内核接口。
- `static/theme/artplayer/`：ArtPlayer + ASS 优先的参考主题（含可选本地字体配置与延迟控件）。


## 可复用 ASS 控制器

```js
const controller = new MediaPagesAss.Controller(window.MEDIAPAGES_ASS_CONFIG || {});
controller.setDelay(0.5); // 字幕晚显示 0.5 秒
await controller.load(player.video, item.ass[0], item, {
  onReady() { player.setSubtitle(-1, { silent: true }); },
  onError(error) { console.warn(error); player.setSubtitle(0, { silent: true }); }
});
// stop / 换媒体 / 改选 VTT 时调用：
controller.dispose();
```

配置支持 `availableFonts`（小写字体族名称 → 用户提供的文件 URL）、`fontAliases`（缺失字体名 → 真实字体族）、可选 `fallbackFont`、`fonts` 预加载数组、`targetFps`、`maxRenderHeight`、`libassMemoryLimit` 和 `libassGlyphLimit`。媒体的 `item.assConfig` 与轨道的 `track.config` 可以逐项覆盖主题配置。参考主题默认不附带字体；需要固定字形时，可在本机创建 `static/theme/artplayer/ass-config.local.js` 配置有权使用的字体。该文件及 `vendor/fonts/` 已被 Git 忽略。路径按 document.baseURI 解析，可用于子目录部署。字体别名处理保留竖排 `@`，并同时处理 Style 的 Fontname 字段与行内 `\fn`，其他 ASS 样式、对话、定位与特效保持原值。

控制器同步暂停、倍速、跳转与初始化后的当前时间，并监听尺寸变化；参考主题的 libass 画布位于 ArtPlayer 内，网页全屏可以保留字幕。设备原生视频全屏和 PiP 可能省略网页画布。

ASS 使用 libass canvas，VTT 使用 ArtPlayer 自带字幕层或原生 TextTrack。主题应在 ASS 启动前关闭 VTT，避免两层字幕同时显示。播放器加载完成事件不代表解码成功；真正的浏览器媒体错误会通过 `error` 事件上报。


## 播放器控件与主题扩展

`playeroptions` 事件在构造 ArtPlayer 前触发，参数为 `{item, player, options}`。主题可调整 `options.settings`，为 ASS 替换名为 `mediapages-subtitles` 的内核 VTT 菜单，避免重复入口；不要直接改第三方 ArtPlayer 文件。

`player.setControlsPinned(key, true/false)` 在媒体库等面板打开时保留控件，关闭后恢复闲置隐藏。`MediaPages.normalizeTracks(value)` 接受数组、单个 URL 或轨道对象并过滤无效条目。参考主题将顶栏与媒体库移动到播放器内部，因此全屏时保持可用；stop 时移回页面以支持音频、图片和原生回退。

播放中默认闲置 3000 ms 隐藏，暂停/结束时保留控件。可通过 `window.MEDIAPAGES_CONFIG.player.controlHideDelay` 修改闲置时长。

## 页面路径与导航

内核在加载目录时给媒体补充 `path`（如 `/watch/目录/视频.mp4`，各段编码）和 `displayTitle`（目录与媒体名）。构建阶段也将 `path` 写入索引。页面路径独立于 `src`，换用 HLS/Range 时不需要让主题根据传输地址查找视频。

`player.play(item)` 默认将媒体页面地址加入浏览器历史；同一地址不会重复添加。`player.play(item, {history: 'replace'})` 替换当前地址，`{history: 'none'}` 只切换媒体。直接链接和 `popstate` 由内核处理，所有主题自动获得对应媒体，无须自行实现路由。

`routechange` 的 detail 为 `{path, item, found}`。当路径不存在时 `item` 为 null、`found` 为 false；主页未选择媒体时 `item` 为 null、`found` 为 true。`beforeplay`/`play` 仍用于目录定位和标题更新。ArtPlayer 参考主题打开直接链接后，会将目录定位到媒体的父目录。

主题部署入口由构建注入 `<base href="/">`，相对脚本、ASS 字体和资源以站点根目录为基准。`/watch/*` 由 Pages Function 处理：浏览器 `Accept: text/html` 返回网页；媒体客户端、Range 或 `?raw=1` 返回虚拟流或跳转到静态媒体。媒体直链可用 `item.path + '?raw=1'`，无需依赖当前 `src` 的传输方式。

构建生成 `player/media-routes.json`，将 `path` 对应到媒体 `src` 和可选 `streamId`。虚拟 MKV 通过 `range_stream.js` 与 `/stream/<id>` 共用实现，避免复制两套分块逻辑；此模块位于 `.pages` 根目录，Function 源码不进入公开 dist。旧 `/watch/*` SPA 重写会被移除，其他主题重写保留。媒体客户端请求必须到达 Function，不能被改写为静态 HTML。
