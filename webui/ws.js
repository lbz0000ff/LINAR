// EchoLily — WebSocket communication + agent response
// Loaded second (depends on render.js)

const WS_URL="ws://127.0.0.1:8081";
var ws=null;
var currentSessionId=null;

function setConnectionStatus(status) {
      connectionStatus = status;
      const dots = document.querySelectorAll('.dot, .connection-dot');
      dots.forEach(function (el) {
        el.classList.remove('online', 'offline', 'processing');
        el.classList.add(status);
      });

      // 更新头部状态文字
      var headerText = document.getElementById('headerStatusText');
      if (headerText) {
        var labels = { 'online': '已连接', 'offline': '离线', 'processing': '处理中' };
        headerText.textContent = labels[status] || '未知';
      }

      // 更新设置面板连接状态
      var settingsConn = document.getElementById('settingsConnStatus');
      if (settingsConn) {
        var connLabels = { 'online': '已连接', 'offline': '离线', 'processing': '处理中' };
        var connColors = { 'online': 'var(--online)', 'offline': 'var(--offline)', 'processing': 'var(--processing)' };
        settingsConn.textContent = connLabels[status] || '未知';
        settingsConn.style.color = connColors[status] || 'var(--fg-muted)';
      }
    }

function connectWS(){
      if(ws)try{ws.close()}catch(e){}
      ws=new WebSocket(WS_URL);
      ws.onopen=function(){
        setConnectionStatus('connected');
        ws.send(JSON.stringify({type:"list_sessions"}));
      };
      ws.onmessage=function(e){
        var ev=JSON.parse(e.data);
        switch(ev.type){
          case "sessions":console.log("sessions received",ev.data&&ev.data.length);loadSessions(ev.data);break;
          case "session_msgs":loadSessionMessages(ev.session_id,ev.title,ev.data);break;
          case "config_json":renderConfigForm(ev.data||{});break;
          case "config_saved":var sb=document.getElementById("btn-save-config");if(sb)sb.textContent="已保存";break;
          case "new_session_created":
            if(ws&&ws._pendingNewConv){
              var oldId=ws._pendingNewConv;
              var newId='s'+ev.session_id;
              // Move messages from old conversation to new one
              var oldConv=CONVERSATIONS.find(function(c){return c.id===oldId});
              if(oldConv){
                oldConv.id=newId;
                oldConv.title='新对话';
                // Now send the pending message to the server
                if(ws._pendingText&&ws){
                  ws.send(JSON.stringify({type:"switch_session",id:ev.session_id}));
                  ws.send(JSON.stringify({type:"get_session",id:ev.session_id}));
                  ws.send(JSON.stringify({type:"message",data:ws._pendingText}));
                }
              }
              ws._pendingNewConv=null;
              ws._pendingText=null;
              renderConversations();
            }
            break;
          case "session_switched":currentSessionId=ev.session_id;break;
          // Agent response events
          case "token":appendAgentToken(ev.data||"");break;
          case "reasoning_token":appendAgentReasoning(ev.data||"");break;
          case "tool_call":showToolCall(ev.name||"");break;
          case "tool_result":showToolResult((ev.result||"").toString().slice(0,200));break;
          case "error":showSystemMsg("⚠️ "+(ev.data||""));break;
          case "complete":case "done":finishAgentResponse();break;
          case "ready":setConnectionStatus("connected");break;
        }
      };
      ws.onclose=function(){setConnectionStatus('offline');setTimeout(connectWS,2000);};
      ws.onerror=function(){ws.close();};
    }


    // ── Agent response handlers ──
    var agentResponseConvId=null;
    function appendAgentToken(text){
      if(!agentResponseConvId)agentResponseConvId=currentConvId;
      if(agentResponseConvId!==currentConvId)return;
      var area=document.getElementById('messageArea');
      if(!area)return;
      var lastMsgEl=area.lastElementChild;
      if(lastMsgEl&&lastMsgEl.classList.contains('msg-ai')&&lastMsgEl.dataset.streaming==='1'){
        var bubble=lastMsgEl.querySelector('.msg-content');
        if(bubble){
          if(!bubble._fullText)bubble._fullText='';
          bubble._fullText+=text;
          if(window.marked){
            try{bubble.innerHTML=marked.parse(bubble._fullText)}catch(e){bubble.textContent=bubble._fullText}
          }else{
            bubble.textContent=bubble._fullText;
          }
        }
      }else{
        var div=document.createElement('div');div.className='msg-ai';div.dataset.streaming='1';
        div.innerHTML='<div class="msg-bubble ai"><div class="msg-content"></div></div>';
        area.appendChild(div);
        // Trigger append again to render this first chunk
        var b=area.lastElementChild.querySelector('.msg-content');
        if(b){
          b._fullText=text;
          if(window.marked){try{b.innerHTML=marked.parse(text)}catch(e){b.textContent=text}}else{b.textContent=text}
        }
      }
      // Also update the data model for persistence
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last.role==='ai'&&last._streaming){
          last.text+=text;
        }else{
          msgs.push({role:'ai',text:text,timestamp:Date.now(),_streaming:true});
        }
      }
      scrollToBottom();
    }
    function appendAgentReasoning(text){
      if(!agentResponseConvId)agentResponseConvId=currentConvId;
      if(agentResponseConvId!==currentConvId)return;
      // Show reasoning inline - append to a thinking section
      var area=document.getElementById('messageArea');
      if(!area)return;
      var lastMsgEl=area.lastElementChild;
      var thinkingEl=null;
      if(lastMsgEl&&lastMsgEl.classList.contains('msg-ai')){
        thinkingEl=lastMsgEl.querySelector('.msg-thinking');
        if(!thinkingEl){
          thinkingEl=document.createElement('div');thinkingEl.className='msg-thinking';
          thinkingEl.style.cssText='font-size:12px;color:var(--fg-muted);font-style:italic;padding:4px 0;cursor:pointer';
          thinkingEl.textContent='思考过程 ▸';
          var bodyEl=document.createElement('div');bodyEl.className='thinking-body';
          bodyEl.style.cssText='display:none;font-size:12px;color:var(--fg-muted);font-style:italic;padding:4px 8px;background:var(--rose-surface);border-radius:6px;margin:4px 0';
          bodyEl.textContent=text;
          thinkingEl._body=bodyEl;
          thinkingEl.onclick=function(){var b=this._body;var o=b.style.display!=='block';b.style.display=o?'block':'none';this.textContent=o?'思考过程 ▾':'思考过程 ▸';};
          lastMsgEl.insertBefore(bodyEl,lastMsgEl.querySelector('.msg-bubble'));
          lastMsgEl.insertBefore(thinkingEl,bodyEl);
        }else{
          var body=thinkingEl._body;
          if(body)body.textContent+=text;
        }
      }
      // Also update data model
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last.role==='ai'){last.thinking=(last.thinking||'')+text;}
      }
    }
    function showToolCall(name){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      conv.messages.push({role:'tool-bubble',toolName:name,completed:false,timestamp:Date.now()});
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function showToolResult(text){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      var msgs=conv.messages;
      for(var i=msgs.length-1;i>=0;i--){
        if(msgs[i].role==='tool-bubble'&&!msgs[i].completed){
          msgs[i].result={text:text};
          msgs[i].completed=true;
          break;
        }
      }
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function showSystemMsg(text){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      conv.messages.push({role:'system',text:text,timestamp:Date.now()});
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function finishAgentResponse(){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last._streaming){delete last._streaming;}
        renderMessages(conv.messages);
      }
      setConnectionStatus('connected');
      agentResponseConvId=null;
    }
    function loadSessions(sessions){
      // Convert backend sessions to design's Conversation format
      CONVERSATIONS.length=0;
      sessions.forEach(function(s,i){
        CONVERSATIONS.push({
          id:'s'+s.id, title:s.title||('Session #'+s.id), preview:'', time:s.created_at||'',
          unread:0, avatar:'💬', color:'slate', pinned:false, messages:[]
        });
      });
      renderConversations();
      // Select first session if none selected
      currentConvId=null;if(CONVERSATIONS.length){selectConversation(CONVERSATIONS[0].id);}
    }

    function loadSessionMessages(sessionId,title,msgs){
      var conv=CONVERSATIONS.find(function(c){return c.id==='s'+sessionId});
      if(!conv)return;
      conv.messages=[];
      conv.title=title||conv.title;
      msgs.forEach(function(m){
        if(m.role==='user'){
          conv.messages.push({role:'user',text:extractText(m.content||''),timestamp:m.created_at,attachments:extractAttachments(m.content)});
        }else if(m.role==='agent'){
          conv.messages.push({role:'ai',text:m.content||'',timestamp:m.created_at,thinking:m.reasoning||''});
        }else if(m.role==='tool'&&m.tool_name){
          var result='';try{var j=JSON.parse(m.content);result=j.result||''}catch(e){result=m.content||''}
          conv.messages.push({role:'tool-bubble',toolName:m.tool_name,result:{text:result.slice(0,300)},completed:true,timestamp:m.created_at});
        }
      });
      // Ensure currentConvId matches
      if(currentConvId!=='s'+sessionId){currentConvId='s'+sessionId;renderConversations();}
      renderMessages(conv.messages);
      // Update header
      var h=document.querySelector('.conv-title');if(h)h.textContent=conv.title;
    }

    function extractText(content){
      var idx=content.indexOf('[附件]');
      return idx>=0?content.slice(0,idx).trim():content;
    }
    function extractAttachments(content){
      var files=[];var re=/\[附件\]\s*(\S+)/g;var m;
      while((m=re.exec(content))!==null){files.push({name:m[1].split(/[\/]/).pop(),type:"file"});}
      return files.length?files:undefined;
    }

    // ── Settings ──
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

function appendAgentToken(text){
      if(!agentResponseConvId)agentResponseConvId=currentConvId;
      if(agentResponseConvId!==currentConvId)return;
      var area=document.getElementById('messageArea');
      if(!area)return;
      var lastMsgEl=area.lastElementChild;
      if(lastMsgEl&&lastMsgEl.classList.contains('msg-ai')&&lastMsgEl.dataset.streaming==='1'){
        var bubble=lastMsgEl.querySelector('.msg-content');
        if(bubble){
          if(!bubble._fullText)bubble._fullText='';
          bubble._fullText+=text;
          if(window.marked){
            try{bubble.innerHTML=marked.parse(bubble._fullText)}catch(e){bubble.textContent=bubble._fullText}
          }else{
            bubble.textContent=bubble._fullText;
          }
        }
      }else{
        var div=document.createElement('div');div.className='msg-ai';div.dataset.streaming='1';
        div.innerHTML='<div class="msg-bubble ai"><div class="msg-content"></div></div>';
        area.appendChild(div);
        // Trigger append again to render this first chunk
        var b=area.lastElementChild.querySelector('.msg-content');
        if(b){
          b._fullText=text;
          if(window.marked){try{b.innerHTML=marked.parse(text)}catch(e){b.textContent=text}}else{b.textContent=text}
        }
      }
      // Also update the data model for persistence
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last.role==='ai'&&last._streaming){
          last.text+=text;
        }else{
          msgs.push({role:'ai',text:text,timestamp:Date.now(),_streaming:true});
        }
      }
      scrollToBottom();
    }
    function appendAgentReasoning(text){
      if(!agentResponseConvId)agentResponseConvId=currentConvId;
      if(agentResponseConvId!==currentConvId)return;
      // Show reasoning inline - append to a thinking section
      var area=document.getElementById('messageArea');
      if(!area)return;
      var lastMsgEl=area.lastElementChild;
      var thinkingEl=null;
      if(lastMsgEl&&lastMsgEl.classList.contains('msg-ai')){
        thinkingEl=lastMsgEl.querySelector('.msg-thinking');
        if(!thinkingEl){
          thinkingEl=document.createElement('div');thinkingEl.className='msg-thinking';
          thinkingEl.style.cssText='font-size:12px;color:var(--fg-muted);font-style:italic;padding:4px 0;cursor:pointer';
          thinkingEl.textContent='思考过程 ▸';
          var bodyEl=document.createElement('div');bodyEl.className='thinking-body';
          bodyEl.style.cssText='display:none;font-size:12px;color:var(--fg-muted);font-style:italic;padding:4px 8px;background:var(--rose-surface);border-radius:6px;margin:4px 0';
          bodyEl.textContent=text;
          thinkingEl._body=bodyEl;
          thinkingEl.onclick=function(){var b=this._body;var o=b.style.display!=='block';b.style.display=o?'block':'none';this.textContent=o?'思考过程 ▾':'思考过程 ▸';};
          lastMsgEl.insertBefore(bodyEl,lastMsgEl.querySelector('.msg-bubble'));
          lastMsgEl.insertBefore(thinkingEl,bodyEl);
        }else{
          var body=thinkingEl._body;
          if(body)body.textContent+=text;
        }
      }
      // Also update data model
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last.role==='ai'){last.thinking=(last.thinking||'')+text;}
      }
    }
    function showToolCall(name){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      conv.messages.push({role:'tool-bubble',toolName:name,completed:false,timestamp:Date.now()});
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function showToolResult(text){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      var msgs=conv.messages;
      for(var i=msgs.length-1;i>=0;i--){
        if(msgs[i].role==='tool-bubble'&&!msgs[i].completed){
          msgs[i].result={text:text};
          msgs[i].completed=true;
          break;
        }
      }
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function showSystemMsg(text){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      conv.messages.push({role:'system',text:text,timestamp:Date.now()});
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function finishAgentResponse(){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last._streaming){delete last._streaming;}
        renderMessages(conv.messages);
      }
      setConnectionStatus('connected');
      agentResponseConvId=null;
    }
    function loadSessions(sessions){
      // Convert backend sessions to design's Conversation format
      CONVERSATIONS.length=0;
      sessions.forEach(function(s,i){
        CONVERSATIONS.push({
          id:'s'+s.id, title:s.title||('Session #'+s.id), preview:'', time:s.created_at||'',
          unread:0, avatar:'💬', color:'slate', pinned:false, messages:[]
        });
      });
      renderConversations();
      // Select first session if none selected
      currentConvId=null;if(CONVERSATIONS.length){selectConversation(CONVERSATIONS[0].id);}
    }

    function loadSessionMessages(sessionId,title,msgs){
      var conv=CONVERSATIONS.find(function(c){return c.id==='s'+sessionId});
      if(!conv)return;
      conv.messages=[];
      conv.title=title||conv.title;
      msgs.forEach(function(m){
        if(m.role==='user'){
          conv.messages.push({role:'user',text:extractText(m.content||''),timestamp:m.created_at,attachments:extractAttachments(m.content)});
        }else if(m.role==='agent'){
          conv.messages.push({role:'ai',text:m.content||'',timestamp:m.created_at,thinking:m.reasoning||''});
        }else if(m.role==='tool'&&m.tool_name){
          var result='';try{var j=JSON.parse(m.content);result=j.result||''}catch(e){result=m.content||''}
          conv.messages.push({role:'tool-bubble',toolName:m.tool_name,result:{text:result.slice(0,300)},completed:true,timestamp:m.created_at});
        }
      });
      // Ensure currentConvId matches
      if(currentConvId!=='s'+sessionId){currentConvId='s'+sessionId;renderConversations();}
      renderMessages(conv.messages);
      // Update header
      var h=document.querySelector('.conv-title');if(h)h.textContent=conv.title;
    }

    function extractText(content){
      var idx=content.indexOf('[附件]');
      return idx>=0?content.slice(0,idx).trim():content;
    }
    function extractAttachments(content){
      var files=[];var re=/\[附件\]\s*(\S+)/g;var m;
      while((m=re.exec(content))!==null){files.push({name:m[1].split(/[\/]/).pop(),type:"file"});}
      return files.length?files:undefined;
    }

    // ── Settings ──
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

function appendAgentReasoning(text){
      if(!agentResponseConvId)agentResponseConvId=currentConvId;
      if(agentResponseConvId!==currentConvId)return;
      // Show reasoning inline - append to a thinking section
      var area=document.getElementById('messageArea');
      if(!area)return;
      var lastMsgEl=area.lastElementChild;
      var thinkingEl=null;
      if(lastMsgEl&&lastMsgEl.classList.contains('msg-ai')){
        thinkingEl=lastMsgEl.querySelector('.msg-thinking');
        if(!thinkingEl){
          thinkingEl=document.createElement('div');thinkingEl.className='msg-thinking';
          thinkingEl.style.cssText='font-size:12px;color:var(--fg-muted);font-style:italic;padding:4px 0;cursor:pointer';
          thinkingEl.textContent='思考过程 ▸';
          var bodyEl=document.createElement('div');bodyEl.className='thinking-body';
          bodyEl.style.cssText='display:none;font-size:12px;color:var(--fg-muted);font-style:italic;padding:4px 8px;background:var(--rose-surface);border-radius:6px;margin:4px 0';
          bodyEl.textContent=text;
          thinkingEl._body=bodyEl;
          thinkingEl.onclick=function(){var b=this._body;var o=b.style.display!=='block';b.style.display=o?'block':'none';this.textContent=o?'思考过程 ▾':'思考过程 ▸';};
          lastMsgEl.insertBefore(bodyEl,lastMsgEl.querySelector('.msg-bubble'));
          lastMsgEl.insertBefore(thinkingEl,bodyEl);
        }else{
          var body=thinkingEl._body;
          if(body)body.textContent+=text;
        }
      }
      // Also update data model
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last.role==='ai'){last.thinking=(last.thinking||'')+text;}
      }
    }
    function showToolCall(name){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      conv.messages.push({role:'tool-bubble',toolName:name,completed:false,timestamp:Date.now()});
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function showToolResult(text){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      var msgs=conv.messages;
      for(var i=msgs.length-1;i>=0;i--){
        if(msgs[i].role==='tool-bubble'&&!msgs[i].completed){
          msgs[i].result={text:text};
          msgs[i].completed=true;
          break;
        }
      }
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function showSystemMsg(text){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      conv.messages.push({role:'system',text:text,timestamp:Date.now()});
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function finishAgentResponse(){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last._streaming){delete last._streaming;}
        renderMessages(conv.messages);
      }
      setConnectionStatus('connected');
      agentResponseConvId=null;
    }
    function loadSessions(sessions){
      // Convert backend sessions to design's Conversation format
      CONVERSATIONS.length=0;
      sessions.forEach(function(s,i){
        CONVERSATIONS.push({
          id:'s'+s.id, title:s.title||('Session #'+s.id), preview:'', time:s.created_at||'',
          unread:0, avatar:'💬', color:'slate', pinned:false, messages:[]
        });
      });
      renderConversations();
      // Select first session if none selected
      currentConvId=null;if(CONVERSATIONS.length){selectConversation(CONVERSATIONS[0].id);}
    }

    function loadSessionMessages(sessionId,title,msgs){
      var conv=CONVERSATIONS.find(function(c){return c.id==='s'+sessionId});
      if(!conv)return;
      conv.messages=[];
      conv.title=title||conv.title;
      msgs.forEach(function(m){
        if(m.role==='user'){
          conv.messages.push({role:'user',text:extractText(m.content||''),timestamp:m.created_at,attachments:extractAttachments(m.content)});
        }else if(m.role==='agent'){
          conv.messages.push({role:'ai',text:m.content||'',timestamp:m.created_at,thinking:m.reasoning||''});
        }else if(m.role==='tool'&&m.tool_name){
          var result='';try{var j=JSON.parse(m.content);result=j.result||''}catch(e){result=m.content||''}
          conv.messages.push({role:'tool-bubble',toolName:m.tool_name,result:{text:result.slice(0,300)},completed:true,timestamp:m.created_at});
        }
      });
      // Ensure currentConvId matches
      if(currentConvId!=='s'+sessionId){currentConvId='s'+sessionId;renderConversations();}
      renderMessages(conv.messages);
      // Update header
      var h=document.querySelector('.conv-title');if(h)h.textContent=conv.title;
    }

    function extractText(content){
      var idx=content.indexOf('[附件]');
      return idx>=0?content.slice(0,idx).trim():content;
    }
    function extractAttachments(content){
      var files=[];var re=/\[附件\]\s*(\S+)/g;var m;
      while((m=re.exec(content))!==null){files.push({name:m[1].split(/[\/]/).pop(),type:"file"});}
      return files.length?files:undefined;
    }

    // ── Settings ──
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

function showToolCall(name){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      conv.messages.push({role:'tool-bubble',toolName:name,completed:false,timestamp:Date.now()});
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function showToolResult(text){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      var msgs=conv.messages;
      for(var i=msgs.length-1;i>=0;i--){
        if(msgs[i].role==='tool-bubble'&&!msgs[i].completed){
          msgs[i].result={text:text};
          msgs[i].completed=true;
          break;
        }
      }
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function showSystemMsg(text){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      conv.messages.push({role:'system',text:text,timestamp:Date.now()});
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function finishAgentResponse(){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last._streaming){delete last._streaming;}
        renderMessages(conv.messages);
      }
      setConnectionStatus('connected');
      agentResponseConvId=null;
    }
    function loadSessions(sessions){
      // Convert backend sessions to design's Conversation format
      CONVERSATIONS.length=0;
      sessions.forEach(function(s,i){
        CONVERSATIONS.push({
          id:'s'+s.id, title:s.title||('Session #'+s.id), preview:'', time:s.created_at||'',
          unread:0, avatar:'💬', color:'slate', pinned:false, messages:[]
        });
      });
      renderConversations();
      // Select first session if none selected
      currentConvId=null;if(CONVERSATIONS.length){selectConversation(CONVERSATIONS[0].id);}
    }

    function loadSessionMessages(sessionId,title,msgs){
      var conv=CONVERSATIONS.find(function(c){return c.id==='s'+sessionId});
      if(!conv)return;
      conv.messages=[];
      conv.title=title||conv.title;
      msgs.forEach(function(m){
        if(m.role==='user'){
          conv.messages.push({role:'user',text:extractText(m.content||''),timestamp:m.created_at,attachments:extractAttachments(m.content)});
        }else if(m.role==='agent'){
          conv.messages.push({role:'ai',text:m.content||'',timestamp:m.created_at,thinking:m.reasoning||''});
        }else if(m.role==='tool'&&m.tool_name){
          var result='';try{var j=JSON.parse(m.content);result=j.result||''}catch(e){result=m.content||''}
          conv.messages.push({role:'tool-bubble',toolName:m.tool_name,result:{text:result.slice(0,300)},completed:true,timestamp:m.created_at});
        }
      });
      // Ensure currentConvId matches
      if(currentConvId!=='s'+sessionId){currentConvId='s'+sessionId;renderConversations();}
      renderMessages(conv.messages);
      // Update header
      var h=document.querySelector('.conv-title');if(h)h.textContent=conv.title;
    }

    function extractText(content){
      var idx=content.indexOf('[附件]');
      return idx>=0?content.slice(0,idx).trim():content;
    }
    function extractAttachments(content){
      var files=[];var re=/\[附件\]\s*(\S+)/g;var m;
      while((m=re.exec(content))!==null){files.push({name:m[1].split(/[\/]/).pop(),type:"file"});}
      return files.length?files:undefined;
    }

    // ── Settings ──
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

function showToolResult(text){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      var msgs=conv.messages;
      for(var i=msgs.length-1;i>=0;i--){
        if(msgs[i].role==='tool-bubble'&&!msgs[i].completed){
          msgs[i].result={text:text};
          msgs[i].completed=true;
          break;
        }
      }
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function showSystemMsg(text){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      conv.messages.push({role:'system',text:text,timestamp:Date.now()});
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function finishAgentResponse(){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last._streaming){delete last._streaming;}
        renderMessages(conv.messages);
      }
      setConnectionStatus('connected');
      agentResponseConvId=null;
    }
    function loadSessions(sessions){
      // Convert backend sessions to design's Conversation format
      CONVERSATIONS.length=0;
      sessions.forEach(function(s,i){
        CONVERSATIONS.push({
          id:'s'+s.id, title:s.title||('Session #'+s.id), preview:'', time:s.created_at||'',
          unread:0, avatar:'💬', color:'slate', pinned:false, messages:[]
        });
      });
      renderConversations();
      // Select first session if none selected
      currentConvId=null;if(CONVERSATIONS.length){selectConversation(CONVERSATIONS[0].id);}
    }

    function loadSessionMessages(sessionId,title,msgs){
      var conv=CONVERSATIONS.find(function(c){return c.id==='s'+sessionId});
      if(!conv)return;
      conv.messages=[];
      conv.title=title||conv.title;
      msgs.forEach(function(m){
        if(m.role==='user'){
          conv.messages.push({role:'user',text:extractText(m.content||''),timestamp:m.created_at,attachments:extractAttachments(m.content)});
        }else if(m.role==='agent'){
          conv.messages.push({role:'ai',text:m.content||'',timestamp:m.created_at,thinking:m.reasoning||''});
        }else if(m.role==='tool'&&m.tool_name){
          var result='';try{var j=JSON.parse(m.content);result=j.result||''}catch(e){result=m.content||''}
          conv.messages.push({role:'tool-bubble',toolName:m.tool_name,result:{text:result.slice(0,300)},completed:true,timestamp:m.created_at});
        }
      });
      // Ensure currentConvId matches
      if(currentConvId!=='s'+sessionId){currentConvId='s'+sessionId;renderConversations();}
      renderMessages(conv.messages);
      // Update header
      var h=document.querySelector('.conv-title');if(h)h.textContent=conv.title;
    }

    function extractText(content){
      var idx=content.indexOf('[附件]');
      return idx>=0?content.slice(0,idx).trim():content;
    }
    function extractAttachments(content){
      var files=[];var re=/\[附件\]\s*(\S+)/g;var m;
      while((m=re.exec(content))!==null){files.push({name:m[1].split(/[\/]/).pop(),type:"file"});}
      return files.length?files:undefined;
    }

    // ── Settings ──
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

function showSystemMsg(text){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(!conv)return;
      conv.messages.push({role:'system',text:text,timestamp:Date.now()});
      renderMessages(conv.messages);
      scrollToBottom();
    }
    function finishAgentResponse(){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last._streaming){delete last._streaming;}
        renderMessages(conv.messages);
      }
      setConnectionStatus('connected');
      agentResponseConvId=null;
    }
    function loadSessions(sessions){
      // Convert backend sessions to design's Conversation format
      CONVERSATIONS.length=0;
      sessions.forEach(function(s,i){
        CONVERSATIONS.push({
          id:'s'+s.id, title:s.title||('Session #'+s.id), preview:'', time:s.created_at||'',
          unread:0, avatar:'💬', color:'slate', pinned:false, messages:[]
        });
      });
      renderConversations();
      // Select first session if none selected
      currentConvId=null;if(CONVERSATIONS.length){selectConversation(CONVERSATIONS[0].id);}
    }

    function loadSessionMessages(sessionId,title,msgs){
      var conv=CONVERSATIONS.find(function(c){return c.id==='s'+sessionId});
      if(!conv)return;
      conv.messages=[];
      conv.title=title||conv.title;
      msgs.forEach(function(m){
        if(m.role==='user'){
          conv.messages.push({role:'user',text:extractText(m.content||''),timestamp:m.created_at,attachments:extractAttachments(m.content)});
        }else if(m.role==='agent'){
          conv.messages.push({role:'ai',text:m.content||'',timestamp:m.created_at,thinking:m.reasoning||''});
        }else if(m.role==='tool'&&m.tool_name){
          var result='';try{var j=JSON.parse(m.content);result=j.result||''}catch(e){result=m.content||''}
          conv.messages.push({role:'tool-bubble',toolName:m.tool_name,result:{text:result.slice(0,300)},completed:true,timestamp:m.created_at});
        }
      });
      // Ensure currentConvId matches
      if(currentConvId!=='s'+sessionId){currentConvId='s'+sessionId;renderConversations();}
      renderMessages(conv.messages);
      // Update header
      var h=document.querySelector('.conv-title');if(h)h.textContent=conv.title;
    }

    function extractText(content){
      var idx=content.indexOf('[附件]');
      return idx>=0?content.slice(0,idx).trim():content;
    }
    function extractAttachments(content){
      var files=[];var re=/\[附件\]\s*(\S+)/g;var m;
      while((m=re.exec(content))!==null){files.push({name:m[1].split(/[\/]/).pop(),type:"file"});}
      return files.length?files:undefined;
    }

    // ── Settings ──
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

