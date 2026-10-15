/**
 * MediaPages ArtPlayer reference theme.
 *
 * Demonstrates the coupling contract:
 *   - reads media data from window.__mediaData
 *   - drives playback through window.MediaPages.player / window.__player
 *   - listens to core events instead of reaching into internals
 *   - optionally renders ASS sidecars with SubtitlesOctopus when the vendor
 *     assets are present (see THEME-API.md)
 */
(function () {
    'use strict';

    const $ = id => document.getElementById(id);
    const core = window.MediaPages || {};
    const player = () => (core.player || window.__player);
    const assController = window.MediaPagesAss ? new window.MediaPagesAss.Controller(window.MEDIAPAGES_ASS_CONFIG || {}) : null;
    let subtitleChoice = 'off';

    // ── Sidebar ──────────────────────────────────────────────────────────────
    class Sidebar {
        constructor() {
            this.el = $('file-tree');
            this.header = $('sidebar-header');
            this.stack = [];
            this.onSelect = () => {};
        }
        render(data) {
            this.stack = [{ name: '媒体资产库', children: data || [] }];
            this.draw();
        }
        reveal(selected) {
            if (!selected || !selected.path) return;
            const find = (dir, parents) => {
                for (const item of dir.children || []) {
                    if (item.type === 'folder') {
                        const result = find(item, parents.concat(item));
                        if (result) return result;
                    } else if (item.path === selected.path) return parents;
                }
                return null;
            };
            const root = { name: '媒体资产库', children: window.__mediaData || [] };
            const stack = find(root, [root]);
            if (stack) { this.stack = stack; this.draw(); }
        }
        draw() {
            const dir = this.stack[this.stack.length - 1];
            this.el.innerHTML = '';
            this.header.textContent = dir.name;
            if (this.stack.length > 1) {
                const back = document.createElement('div');
                back.className = 'back-btn';
                back.textContent = '⬅️ 返回上一级';
                back.onclick = () => { this.stack.pop(); this.draw(); };
                this.el.appendChild(back);
            }
            const ul = document.createElement('ul');
            ul.className = 'file-list';
            (dir.children || []).forEach(item => {
                const li = document.createElement('li');
                if (item.type === 'folder') {
                    li.textContent = '📁 ' + item.name;
                    li.onclick = () => { this.stack.push(item); this.draw(); };
                } else {
                    const icon = item.type === 'video' ? '🎬' : item.type === 'audio' ? '🎵' : '🖼️';
                    li.textContent = icon + ' ' + item.name;
                    li.onclick = () => {
                        ul.querySelectorAll('li').forEach(node => node.classList.remove('active'));
                        li.classList.add('active');
                        this.onSelect({ ...item, displayTitle: this.stack.slice(1).map(folder => folder.name).concat(item.name || '媒体').join(' / ') });
                        toggleSidebar(false);
                    };
                }
                ul.appendChild(li);
            });
            this.el.appendChild(ul);
        }
    }

    function toggleSidebar(force) {
        const sidebar = $('sidebar');
        const open = typeof force === 'boolean' ? force : !sidebar.classList.contains('open');
        sidebar.classList.toggle('open', open);
        $('menu-toggle-btn').setAttribute('aria-expanded', String(open));
        sidebar.inert = !open;
        sidebar.setAttribute('aria-hidden', String(!open));
        if (!open && sidebar.contains(document.activeElement)) $('menu-toggle-btn').focus();
        if (player()) player().setControlsPinned('library', open);
    }

    function directPlaybackUrl(item) {
        if (!item || !window.location) return null;
        const target = item.src || item.path;
        if (!target) return null;
        try {
            const url = new URL(target, document.baseURI || window.location.href);
            if (!item.src && item.path) {
                url.search = '';
                url.hash = '';
                url.searchParams.set('raw', '1');
            }
            return url.href;
        } catch (_error) { return null; }
    }

    async function copyText(value) {
        if (window.navigator && window.navigator.clipboard && window.navigator.clipboard.writeText) {
            try { await window.navigator.clipboard.writeText(value); return; } catch (_error) {}
        }
        const input = document.createElement('textarea');
        input.value = value;
        input.setAttribute('readonly', '');
        input.style.position = 'fixed';
        input.style.opacity = '0';
        document.body.appendChild(input);
        input.select();
        let copied = false;
        try { copied = Boolean(document.execCommand && document.execCommand('copy')); }
        finally { input.remove(); }
        if (!copied) throw new Error('Clipboard copy is unavailable');
    }

    function addShareControl(options, item) {
        options.controls = (Array.isArray(options.controls) ? options.controls : []).filter(control => control.name !== 'mediapages-share');
        options.controls.push({
            name: 'mediapages-share',
            position: 'right',
            index: 25,
            tooltip: '复制播放直链',
            html: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="3"></circle><circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle><path d="m8.7 10.7 6.6-4.4M8.7 13.3l6.6 4.4"></path></svg>',
            click() {
                const url = directPlaybackUrl(item);
                if (!url) {
                    if (this.notice) this.notice.show = '当前媒体没有可分享的直链';
                    return;
                }
                return copyText(url).then(() => {
                    if (this.notice) this.notice.show = '播放直链已复制';
                }).catch(() => {
                    if (this.notice) this.notice.show = '复制失败，请检查浏览器剪贴板权限';
                });
            }
        });
    }

    let subtitleGeneration = 0;

    function destroyRenderer() {
        subtitleGeneration += 1;
        if (assController) assController.dispose();
    }

    const tracks = (item, key) => core.normalizeTracks(item && item[key]);
    function initialChoice(item) {
        const ass = tracks(item, 'ass');
        if (ass.length && assController && player() && player().engineName === 'artplayer') return 'ass:' + Math.max(0, ass.findIndex(track => track.default));
        const vtt = tracks(item, 'subtitles');
        return vtt.length ? 'vtt:' + Math.max(0, vtt.findIndex(track => track.default)) : 'off';
    }
    function updateSettings(value) {
        const art = player() && player().art;
        const option = art && art.setting && art.setting.find('mediapages-subtitles');
        if (option && option.selector) {
            const selected = option.selector.find(track => track.value === value);
            if (selected) art.setting.check(selected);
        }
    }
    async function selectSubtitle(item, value) {
        destroyRenderer();
        subtitleChoice = value;
        const generation = subtitleGeneration;
        const current = player();
        if (!current || current.currentItem !== item) return;
        const [kind, number] = value.split(':');
        const index = Number(number);
        updateSettings(value);
        if (kind !== 'ass') { current.setSubtitle(kind === 'vtt' ? index : -1, { silent: true }); return; }
        const video = current.video, track = tracks(item, 'ass')[index];
        if (!video || !track || !assController) return;
        const valid = () => generation === subtitleGeneration && player().currentItem === item && player().video === video && video.isConnected;
        current.setSubtitle(-1, { silent: true });
        let delay = 0;
        try { delay = Number(localStorage.getItem('mediapages-ass-delay:' + track.src) || 0); } catch (_error) {}
        assController.setDelay(delay);
        await assController.load(video, track, item, {
            onReady: () => { if (valid()) current.setSubtitle(-1, { silent: true }); },
            onError: error => {
                if (!valid()) return;
                console.warn('ASS rendering unavailable:', error);
                const vtt = tracks(item, 'subtitles');
                selectSubtitle(item, vtt.length ? 'vtt:0' : 'off');
            }
        });
    }

    // Use the ArtPlayer selector and range setting with arbitrary track labels.
    core.on('playeroptions', detail => {
        const item = detail.item, options = detail.options;
        addShareControl(options, item);
        const ass = tracks(item, 'ass'), vtt = tracks(item, 'subtitles');
        if (!ass.length || !assController) {
            if (vtt.length) { options.subtitleOffset = true; options.setting = true; }
            return;
        }
        const selected = initialChoice(item);
        options.settings = options.settings.filter(option => option.name !== 'mediapages-subtitles');
        const selector = [{ html: '关闭字幕', value: 'off', default: selected === 'off' }];
        for (const [kind, list] of [['ass', ass], ['vtt', vtt]]) list.forEach((track, index) => {
            const value = kind + ':' + index;
            selector.push({ html: (track.label || '字幕 ' + (index + 1)) + ' · ' + kind.toUpperCase(), value, default: selected === value });
        });
        const track = ass[Number(selected.split(':')[1])];
        let delay = 0;
        try { delay = Number(localStorage.getItem('mediapages-ass-delay:' + track.src) || 0); } catch (_error) {}
        delay = Math.max(-2, Math.min(2, delay)) || 0;
        options.settings.push({
            name: 'mediapages-subtitles', html: '字幕', width: 240,
            tooltip: selector.find(option => option.default).html, selector,
            onSelect(option) { selectSubtitle(item, option.value); return option.html; }
        }, {
            name: 'mediapages-subtitle-delay', html: 'ASS 字幕延迟', width: 240,
            tooltip: delay.toFixed(1) + 's', range: [delay, -2, 2, 0.1],
            onChange(option) {
                const value = assController.setDelay(option.range[0]);
                const selectedTrack = subtitleChoice.startsWith('ass:') && tracks(item, 'ass')[Number(subtitleChoice.split(':')[1])];
                if (selectedTrack) try { localStorage.setItem('mediapages-ass-delay:' + selectedTrack.src, String(value)); } catch (_error) {}
                return (value >= 0 ? '+' : '') + value.toFixed(1) + 's';
            }
        });
        options.setting = true;
    });

    let bootstrapped = false;
    function bootstrap() {
        if (bootstrapped) return;
        const data = window.__mediaData;
        const activePlayer = player();
        if (!data || !activePlayer) { window.__onCoreReady = bootstrap; return; }
        bootstrapped = true;
        const sidebar = new Sidebar();
        sidebar.onSelect = item => activePlayer.play(item);
        sidebar.render(data);
        sidebar.reveal(activePlayer.currentItem);
        core.on('beforeplay', detail => sidebar.reveal(detail.item));
        $('menu-toggle-btn').addEventListener('click', () => toggleSidebar());
        $('library-close').addEventListener('click', () => toggleSidebar(false));
        document.addEventListener('keydown', event => { if (event.key === 'Escape') toggleSidebar(false); });
        $('player-topbar').addEventListener('click', event => event.stopPropagation());
        toggleSidebar(false);
        if (activePlayer.currentItem) selectSubtitle(activePlayer.currentItem, initialChoice(activePlayer.currentItem));
    }

    function describePlaybackError(item) {
        const codecs = String(item && item.codecs || '').toLowerCase();
        if (/hvc1|hev1/.test(codecs)) return 'HEVC 播放失败；请尝试 AV1 或 H264 版本';
        if (codecs.includes('av01')) return 'AV1 播放失败；请尝试 H264 版本';
        return '播放失败，请尝试其他版本或外部播放器';
    }

    core.on('stop', () => {
        destroyRenderer();
        $('topbar-home').appendChild($('player-topbar'));
        document.body.appendChild($('sidebar'));
        toggleSidebar(false);
    });
    core.on('subtitlechange', detail => {
        destroyRenderer();
        subtitleChoice = detail.index < 0 ? 'off' : 'vtt:' + detail.index;
    });
    core.on('error', detail => { $('now-playing').textContent = describePlaybackError(detail.item); });
    core.on('routechange', detail => {
        if (!detail.item) $('now-playing').textContent = detail.found ? '请选择媒体' : '未找到媒体';
    });
    core.on('play', detail => {
        const item = detail.item;
        $('now-playing').textContent = item.displayTitle || item.title || item.name || '媒体';
        $('now-playing').title = item.displayTitle || item.title || item.name || '媒体';
        const art = player().art;
        if (art && art.layers) {
            art.template.$player.appendChild($('sidebar'));
            art.layers.add({ name: 'mediapages-topbar', html: $('player-topbar'),
                style: { position: 'absolute', inset: '0 0 auto 0', padding: '0' } });
        }
        if (item.type === 'video') selectSubtitle(item, initialChoice(item));
    });
    bootstrap();
})();
