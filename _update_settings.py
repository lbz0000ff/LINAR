import re

with open('webui/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add js-yaml CDN
content = content.replace(
    '<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>',
    '<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>\n<script src="https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js"></script>'
)

# 2. Replace settings panel HTML
old_panel = '''<div id="settings-panel">
  <h2>配置</h2>
  <textarea id="settings-editor"></textarea>
  <button id="btn-save-config" disabled>保存</button>
</div>'''

new_panel = '''<div id="settings-panel">
  <h2 style="margin-bottom:12px">配置</h2>
  <div id="config-form" style="flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:16px"></div>
  <button id="btn-save-config" style="display:none">保存</button>
</div>'''

content = content.replace(old_panel, new_panel)

# 3. Replace config event handlers
old_ev = '''case "config":settingsEditor.value=ev.data||"";btnSaveConfig.disabled=false;break;
      case "config_saved":btnSaveConfig.textContent="已保存";setTimeout(()=>{btnSaveConfig.textContent="保存"},2000);break;'''
new_ev = '''case "config_json":renderConfigForm(ev.data||{});break;
      case "config_saved":document.getElementById("btn-save-config").textContent="已保存";setTimeout(()=>{const b=document.getElementById("btn-save-config");if(b)b.textContent="保存"},2000);break;'''
content = content.replace(old_ev, new_ev)

# 4. Update settings button to request config_json
content = content.replace(
    'if(ws)ws.send(JSON.stringify({type:"get_config"}))',
    'if(ws)ws.send(JSON.stringify({type:"get_config_json"}))'
)

# 5. Add renderConfigForm before end of html
with open('webui/_settings_js.html', 'r', encoding='utf-8') as f:
    js_snippet = f.read()

content = content.replace('</script>\n</body>\n</html>', js_snippet + '\n</script>\n</body>\n</html>')

with open('webui/index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('OK')
