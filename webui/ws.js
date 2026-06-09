// EchoLily — WebSocket communication + agent response
// Loaded second (depends on render.js)

const WS_URL="ws://127.0.0.1:8081";
var ws=null;
var currentSessionId=null;   // current DB session id (numeric)
var isNewSession=false;      // true while current conversation hasn't been saved yet

// ── Connection status ──
function setConnectionStatus(status) {
  const dots = document.querySelectorAll('.dot, .connection-dot');
  dots.forEach(function (el) {
    el.classList.remove('online', 'offline', 'processing');
    el.classList.add(status);
  });
  var headerText = document.getElementById('headerStatusText');
  if (headerText) {
    var labels = { 'online': '已连接', 'offline': '离线', 'processing': '处理中' };
    headerText.textContent = labels[status] || '未知';
  }
  var settingsConn = document.getElementById('settingsConnStatus');
  if (settingsConn) {
    var connLabels = { 'online': '已连接', 'offline': '离线', 'processing': '处理中' };
    settingsConn.textContent = connLabels[status] || '未知';
    settingsConn.style.color = connLabels[status] ? 'var(--' + connLabels[status].replace('已','').replace('处','').replace('离','') + ')' : 'var(--fg-muted)';
  }
}

// ── WebSocket ──
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
      case "sessions":loadSessions(ev.data);break;
      case "session_msgs":loadSessionMessages(ev.data);break;
      case "token":appendAgentToken(ev.data||"");break;
      case "reasoning_token":appendAgentReasoning(ev.data||"");break;
      case "tool_call":showToolCall(ev.name||"");break;
      case "tool_result":showToolResult((ev.result||"").toString().slice(0,200));break;
      case "error":showSystemMsg("⚠ "+(ev.data||""));break;
      case "complete":case "done":finishAgentResponse();break;
      case "ready":setConnectionStatus('connected');break;
      case "config_json":renderConfigForm(ev.data||{});break;
      case "config_saved":var sb=document.getElementById("btn-save-config");if(sb)sb.textContent="已保存";break;
      case "new_session_created":
        if(isNewSession){
          currentSessionId=ev.session_id;
          isNewSession=false;
        }
        loadSessions(null);
        break;
    }
  };
  ws.onclose=function(){setConnectionStatus('offline');setTimeout(connectWS,2000);};
  ws.onerror=function(){ws.close();};
}

// ── Session list (sidebar) ──
var CONVERSATIONS=[];

function loadSessions(sessions){
  if(!sessions)return; // just refresh, data unchanged
  CONVERSATIONS.length=0;
  sessions.forEach(function(s){
    CONVERSATIONS.push({
      id:'s'+s.id, title:s.title||('Session #'+s.id), preview:'',
      time:s.created_at||'', unread:0, avatar:'💬', color:'slate', pinned:false
    });
  });
  renderConversations();
  // Select first session if none selected
  if(!currentSessionId&&CONVERSATIONS.length){
    switchToSession(parseInt(CONVERSATIONS[0].id.slice(1)));
  }
}

function loadSessionMessages(msgs){
  if(!msgs||!msgs.length){return;}
  // Clear existing messages
  var area=document.getElementById('messageArea');
  if(area)area.innerHTML='';
  hideTypingIndicator();
  // Render each message from DB
  msgs.forEach(function(m){
    if(m.role==='user'){
      var text=m.content||'';
      var idx=text.indexOf('[附件]');
      var clean=idx>=0?text.slice(0,idx).trim():text;
      appendUserMessage(clean);
    }else if(m.role==='agent'){
      appendAgentMessage(m.content||'',m.reasoning||'');
    }else if(m.role==='tool'&&m.tool_name){
      var result='';
      try{var j=JSON.parse(m.content||'{}');result=j.result||''}catch(e){result=m.content||''}
      showToolComplete(m.tool_name,result.slice(0,200));
    }
  });
  scrollToBottom();
}

// ── Session switching (called from renderConversations) ──
function switchToSession(sessionId){
  if(isProcessing){cancelProcessing();}
  currentSessionId=sessionId;
  isNewSession=false;
  var welcome=document.getElementById('welcomeScreen');
  if(welcome)welcome.style.display='none';
  var area=document.getElementById('messageArea');
  if(area)area.innerHTML='';
  // Update header
  var conv=CONVERSATIONS.find(function(c){return c.id==='s'+sessionId});
  var title=conv?conv.title:'Session #'+sessionId;
  document.getElementById('chatTitle').textContent=title;
  // Load messages from server
  if(ws){ws.send(JSON.stringify({type:"switch_session",id:sessionId}));}
  if(ws){ws.send(JSON.stringify({type:"get_session",id:sessionId}));}
}

