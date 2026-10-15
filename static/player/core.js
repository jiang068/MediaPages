/**
 * core.js — MediaPages playback core.
 *
 * The core is deliberately engine-agnostic:
 *   - native <video>/<audio>/<img> elements remain the compatibility baseline
 *   - ArtPlayer is used when a theme provides a player container and the
 *     ArtPlayer bundle is available
 *   - hls.js is used for HLS when MSE advertises support for the stream codecs
 *
 * Theme API (stable):
 *   window.MediaPages.on(event, handler)
 *   window.MediaPages.off(event, handler)
 *   window.MediaPages.player.play(item)
 *   window.MediaPages.player.stop()
 *   window.MediaPages.config
 *
 * Legacy API kept for existing themes:
 *   window.__player, window.__mediaData, window.updatePlayer
 */
(function (global) {
  'use strict';

  const DEFAULT_CONFIG = {
    indexUrl: './index.json',
    autoplayDefault: true,
    player: {
      engine: 'auto',              // auto | artplayer | native
      containerId: 'artplayer-container',
      videoId: 'video-viewer',
      theme: '#f18b48',
      lang: 'zh-cn'
    },
    hls: {
      maxBufferLength: 30,
      maxMaxBufferLength: 60,
      preferManagedMediaSource: true
    },
    features: {
      artplayer: true
    }
  };

  function isObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function merge(target, source) {
    const out = Object.assign({}, target);
    if (!isObject(source)) return out;
    Object.keys(source).forEach(function (key) {
      const value = source[key];
      out[key] = isObject(value) && isObject(target[key]) ? merge(target[key], value) : value;
    });
    return out;
  }

  const CONFIG = merge(DEFAULT_CONFIG, global.MEDIAPAGES_CONFIG || {});

  function emit(name, detail) {
    try {
      global.dispatchEvent(new CustomEvent('mediapages:' + name, { detail: detail }));
    } catch (_error) {
      // CustomEvent is unavailable only in very old browsers; the legacy
      // callback below still keeps themes working there.
    }
    const callbacks = listeners[name];
    if (callbacks) {
      callbacks.slice().forEach(function (callback) {
        try { callback(detail); } catch (error) { console.error('MediaPages listener failed:', error); }
      });
    }
  }

  const listeners = Object.create(null);

  function on(name, callback) {
    if (typeof callback !== 'function') return function () {};
    (listeners[name] || (listeners[name] = [])).push(callback);
    return function () { off(name, callback); };
  }

  function off(name, callback) {
    const callbacks = listeners[name];
    if (!callbacks) return;
    const index = callbacks.indexOf(callback);
    if (index >= 0) callbacks.splice(index, 1);
  }

  function mediaType(item) {
    if (!item || !item.src) return item && item.type ? item.type : 'unknown';
    if (item.playbackType) return item.playbackType;
    const clean = String(item.src).split('?')[0].split('#')[0].toLowerCase();
    if (clean.endsWith('.m3u8')) return 'hls';
    if (clean.endsWith('.mpd')) return 'dash';
    if (/\.(mp4|m4v|mov|webm|mkv|avi|wmv)$/.test(clean)) return 'video';
    return item.type || 'unknown';
  }

  function artplayerType(item) {
    const type = mediaType(item);
    if (type === 'hls') return 'm3u8';
    if (type === 'video') {
      const clean = String(item.src).split('?')[0].split('#')[0].toLowerCase();
      if (clean.endsWith('.mkv')) return 'mkv';
      if (clean.endsWith('.webm')) return 'webm';
      if (clean.endsWith('.mov')) return 'mov';
      return 'mp4';
    }
    return type;
  }

  function isHlsSource(item) {
    return mediaType(item) === 'hls' || /\.m3u8(\?|#|$)/i.test(String(item && item.src || ''));
  }

  function mseSupports(item) {
    if (!item || !item.codecs) return true; // let hls.js probe when metadata is absent
    const mse = global.ManagedMediaSource || global.MediaSource;
    if (!mse || typeof mse.isTypeSupported !== 'function') return true;
    return mse.isTypeSupported('video/mp4; codecs="' + item.codecs + '"');
  }

  function canUseHls(item) {
    return Boolean(global.Hls && global.Hls.isSupported && global.Hls.isSupported() && isHlsSource(item) && mseSupports(item));
  }

  function nativeHlsSupported(video) {
    return Boolean(video && video.canPlayType && video.canPlayType('application/vnd.apple.mpegurl'));
  }

  function attachHls(video, item, options) {
    options = options || {};
    let hls = null;
    let destroyed = false;
    let fallbackMetadata = null;
    const onError = options.onError || function () {};
    const onReady = options.onReady || function () {};
    const start = function () {
      if (options.autoplay === false) return;
      const playResult = options.play ? options.play() : video.play();
      if (playResult && typeof playResult.catch === 'function') playResult.catch(function () {});
    };

    if (!canUseHls(item)) return { destroy: function () {}, fallback: false };

    try {
      hls = new global.Hls({
        maxBufferLength: CONFIG.hls.maxBufferLength,
        maxMaxBufferLength: CONFIG.hls.maxMaxBufferLength,
        preferManagedMediaSource: CONFIG.hls.preferManagedMediaSource
      });
      hls.subtitleDisplay = false;
      hls.loadSource(item.src);
      hls.attachMedia(video);
      hls.on(global.Hls.Events.MANIFEST_PARSED, function () {
        if (destroyed) return;
        onReady();
        start();
      });
      hls.on(global.Hls.Events.ERROR, function (_event, data) {
        if (destroyed || !data || !data.fatal) return;
        if (nativeHlsSupported(video)) {
          const position = Number(video.currentTime) || 0;
          destroy();
          video.dataset.transport = 'native';
          video.src = item.src;
          if (position > 0) {
            fallbackMetadata = function () { video.currentTime = position; fallbackMetadata = null; };
            video.addEventListener('loadedmetadata', fallbackMetadata, { once: true });
          }
          nativePlay(video, options);
        } else {
          onError(data);
        }
      });
      return {
        destroy: destroy,
        fallback: false,
        get instance() { return hls; }
      };
    } catch (error) {
      destroy();
      onError(error);
      return { destroy: function () {}, fallback: true };
    }

    function destroy() {
      if (fallbackMetadata) { video.removeEventListener('loadedmetadata', fallbackMetadata); fallbackMetadata = null; }
      if (destroyed) return;
      destroyed = true;
      if (hls) {
        try { hls.destroy(); } catch (_error) {}
        hls = null;
      }
    }
  }

  function nativePlay(video, options) {
    options = options || {};
    video.dataset.transport = 'native';
    if (options.src) {
      video.src = options.src;
      if (typeof video.load === 'function') video.load();
    }
    if (options.autoplay === false) return;
    const result = options.play ? options.play() : video.play();
    if (result && typeof result.catch === 'function') result.catch(function () {});
  }

  function setHidden(element, hidden) {
    if (element) element.hidden = Boolean(hidden);
  }

  function normalizeTracks(value) {
    const list = Array.isArray(value) ? value : value ? [value] : [];
    return list.map(function (track) { return typeof track === 'string' ? { src: track, label: '字幕' } : track; })
      .filter(function (track) { return track && typeof track.src === 'string' && track.src; });
  }

  function installControlsVisibility(art, delay) {
    const host = art.template && art.template.$player;
    if (!host || !art.controls || !art.on) return null;
    const pins = new Set();
    const cleanups = [];
    let timer = null, dragging = false, disposed = false;
    const timeout = Math.max(500, Number(delay) || 3000);
    const clear = function () { clearTimeout(timer); timer = null; };
    const visible = function () { host.classList.remove('mp-controls-idle'); art.controls.show = true; };
    const schedule = function () {
      clear();
      if (disposed || art.video.paused || art.video.ended) return;
      timer = setTimeout(function () {
        if (disposed) return;
        // A stationary cursor over the bottom bar must not pin the controls.
        const input = document.activeElement;
        const editing = input && host.contains(input) && /^(INPUT|SELECT|TEXTAREA)$/.test(input.tagName) && input.getClientRects().length;
        if (dragging || pins.size || (art.setting && art.setting.show) || editing) { schedule(); return; }
        art.controls.show = false;
        host.classList.add('mp-controls-idle');
      }, timeout);
    };
    const activity = function () { visible(); schedule(); };
    const listen = function (target, event, fn) {
      target.addEventListener(event, fn);
      cleanups.push(function () { target.removeEventListener(event, fn); });
    };
    listen(host, 'pointermove', activity);
    listen(host, 'click', activity);
    listen(host, 'keydown', activity);
    listen(host, 'pointerdown', function () { dragging = true; activity(); });
    listen(document, 'pointerup', function () { if (dragging) { dragging = false; schedule(); } });
    listen(document, 'pointercancel', function () { dragging = false; schedule(); });
    listen(art.video, 'playing', activity);
    listen(art.video, 'pause', function () { clear(); visible(); });
    listen(art.video, 'ended', function () { clear(); visible(); });
    art.on('setting', activity);
    art.on('control', function (show) {
      if (disposed) return;
      if (show) host.classList.remove('mp-controls-idle');
      // ArtPlayer's own timeupdate timer also hides controls; respect open panels.
      else if (pins.size || dragging || (art.setting && art.setting.show)) visible();
    });
    schedule();
    return {
      pin: function (key, value) { value ? pins.add(key) : pins.delete(key); activity(); },
      dispose: function () { disposed = true; clear(); cleanups.forEach(function (cleanup) { cleanup(); }); }
    };
  }

  class NativeVideoEngine {
    constructor(player) {
      this.player = player;
      this.video = document.getElementById(CONFIG.player.videoId);
      if (!this.video) {
        this.video = document.createElement('video');
        this.video.id = CONFIG.player.videoId;
        this.video.className = 'media-viewer';
        this.video.controls = true;
        this.video.playsInline = true;
        const parent = document.querySelector('.main-content') || document.body;
        parent.appendChild(this.video);
      }
      this.video.controls = true;
      this.video.playsInline = true;
    }

    play(item) {
      const video = this.video;
      this.player._watchErrors(video, item);
      const autoplay = item.autoplay !== false;
      video.style.display = 'block';
      video.hidden = false;
      video.dataset.transport = 'native';
      video.querySelectorAll('track').forEach(function (track) { track.remove(); });
      this._addTextTracks(normalizeTracks(item.subtitles));
      this.player._destroyHls();

      if (isHlsSource(item) && canUseHls(item)) {
        video.dataset.transport = 'mse';
        const controller = attachHls(video, item, {
          autoplay: autoplay,
          onError: function (error) { emit('error', { item: item, error: error }); }
        });
        this.player._setHls(controller);
      } else {
        nativePlay(video, { autoplay: autoplay, src: item.src });
      }
    }

    _addTextTracks(subtitles) {
      if (!Array.isArray(subtitles) || !subtitles.length) return;
      const video = this.video;
      subtitles.forEach(function (sub) {
        const track = document.createElement('track');
        track.kind = 'subtitles';
        track.label = sub.label || '';
        track.srclang = sub.srclang || 'und';
        track.src = sub.src;
        video.appendChild(track);
        if (sub.default) {
          track.default = true;
          if (track.track) track.track.mode = 'showing';
        }
      });
    }

    stop() {
      if (this.video) this.video.pause();
    }

    destroy() {
      this.stop();
      if (this.video) {
        this.video.removeAttribute('src');
        this.video.load();
      }
    }
  }

  class ArtPlayerEngine {
    constructor(player) {
      this.player = player;
      this.container = document.getElementById(CONFIG.player.containerId);
      this.art = null;
    }

    static isSupported() {
      return Boolean(CONFIG.features.artplayer && document.getElementById(CONFIG.player.containerId));
    }

    loadBundle() {
      if (global.Artplayer) return Promise.resolve(global.Artplayer);
      if (this._bundlePromise) return this._bundlePromise;
      this._bundlePromise = new Promise(function (resolve, reject) {
        const script = document.createElement('script');
        script.src = './player/artplayer/artplayer.js';
        script.onload = function () { global.Artplayer ? resolve(global.Artplayer) : reject(new Error('ArtPlayer bundle did not expose window.Artplayer')); };
        script.onerror = function () { reject(new Error('ArtPlayer bundle failed to load')); };
        document.head.appendChild(script);
      }).catch(function (error) {
        this._bundlePromise = null;
        throw error;
      }.bind(this));
      return this._bundlePromise;
    }

    async play(item) {
      if (!this.container) throw new Error('ArtPlayer container is missing');
      await this.loadBundle();
      if (this.player.engine !== this || this.player.currentItem !== item) return;
      const player = this.player;
      const autoplay = item.autoplay !== false;
      const self = this;
      this.container.hidden = false;
      this.container.style.display = 'block';
      if (this.art) {
        try { this.art.destroy(); } catch (_error) {}
        this.art = null;
      }
      player._destroyHls();

      const subtitles = normalizeTracks(item.subtitles);
      const defaultIndex = Math.max(0, subtitles.findIndex(function (sub) { return sub.default; }));
      const defaultSubtitle = subtitles[defaultIndex];
      const settings = Array.isArray(item.settings) ? item.settings.slice() : [];
      if (subtitles.length) settings.push({
        name: 'mediapages-subtitles', html: '字幕', tooltip: defaultSubtitle.label || '字幕',
        selector: [{ html: '关闭', index: -1 }].concat(subtitles.map(function (sub, index) {
          return { html: sub.label || ('字幕 ' + (index + 1)), index: index, default: index === defaultIndex };
        })),
        onSelect: function (choice) { player.setSubtitle(choice.index); return choice.html; }
      });
      const customType = {};
      function custom(video, url, art) {
        player._attachMedia(video, url, art, item, autoplay);
      }
      ['m3u8', 'mp4', 'mkv', 'webm', 'mov'].forEach(function (type) { customType[type] = custom; });

      const options = {
        container: this.container,
        url: item.src,
        type: artplayerType(item),
        poster: item.poster || '',
        autoplay: false,
        autoSize: false,
        autoPlayback: false,
        mutex: false,
        backdrop: false,
        playbackRate: false,
        aspectRatio: false,
        screenshot: false,
        pip: false,
        airplay: false,
        fullscreen: true,
        fullscreenWeb: true,
        hotkey: true,
        lang: CONFIG.player.lang,
        theme: item.theme || CONFIG.player.theme,
        settings: settings,
        setting: settings.length > 0,
        subtitle: { url: defaultSubtitle ? defaultSubtitle.src : '', type: 'vtt',
                    name: defaultSubtitle ? defaultSubtitle.label || '字幕' : '' },
        moreVideoAttr: {
          controls: false,
          preload: 'auto',
          playsInline: true,
          'webkit-playsinline': true
        },
        customType: customType
      };
      emit('playeroptions', { item: item, player: player, options: options });
      this.art = new global.Artplayer(options);
      this.controlsVisibility = installControlsVisibility(this.art, CONFIG.player.controlHideDelay);
      player.video = this.art.video;
      player._watchErrors(this.art.video, item);
      return this.art;
    }

    selectSubtitle(index) {
      const art = this.art;
      const tracks = normalizeTracks(this.player.currentItem && this.player.currentItem.subtitles);
      if (!art || !art.subtitle) return;
      const track = tracks[index];
      art.subtitle.show = Boolean(track);
      if (track) {
        const result = art.subtitle.switch(track.src, { type: 'vtt', name: track.label || '字幕' });
        if (result && result.catch) result.catch(function (error) {
          if (!art.isDestroy) emit('subtitleerror', { error: error });
        });
      }
    }

    stop() {
      if (this.art) {
        try { this.art.pause(); } catch (_error) {}
      }
    }

    destroy() {
      if (this.controlsVisibility) { this.controlsVisibility.dispose(); this.controlsVisibility = null; }
      if (this.art) {
        try { this.art.destroy(); } catch (_error) {}
        this.art = null;
      }
    }
  }

  class MediaPlayer {
    constructor(options) {
      this.options = options || {};
      this.hls = null;
      this.engine = null;
      this.engineName = null;
      this.video = null;
      this.audio = document.getElementById('audio-viewer');
      this.image = document.getElementById('image-viewer');
      this.placeholder = document.getElementById('placeholder');
      this._currentItem = null;
      this._playSequence = 0;
    }

    get _hls() { return this.hls; }
    get currentItem() { return this._currentItem; }
    get art() { return this.engine && this.engine.art || null; }

    _setHls(controller) {
      this.hls = controller || null;
      if (controller && controller.instance) {
        this._hlsInstance = controller.instance;
      }
    }

    _destroyHls() {
      if (this.hls) {
        try { this.hls.destroy(); } catch (_error) {}
        this.hls = null;
      }
      this._hlsInstance = null;
    }

    _hideAll() {
      const container = document.getElementById(CONFIG.player.containerId);
      const video = document.getElementById(CONFIG.player.videoId);
      [container, video, this.audio, this.image, this.placeholder].forEach(function (element) {
        if (!element) return;
        element.hidden = true;
        // Engines set an inline display on the active element; clearing it here
        // is required or the [hidden] attribute loses to the inline style.
        element.style.display = 'none';
      });
    }

    _pickEngine(item) {
      const requested = CONFIG.player.engine || 'auto';
      const artSupported = ArtPlayerEngine.isSupported();
      if (requested === 'artplayer') return artSupported ? 'artplayer' : 'native';
      if (requested === 'native') return 'native';
      return artSupported ? 'artplayer' : 'native';
    }

    async play(item, options) {
      this.stop();
      const sequence = this._playSequence;
      this._currentItem = item;
      syncMediaPath(item, options && options.history);
      emit('beforeplay', { item: item, player: this });
      this._hideAll();

      try {
        if (item.type === 'audio') {
          this._playAudio(item.src);
        } else if (item.type === 'image') {
          this._showImage(item.src);
        } else if (item.type === 'video') {
          const engineName = this._pickEngine(item);
          this.engineName = engineName;
          this.engine = engineName === 'artplayer' ? new ArtPlayerEngine(this) : new NativeVideoEngine(this);
          const engine = this.engine;
          await engine.play(item);
          if (sequence !== this._playSequence) return;
          this.video = this.engine.video || (this.engine.art && this.engine.art.video) || this.video;
          if (this.video) this.video.dataset.player = engineName;
        }
        emit('play', { item: item, player: this, engine: this.engineName });
      } catch (error) {
        if (sequence !== this._playSequence) return;
        console.error('MediaPages playback failed:', error);
        emit('error', { item: item, error: error });
        if (this.engineName !== 'native') {
          this._destroyHls();
          if (this.engine) this.engine.destroy();
          this._hideAll();
          this.engine = new NativeVideoEngine(this);
          this.engineName = 'native';
          try {
            await this.engine.play(item);
            this.video = this.engine.video;
            emit('play', { item: item, player: this, engine: 'native' });
          } catch (fallbackError) {
            emit('error', { item: item, error: fallbackError });
          }
        }
      }

      if (global.updatePlayer) global.updatePlayer(item);
    }

    _attachMedia(video, url, art, item, autoplay) {
      this.video = video;
      video.dataset.transport = 'native';
      if (isHlsSource(item) && canUseHls(item)) {
        video.dataset.transport = 'mse';
        const controller = attachHls(video, item, {
          autoplay: autoplay,
          play: function () { return art.play(); },
          onError: function (error) { emit('error', { item: item, error: error }); }
        });
        this._setHls(controller);
      } else {
        video.src = url;
        nativePlay(video, { autoplay: autoplay, play: function () { return art.play(); } });
      }
    }

    stop() {
      this._playSequence += 1;
      emit('stop', { item: this._currentItem, player: this });
      if (this._videoErrorCleanup) { this._videoErrorCleanup(); this._videoErrorCleanup = null; }
      this._destroyHls();
      if (this.engine) {
        try { this.engine.destroy(); } catch (_error) {}
      }
      this.engine = null;
      this.engineName = null;
      if (this.audio) this.audio.pause();
      this.video = null;
    }

    setControlsPinned(key, pinned) {
      const control = this.engine && this.engine.controlsVisibility;
      if (control) control.pin(key, pinned);
    }

    _watchErrors(video, item) {
      if (this._videoErrorCleanup) this._videoErrorCleanup();
      const handler = function () {
        if (this.video === video && this.currentItem === item) {
          emit('error', { item: item, error: video.error || new Error('Video playback failed') });
        }
      }.bind(this);
      video.addEventListener('error', handler);
      this._videoErrorCleanup = function () { video.removeEventListener('error', handler); };
    }

    setSubtitle(index, options) {
      if (this.engine && this.engine.selectSubtitle) {
        this.engine.selectSubtitle(index);
      } else if (this.video && this.video.textTracks) {
        Array.from(this.video.textTracks).forEach(function (track, i) {
          track.mode = i === index ? 'showing' : 'disabled';
        });
      }
      if (!options || !options.silent) emit('subtitlechange', { index: index, item: this.currentItem });
    }

    _playAudio(src) {
      if (!this.audio) return;
      this.audio.hidden = false;
      this.audio.style.display = 'block';
      this.audio.src = src;
      const result = this.audio.play();
      if (result && result.catch) result.catch(function () {});
    }

    _showImage(src) {
      if (!this.image) return;
      this.image.hidden = false;
      this.image.style.display = 'block';
      this.image.src = src;
    }
  }

  function findDefaultMedia(items) {
    for (let i = 0; i < (items || []).length; i += 1) {
      const item = items[i];
      if (item.type === 'folder' && item.children) {
        const found = findDefaultMedia(item.children);
        if (found) return found;
      } else if (item.isDefault === true) {
        return item;
      }
    }
    return null;
  }

  const mediaRoutes = new Map();
  const encodeSegment = value => encodeURIComponent(value).replace(/[!'()*]/g, char => '%' + char.charCodeAt(0).toString(16).toUpperCase());

  function canonicalMediaPath(path) {
    try {
      const parts = String(path).split('/');
      if (parts[0] !== '' || parts[1] !== 'watch') return null;
      while (parts.length > 2 && parts[parts.length - 1] === '') parts.pop();
      if (parts.length < 3 || parts.slice(2).some(part => !part)) return null;
      return '/watch/' + parts.slice(2).map(part => encodeSegment(decodeURIComponent(part))).join('/');
    } catch (_error) { return null; }
  }

  function indexMediaPaths(data) {
    mediaRoutes.clear();
    const walk = function (items, parents) {
      (items || []).forEach(function (item) {
        const name = String(item.name || '媒体');
        if (item.type === 'folder') walk(item.children, parents.concat(name));
        else if (['video', 'audio', 'image'].includes(item.type)) {
          const segments = parents.concat(name);
          const base = '/watch/' + segments.map(segment => encodeSegment(segment === '.' || segment === '..' ? '_' + segment : segment)).join('/');
          let path = base, suffix = 2;
          while (mediaRoutes.has(path)) path = base + '~' + suffix++;
          item.path = path;
          item.displayTitle = segments.join(' / ');
          mediaRoutes.set(path, item);
        }
      });
    };
    walk(data, []);
    return mediaRoutes;
  }

  function syncMediaPath(item, mode) {
    if (mode === 'none' || !item || !item.path || !global.history || !global.location) return;
    if (global.location.pathname === item.path) return;
    const method = mode === 'replace' ? 'replaceState' : 'pushState';
    global.history[method]({ mediaPath: item.path }, '', item.path);
    emit('routechange', { path: item.path, item: item, found: true });
  }

  async function openLocation(player, data, initial) {
    if (!global.location) {
      const fallback = CONFIG.autoplayDefault && findDefaultMedia(data);
      if (fallback) await player.play(fallback, { history: 'none' });
      return;
    }
    const pathname = global.location.pathname;
    const home = pathname === '/' || pathname === '/index.html';
    const path = canonicalMediaPath(pathname);
    const item = home ? (CONFIG.autoplayDefault && findDefaultMedia(data)) : mediaRoutes.get(path);
    if (item) {
      await player.play(item, { history: home && initial ? 'replace' : 'none' });
      if (!home && pathname !== item.path && global.history) global.history.replaceState({ mediaPath: item.path }, '', item.path + (global.location.search || '') + (global.location.hash || ''));
    } else {
      player.stop();
      player._currentItem = null;
      player._hideAll();
      if (player.placeholder) {
        player.placeholder.hidden = false;
        player.placeholder.style.display = 'block';
        player.placeholder.textContent = home ? '请在媒体库中选择文件进行预览' : '未找到此路径对应的媒体，请打开媒体库重新选择';
      }
    }
    emit('routechange', { path: pathname, item: item || null, found: home || Boolean(item) });
  }

  const MediaPages = {
    version: '2.0.0-dev',
    normalizeTracks: normalizeTracks,
    installControlsVisibility: installControlsVisibility,
    indexMediaPaths: indexMediaPaths,
    canonicalMediaPath: canonicalMediaPath,
    config: CONFIG,
    on: on,
    off: off,
    emit: emit,
    findDefaultMedia: findDefaultMedia
  };

  global.MediaPages = MediaPages;

  (async function init() {
    try {
      const response = await fetch(CONFIG.indexUrl);
      if (!response.ok) throw new Error('index.json returned HTTP ' + response.status);
      const data = await response.json();
      indexMediaPaths(data);
      global.__mediaData = data;
      const player = new MediaPlayer();
      MediaPages.player = player;
      global.__player = player;
      await openLocation(player, data, true);
      if (global.addEventListener) global.addEventListener('popstate', function () {
        openLocation(player, data, false).catch(error => emit('error', { error: error }));
      });
      if (global.__onCoreReady) global.__onCoreReady();
      emit('ready', { data: data, player: player });
    } catch (error) {
      console.error('core.js init failed:', error);
      emit('error', { error: error });
    }
  })();
})(typeof window !== 'undefined' ? window : this);
