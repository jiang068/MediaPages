# SubtitlesOctopus 4.1.0

Unmodified browser assets from the official binary release:

- Project: https://github.com/libass/JavascriptSubtitlesOctopus
- Release: https://github.com/libass/JavascriptSubtitlesOctopus/releases/tag/4.1.0
- Binary package: https://github.com/libass/JavascriptSubtitlesOctopus/releases/download/4.1.0/libass-wasm-4.1.0.tgz
- Source: https://github.com/libass/JavascriptSubtitlesOctopus/tree/4.1.0
- Source archive: https://github.com/libass/JavascriptSubtitlesOctopus/archive/refs/tags/4.1.0.tar.gz
- API documentation: https://github.com/libass/JavascriptSubtitlesOctopus/blob/4.1.0/README.md

Downloaded 2026-10-13. LICENSE and COPYRIGHT are copied verbatim from the release. COPYRIGHT contains the bundled dependencies' copyright and license notices, including libass LGPL-2.1-or-later; retain both files when redistributing. No renderer assets have been rebuilt or modified.

## Files

| File | Bytes | Purpose |
| --- | ---: | --- |
| subtitles-octopus.js | 76,658 | Classic script; defines window.SubtitlesOctopus |
| subtitles-octopus-worker.js | 399,686 | WebAssembly worker |
| subtitles-octopus-worker.wasm | 2,305,844 | libass rendering binary; keep beside worker |
| subtitles-octopus-worker-legacy.js | 4,847,128 | Optional asm.js fallback, automatically selected only if WebAssembly is unavailable |

The normal WASM path does not load the legacy worker. This repository does not bundle font files; deployments that need specific glyph coverage should supply fonts they are authorized to use through the theme's local font configuration. Use application/wasm for the WASM asset and JavaScript MIME types for scripts/workers. These assets require a same-origin Web Worker, not cross-origin isolation or a build system.

## Integration

Load this file as a classic script (on demand is appropriate):

```html
<script src="./vendor/ass/subtitles-octopus.js"></script>
```

Use absolute URLs derived from the page URL so worker-relative font/subtitle fetches resolve correctly:

```js
const asset = path => new URL(path, document.baseURI).href;
const font = asset('./fonts/your-authorized-font.otf'); // provide this file locally
const renderer = new window.SubtitlesOctopus({
  video: document.getElementById('video-viewer'),
  subUrl: asset('./subtitles/example.ass'), // replace with this version's ASS URL
  workerUrl: asset('./vendor/ass/subtitles-octopus-worker.js'),
  legacyWorkerUrl: asset('./vendor/ass/subtitles-octopus-worker-legacy.js'),
  fallbackFont: font,
  // Keys must be lowercase ASS font-family names. Add aliases only when
  // intentional font substitution is acceptable for that subtitle track.
  availableFonts: { 'noto sans cjk sc': font },
  renderMode: 'wasm-blend',
  targetFps: 24,
  maxRenderHeight: Math.min(2160, video.videoHeight || 1080),
  libassMemoryLimit: 32, // approximate bitmap-cache MiB limit, not total memory
  libassGlyphLimit: 16, // approximate glyph-cache MiB limit
  timeOffset: 0, // validate per-version HLS timestamp offset before changing
  onReady: () => {},
  onError: error => console.error('ASS renderer unavailable', error)
});

// Switching subtitle content on the same video instance:
renderer.setTrackByUrl(asset('./subtitles/another.ass'));
// Before switching films/versions or removing the video/canvas:
renderer.dispose();
```

Use fonts: [url1, url2] to preload actual font attachments when present. A fallback font can fill missing glyphs but does not reproduce another font's exact metrics. Do not duplicate the same font in fonts and availableFonts unless intended. This site rewrites only unavailable ASS font-family names in the in-memory subtitle text, then loads local font files whose internal family names match those replacements. The original ASS sidecar remains unchanged. ASS is drawn on a separate canvas and is not burned into video. Fullscreen the containing player element to keep the subtitle canvas visible; native video fullscreen/PiP can omit DOM canvas overlays.