// ── New conversation ──
function createNewConversation(){
  if(isProcessing)return;
  // Clear chat UI
  var area=document.getElementById('messageArea');
  if(area)area.innerHTML='';
  var welcome=document.getElementById('welcomeScreen');
  if(welcome)welcome.style.display='none';
  document.getElementById('chatTitle').textContent='新对话';
  // Set local state
  currentSessionId=null;
  isNewSession=true;
  // Update sidebar — remove active highlight
  document.querySelectorAll('.conv-item').forEach(function(el){el.classList.remove('active');});
  document.getElementById('chatInput').focus();
}

// ── Send message ──
function sendMessage(){
  var input=document.getElementById('chatInput');
  var text=input.value.trim();
  if(!text||isProcessing||!ws)return;
  input.value='';
  input.style.height='auto';
  // Clear welcome
  document.getElementById('welcomeScreen').style.display='none';
  // Show user message
  appendUserMessage(text);
  // If unsaved new session, create server session first
  if(isNewSession){
    ws.send(JSON.stringify({type:"new_session"}));
    ws._pendingMsg=text;
    isProcessing=true;
    setConnectionStatus('processing');
    return;
  }
  // Normal send
  ws.send(JSON.stringify({type:"message",data:text}));
  isProcessing=true;
  setConnectionStatus('processing');
}

// ── Response from send after new_session_created ──
// Handled in ws.onmessage: new_session_created case

// ── Agent response — direct DOM rendering ──
var agentResponseConvId=null;

function appendUserMessage(text){
  var area=document.getElementById('messageArea');
  if(!area)return;
  var div=document.createElement('div');div.className='message user';
  div.innerHTML='<div class="msg-avatar">你</div><div><div class="msg-bubble"><div class="msg-content">'+escHtml(text)+'</div></div></div>';
  area.appendChild(div);
}

function appendAgentMessage(text,reasoning){
  var area=document.getElementById('messageArea');
  if(!area)return;
  var div=document.createElement('div');div.className='message ai';
  var thinkingHtml=reasoning?'<div class="msg-thinking" data-expanded="false"><div class="thinking-toggle"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg> 思考过程</div><div class="thinking-text">'+escHtml(reasoning)+'</div></div>':'';
  var textHtml=window.marked?marked.parse(text):escHtml(text);
  div.innerHTML='<div class="msg-avatar">❄</div><div>'+thinkingHtml+'<div class="msg-bubble"><div class="msg-content">'+textHtml+'</div></div></div>';
  area.appendChild(div);
  renderMermaid(div);
}

function appendAgentToken(text){
  if(!agentResponseConvId)agentResponseConvId='active';
  var area=document.getElementById('messageArea');
  if(!area)return;
  var last=area.lastElementChild;
  if(last&&last.classList.contains('message')&&last.classList.contains('ai')){
    var bubble=last.querySelector('.msg-content');
    if(bubble){
      if(!bubble._fullText)bubble._fullText='';
      bubble._fullText+=text;
      if(window.marked){
        try{bubble.innerHTML=marked.parse(bubble._fullText)}catch(e){bubble.textContent=bubble._fullText}
      }else{
        bubble.textContent=bubble._fullText;
      }
      scrollToBottom();
      return;
    }
  }
  // No existing AI message — create one
  var div=document.createElement('div');div.className='message ai';
  div.innerHTML='<div class="msg-avatar">❄</div><div><div class="msg-bubble"><div class="msg-content"></div></div></div>';
  area.appendChild(div);
  var bubble=div.querySelector('.msg-content');
  if(bubble){
    bubble._fullText=text;
    if(window.marked){try{bubble.innerHTML=marked.parse(text)}catch(e){bubble.textContent=text}}else{bubble.textContent=text}
  }
  scrollToBottom();
}

function appendAgentReasoning(text){
  var area=document.getElementById('messageArea');
  if(!area)return;
  var last=area.lastElementChild;
  if(!last||!last.classList.contains('ai')&&!last.classList.contains('message'))return;
  var thinkingBody=last.querySelector('.thinking-text');
  if(thinkingBody){
    thinkingBody.textContent+=text;
  }else{
    var toggle=document.createElement('div');toggle.className='msg-thinking';toggle.dataset.expanded='false';
    toggle.innerHTML='<div class="thinking-toggle"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg> 思考过程</div><div class="thinking-text">'+escHtml(text)+'</div>';
    var bubble=last.querySelector('.msg-bubble');
    if(bubble){bubble.parentNode.insertBefore(toggle,bubble);}
  }
  scrollToBottom();
}

