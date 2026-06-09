// EchoLily — DOM rendering utilities
// Loaded first (no dependencies on ws.js or app.js)

function renderMarkdown(text){
  if(window.marked)try{return marked.parse(text)}catch(e){return text}
  return text;
}
function renderMermaid(container){
  if(!container)container=document;
  container.querySelectorAll("pre code.language-mermaid").forEach(function(el){
    var txt=el.textContent;
    var pre=el.parentNode;
    var div=document.createElement("div");div.className="mermaid";div.textContent=txt;
    pre.parentNode.replaceChild(div,pre);
  });
  if(document.querySelectorAll(".mermaid").length)mermaid.run({nodes:document.querySelectorAll(".mermaid")});
}
function escapeHtml(t){var d=document.createElement("div");d.textContent=t;return d.innerHTML}
function escHtml(s){
  if(s==null)return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function scrollToBottom(){
  var area=document.getElementById('messageArea');
  if(area)area.scrollTop=area.scrollHeight;
}

// ── Conversation rendering ──

function renderConversations(filter) {
      const list = document.getElementById('convList');
      const f = (filter || '').toLowerCase().trim();

      // 排序：置顶 > 时间
      const sorted = [...CONVERSATIONS].sort((a, b) => {
        if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
        const order = ['刚刚', '1小时前', '3小时前', '昨天', '前天', '3天前'];
        return order.indexOf(a.time) - order.indexOf(b.time);
      });

      const filtered = f
        ? sorted.filter(c => c.title.toLowerCase().includes(f) || c.preview.toLowerCase().includes(f))
        : sorted;

      if (filtered.length === 0) {
        list.innerHTML = `
          <div class="empty-state">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
            <p>没有找到匹配的会话</p>
          </div>`;
        return;
      }

      list.innerHTML = filtered.map(c => `
        <div class="conv-item ${c.id === currentConvId ? 'active' : ''}" data-id="${c.id}">
          <div class="conv-avatar ${c.color}">${c.avatar}</div>
          <div class="conv-content">
            <div class="conv-top">
              <span class="conv-title">${c.pinned ? '📌 ' : ''}${escHtml(c.title)}</span>
              <span class="conv-time">${c.time}</span>
            </div>
            <div class="conv-preview">${escHtml(c.preview)}</div>
            <div class="conv-meta">
              ${c.unread > 0 ? `<span class="unread-badge">${c.unread}</span>` : ''}
            </div>
          </div>
        </div>
      `).join('');

      // 绑定点击事件
      list.querySelectorAll('.conv-item').forEach(el => {
        el.addEventListener('click', () => {
          selectConversation(el.dataset.id);
          // 移动端关闭侧栏
          closeSidebarMobile();
        });
      });
    }

function selectConversation(id) {
      if (isProcessing) return;
      currentConvId = id;
      const conv = CONVERSATIONS.find(c => c.id === id);
      if (!conv) return;
      // Load messages from server if not loaded
      if(conv.messages.length===0&&id.startsWith('s')&&ws){
        var sid=parseInt(id.slice(1));
        ws.send(JSON.stringify({type:"switch_session",id:sid}));
        ws.send(JSON.stringify({type:"get_session",id:sid}));
      }

      // 标记已读
      conv.unread = 0;

      // 更新列表高亮
      document.querySelectorAll('.conv-item').forEach(el => {
        el.classList.toggle('active', el.dataset.id === id);
      });

      // 更新头部
      document.getElementById('chatTitle').textContent = conv.title;

      // 隐藏欢迎页，渲染消息
      const welcome = document.getElementById('welcomeScreen');
      welcome.style.display = 'none';
      renderMessages(conv.messages);

      // 滚动到底部
      scrollToBottom();
    }

function formatMsgTime(msg, role) {
      const now = msg.timestamp ? new Date(msg.timestamp) : new Date();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      const ss = String(now.getSeconds()).padStart(2, '0');
      const time = hh + ':' + mm + ':' + ss;
      const words = (msg.text || '').replace(/\s/g, '').length;

      if (role === 'user') {
        return time + ' - ' + words + '字';
      }
      const model = msg.model || '雪覆红玫·1.0';
      const tokens = msg.tokens != null ? msg.tokens : Math.max(1, Math.floor(words * 1.5 + Math.random() * 20));
      const duration = msg.duration != null ? msg.duration.toFixed(1) + 's' : '—';
      return time + ' - ' + model + ' - ' + tokens + ' tok - ' + words + '字 - ' + duration;
    }

function formatToolTime(m) {
      if (!m.timestamp) return '';
      const t = new Date(m.timestamp);
      return String(t.getHours()).padStart(2,'0') + ':' + String(t.getMinutes()).padStart(2,'0') + ':' + String(t.getSeconds()).padStart(2,'0')
        + ' · ' + (m.denied ? '已拒绝' : m.completed ? '完成' : '处理中');
    }

function getActionHTML(role, msgIdx) {
      var copySvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
      var moreSvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>';
      if (role === 'user') {
        return '<div class="msg-actions">'
          + '<button class="msg-action" data-action="pause-edit" data-idx="' + msgIdx + '" title="暂停生成·修改输入">'
          + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/><path d="M4 20h16"/></svg></button>'
          + '<button class="msg-action" data-action="copy" data-idx="' + msgIdx + '" title="复制">' + copySvg + '</button>'
          + '<div class="msg-action-more">'
          + '<button class="msg-action" data-action="more" title="更多">' + moreSvg + '</button>'
          + '<div class="more-panel">'
          + '<button data-action="quote">引用</button>'
          + '<button data-action="forward">转发</button>'
          + '</div></div></div>';
      }
      var regenSvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>';
      return '<div class="msg-actions">'
        + '<button class="msg-action" data-action="copy" data-idx="' + msgIdx + '" title="复制">' + copySvg + '</button>'
        + '<button class="msg-action" data-action="regenerate" data-idx="' + msgIdx + '" title="重新生成">' + regenSvg + '</button>'
        + '<div class="msg-action-more">'
        + '<button class="msg-action" data-action="more" title="更多">' + moreSvg + '</button>'
        + '<div class="more-panel">'
        + '<button data-action="quote">引用</button>'
        + '<button data-action="report">举报</button>'
        + '<button data-action="delete">删除</button>'
        + '</div></div></div>';
    }

function renderMessages(messages) {
      const area = document.getElementById('messageArea');
      if (!messages || messages.length === 0) {
        area.innerHTML = '';
        return;
      }

      area.innerHTML = messages.map((m, idx) => {
        if (m.role === 'tool-bubble') {
          const paramsHtml = m.params ? ''
            + '<div class="tool-bubble-collapse">'
            + '<div class="tool-bubble-collapse-header" data-expand="params-' + idx + '">'
            + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg> 参数'
            + '</div>'
            + '<div class="tool-bubble-collapse-body" id="params-' + idx + '"><pre>' + escHtml(JSON.stringify(m.params, null, 2)) + '</pre></div>'
            + '</div>' : '';
          const resultHtml = m.result ? ''
            + '<div class="tool-bubble-collapse">'
            + '<div class="tool-bubble-collapse-header" data-expand="result-' + idx + '">'
            + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg> 返回结果'
            + '</div>'
            + '<div class="tool-bubble-collapse-body" id="result-' + idx + '"><pre>' + escHtml(typeof m.result === 'string' ? m.result : JSON.stringify(m.result, null, 2)) + '</pre></div>'
            + '</div>' : '';
          const statusIcon = m.completed && !m.denied ? '' : m.denied ? '' : '<span class="spinner-sm"></span>';
          const deniedIcon = m.denied ? '<span style="color:#EF4444;">✖</span> ' : '';
          const deniedStatus = m.denied ? '<span class="tool-bubble-status" style="color:#EF4444;">已拒绝</span>' : '';
          const permResultHtml = m.denied && m.permissionResultText ? ''
            + '<div class="tool-perm-section"><div class="tool-perm-result denied">' + escHtml(m.permissionResultText) + '</div></div>' : '';
          return ''
            + '<div class="message tool-bubble" data-msg-idx="' + idx + '">'
            + '<div class="msg-avatar" style="background:oklch(75% 0.01 250/0.3);color:var(--fg-muted);font-size:13px;">⚙</div>'
            + '<div>'
            + '<div class="msg-bubble">'
            + '<div class="tool-bubble-header">'
            + deniedIcon + statusIcon + ' ' + escHtml(m.toolName || m.text)
            + (m.duration ? '<span class="tool-bubble-status">' + m.duration.toFixed(1) + 's</span>' : '')
            + deniedStatus
            + '</div>'
            + paramsHtml
            + permResultHtml
            + resultHtml
            + '</div>'
            + (m.timestamp ? '<div class="tool-bubble-time">' + formatToolTime(m) + '</div>' : '')
            + '</div>'
            + '</div>';
        }
        if (m.role === 'ask_user') {
          var optsHtml = (m.options || []).map(function (opt, i) {
            return '<button class="ask-option" data-value="' + escHtml(opt.value) + '">'
              + '<span class="opt-num">' + (i + 1) + '</span>'
              + '<span>' + escHtml(opt.label) + '<br><small style="color:var(--fg-muted);font-weight:400;font-size:11px;">' + escHtml(opt.desc || '') + '</small></span>'
              + '</button>';
          }).join('');
          var ts = formatMsgTime(m, 'ai');
          return ''
            + '<div class="message ai" data-msg-idx="' + idx + '">'
            + '<div class="msg-avatar">❄</div>'
            + '<div>'
            + '<div class="msg-bubble">'
            + '<div style="margin-bottom:2px;">' + escHtml(m.text) + '</div>'
            + '<div class="ask-user-card">'
            + '<div class="ask-question">' + escHtml(m.question) + '</div>'
            + '<div class="ask-options">' + optsHtml + '</div>'
            + '<div class="ask-custom">'
            + '<input type="text" placeholder="' + escHtml(m.customPrompt || '输入你的想法…') + '">'
            + '<button class="ask-send-btn">发送</button>'
            + '</div>'
            + '</div>'
            + '</div>'
            + '<div class="msg-time">' + ts + '</div>'
            + '</div>'
            + '</div>';
        }

        const thinkingHtml = m.thinking ? ''
          + '<div class="msg-thinking" data-expanded="false">'
          + '<div class="thinking-toggle">'
          + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>'
          + ' 思考过程'
          + '</div>'
          + '<div class="thinking-text">' + escHtml(m.thinking).replace(/\n/g, '<br>') + '</div>'
          + '</div>' : '';

        const imageHtml = m.image ? ''
          + '<div class="msg-image">'
          + '<img src="' + escHtml(m.image) + '" alt="附件图片" loading="lazy" onclick="window.open(this.src,\'_blank\')">'
          + '</div>' : '';

        var textWithImages;
        if(m.role==='ai'&&window.marked){
          try{textWithImages=marked.parse(m.text||'');}catch(e){textWithImages=escHtml(m.text||'')}
        }else{
          textWithImages = renderInlineImages(escHtml(m.text||"''".replace(/\n/g, '<br>')));
        }

        const timeLabel = formatMsgTime(m, m.role);
        const actionsHtml = getActionHTML(m.role, idx);

        return ''
          + '<div class="message ' + m.role + '" data-msg-idx="' + idx + '">'
          + '<div class="msg-avatar">' + (m.role === 'user' ? '你' : '❄') + '</div>'
          + '<div>'
          + '<div class="msg-bubble">'
          + (m.role === 'ai' ? thinkingHtml : '')
          + textWithImages
          + imageHtml
          + '</div>'
          + '<div class="msg-time">' + timeLabel + '</div>'
          + actionsHtml
          + '</div>'
          + '</div>';
      }).join('');

      // 绑定思考过程折叠事件
      area.querySelectorAll('.msg-thinking').forEach(function (el) {
        el.addEventListener('click', function (e) {
          e.stopPropagation();
          const expanded = this.dataset.expanded === 'true';
          this.dataset.expanded = expanded ? 'false' : 'true';
          this.querySelector('.thinking-toggle svg').classList.toggle('open', !expanded);
          this.querySelector('.thinking-text').classList.toggle('open', !expanded);
        });
      });

      // 绑定工具气泡折叠事件
      area.querySelectorAll('.tool-bubble-collapse-header').forEach(function (el) {
        el.addEventListener('click', function (e) {
          e.stopPropagation();
          const targetId = this.dataset.expand;
          if (!targetId) return;
          const body = document.getElementById(targetId);
          if (!body) return;
          body.classList.toggle('open');
          this.querySelector('svg').classList.toggle('open');
        });
      });

      // 绑定操作按钮事件
      area.querySelectorAll('.msg-action').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
          e.stopPropagation();
          const action = this.dataset.action;
          if (action === 'copy') handleCopyMessage(this.dataset.idx);
          else if (action === 'regenerate') handleRegenerate(this.dataset.idx);
          else if (action === 'pause-edit') handlePauseEdit(this.dataset.idx);
          else if (action === 'more') toggleMorePanel(this);
        });
      });

      // 绑定扩展面板子按钮
      area.querySelectorAll('.more-panel button').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
          e.stopPropagation();
          const action = this.dataset.action;
          const msgEl = this.closest('.message');
          if (!msgEl) return;
          if (action === 'delete') { msgEl.remove(); return; }
          if (action === 'quote') alert('引用功能将在后端对接时实现');
          else if (action === 'forward') alert('转发功能将在后端对接时实现');
          else if (action === 'report') alert('举报功能将在后端对接时实现');
          // 关闭面板
          const panel = this.closest('.more-panel');
          if (panel) panel.classList.remove('open');
        });
      });

      // 绑定 ask_user 选项点击
      area.querySelectorAll('.ask-option').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var val = this.dataset.value;
          var text = this.querySelector('span') ? this.querySelector('span').textContent.trim() : val;
          // 禁用所有选项，显示选中状态
          var parent = this.closest('.ask-options');
          parent.querySelectorAll('.ask-option').forEach(function (b) {
            b.style.borderColor = 'var(--border-glass)';
            b.style.opacity = '0.5';
          });
          this.style.borderColor = 'var(--rose)';
          this.style.opacity = '1';
          this.style.background = 'var(--rose-surface)';
          // 在卡片底部显示确认信息
          var card = this.closest('.ask-user-card');
          var confirmEl = card.querySelector('.ask-confirm') || document.createElement('div');
          confirmEl.className = 'ask-confirm';
          confirmEl.style.cssText = 'margin-top:10px;padding:8px 12px;background:var(--rose-surface);border-radius:8px;font-size:12px;color:var(--rose);';
          confirmEl.textContent = '✓ 已选择: ' + text + '（后端对接后将发送给 AI）';
          if (!card.querySelector('.ask-confirm')) card.appendChild(confirmEl);
        });
      });

      // 绑定 ask_user 自定义输入发送
      area.querySelectorAll('.ask-send-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var input = this.previousElementSibling;
          if (!input || !input.value.trim()) return;
          var text = input.value.trim();
          var card = this.closest('.ask-user-card');
          var confirmEl = card.querySelector('.ask-confirm') || document.createElement('div');
          confirmEl.className = 'ask-confirm';
          confirmEl.style.cssText = 'margin-top:10px;padding:8px 12px;background:var(--rose-surface);border-radius:8px;font-size:12px;color:var(--rose);';
          confirmEl.textContent = '✓ 已发送: "' + text + '"（后端对接后将发送给 AI）';
          if (!card.querySelector('.ask-confirm')) card.appendChild(confirmEl);
          this.textContent = '已发送';
          this.disabled = true;
          input.disabled = true;
        });
      });
    }

