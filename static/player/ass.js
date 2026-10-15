/** Reusable libass controller. Theme configuration owns fonts and font aliases. */
(function (global) {
    'use strict';
    let libraryPromise;
    const absolute = path => new URL(path, document.baseURI).href;
    const defaults = {
        workerUrl: './vendor/ass/subtitles-octopus-worker.js',
        legacyWorkerUrl: './vendor/ass/subtitles-octopus-worker-legacy.js',
        scriptUrl: './vendor/ass/subtitles-octopus.js',
        fallbackFont: null,
        availableFonts: {}, fontAliases: {}, targetFps: 24,
        maxRenderHeight: 2160, libassMemoryLimit: 32, libassGlyphLimit: 16
    };

    function rewriteFonts(content, aliases) {
        const normalized = Object.fromEntries(Object.entries(aliases || {}).map(([key, value]) => [key.toLowerCase(), value]));
        const replaceName = name => {
            const trimmed = name.trim();
            const vertical = trimmed.startsWith('@');
            const key = (vertical ? trimmed.slice(1) : trimmed).trim().toLowerCase();
            return normalized[key] ? (vertical ? '@' : '') + normalized[key] : trimmed;
        };
        let inStyles = false, fontColumn = 1;
        const rewritten = content.split(/\r?\n/).map(line => {
            const section = /^\s*\[([^\]]+)\]\s*$/i.exec(line);
            if (section) { inStyles = /^v4\+? styles$/i.test(section[1]); return line; }
            if (!inStyles) return line;
            if (/^\s*format\s*:/i.test(line)) {
                fontColumn = line.slice(line.indexOf(':') + 1).split(',').findIndex(field => field.trim().toLowerCase() === 'fontname');
                return line;
            }
            if (!/^\s*style\s*:/i.test(line) || fontColumn < 0) return line;
            const colon = line.indexOf(':'), values = line.slice(colon + 1).split(',');
            if (values.length > fontColumn) values[fontColumn] = replaceName(values[fontColumn]);
            return line.slice(0, colon + 1) + values.join(',');
        }).join('\n');
        return rewritten.replace(/\\fn([^\\}]*)/gi, (_tag, name) => '\\fn' + replaceName(name));
    }

    async function library(config) {
        if (global.SubtitlesOctopus) return global.SubtitlesOctopus;
        if (!libraryPromise) libraryPromise = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = absolute(config.scriptUrl);
            script.onload = () => global.SubtitlesOctopus ? resolve(global.SubtitlesOctopus) : reject(new Error('SubtitlesOctopus missing'));
            script.onerror = () => reject(new Error('SubtitlesOctopus unavailable'));
            document.head.appendChild(script);
        }).catch(error => { libraryPromise = null; throw error; });
        return libraryPromise;
    }

    class Controller {
        constructor(config) {
            this.config = { ...defaults, ...config };
            this.generation = 0;
            this.renderer = null;
            this.video = null;
            this.cleanups = [];
            this.delay = 0;
        }

        async load(video, track, item, handlers) {
            this.dispose();
            const generation = this.generation;
            this.video = video;
            const config = { ...this.config, ...(item.assConfig || {}), ...(track.config || {}) };
            const valid = () => generation === this.generation && video.isConnected;
            const onError = error => { if (valid() && handlers.onError) handlers.onError(error); };
            try {
                const Octopus = await library(config);
                if (!valid()) return;
                const response = await fetch(absolute(track.src), { cache: 'force-cache' });
                if (!response.ok) throw new Error('ASS subtitle returned HTTP ' + response.status);
                const content = rewriteFonts(await response.text(), config.fontAliases);
                if (!valid()) return;
                // Eva waits for metadata before choosing a 1080p/4K render size.
                if (video.readyState < 1) {
                    await new Promise((resolve, reject) => {
                        const cleanup = () => {
                            clearTimeout(timer);
                            video.removeEventListener('loadedmetadata', ready);
                            video.removeEventListener('error', failed);
                        };
                        const ready = () => { cleanup(); resolve(); };
                        const failed = () => { cleanup(); reject(new Error('Video metadata unavailable for ASS')); };
                        const timer = setTimeout(failed, 15000);
                        video.addEventListener('loadedmetadata', ready, { once: true });
                        video.addEventListener('error', failed, { once: true });
                        this.cleanups.push(() => { cleanup(); resolve(); });
                    });
                    if (!valid()) return;
                }
                this.renderer = new Octopus({
                    video, subContent: content,
                    workerUrl: absolute(config.workerUrl), legacyWorkerUrl: absolute(config.legacyWorkerUrl),
                    ...(config.fallbackFont ? { fallbackFont: absolute(config.fallbackFont) } : {}),
                    availableFonts: Object.fromEntries(Object.entries(config.availableFonts).map(([family, path]) => [family.toLowerCase(), absolute(path)])),
                    fonts: (config.fonts || []).map(absolute),
                    timeOffset: -this.delay,
                    renderMode: 'wasm-blend', targetFps: config.targetFps,
                    maxRenderHeight: Math.min(config.maxRenderHeight, Math.max(720, video.videoHeight || 1080)),
                    libassMemoryLimit: config.libassMemoryLimit, libassGlyphLimit: config.libassGlyphLimit,
                    onReady: () => { if (valid()) { this.sync(); this.resize(); if (handlers.onReady) handlers.onReady(); } },
                    onError
                });
                const sync = () => this.sync();
                const resize = () => this.resize();
                for (const event of ['play', 'pause', 'seeking', 'seeked', 'ratechange', 'loadedmetadata']) {
                    video.addEventListener(event, sync);
                    this.cleanups.push(() => video.removeEventListener(event, sync));
                }
                for (const event of ['resize', 'fullscreenchange', 'webkitendfullscreen']) {
                    video.addEventListener(event, resize);
                    this.cleanups.push(() => video.removeEventListener(event, resize));
                }
                if (global.ResizeObserver) {
                    const observer = new global.ResizeObserver(resize);
                    observer.observe(video);
                    this.cleanups.push(() => observer.disconnect());
                }
                this.sync(); this.resize();
            } catch (error) { onError(error); }
        }

        setDelay(value) {
            this.delay = Math.max(-2, Math.min(2, Math.round(Number(value) * 10) / 10)) || 0;
            if (this.renderer) this.renderer.timeOffset = -this.delay;
            this.sync();
            return this.delay;
        }

        sync() {
            if (!this.renderer || !this.video) return;
            this.renderer.setIsPaused(this.video.paused, this.video.currentTime + this.renderer.timeOffset);
            this.renderer.setRate(this.video.playbackRate || 1);
        }

        resize() {
            const generation = this.generation;
            const run = () => { if (generation === this.generation && this.renderer) this.renderer.resize(); };
            run();
            for (const ms of [180, 650]) {
                const timer = setTimeout(run, ms);
                this.cleanups.push(() => clearTimeout(timer));
            }
        }

        dispose() {
            this.generation += 1;
            this.cleanups.splice(0).forEach(cleanup => cleanup());
            if (this.renderer) this.renderer.dispose();
            this.renderer = null;
            this.video = null;
        }
    }

    global.MediaPagesAss = { Controller, rewriteFonts };
})(window);
