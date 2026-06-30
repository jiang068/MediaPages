/**
 * core.js — 【绝对不动产】播放核心
 * 职责：
 *   1. 定义 MediaPlayer 类（播放控制、hls.js 生命周期、字幕）
 *   2. 获取 index.json，自动播放默认片
 *   3. 对外暴露 window.__player、window.__mediaData
 * 不依赖任何 UI/主题代码
 */
class MediaPlayer {
  constructor() {
    this.hls = null;
    this.video = document.getElementById('video-viewer');
    this.audio = document.getElementById('audio-viewer');
    this.image = document.getElementById('image-viewer');
    this.placeholder = document.getElementById('placeholder');
  }

  play(item) {
    this._currentItem = item; // 保存当前播放项供主题同步
    const { type, src, subtitles } = item;
    this._hideAll();

    if (type === 'video') {
      this._playVideo(src, subtitles);
    } else if (type === 'audio') {
      this._playAudio(src);
    } else if (type === 'image') {
      this._showImage(src);
    }

    // 通知主题更新 UI
    if (window.updatePlayer) window.updatePlayer(item);
  }

  stop() {
    this.video.pause();
    this.audio.pause();
    if (this.hls) { this.hls.destroy(); this.hls = null; }
  }

  _hideAll() {
    this.placeholder.style.display = 'none';
    this.video.style.display = 'none';
    this.audio.style.display = 'none';
    this.image.style.display = 'none';
  }

  _playVideo(src, subtitles) {
    this.video.style.display = 'block';
    this.video.querySelectorAll('track').forEach(t => t.remove());

    if (subtitles && subtitles.length) {
      subtitles.forEach(sub => {
        const track = document.createElement('track');
        track.kind = 'subtitles';
        track.label = sub.label;
        track.srclang = sub.srclang;
        track.src = sub.src;
        this.video.appendChild(track);
        if (sub.default) track.track.mode = 'showing';
      });
    }

    this._loadVideo(src);
  }

  _loadVideo(src) {
    if (Hls.isSupported() && src.endsWith('.m3u8')) {
      this.hls = new Hls({ maxBufferLength: 30, maxMaxBufferLength: 60 });
      this.hls.loadSource(src);
      this.hls.attachMedia(this.video);
      this.hls.on(Hls.Events.MANIFEST_PARSED, () => {
        this.video.play().catch(e => console.log(e));
      });
    } else {
      this.video.src = src;
      this.video.play().catch(e => console.log(e));
    }
  }

  _playAudio(src) {
    this.audio.style.display = 'block';
    this.audio.src = src;
    this.audio.play().catch(e => console.log(e));
  }

  _showImage(src) {
    this.image.style.display = 'block';
    this.image.src = src;
  }
}

function _findDefaultMedia(items) {
  for (const item of items) {
    if (item.type === 'folder' && item.children) {
      const found = _findDefaultMedia(item.children);
      if (found) return found;
    } else if (item.isDefault === true) {
      return item;
    }
  }
  return null;
}

(async function () {
  try {
    const resp = await fetch('./index.json');
    const data = await resp.json();

    window.__mediaData = data;
    window.__player = new MediaPlayer();

    const defaultItem = _findDefaultMedia(data);
    if (defaultItem) {
      window.__player.play(defaultItem);
    }

    if (window.__onCoreReady) window.__onCoreReady();
  } catch (error) {
    console.error('core.js init failed:', error);
  }
})();