function renderInlineImages(text) {
      var result = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, function (match, alt, url) {
        return '<div class="msg-image"><img src="' + escHtml(url) + '" alt="' + escHtml(alt) + '" loading="lazy" onclick="window.open(this.src,\'_blank\')"></div>';
      });
      return result;
    }

function renderAttachments() {
      const row = document.getElementById('attachmentsRow');
      if (currentAttachments.length === 0) {
        row.innerHTML = '';
        return;
      }
      row.innerHTML = currentAttachments.map((file, i) => `
        <div class="attachment-chip">
          ${file.isImage
            ? `<img class="chip-thumb" src="${file.dataUrl}" alt="${escHtml(file.name)}">`
            : `<svg class="chip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`
          }
          <span class="chip-name">${escHtml(file.name)}</span>
          <span class="chip-size">${file.size}</span>
          <button class="chip-remove" data-index="${i}" aria-label="移除附件">✕</button>
        </div>
      `).join('');

      // 绑定删除
      row.querySelectorAll('.chip-remove').forEach(btn => {
        btn.addEventListener('click', function(e) {
          e.stopPropagation();
          const idx = parseInt(this.dataset.index);
          currentAttachments.splice(idx, 1);
          renderAttachments();
        });
      });
    }

function updateSendButton(processing) {
      const btn = document.getElementById('sendBtn');
      const sendIcon = btn.querySelector('.send-icon');
      const stopIcon = btn.querySelector('.stop-icon');
      if (processing) {
        btn.classList.add('processing');
        sendIcon.style.display = 'none';
        stopIcon.style.display = 'grid';
        btn.disabled = false;
        btn.title = '中止';
      } else {
        btn.classList.remove('processing');
        sendIcon.style.display = 'grid';
        stopIcon.style.display = 'none';
        btn.title = '发送';
      }
    }

function showTypingIndicator() {
      const area = document.getElementById('messageArea');
      const div = document.createElement('div');
      div.className = 'message ai';
      div.id = 'typingIndicator';
      div.innerHTML = `
        <div class="msg-avatar">❄</div>
        <div>
          <div class="msg-bubble msg-typing">
            <span class="dot"></span>
            <span class="dot"></span>
            <span class="dot"></span>
          </div>
        </div>
      `;
      area.appendChild(div);
      scrollToBottom();
    }

function hideTypingIndicator() {
      const el = document.getElementById('typingIndicator');
      if (el) el.remove();
    }

function closeSidebarMobile() {
      const sidebar = document.getElementById('sidebar');
      const overlay = document.getElementById('mobileOverlay');
      if (window.innerWidth <= 780) {
        sidebar.classList.remove('open');
        overlay.classList.remove('visible');
      }
    }

function renderConfigForm(cfg){
      if(!cfg)return;
      // Populate the settings form with config values
      var els=document.querySelectorAll('.settings-field');
      els.forEach(function(el){
        var key=el.dataset.key;
        if(!key)return;
        var parts=key.split('.');
        var val=cfg;
        parts.forEach(function(p){if(val)val=val[p];});
        if(val!==undefined){
          if(el.type==='checkbox')el.checked=!!val;
          else el.value=String(val);
        }
      });
    }
