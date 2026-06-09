// EchoLily — Application initialization + UI state
// Loaded last (depends on render.js + ws.js)

function toggleSidebar() {
      const sidebar = document.getElementById('sidebar');
      const isCollapsed = sidebar.classList.toggle('collapsed');
      const btn = document.getElementById('sidebarCollapseBtn');
      btn.title = isCollapsed ? '展开侧栏' : '收起侧栏';
      if (window.innerWidth > 780) {
        try { localStorage.setItem('sidebarCollapsed', isCollapsed ? '1' : '0'); } catch (_) {}
      }
    }

function handleCopyMessage(idx) {
      const conv = CONVERSATIONS.find(function (c) { return c.id === currentConvId; });
      if (!conv || !conv.messages[idx]) return;
      const text = conv.messages[idx].text;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).catch(function () {});
      }
    }

function handleRegenerate(idx) {
      if (isProcessing) return;
      const conv = CONVERSATIONS.find(function (c) { return c.id === currentConvId; });
      if (!conv || !conv.messages[idx] || conv.messages[idx].role !== 'ai') return;
      // 删除这条 AI 回复及之后的消息，重新生成
      conv.messages.splice(idx);
      renderMessages(conv.messages);
      scrollToBottom();
      // 触发重新生成
      setTimeout(function () { sendMessageInternal(conv); }, 100);
    }

function handlePauseEdit(idx) {
      if (isProcessing) cancelProcessing();
      const conv = CONVERSATIONS.find(function (c) { return c.id === currentConvId; });
      if (!conv || !conv.messages[idx]) return;
      const text = conv.messages[idx].text;
      const input = document.getElementById('chatInput');
      input.value = text;
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
      input.focus();
      // 删除用户消息及之后的内容
      conv.messages.splice(idx);
      renderMessages(conv.messages);
      scrollToBottom();
    }

function toggleMorePanel(btn) {
      const panel = btn.parentElement.querySelector('.more-panel');
      if (panel) panel.classList.toggle('open');
      // 关闭其他面板
      document.querySelectorAll('.more-panel.open').forEach(function (p) {
        if (p !== panel) p.classList.remove('open');
      });
    }

function openSettings() {
      const chatArea = document.getElementById('chatArea');
      chatArea.classList.add('settings-mode');
      document.getElementById('settingsPage').classList.add('open');
      // 切换标签到「通用」
      switchSettingsSection('general');
    }

function closeSettings() {
      const chatArea = document.getElementById('chatArea');
      chatArea.classList.remove('settings-mode');
      document.getElementById('settingsPage').classList.remove('open');
    }

function switchSettingsSection(sectionId) {
      document.querySelectorAll('.settings-nav-item').forEach(function (el) {
        el.classList.toggle('active', el.dataset.section === sectionId);
      });
      document.querySelectorAll('.settings-section').forEach(function (el) {
        el.classList.toggle('active', el.dataset.section === sectionId);
      });
    }

function toggleDarkMode() {
      document.body.classList.toggle('dark');
      const isDark = document.body.classList.contains('dark');
      document.getElementById('darkModeSwitch').classList.toggle('on', isDark);
      document.getElementById('darkModeSwitch').setAttribute('aria-checked', isDark ? 'true' : 'false');
      try { localStorage.setItem('darkMode', isDark ? '1' : '0'); } catch (_) {}
    }

function initMessageMetadata() {
      var base = Date.now() - 86400000; // 昨天
      CONVERSATIONS.forEach(function (conv) {
        conv.messages.forEach(function (m, i) {
          if (m.role === 'user' && !m.timestamp) {
            m.timestamp = base + i * 30000;
          } else if (m.role === 'ai' && !m.timestamp) {
            m.timestamp = base + i * 30000 + 5000;
            if (!m.model) m.model = '雪覆红玫·1.0';
            if (m.tokens == null) m.tokens = Math.floor((m.text || '').replace(/\s/g, '').length * 1.5 + Math.random() * 30);
            if (m.duration == null) m.duration = 1.5 + Math.random() * 4;
          }
        });
      });
    }