function showToolCall(name){
  var area=document.getElementById('messageArea');
  if(!area)return;
  var div=document.createElement('div');div.className='message tool-bubble';
  div.innerHTML='<div class="msg-avatar" style="background:oklch(75% 0.01 250/0.3);color:var(--fg-muted);font-size:13px;">⚙</div><div><div class="msg-bubble"><div class="tool-bubble-header"><span class="spinner-sm"></span> '+escHtml(name)+'</div></div></div>';
  area.appendChild(div);
  scrollToBottom();
}

function showToolResult(text){
  var area=document.getElementById('messageArea');
  if(!area)return;
  var last=area.lastElementChild;
  if(last&&last.classList.contains('tool-bubble')){
    var header=last.querySelector('.tool-bubble-header');
    if(header)header.innerHTML='<span style="color:#10B981;">✓</span> '+header.textContent.replace(/^\s*/, '');
    var resultDiv=document.createElement('div');resultDiv.textContent='→ '+text;
    resultDiv.style.cssText='font-size:12px;color:var(--fg-muted);padding:4px 0;border-top:1px solid var(--border-glass);margin-top:4px';
    last.querySelector('.msg-bubble').appendChild(resultDiv);
  }
  scrollToBottom();
}

function showToolComplete(name,result){
  var area=document.getElementById('messageArea');
  if(!area)return;
  var div=document.createElement('div');div.className='message tool-bubble';
  div.innerHTML='<div class="msg-avatar" style="background:oklch(75% 0.01 250/0.3);color:var(--fg-muted);font-size:13px;">⚙</div><div><div class="msg-bubble"><div class="tool-bubble-header"><span style="color:#10B981;">✓</span> '+escHtml(name)+'</div><div class="tool-result-short" style="font-size:12px;color:var(--fg-muted);padding:4px 0;border-top:1px solid var(--border-glass);margin-top:4px">'+escHtml(result)+'</div></div></div>';
  area.appendChild(div);
  scrollToBottom();
}

function showSystemMsg(text){
  var area=document.getElementById('messageArea');
  if(!area)return;
  var div=document.createElement('div');div.className='message system';
  div.innerHTML='<div class="msg-bubble" style="background:var(--rose-surface);border-radius:8px;font-size:13px;text-align:center;padding:8px 16px;color:var(--fg-primary)">'+escHtml(text)+'</div>';
  area.appendChild(div);
  scrollToBottom();
}

function finishAgentResponse(){
  agentResponseConvId=null;
  setConnectionStatus('connected');
  // Re-render the last AI message with full markdown
  var area=document.getElementById('messageArea');
  if(!area)return;
  var last=area.lastElementChild;
  if(last&&last.classList.contains('ai')){
    var bubble=last.querySelector('.msg-content');
    if(bubble&&bubble._fullText&&window.marked){
      try{bubble.innerHTML=marked.parse(bubble._fullText);renderMermaid(bubble)}catch(e){}
    }
  }
  // If this was a pending new session message, send it now
  if(ws&&ws._pendingMsg){
    var msg=ws._pendingMsg;ws._pendingMsg=null;
    ws.send(JSON.stringify({type:"message",data:msg}));
  }
}

// ── Cancel / processing state ──
var isProcessing=false;
var abortPending=false;

function cancelProcessing(){
  if(ws)ws.send(JSON.stringify({type:"stop"}));
  setConnectionStatus('connected');
  isProcessing=false;
  abortPending=false;
  // Remove in-progress tool bubbles
  document.querySelectorAll('.tool-bubble').forEach(function(el){
    if(el.querySelector('.spinner-sm'))el.remove();
  });
}

// ── Typing indicator ──
function showTypingIndicator(){
  var area=document.getElementById('messageArea');
  if(!area||document.getElementById('typingIndicator'))return;
  var div=document.createElement('div');div.className='message ai';div.id='typingIndicator';
  div.innerHTML='<div class="msg-avatar">❄</div><div><div class="msg-bubble msg-typing"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div></div>';
  area.appendChild(div);scrollToBottom();
}
function hideTypingIndicator(){
  var el=document.getElementById('typingIndicator');
  if(el)el.remove();
}

// ── File upload ──
function uploadPendingFiles(){
  var input=document.getElementById('fileInput');
  if(!input||!input.files||!input.files.length)return Promise.resolve([]);
  var promises=[];
  Array.from(input.files).forEach(function(file){
    var maxSize=20*1024*1024;
    if(file.size>maxSize)return;
    promises.push(
      fetch('/upload',{method:'POST',headers:{'X-Filename':encodeURIComponent(file.name),'Content-Type':'application/octet-stream'},body:file})
        .then(function(r){return r.json()})
        .then(function(d){return d.path})
        .catch(function(){return null})
    );
  });
  input.value='';
  return Promise.all(promises).then(function(paths){return paths.filter(function(p){return p});});
}
