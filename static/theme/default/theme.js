/**
 * theme.js — 【完全可变皮囊】主题交互
 * 职责：
 *   1. 定义 Sidebar 类（文件树渲染、导航）
 *   2. UI 交互（菜单按钮、自动隐藏）
 *   3. 通过 window.__player、window.__mediaData 与内核通信
 */
class Sidebar {
  constructor() {
    this.el = document.getElementById('file-tree');
    this.header = document.getElementById('sidebar-header');
    this.directoryStack = [];
    this._onSelect = () => {};
  }

  render(data) {
    this.directoryStack = [{ name: '媒体资产库', children: data }];
    this._renderCurrentDirectory();
  }

  onSelect(callback) {
    this._onSelect = callback;
  }

  _renderCurrentDirectory() {
    this.el.innerHTML = '';
    const currentDir = this.directoryStack[this.directoryStack.length - 1];
    this.header.innerText = currentDir.name;

    if (this.directoryStack.length > 1) {
      const backBtn = document.createElement('div');
      backBtn.className = 'back-btn';
      backBtn.innerHTML = '<span>⬅️</span> 返回上一级';
      backBtn.onclick = () => {
        this.directoryStack.pop();
        this._renderCurrentDirectory();
      };
      this.el.appendChild(backBtn);
    }

    const ul = document.createElement('ul');
    ul.className = 'file-list';

    currentDir.children.forEach(item => {
      const li = document.createElement('li');

      if (item.type === 'folder') {
        li.className = 'folder-item';
        li.innerHTML = `<span>📁</span> ${item.name}`;
        li.onclick = () => {
          this.directoryStack.push(item);
          this._renderCurrentDirectory();
        };
      } else {
        const icon = item.type === 'video' ? '🎬' : (item.type === 'audio' ? '🎵' : '🖼️');
        li.innerHTML = `<span>${icon}</span> ${item.name}`;
        li.title = item.name;

        li.onclick = () => {
          document.querySelectorAll('.file-list li').forEach(el => el.classList.remove('active'));
          li.classList.add('active');
          this._onSelect(item);

          if (window.innerWidth <= 768) {
            document.getElementById('sidebar').classList.remove('open');
            window.updateMenuButtonState();
          }
        };
      }
      ul.appendChild(li);
    });

    this.el.appendChild(ul);
  }
}

let mouseHideTimeout;

window.updateMenuButtonState = function () {
  const btn = document.getElementById('menu-toggle-btn');
  const sidebarEl = document.getElementById('sidebar');
  if (sidebarEl.classList.contains('open')) {
    btn.innerText = '✕ 关闭';
    btn.style.opacity = '1';
    clearTimeout(mouseHideTimeout);
  } else {
    btn.innerText = '☰ 媒体库';
    startHideTimer();
  }
};

function startHideTimer() {
  clearTimeout(mouseHideTimeout);
  if (!document.getElementById('sidebar').classList.contains('open')) {
    mouseHideTimeout = setTimeout(() => {
      document.getElementById('menu-toggle-btn').style.opacity = '0';
    }, 2500);
  }
}

function showButtonAndStartTimer() {
  document.getElementById('menu-toggle-btn').style.opacity = '1';
  startHideTimer();
}

(function initTheme() {
  function bootstrap() {
    const player = window.__player;
    const data = window.__mediaData;
    if (!player || !data) {
      window.__onCoreReady = bootstrap;
      return;
    }

    const sidebar = new Sidebar();

    sidebar.onSelect((item) => player.play(item));
    sidebar.render(data);

    const btn = document.getElementById('menu-toggle-btn');
    const sidebarEl = document.getElementById('sidebar');

    btn.addEventListener('click', () => {
      sidebarEl.classList.toggle('open');
      window.updateMenuButtonState();
    });

    document.addEventListener('mousemove', showButtonAndStartTimer);
    document.addEventListener('touchstart', showButtonAndStartTimer, { passive: true });

    startHideTimer();
  }

  bootstrap();
})();