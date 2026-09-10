"""Local comparison viewer for the current native/PDF preview reports only."""
import json
from pathlib import Path


def build_viewer(output):
    output = Path(output)
    batch = output / 'batch-report.json'
    reports = [output / 'report.json']
    if batch.exists():
        records = json.loads(batch.read_text(encoding='utf-8'))
        reports = [Path(r['output']) / 'report.json' for r in records.get('results', [])]
    pages = []
    for report in reports:
        if not report.exists():
            continue
        for page in json.loads(report.read_text(encoding='utf-8')).get('pages', []):
            if not page.get('preview'):
                continue
            pages.append({'name': Path(page['input']).name, 'id': page.get('id', ''), 'status': page.get('status', ''),
                          'message': page.get('message', ''), 'original': Path(page.get('source_preview') or page['input']).resolve().as_uri(),
                          'result': Path(page['preview']).resolve().as_uri()})
    data = json.dumps(pages, ensure_ascii=False).replace('<', '\\u003c')
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ScanTailor · 预览对比</title><style>
*{box-sizing:border-box}body{margin:0;background:#0f1724;color:#dce4f0;font:15px/1.6 "Segoe UI","Microsoft YaHei",sans-serif}
header{padding:24px 32px;border-bottom:1px solid #314558;display:flex;gap:24px;align-items:center;flex-wrap:wrap}
h1{font-size:22px;margin:0;color:#5bdbd1}small{color:#8b9cb2}button,select{font:inherit;color:inherit;background:#1a2a3d;border:1px solid #314558;border-radius:8px;padding:8px 14px;cursor:pointer}
button.active{background:#1a414d;border-color:#5bdbd1}nav{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:18px 32px}
#info{padding:0 32px 16px;color:#8b9cb2}.pages{display:grid;grid-template-columns:1fr 1fr;gap:20px;padding:0 32px 32px}.pages.single{grid-template-columns:1fr}
figure{margin:0;background:#182437;border:1px solid #314558;border-radius:12px;overflow:hidden}figcaption{padding:10px 16px}img{display:block;width:100%;height:72vh;object-fit:contain;background:#e8ecf0}figure[hidden]{display:none}body.zoom img{height:auto;object-fit:initial}
@media(max-width:760px){.pages{grid-template-columns:1fr}header,nav{padding:16px}img{height:50vh}.pages{padding:0 16px 20px}}
</style><header><div><h1>ScanTailor · 预览对比</h1><small>仅在本机查看 · 首、中、尾页抽样不代表整本文档均无异常</small></div><select id="page" aria-label="选择页面"></select></header>
<nav><button data-mode="both" class="active">左右对比</button><button data-mode="original">只看原图</button><button data-mode="result">只看结果</button><button id="zoom">放大检查细节</button><button id="prev">上一页</button><button id="next">下一页</button></nav>
<div id="info"></div><main class="pages"><figure id="original"><figcaption>原始扫描</figcaption><img alt="原始扫描图"></figure><figure id="result"><figcaption>处理结果</figcaption><img alt="处理后的页面"></figure></main>
<script>const data=__DATA__;const picker=document.querySelector('#page');const info=document.querySelector('#info');
data.forEach((p,i)=>{const option=document.createElement('option');option.value=i;option.textContent=`${i+1} / ${data.length} · ${p.name}`;picker.append(option)});
function show(){if(!data.length){info.textContent='没有可显示的预览图，请返回任务日志检查处理结果。';return}const p=data[Number(picker.value)];document.querySelector('#original img').src=p.original;document.querySelector('#result img').src=p.result;info.textContent=`${p.id} · ${p.status==='complete'?'完成':p.status==='review'?'需要复核':p.status} ${p.message}`;document.querySelector('#prev').disabled=picker.selectedIndex===0;document.querySelector('#next').disabled=picker.selectedIndex===data.length-1}
picker.onchange=show;document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{const mode=b.dataset.mode;document.querySelectorAll('[data-mode]').forEach(x=>x.classList.toggle('active',x===b));document.querySelector('#original').hidden=mode==='result';document.querySelector('#result').hidden=mode==='original';document.querySelector('main').classList.toggle('single',mode!=='both')});
document.querySelector('#zoom').onclick=()=>document.body.classList.toggle('zoom');for(const [id,step] of [['prev',-1],['next',1]])document.querySelector('#'+id).onclick=()=>{picker.selectedIndex=Math.max(0,Math.min(data.length-1,picker.selectedIndex+step));show()};show();</script></html>'''
    target = output / 'preview.html'
    target.write_text(html.replace('__DATA__', data), encoding='utf-8')
    return target
