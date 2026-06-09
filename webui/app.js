// EchoLily — 主应用逻辑

    /* ============================================================
       数据
       ============================================================ */
    // ── WebSocket connection ──
const WS_URL="ws://127.0.0.1:8081";
var ws=null;
var currentSessionId=null;

// ── Markdown / Mermaid rendering ──
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


const CONVERSATIONS = [
      { id: 'c1', title: '冬日诗稿创作',   preview: '雪落在寂静的庭院里，我听见…', time: '刚刚',   unread: 2, avatar: '❄️', color: 'rose',  pinned: false, messages: [
        { role: 'user', text: '帮我写一首关于冬日玫瑰的小诗' },
        { role: 'ai',   text: '雪的重量压低了枝头，\n玫瑰在寂静中燃烧。\n白与红，冷与暖，\n在相遇的瞬间达成了永恒。',
          thinking: '用户想要一首冬日主题的诗，意象需要同时包含「雪」和「玫瑰」的对比。可以用「雪的重量」和「寂静中燃烧」来表现冷与暖的张力，结尾需要落在二者关系的哲学意味上。' },
        { role: 'user', text: '再改一版，更简练一点，像俳句那样' },
        { role: 'ai',   text: '雪压枝低，\n一朵红，\n烧破了冬。',
          thinking: '用户要求简练如俳句。需要保留核心意象（雪、枝、红），但用最短的句式。三行结构对应俳句的 5-7-5 节奏感，「烧破」比「燃烧」更有画面冲击力。' },
        { role: 'user', text: '帮我查一下古典诗词中雪与花的意象对比，然后结合这些创作一首短诗' },
        { role: 'ai',
          text: '好的，我先搜索相关的古典诗词文献，看看有哪些经典的雪与花意象可以参考。',
          thinking: '用户想要两步操作：先搜索文献再创作诗歌。我需要先用工具检索知识库获取数据，再提炼意象进行创作。搜索范围应该覆盖唐宋诗词中雪与花的经典对比。',
          timestamp: Date.now() + 200000,
          model: '雪覆红玫·1.0',
          tokens: 28,
          duration: 1.3 },
        { role: 'tool-bubble', toolName: '🔍 搜索知识库', completed: true, timestamp: Date.now() + 202000, params: { query: '古典诗词 雪 意象 对比', limit: 10, source: 'poetry-db' }, result: { total: 32, matches: ['白居易《夜雪》', '卢梅坡《雪梅》', '王安石《梅花》', '王冕《墨梅》'], summary: '雪与花的对比意象集中在唐宋时期，以白与红的视觉对比和清冷与热烈的温度反差为主' }, duration: 0.6 },
        { role: 'ai',
          text: '搜索到了32条相关记录。白居易《夜雪》"已讶衾枕冷，复见窗户明"以触觉写雪；卢梅坡《雪梅》"梅须逊雪三分白，雪却输梅一段香"直接对比雪与花。让我进一步检索诗词中「红白」意象的组合方式。',
          thinking: '从搜索结果中筛选了两位最具代表性的诗人。白居易的夜雪以触觉入诗很独特，卢梅坡的对比手法正是用户需要的。还需要再查一下红白意象的经典组合来丰富创作素材。',
          timestamp: Date.now() + 205000,
          model: '雪覆红玫·1.0',
          tokens: 58,
          duration: 3.1 },
        { role: 'tool-bubble', toolName: '📖 检索诗文集', completed: true, timestamp: Date.now() + 210000, params: { query: '王安石 王冕 梅花诗 赏析', limit: 5, source: 'literature-index' }, result: { total: 12, matches: ['王安石《梅花》墙角数枝梅', '王冕《墨梅》不要人夸好颜色'], summary: '两位诗人分别从嗅觉通感和色彩自喻的角度描写梅花，与雪的意像形成互补' }, duration: 0.8 },
        { role: 'ai',
          text: '查到了一段非常契合的意象：王安石"遥知不是雪，为有暗香来"以雪拟梅，王冕"不要人夸好颜色，只留清气满乾坤"以墨梅自喻。结合这些意象，为你创作了一首：\n\n❄ 雪落梅枝两不知，\n🌹 暗香浮动月明时。\n白红相映成双色，\n却是人间最静诗。',
          thinking: '王安石和王冕的意象各有侧重——一个是嗅觉通感，一个是色彩自喻。将两者融合：用「两不知」表现雪与梅的若即若离，「最静诗」收束全篇，既有古典底蕴又有现代简洁感。白红双色也恰好呼应了「雪覆红玫」的配色哲学。',
          timestamp: Date.now() + 210000,
          model: '雪覆红玫·1.0',
          tokens: 82,
          duration: 5.2 },
      ]},
      { id: 'c2', title: '产品创意头脑风暴', preview: '我觉得这个方向很有潜力…',      time: '1小时前', unread: 0, avatar: '💡', color: 'teal',  pinned: true, messages: [
        { role: 'user', text: '我们想设计一个结合 AI 的日记应用' },
        { role: 'ai',   text: '有意思的方向。我建议从「情感温度」切入——用户每天记录时，AI 分析情绪曲线，用色彩和文字生成可视化的「心情天气」。可以加入私密与分享双模式。',
          thinking: '日记 + AI 是一个常见的产品方向，需要找到差异点。从「情感温度」而非「效率提升」切入，用色彩可视化情绪变化——这个切入点既有诗意又有产品辨识度。' },
        { role: 'user', text: '第一个版本应该优先做什么功能？' },
        { role: 'ask_user', text: '关于第一版的核心功能，我有一个建议——你认为最应该优先启动哪个方向？',
          question: '优先启动哪个方向？',
          timestamp: Date.now() + 100000,
          options: [
            { label: '📱 移动端 App 优先', value: 'mobile', desc: '从原生 iOS/Android 开始建立口碑' },
            { label: '🌐 Web 端 MVP', value: 'web', desc: '快速上线 Web 原型验证核心需求' },
            { label: '🤖 API + 插件', value: 'api', desc: '先做 API 让第三方集成使用' },
            { label: '📊 数据看板', value: 'dashboard', desc: '先做可视化的情绪分析面板' },
          ],
          customPrompt: '我想要的不是这些…' },
      ]},
      { id: 'c3', title: '品牌文案润色',     preview: '「在寒冬里绽放」这段不错…',    time: '3小时前', unread: 1, avatar: '✍️', color: 'amber', pinned: false, messages: [
        { role: 'user', text: '帮我看一下这段品牌语：「我们不只做产品，我们在寒冬里种花」' },
        { role: 'ai',   text: '隐喻很美，但「种花」略显被动。建议：「我们不是在寒冬里种花——我们让寒冬开花。」保留原意，但语气更坚定，带一点叛逆感。',
          thinking: '原句的核心问题是「种花」的语态偏弱。改成「让寒冬开花」把主语从「花」变回「我们」，态度更主动。使用破折号制造节奏停顿，增强语气。' },
      ]},
      { id: 'c4', title: '代码审查请求',     preview: '这个 API 的返回格式需要调整…', time: '昨天',   unread: 0, avatar: '🖥️', color: 'plum',  pinned: false, messages: [
        { role: 'user', text: '帮我 review 一下这段 Python 代码' },
        { role: 'ai',   text: '好的，我注意到几个可以改进的地方：1. 缺少类型注解 2. 异常处理太宽泛 3. 建议用 dataclass 代替手动 __init__。详细建议如下：' },
      ]},
      { id: 'c5', title: '旅行计划讨论',     preview: '京都的红叶季大概在 11 月下旬…', time: '前天',   unread: 0, avatar: '🌸', color: 'cyan',  pinned: false, messages: [
        { role: 'user', text: '计划 11 月去京都，推荐一些赏枫的地方' },
        { role: 'ai',   text: '11 月下旬是京都红叶见顷的最佳时段。推荐：永观堂（夜枫极美）、岚山（竹林＋红叶的层次感）、东福寺（通天桥俯瞰）…' },
      ]},
      { id: 'c6', title: '阅读笔记整理',     preview: '博尔赫斯的《小径分岔的花园》…',  time: '3天前',  unread: 0, avatar: '📖', color: 'coral', pinned: false, messages: [
        { role: 'user', text: '帮我整理一下这周的阅读笔记要点' },
        { role: 'ai',   text: '当然。你本周读了三本书：《小径分岔的花园》《雪国》《Designing Data-Intensive Applications》。我提取了每本的核心观点如下：' },
      ]},
    ];

    // —— 思考过程池（模拟 AI 推理） ——
    const THINKING_POOL = [
      '用户的问题需要先理解上下文中的关键信息。让我拆解一下：核心诉求是…',
      '正在分析问题的多个维度。从语义上看，用户可能隐含的需求是…',
      '我需要先检查相关的知识库条目。涉及的概念有：雪覆红玫配色哲学、毛玻璃参数方案…',
      '这个问题可以分解为三个子问题。第一步需要确定的是…',
      '从对话历史来看，用户偏好简洁有诗意的表达方式。因此我的回复应该…',
      '正在评估几种可能的回复策略。方案A：直接回答；方案B：先提供背景再给答案…',
      '用户提到了一个我之前没有遇到过的新角度。让我结合已有的知识进行推理…',
    ];

    // —— 工具调用池 ——
    const TOOL_CALLS_POOL = [
      { icon: '🔍', label: '搜索知识库…',            duration: 400 },
      { icon: '📖', label: '检索对话记忆…',          duration: 300 },
      { icon: '⚙',  label: '调用推理引擎…',         duration: 500 },
      { icon: '🧮', label: '计算文本相似度…',        duration: 250 },
      { icon: '📂', label: '查询文件索引…',          duration: 350 },
      { icon: '🌐', label: '检查网络资源…',          duration: 450 },
    ];

    const AI_RESPONSES = [
      '雪落无声，却在每一片花瓣上留下了痕迹。就像好的设计，越是克制，越是动人。',
      '这个想法很美。让我想起雪后初晴时，阳光穿过冰晶折射出的七彩——细致的光学现象里藏着自然的精密设计。',
      '嗯，我在听。你继续说，我帮你梳理思路。',
      '用「绯红」来点缀「素白」，就像在一篇极简的界面里，只留一个精心设计的交互触点——少即是多。',
      '我理解你的意思了。让我换个角度帮你分析：如果核心问题不是「怎么做」，而是「为什么做」，答案会更清晰。',
      '温润如玉，烈如火。这两种气质的平衡点，正是我们想要的设计语言。',
      '这是一段很有深度的思考。我试着将它拆解成三个可执行的步骤：第一…',
      '就像雪覆红玫的配色哲学——温暖的基底上，那一抹红不需要多，但必须在关键的位置。你的方案也适用这个逻辑。',
    ];
    const sessionPermissions = {};

    // SVG icon strings for permission buttons
    const PERM_SVGS = {
      allowOnce: '<svg viewBox="0 0 28 28"><polyline points="20 8 11 20 5 13" fill="none" stroke="#10B981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
      denyOnce: '<svg viewBox="0 0 28 28"><path d="M7 7l14 14M21 7L7 21" fill="none" stroke="#EF4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
      allowSession: '<svg viewBox="0 0 24 24" style="width:26px;height:26px;"><g class="perm-arrow-cycle" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" color="#6B7280"><polyline points="20 4 20 10 14 10"/><polyline points="4 20 4 14 10 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L20 10M4 14l4.64 4.36A9 9 0 0 0 17.49 15"/></g><polyline points="14 9 10 14 7 11.5" fill="none" stroke="#10B981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
      denySession: '<svg viewBox="0 0 24 24" style="width:26px;height:26px;"><g class="perm-arrow-cycle" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" color="#6B7280"><polyline points="20 4 20 10 14 10"/><polyline points="4 20 4 14 10 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L20 10M4 14l4.64 4.36A9 9 0 0 0 17.49 15"/></g><path d="M13.5 9L9.5 14.5M9.5 9l4 5.5" fill="none" stroke="#EF4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    };


    let currentConvId = 'c1';
    let isProcessing = false;
    let pendingTimeout = null;
    let abortPending = false;

    /* ============================================================
       连接状态管理
       ============================================================ */
    let connectionStatus = 'online'; // 'online' | 'offline' | 'processing'

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

    /* ============================================================
       渲染会话列表
       ============================================================ */
        // ── WebSocket handlers ──
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

    /* ============================================================
       选择会话
       ============================================================ */
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

    /* ============================================================
       辅助函数
       ============================================================ */
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

    /* ============================================================
       渲染消息（支持 thinking / 图片嵌套）
       ============================================================ */
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

        const textWithImages = renderInlineImages(escHtml(m.text).replace(/\n/g, '<br>'));

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

    /* —— 操作按钮处理函数 —— */
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

    /* ============================================================
       渲染内联图片（检测文本中的图片 URL）
       ============================================================ */
    function renderInlineImages(text) {
      var result = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, function (match, alt, url) {
        return '<div class="msg-image"><img src="' + escHtml(url) + '" alt="' + escHtml(alt) + '" loading="lazy" onclick="window.open(this.src,\'_blank\')"></div>';
      });
      return result;
    }

    /* ============================================================
       发送消息 — 带工具调用 + 思考过程 + 中止支持
       ============================================================ */
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

    /* —— 内部发送流程（支持工具气泡 + 重新生成调用） —— */
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

    /* ============================================================
       发送按钮双状态
       ============================================================ */
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

    /* ============================================================
       打字指示器
       ============================================================ */
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

    /* ============================================================
       附件管理
       ============================================================ */
    let currentAttachments = [];

    // File upload
    document.getElementById('attachBtn').addEventListener('click',function(){document.getElementById('fileInput').click();});
    document.getElementById('fileInput').addEventListener('change',function(e){
      Array.from(e.target.files).forEach(function(file){
        var maxSize=20*1024*1024;
        if(file.size>maxSize){alert('文件超过 20MB');return}
        var sz=(file.size/1024).toFixed(1)+'KB';
        var isImg=file.type.startsWith('image/');
        if(isImg){
          var reader=new FileReader();
          reader.onload=function(ev){currentAttachments.push({name:file.name,size:sz,isImage:true,dataUrl:ev.target.result,file:file});renderAttachments();};
          reader.readAsDataURL(file);
        }else{
          currentAttachments.push({name:file.name,size:sz,isImage:false,file:file});renderAttachments();
        }
      });
      e.target.value='';
    });

    // Upload files to server and return paths
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

    /* ============================================================
       工具函数
       ============================================================ */
    function escHtml(s) {
      const d = document.createElement('div');
      d.textContent = s;
      return d.innerHTML;
    }