function finishAgentResponse(){
      var conv=CONVERSATIONS.find(function(c){return c.id===currentConvId});
      if(conv){
        var msgs=conv.messages;
        var last=msgs.length?msgs[msgs.length-1]:null;
        if(last&&last._streaming){delete last._streaming;}
        renderMessages(conv.messages);
      }
      setConnectionStatus('connected');
      agentResponseConvId=null;
    }
    function loadSessions(sessions){
      // Convert backend sessions to design's Conversation format
      CONVERSATIONS.length=0;
      sessions.forEach(function(s,i){
        CONVERSATIONS.push({
          id:'s'+s.id, title:s.title||('Session #'+s.id), preview:'', time:s.created_at||'',
          unread:0, avatar:'💬', color:'slate', pinned:false, messages:[]
        });
      });
      renderConversations();
      // Select first session if none selected
      currentConvId=null;if(CONVERSATIONS.length){selectConversation(CONVERSATIONS[0].id);}
    }

    function loadSessionMessages(sessionId,title,msgs){
      var conv=CONVERSATIONS.find(function(c){return c.id==='s'+sessionId});
      if(!conv)return;
      conv.messages=[];
      conv.title=title||conv.title;
      msgs.forEach(function(m){
        if(m.role==='user'){
          conv.messages.push({role:'user',text:extractText(m.content||''),timestamp:m.created_at,attachments:extractAttachments(m.content)});
        }else if(m.role==='agent'){
          conv.messages.push({role:'ai',text:m.content||'',timestamp:m.created_at,thinking:m.reasoning||''});
        }else if(m.role==='tool'&&m.tool_name){
          var result='';try{var j=JSON.parse(m.content);result=j.result||''}catch(e){result=m.content||''}
          conv.messages.push({role:'tool-bubble',toolName:m.tool_name,result:{text:result.slice(0,300)},completed:true,timestamp:m.created_at});
        }
      });
      // Ensure currentConvId matches
      if(currentConvId!=='s'+sessionId){currentConvId='s'+sessionId;renderConversations();}
      renderMessages(conv.messages);
      // Update header
      var h=document.querySelector('.conv-title');if(h)h.textContent=conv.title;
    }

    function extractText(content){
      var idx=content.indexOf('[附件]');
      return idx>=0?content.slice(0,idx).trim():content;
    }
    function extractAttachments(content){
      var files=[];var re=/\[附件\]\s*(\S+)/g;var m;
      while((m=re.exec(content))!==null){files.push({name:m[1].split(/[\/]/).pop(),type:"file"});}
      return files.length?files:undefined;
    }

    // ── Settings ──
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

