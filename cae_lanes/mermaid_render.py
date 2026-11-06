# -*- coding: utf-8 -*-
"""mermaid_render —— mermaid 流程图渲染（2026-10-25，审美三链路之快图链固化）。

链路（本机已验证）: mermaid 源码 → 本地 HTML(内嵌 assets/mermaid.min.js, 不依赖网络)
→ Edge 无头截图(--virtual-time-budget 等 JS) → PNG。

治什么：AI 按 AGENTS.md 流程图纪律改用 mermaid 后，只能吐源码让用户自己找渲染器粘
（2026-10-25 用户实测撞上的缺口）。本工具补上"源码即出图"的最后一环。

注意：
  - mermaid 源码里的语法字符需转义（如 |R| 写 &#124;R&#124;）——AI 侧责任，本工具不改动源码。
  - Edge 路径写死本机（config 可覆盖）；窗口尺寸按内容自适应：先按宽度出图,
    高度给足(2400)——白边由截图窗口决定, 内容不足时留白在底部。
"""
import subprocess
from pathlib import Path

try:
    from . import config as _cfg
except ImportError:
    import config as _cfg

EDGE = getattr(_cfg, 'MERMAID_EDGE', r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
_ASSETS = Path(__file__).parent / 'assets'
_MERMAID_JS = _ASSETS / 'mermaid.min.js'

_HTML_TMPL = '''<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
  body {{ margin:0; padding:26px 32px; background:#fff;
         font-family:"Segoe UI","Microsoft YaHei",sans-serif; }}
</style>
<script src="file:///{mermaid_js}"></script>
<script>
  mermaid.initialize({{
    startOnLoad: true,
    theme: 'base',
    themeVariables: {{
      fontFamily: '"Segoe UI","Microsoft YaHei",sans-serif',
      fontSize: '15px',
      primaryColor: '#f8fafc', primaryBorderColor: '#94a3b8', primaryTextColor: '#1f2937',
      lineColor: '#94a3b8', edgeLabelBackground: '#ffffff'
    }},
    flowchart: {{ curve: 'basis', nodeSpacing: 42, rankSpacing: 54, padding: 12 }}
  }});
</script>
</head><body>
<pre class="mermaid">
{code}
</pre>
</body></html>
'''


def render_png(code, out_png, width=1200, height=2400, budget_ms=12000):
    """mermaid 源码 → PNG（playwright + 系统 Edge，CDP 通道）。返回 PNG 路径。

    通道演进（2026-10-25 一天踩完的坑，别走回头路）：
      mmdc(puppeteer CLI) → node25 语法崩；
      Edge --headless --screenshot → 被常驻 Edge 进程非确定性劫持（rc=0 无产物）；
      手动 puppeteer-core → npm 在 quest 子进程环境装的包残缺（无 package.json）；
      → 最终: playwright(pip) + channel='msedge'，CDP 协议直连，稳。
    """
    if not _MERMAID_JS.exists():
        raise FileNotFoundError('mermaid.min.js 不在 %s（从 CDN 下载一次放进去）' % _ASSETS)
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = out.with_suffix('.mm.html')
    html.write_text(_HTML_TMPL.format(mermaid_js=str(_MERMAID_JS).replace('\\', '/'),
                                      code=code.strip()),
                    encoding='utf-8')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True,
                                     args=['--disable-gpu', '--hide-scrollbars'])
        try:
            page = browser.new_page(viewport={'width': width, 'height': height})
            page.goto('file:///%s' % str(html).replace('\\', '/'), timeout=30000)
            page.wait_for_function(
                "() => { const el = document.querySelector('.mermaid svg');"
                " return el && el.getBoundingClientRect().height > 10; }",
                timeout=20000)
            box = page.evaluate(
                "() => { const r = document.querySelector('.mermaid svg').getBoundingClientRect();"
                " return { x: Math.max(0, r.x-16), y: Math.max(0, r.y-16),"
                " width: Math.ceil(r.width)+32, height: Math.ceil(r.height)+32 }; }")
            page.screenshot(path=str(out), clip=box)
        finally:
            browser.close()
    html.unlink(missing_ok=True)                      # 中间 HTML 即弃
    return str(out)
