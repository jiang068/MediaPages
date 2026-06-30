/**
 * MediaPages — bg-theme UI 交互层
 * 经典动漫主题皮肤，与 core.js 解耦，仅负责 UI 行为
 */

(function () {
    'use strict';

    const DOM = {
        video: document.getElementById('video-viewer'),
        audio: document.getElementById('audio-viewer'),
        image: document.getElementById('image-viewer'),
        placeholder: document.getElementById('placeholder'),
        videoTitle: document.getElementById('video-title'),
        episodeList: document.getElementById('episode-list'),
        mobileMenu: document.getElementById('mobile-menu'),
        // 动态组件挂载节点
        heroStrips: document.getElementById('hero-strips'),
        charNav: document.getElementById('char-nav'),
        galleryGrid: document.getElementById('gallery-grid')
    };

    // 全局数据仓库
    const THEME_DATA = {
        characters: [
            {
                name: '折木 奉太郎', enName: 'Houtarou Oreki',
                role: '古典部成员 · 洞察推解析',
                motto: '能不做的事就不做，非做不可的事就从简。',
                desc: '神山高校古典部的节能少年。拥有惊人的主观洞察力与逻辑推导天赋，尽管自身极度抗拒消耗多余的能量，但在千反田爱瑠无辜且炽热的眼神攻势下，总能将日常中看似微不足道的谜题逐一完美拆解。',
                bgUrl: '.MediaPages\static\theme\bg-theme\assets\b1.jpg',
                portraitUrl: '.MediaPages\static\theme\bg-theme\assets\b1.jpg'
            },
            {
                name: '千反田 爱瑠', enName: 'Eru Chitanda',
                role: '古典部部长 · 核心好奇心驱动',
                motto: '我很好奇！我非常在意！',
                desc: '富农名门千反田家的千金。外表清秀端庄，待人温柔极具教养。然而她对日常中所有不可思议的事物都有着无与伦比的探求欲，一旦陷入沉思，那双充满好奇的硕大眼眸便让任何人都无法拒绝。',
                bgUrl: '.MediaPages\static\theme\bg-theme\assets\a1.jpg',
                portraitUrl: '.MediaPages\static\theme\bg-theme\assets\a1.jpg'
            },
            {
                name: '福部 里志', enName: 'Satoshi Fukube',
                role: '古典部成员 · 随身人体数据库',
                motto: '数据是无法得出结论的。',
                desc: '奉太郎的挚友。随身携带各色布兜的乐天少年，涉猎面极其广泛，热衷于收集冷门杂学知识，自封为“数据库”。他深知自己无法对线索做精细推论，因此在信息和精神上全力给予奉太郎最好的声援。',
                bgUrl: '.MediaPages\static\theme\bg-theme\assets\b2.jpg',
                portraitUrl: '.MediaPages\static\theme\bg-theme\assets\b2.jpg'
            },
            {
                name: '伊原 摩耶花', enName: 'Mayaka Ibara',
                role: '古典部成员 · 严苛图书委员',
                motto: '对他人严厉，对自己更加严格。',
                desc: '身材娇小但原则极强的少女。同时跨界在漫画研究社与古典部活动。虽然平日里对奉太郎慢吞吞的节能态度表现得相当毒舌和严厉，打心底看重古典部四人组之间的深厚羁绊。',
                bgUrl: '.MediaPages\static\theme\bg-theme\assets\a2.jpg',
                portraitUrl: '.MediaPages\static\theme\bg-theme\assets\a2.jpg'
            }
        ],
        gallery: [
            'https://images.unsplash.com/photo-1528459801416-a9e53bbf4e17?w=500&auto=format&fit=crop',
            'https://images.unsplash.com/photo-1542273917363-3b1817f69a2d?w=500&auto=format&fit=crop',
            'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=500&auto=format&fit=crop',
            'https://images.unsplash.com/photo-1447752875215-b2761acb3c5d?w=500&auto=format&fit=crop'
        ],
        activeCharIndex: 0
    };

    /** 开屏切片渲染 */
    function renderHeroStrips() {
        if (!DOM.heroStrips) return;
        DOM.heroStrips.innerHTML = THEME_DATA.characters.map(function (char, index) {
            return '<div onclick="scrollToSection(\'characters\'); switchCharacter(' + index + ')" ' +
                   'class="hero-strip border-b md:border-b-0 md:border-r border-zinc-900/30 dark:border-zinc-950/50 last:border-none group">' +
                        '<div class="absolute inset-0 bg-cover bg-center transition-transform duration-700 group-hover:scale-105" style="background-image: url(\'' + char.bgUrl + '\')">' +
                            '<div class="absolute inset-0 bg-black/40 group-hover:bg-black/10 transition-colors duration-500"></div>' +
                        '</div>' +
                        '<div class="absolute bottom-4 left-4 md:bottom-8 md:left-8 z-20 text-white flex flex-col justify-end select-none">' +
                            '<span class="text-[10px] tracking-widest font-mono text-classic-gold uppercase opacity-80">' + char.enName + '</span>' +
                            '<h3 class="text-xl md:text-2xl font-black tracking-wider mt-0.5">' + char.name + '</h3>' +
                        '</div>' +
                   '</div>';
        }).join('');
    }

    /** 【全面优化】采用数据靶向打入，去除任何 innerHTML 替换与延迟造成的抖动闪烁 */
    function renderCharacterShowcase() {
        if (!DOM.charNav) return;
        
        // 1. 刷新左侧导航样式状态
        DOM.charNav.innerHTML = THEME_DATA.characters.map(function (char, index) {
            var activeStyle = index === THEME_DATA.activeCharIndex
                ? 'bg-zinc-800 text-white dark:bg-classic-gold dark:text-zinc-950 border-transparent font-bold'
                : 'bg-transparent border-zinc-300 dark:border-zinc-800 text-zinc-500 hover:text-zinc-800 dark:hover:text-white';
            return '<button onclick="switchCharacter(' + index + ')" class="snap-start flex-shrink-0 text-left px-5 py-3 rounded-xl border transition-all duration-200 lg:w-full ' + activeStyle + '">' +
                        char.name +
                   '</button>';
        }).join('');

        // 2. 原位直接更新静态骨架内容，毫无 Layout Shift
        var curChar = THEME_DATA.characters[THEME_DATA.activeCharIndex];
        
        var elEn = document.getElementById('char-p-en');
        var elName = document.getElementById('char-p-name');
        var elRole = document.getElementById('char-p-role');
        var elMotto = document.getElementById('char-p-motto');
        var elDesc = document.getElementById('char-p-desc');
        var elImg = document.getElementById('char-p-img');

        if (elEn) elEn.textContent = curChar.enName.toUpperCase();
        if (elName) elName.textContent = curChar.name;
        if (elRole) elRole.textContent = curChar.role;
        if (elMotto) elMotto.textContent = curChar.motto;
        if (elDesc) elDesc.textContent = curChar.desc;
        
        if (elImg) {
            // 先将上一个人的图像隐去，替换源，等待新图网络加载完触发 onload 流畅淡入
            elImg.style.opacity = '0';
            elImg.src = curChar.portraitUrl;
            elImg.alt = curChar.name;
        }
    }

    window.switchCharacter = function (index) {
        if (THEME_DATA.activeCharIndex === index) return;
        THEME_DATA.activeCharIndex = index;
        renderCharacterShowcase();
    };

    /** 画廊渲染 */
    function renderGallery() {
        if (!DOM.galleryGrid) return;
        DOM.galleryGrid.innerHTML = THEME_DATA.gallery.map(function (url, index) {
            return '<div class="relative aspect-[4/3] rounded-xl overflow-hidden bg-zinc-800 shadow-md group">' +
                        '<img src="' + url + '" alt="Gallery ' + index + '" class="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105" loading="lazy" />' +
                        '<div class="absolute inset-0 bg-black/30 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-end p-3">' +
                            '<span class="text-white text-xs font-mono font-light">SCENE _0' + (index + 1) + '</span>' +
                        '</div>' +
                   '</div>';
        }).join('');
    }

    /** 同步后端 core.js 数据通信 */
    function onCoreReady() {
        var data = window.__mediaData || [];
        if (data.length > 0) {
            renderEpisodes(data);
            if (window.__player) {
                updatePlayer(window.__player._currentItem || data[0]);
            }
        }
    }

    function renderEpisodes(items) {
        if (!items || items.length === 0) return;
        var total = items.length;
        var listInfo = document.querySelector('#episode-list').previousElementSibling;
        if (listInfo && listInfo.tagName === 'SPAN') {
            listInfo.innerHTML = '<i data-lucide="list-video" class="w-4 h-4"></i> 剧集列表 (共' + total + '集)';
            if (window.lucide) window.lucide.createIcons();
        }

        DOM.episodeList.innerHTML = items.map(function (item, index) {
            var label = item.type;
            if (item.duration) label += ' · ' + item.duration;
            return '<button class="episode-item text-left w-full px-3 py-2 rounded-lg transition-all duration-200 text-zinc-600 dark:text-zinc-400 hover:bg-classic-gold/20 dark:hover:bg-classic-gold/10 hover:text-classic-gold"' +
                   ' data-index="' + index + '">' +
                '<div class="text-sm font-bold truncate">' + item.name + '</div>' +
                '<div class="text-xs text-zinc-400 dark:text-zinc-500 mt-0.5">' + label + '</div>' +
            '</button>';
        }).join('');

        DOM.episodeList.addEventListener('click', function (e) {
            var btn = e.target.closest('.episode-item');
            if (!btn) return;
            var idx = parseInt(btn.dataset.index, 10);
            var item = items[idx];
            if (item && window.__player) {
                window.__player.play(item);
            }
        });
    }

    function updatePlayer(item) {
        if (DOM.videoTitle) {
            DOM.videoTitle.textContent = item ? item.name : '选择剧集开始观看';
        }

        var buttons = DOM.episodeList.querySelectorAll('.episode-item');
        buttons.forEach(function (el) {
            el.classList.remove('bg-classic-gold/20', 'dark:bg-classic-gold/10', 'text-classic-gold');
        });
        if (item) {
            var data = window.__mediaData || [];
            var idx = data.indexOf(item);
            if (idx !== -1) {
                var current = DOM.episodeList.querySelector('[data-index="' + idx + '"]');
                if (current) {
                    current.classList.add('bg-classic-gold/20', 'dark:bg-classic-gold/10', 'text-classic-gold');
                }
            } else {
                var first = DOM.episodeList.querySelector('.episode-item');
                if (first) first.classList.add('bg-classic-gold/20', 'dark:bg-classic-gold/10', 'text-classic-gold');
            }
        }

        DOM.video.style.display = 'none';
        DOM.audio.style.display = 'none';
        DOM.image.style.display = 'none';
        DOM.placeholder.style.display = 'none';

        if (!item) {
            DOM.placeholder.style.display = 'block';
            return;
        }
        if (item.type === 'folder') {
            DOM.placeholder.style.display = 'block';
            return;
        }
        if (item.type === 'audio') {
            DOM.audio.style.display = '';
            DOM.audio.src = item.src;
            DOM.audio.load();
            return;
        }

        DOM.video.style.display = '';
        if (window.__player && window.__player._hls) {
            // HLS 引擎托管
        } else {
            DOM.video.src = item.src;
            DOM.video.load();
        }

        if (window.innerWidth < 1024) {
            DOM.episodeList.classList.remove('hidden');
            var toggleIcon = document.querySelector('#episode-toggle i');
            if (toggleIcon) toggleIcon.setAttribute('data-lucide', 'chevron-up');
            if (window.lucide) window.lucide.createIcons();
        }
    }

    window.toggleEpisodeList = function () {
        DOM.episodeList.classList.toggle('hidden');
        var toggleIcon = document.querySelector('#episode-toggle i');
        if (toggleIcon) {
            var isHidden = DOM.episodeList.classList.contains('hidden');
            toggleIcon.setAttribute('data-lucide', isHidden ? 'chevron-down' : 'chevron-up');
            if (window.lucide) window.lucide.createIcons();
        }
    };

    window.toggleTheme = function () {
        document.documentElement.classList.toggle('dark');
        if (window.lucide) {
            setTimeout(function () { window.lucide.createIcons(); }, 0);
        }
    };

    window.toggleMobileMenu = function () {
        DOM.mobileMenu.classList.toggle('hidden');
    };

    window.scrollToSection = function (id) {
        var el = document.getElementById(id);
        if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    };

    // 系统基础挂载
    window.addEventListener('DOMContentLoaded', function () {
        renderHeroStrips();
        renderCharacterShowcase(); // 初始化同步填入第一人数据
        renderGallery();
        if (window.lucide) window.lucide.createIcons();
    });

    window.__onCoreReady = onCoreReady;

    if (window.__mediaData && window.__mediaData.length > 0) {
        onCoreReady(window.__mediaData);
    }
})();