function loadSessions(sessions){
      // Convert backend sessions to design's Conversation format
      CONVERSATIONS.length=0;
      sessions.forEach(function(s,i){
        CONVERSATIONS.push({
          id:'s'+s.id, title:s.title||('Session #'+s.id), preview:'', time:s.created_at||'',
          unread:0, avatar:'💬', color:'slate', pinned:false, messages:[]
        });
      });
      renderConversations();
      // Select first session if none selected
      currentConvId=null;if(CONVERSATIONS.length){selectConversation(CONVERSATIONS[0].id);}
    }

    function loadSessionMessages(sessionId,title,msgs){
      var conv=CONVERSATIONS.find(function(c){return c.id==='s'+sessionId});
      if(!conv)return;
      conv.messages=[];
      conv.title=title||conv.title;
      msgs.forEach(function(m){
        if(m.role==='user'){
          conv.messages.push({role:'user',text:extractText(m.content||''),timestamp:m.created_at,attachments:extractAttachments(m.content)});
        }else if(m.role==='agent'){
          conv.messages.push({role:'ai',text:m.content||'',timestamp:m.created_at,thinking:m.reasoning||''});
        }else if(m.role==='tool'&&m.tool_name){
          var result='';try{var j=JSON.parse(m.content);result=j.result||''}catch(e){result=m.content||''}
          conv.messages.push({role:'tool-bubble',toolName:m.tool_name,result:{text:result.slice(0,300)},completed:true,timestamp:m.created_at});
        }
      });
      // Ensure currentConvId matches
      if(currentConvId!=='s'+sessionId){currentConvId='s'+sessionId;renderConversations();}
      renderMessages(conv.messages);
      // Update header
      var h=document.querySelector('.conv-title');if(h)h.textContent=conv.title;
    }

    function extractText(content){
      var idx=content.indexOf('[附件]');
      return idx>=0?content.slice(0,idx).trim():content;
    }
    function extractAttachments(content){
      var files=[];var re=/\[附件\]\s*(\S+)/g;var m;
      while((m=re.exec(content))!==null){files.push({name:m[1].split(/[\/]/).pop(),type:"file"});}
      return files.length?files:undefined;
    }

    // ── Settings ──
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