function escapeHtml(t){var d=document.createElement("div");d.textContent=t;return d.innerHTML}
    function scrollToBottom() {
      requestAnimationFrame(() => {
        const area = document.getElementById('messageArea');
        area.scrollTop = area.scrollHeight;
      });
    }

    function closeSidebarMobile() {
      const sidebar = document.getElementById('sidebar');
      const overlay = document.getElementById('mobileOverlay');
      if (window.innerWidth <= 780) {
        sidebar.classList.remove('open');
        overlay.classList.remove('visible');
      }
    }

    /* ============================================================
       侧栏收起/展开
       ============================================================ */
    function toggleSidebar() {
      const sidebar = document.getElementById('sidebar');
      const isCollapsed = sidebar.classList.toggle('collapsed');
      const btn = document.getElementById('sidebarCollapseBtn');
      btn.title = isCollapsed ? '展开侧栏' : '收起侧栏';
      if (window.innerWidth > 780) {
        try { localStorage.setItem('sidebarCollapsed', isCollapsed ? '1' : '0'); } catch (_) {}
      }
    }

    /* 迷你工具栏按钮事件 */
    document.getElementById('miniExpand').addEventListener('click', function () {
      const sidebar = document.getElementById('sidebar');
      sidebar.classList.remove('collapsed');
      document.getElementById('sidebarCollapseBtn').title = '收起侧栏';
      if (window.innerWidth > 780) {
        try { localStorage.setItem('sidebarCollapsed', '0'); } catch (_) {}
      }
    });
    document.getElementById('miniNewChat').addEventListener('click', function () {
      document.getElementById('newChatBtn').click();
    });
    document.getElementById('miniSearch').addEventListener('click', function () {
      if (window.innerWidth > 780) {
        // 展开侧栏并聚焦搜索
        const sidebar = document.getElementById('sidebar');
        sidebar.classList.remove('collapsed');
        document.getElementById('sidebarCollapseBtn').title = '收起侧栏';
        try { localStorage.setItem('sidebarCollapsed', '0'); } catch (_) {}
        setTimeout(function () {
          document.getElementById('searchInput').focus();
        }, 350);
      }
    });
    document.getElementById('miniSettings').addEventListener('click', function () {
      openSettings();
    });

    /* ============================================================
       设置页面（内嵌于聊天区）
       ============================================================ */
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

    /* —— 设置标签切换 —— */
    function switchSettingsSection(sectionId) {
      document.querySelectorAll('.settings-nav-item').forEach(function (el) {
        el.classList.toggle('active', el.dataset.section === sectionId);
      });
      document.querySelectorAll('.settings-section').forEach(function (el) {
        el.classList.toggle('active', el.dataset.section === sectionId);
      });
    }

    /* ============================================================
       深色模式
       ============================================================ */
    function toggleDarkMode() {
      document.body.classList.toggle('dark');
      const isDark = document.body.classList.contains('dark');
      document.getElementById('darkModeSwitch').classList.toggle('on', isDark);
      document.getElementById('darkModeSwitch').setAttribute('aria-checked', isDark ? 'true' : 'false');
      try { localStorage.setItem('darkMode', isDark ? '1' : '0'); } catch (_) {}
    }

    /* ============================================================
       初始化
       ============================================================ */
    /* —— 为现有消息补充默认元数据 —— */
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

    document.addEventListener('DOMContentLoaded', init);
  