function init() {
function checkLayout() {
        const menuBtn = document.getElementById('menuBtn');
        const collapseBtn = document.getElementById('sidebarCollapseBtn');
        if (window.innerWidth <= 780) {
          menuBtn.style.display = 'grid';
          collapseBtn.style.display = 'none';
        } else {
          menuBtn.style.display = 'none';
          collapseBtn.style.display = 'grid';
        }
      }

      connectWS();
      initMessageMetadata();
      const messageArea = document.getElementById('messageArea');

      // 恢复深色模式偏好
      try {
        if (localStorage.getItem('darkMode') === '1') {
          document.body.classList.add('dark');
          document.getElementById('darkModeSwitch').classList.add('on');
          document.getElementById('darkModeSwitch').setAttribute('aria-checked', 'true');
        }
      } catch (_) {}

      renderConversations();
      selectConversation('c1');
      setConnectionStatus('online');

      // ----- 搜索 -----
      document.getElementById('searchInput').addEventListener('input', function() {
        renderConversations(this.value);
      });

      // ----- 发送 / 中止 -----
      document.getElementById('sendBtn').addEventListener('click', function() {
        if (isProcessing) {
          cancelProcessing();
        } else {
          sendMessage();
        }
      });

      // ----- 输入框 -----
      const chatInput = document.getElementById('chatInput');
      chatInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 120) + 'px';
        if (!isProcessing) {
          document.getElementById('sendBtn').disabled = this.value.trim().length === 0;
        }
      });
      chatInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          if (isProcessing) {
            cancelProcessing();
          } else {
            sendMessage();
          }
        }
      });

      // ----- 附件 -----
      const fileInput = document.getElementById('fileInput');
      document.getElementById('attachBtn').addEventListener('click', function() {
        this.classList.toggle('active');
        fileInput.click();
        // 延迟取消 active 状态
        setTimeout(() => this.classList.remove('active'), 200);
      });
      fileInput.addEventListener('change', function() {
        for (const file of this.files) {
          const isImage = file.type.startsWith('image/');
          const size = file.size > 1024 * 1024
            ? (file.size / (1024 * 1024)).toFixed(1) + ' MB'
            : (file.size / 1024).toFixed(0) + ' KB';
          const attachment = { name: file.name, size, isImage };
          if (isImage) {
            attachment.dataUrl = URL.createObjectURL(file);
          }
          currentAttachments.push(attachment);
        }
        renderAttachments();
        this.value = '';
      });

      // ----- 新建对话 -----
      document.getElementById('newChatBtn').addEventListener('click', function() {
        if (isProcessing) return;
        // Create unsaved local conversation (id starts with 'new_')
        var id = 'new_' + Date.now();
        var conv = { id: id, title: '新对话', preview: '', time: '刚刚', unread: 0, avatar: '💬', color: 'rose', pinned: false, messages: [] };
        CONVERSATIONS.unshift(conv);
        renderConversations();
        selectConversation(id);
        document.getElementById('welcomeScreen').style.display = 'none';
        document.getElementById('messageArea').innerHTML = '';
        document.getElementById('chatInput').focus();
      });

      // ----- 欢迎页快捷按钮 -----
      document.querySelectorAll('.welcome-suggestions button').forEach(btn => {
        btn.addEventListener('click', function() {
          if (isProcessing) return;
          const input = document.getElementById('chatInput');
          input.value = this.dataset.prompt;
          input.dispatchEvent(new Event('input'));
          input.focus();
        });
      });

      // ----- 移动端菜单 -----
      document.getElementById('menuBtn').addEventListener('click', function() {
        document.getElementById('sidebar').classList.toggle('open');
        document.getElementById('mobileOverlay').classList.toggle('visible');
      });
      document.getElementById('mobileOverlay').addEventListener('click', closeSidebarMobile);

      // ----- 侧栏收起/展开 -----
      document.getElementById('sidebarCollapseBtn').addEventListener('click', toggleSidebar);
      // 恢复侧栏状态
      try {
        if (localStorage.getItem('sidebarCollapsed') === '1' && window.innerWidth > 780) {
          document.getElementById('sidebar').classList.add('collapsed');
          document.getElementById('sidebarCollapseBtn').title = '展开侧栏';
        }
      } catch (_) {}

      // ----- 设置页面（内嵌于聊天区） -----
      document.getElementById('settingsBtn').addEventListener('click', openSettings);
      document.getElementById('closeSettings').addEventListener('click', closeSettings);

      // 设置导航标签绑定
      document.querySelectorAll('.settings-nav-item').forEach(function(el) {
        el.addEventListener('click', function() {
          switchSettingsSection(this.dataset.section);
        });
      });

      // ----- 通用开关切换（toggle-switch 点击切换 .on 状态） -----
      document.querySelectorAll('.toggle-switch').forEach(function(el) {
        el.addEventListener('click', function() {
          this.classList.toggle('on');
          this.setAttribute('aria-checked', this.classList.contains('on') ? 'true' : 'false');
        });
      });

      // ----- 深色模式 -----
      document.getElementById('darkModeToggle').addEventListener('click', toggleDarkMode);
      document.getElementById('darkModeSwitch').addEventListener('click', toggleDarkMode);

      // ----- 响应式检查 — 移动端显示菜单按钮 -----
      function checkLayout() {
        const menuBtn = document.getElementById('menuBtn');
        const collapseBtn = document.getElementById('sidebarCollapseBtn');
        if (window.innerWidth <= 780) {
          menuBtn.style.display = 'grid';
          collapseBtn.style.display = 'none';
        } else {
          menuBtn.style.display = 'none';
          collapseBtn.style.display = 'grid';
        }
      }
      window.addEventListener('resize', checkLayout);
      checkLayout();

      // 移动端关闭侧栏按钮
      document.getElementById('closeSidebar').addEventListener('click', closeSidebarMobile);

      // 点击空白处关闭侧栏（移动端）
      document.addEventListener('click', function(e) {
        const sidebar = document.getElementById('sidebar');
        const menuBtn = document.getElementById('menuBtn');
        if (window.innerWidth <= 780 && sidebar.classList.contains('open')) {
          if (!sidebar.contains(e.target) && !menuBtn.contains(e.target)) {
            closeSidebarMobile();
          }
        }
      });

      chatInput.focus();
}