function loadSessionMessages(sessionId,title,msgs){
      var conv=CONVERSATIONS.find(function(c){return c.id==='s'+sessionId});
      if(!conv)return;
      conv.messages=[];
      conv.title=title||conv.title;
      msgs.forEach(function(m){
        if(m.role==='user'){
          conv.messages.push({role:'user',text:extractText(m.content||''),timestamp:m.created_at,attachments:extractAttachments(m.content)});
        }else if(m.role==='agent'){
          conv.messages.push({role:'ai',text:m.content||'',timestamp:m.created_at,thinking:m.reasoning||''});
        }else if(m.role==='tool'&&m.tool_name){
          var result='';try{var j=JSON.parse(m.content);result=j.result||''}catch(e){result=m.content||''}
          conv.messages.push({role:'tool-bubble',toolName:m.tool_name,result:{text:result.slice(0,300)},completed:true,timestamp:m.created_at});
        }
      });
      // Ensure currentConvId matches
      if(currentConvId!=='s'+sessionId){currentConvId='s'+sessionId;renderConversations();}
      renderMessages(conv.messages);
      // Update header
      var h=document.querySelector('.conv-title');if(h)h.textContent=conv.title;
    }

    function extractText(content){
      var idx=content.indexOf('[附件]');
      return idx>=0?content.slice(0,idx).trim():content;
    }
    function extractAttachments(content){
      var files=[];var re=/\[附件\]\s*(\S+)/g;var m;
      while((m=re.exec(content))!==null){files.push({name:m[1].split(/[\/]/).pop(),type:"file"});}
      return files.length?files:undefined;
    }

    // ── Settings ──
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

function extractText(content){
      var idx=content.indexOf('[附件]');
      return idx>=0?content.slice(0,idx).trim():content;
    }
    function extractAttachments(content){
      var files=[];var re=/\[附件\]\s*(\S+)/g;var m;
      while((m=re.exec(content))!==null){files.push({name:m[1].split(/[\/]/).pop(),type:"file"});}
      return files.length?files:undefined;
    }

    // ── Settings ──
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

function extractAttachments(content){
      var files=[];var re=/\[附件\]\s*(\S+)/g;var m;
      while((m=re.exec(content))!==null){files.push({name:m[1].split(/[\/]/).pop(),type:"file"});}
      return files.length?files:undefined;
    }

    // ── Settings ──
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

function sendMessage() {
      const input = document.getElementById('chatInput');
      const text = input.value.trim();
      if (!text || isProcessing) return;

      const conv = CONVERSATIONS.find(c => c.id === currentConvId);
      if (!conv) return;

      // 清空附件
      const attachments = currentAttachments;
      currentAttachments = [];
      renderAttachments();

      // 添加到消息（带时间戳）
      var userMsg = { role: 'user', text: text, timestamp: Date.now() };
      if (attachments.length > 0) {
        userMsg.image = attachments[0].dataUrl || attachments[0].name;
      }
      conv.messages.push(userMsg);

      // 更新预览和时间
      conv.preview = text;
      conv.time = '刚刚';

      // 重新渲染
      const welcome = document.getElementById('welcomeScreen');
      welcome.style.display = 'none';
      renderMessages(conv.messages);
      scrollToBottom();

      input.value = '';
      input.style.height = 'auto';

      // 更新列表
      renderConversations(document.getElementById('searchInput').value);

      // —— 上传文件并开始处理 ——
      var self=this;
      uploadPendingFiles().then(function(filePaths){
        if(filePaths&&filePaths.length){
          // Append file paths to last user message's text
          var lastMsg=conv.messages[conv.messages.length-1];
          if(lastMsg&&lastMsg.role==='user'){
            lastMsg.text+="\n[附件] "+filePaths.join(", ");
          }
        }
        sendMessageInternal(conv);
      });
      return;
    }

function sendMessageInternal(conv) {
      if(ws&&conv&&conv.messages.length){var lastMsg=conv.messages[conv.messages.length-1];if(lastMsg.role==="user"){ws.send(JSON.stringify({type:"message",data:lastMsg.text}));}}
      setConnectionStatus("processing");
      return;
    }

function cancelProcessing() {
      if(ws)ws.send(JSON.stringify({type:"stop"}));
      setConnectionStatus("connected");
      if (!isProcessing) return;
      abortPending = true;
      if (pendingTimeout) {
        clearTimeout(pendingTimeout);
        pendingTimeout = null;
      }
      // 移除所有进行中的 tool-bubble
      document.querySelectorAll('.tool-bubble').forEach(el => {
        if (el.querySelector('.spinner-sm')) el.remove();
      });
      // 从会话数据中移除未完成的 tool-bubble 消息
      var conv = CONVERSATIONS.find(function(c) { return c.id === currentConvId; });
      if (conv) {
        conv.messages = conv.messages.filter(function(m) {
          return !(m.role === 'tool-bubble' && !m.completed);
        });
        renderMessages(conv.messages);
      }
      // 移除打字指示器
      hideTypingIndicator();
      finishProcessing();
    }

function finishProcessing() {
      isProcessing = false;
      abortPending = false;
      pendingTimeout = null;
      setConnectionStatus('online');
      updateSendButton(false);
      document.getElementById('sendBtn').disabled = document.getElementById('chatInput').value.trim().length === 0;
    }

function uploadPendingFiles(){
      var promises=[];
      currentAttachments.forEach(function(att){
        if(att.file){
          var fd=new FormData();
          fd.append('file',att.file,att.name);
          promises.push(fetch('/upload',{method:'POST',body:fd,headers:{'X-Filename':att.name}}).then(function(r){return r.json()}).then(function(d){return d.path}).catch(function(){return null}));
        }else if(att.dataUrl&&att.isImage){
          // For base64 images, convert to blob and upload
          var byteString=atob(att.dataUrl.split(',')[1]);
          var ab=new ArrayBuffer(byteString.length);
          var ia=new Uint8Array(ab);
          for(var i=0;i<byteString.length;i++){ia[i]=byteString.charCodeAt(i);}
          var blob=new Blob([ab],{type:'image/png'});
          var fd=new FormData();fd.append('file',blob,att.name);
          promises.push(fetch('/upload',{method:'POST',body:fd,headers:{'X-Filename':att.name}}).then(function(r){return r.json()}).then(function(d){return d.path}).catch(function(){return null}));
        }
      });
      return Promise.all(promises).then(function(paths){return paths.filter(function(p){return p});});
    }
