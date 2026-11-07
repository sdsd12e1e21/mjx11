import './style.css';
import { MODEL, splitText, median, quality, type Chunk, type Precision, type Backend } from './shared';
import { corpus, queries } from './fixture';
document.querySelector('#app')!.innerHTML = `
<aside><a class="brand" href="/">✳ <span>星屿<span class="brand-small">LOCAL KNOWLEDGE</span></span></a><div class="side-label">工作空间</div><div class="nav-active">▧ &nbsp; 我的知识库</div><p class="side-note">让知识留在身边。<br>让答案触手可及。</p><div class="local-label"><span class="dot"></span> 浏览器本地推理</div></aside>
<main><header><span>工作空间 <b>/</b> 我的知识库</span><span id="db" class="badge">正在连接 seekdb…</span></header>
<section class="intro"><div><div class="eyebrow">YOUR KNOWLEDGE, ON YOUR DEVICE</div><h1>每一份知识，都有回响。</h1><p>导入你的文档，发现关键词之外的关联。</p></div><div class="backend-box"><span>当前推理后端</span><strong id="backend">等待模型加载</strong><small id="backend-reason">优先 WebGPU · 自动降级 WASM</small></div></section>
<div class="toolbar"><label>知识库 <select id="kb"><option value="personal">personal</option></select></label><button id="new-kb" class="quiet">＋ 新建</button><span class="separator"></span><label>模型 <select id="precision"><option value="q8">INT8 · 轻量模式</option><option value="fp32">FP32 · 对照基线</option></select></label><label>后端 <select id="mode"><option value="auto">自动选择</option><option value="wasm">强制 WASM</option></select></label><span id="count" class="count">0 个文本块</span></div>
<div class="workspace"><section class="panel import"><div class="panel-title"><span class="step">01</span><h2>收集知识</h2></div><label class="drop" id="drop"><span class="upload-icon">↥</span><strong>选择或拖入文本文档</strong><span>支持 .txt / .md，可连续导入</span><input id="files" type="file" accept=".txt,.md,text/plain,text/markdown" multiple></label><div class="or">或直接输入</div><input id="title" placeholder="文档标题（选填）" aria-label="文档标题"><textarea id="content" placeholder="把想收藏的内容放在这里…" aria-label="文档内容"></textarea><button id="import" class="primary">添加到知识库 <span>↗</span></button><button id="demo" class="quiet full">导入 12 篇示例文档</button><div id="progress" role="status" class="progress">准备就绪。首次使用将下载开源模型。</div><div class="model-note">BGE small 中文 · 512 维<br>分块与向量化在浏览器完成</div></section>
<section class="panel retrieval"><div class="panel-title"><span class="step">02</span><h2>发现答案</h2><span class="badge">语义 + 全文</span></div><form id="search-form"><div class="search-box"><span>⌕</span><input id="query" maxlength="500" placeholder="用自然语言，寻找你需要的知识" aria-label="检索问题"><button id="search" class="primary">检索 ↗</button></div></form><div class="suggestions"><button data-q="浏览器没有可用显卡时怎么办？">没有显卡，能本地推理吗？</button><button data-q="关键词与语义结果在哪里一起排序？">了解混合检索</button></div><div id="result-info" class="result-info">由 seekdb 执行混合召回与排序</div><div id="results" aria-live="polite"><div class="empty"><div>✳</div><h3>知识的连接，从一个问题开始</h3><p>先导入文档，再输入问题。<br>这里将展示匹配的原文和来源。</p></div></div></section></div>
<section class="bench panel"><div><div class="eyebrow">MEASURE, DON'T GUESS</div><h2>端侧性能实验室</h2><p>同一语料和查询集，对比 FP32 基线、INT8 自动后端及 INT8 WASM。另含批量与刷新策略对照。保留原始记录，报告中位数。</p></div><button id="benchmark" class="quiet">运行完整对照实验 ↗</button><button id="inference" class="quiet">仅验证本地推理</button><button id="export" class="quiet" disabled>导出实测 JSON</button><pre id="benchmark-result">尚未运行实验 · 不展示预设性能分数</pre></section>
<footer>星屿 / seekdb × 阶跃星辰 <span>文档与向量写入本地 seekdb · 无云端推理调用</span></footer></main>
<dialog id="kb-dialog"><form method="dialog"><h2>新建知识库</h2><p>小写字母开头，可含数字和下划线，最多 32 位。</p><input id="kb-name" required pattern="[a-z][a-z0-9_]{0,31}" maxlength="32" placeholder="例如 research"><div class="dialog-actions"><button value="cancel" formnovalidate>取消</button><button value="create" class="primary">创建</button></div></form></dialog>`;
const $ = <T extends HTMLElement = HTMLElement>(id:string) => document.getElementById(id) as T;
const worker = new Worker(new URL('./embed.worker.ts',import.meta.url),{type:'module'});
let nextId=1, busy=false, epoch=0, actualBackend='未加载', rawReport:any=null;
const pending = new Map<number,{resolve:(x:any)=>void,reject:(e:Error)=>void}>();
worker.onmessage=({data})=> {
  if(data.event==='backend') { actualBackend=data.backend; $('backend').textContent=`${data.backend} · ${data.precision==='q8'?'INT8':'FP32'}`;$('backend-reason').textContent=data.reason || '在浏览器设备上执行推理'; }
  else if(data.event==='progress') {const p=data.progress;$('progress').textContent=p.status==='progress'?`下载模型 ${p.file}：${Math.round(p.progress || 0)}%`:`模型：${p.status} ${p.file || ''}`;}
  else if(data.event==='encoded') $('progress').textContent=`本地向量化 ${data.done} / ${data.total}`;
  else if(pending.has(data.id)) {const p=pending.get(data.id)!;pending.delete(data.id);data.error?p.reject(new Error(data.error)):p.resolve(data);}
};
worker.onerror=(e)=> {for(const p of pending.values())p.reject(new Error(e.message));pending.clear();};
function embed(texts:string[],precision:Precision,backend:Backend,batchSize=8,isQuery=false):Promise<any> {
  return new Promise((resolve,reject)=>{const id=nextId++;pending.set(id,{resolve,reject});worker.postMessage({id,texts,precision,backend,batchSize,isQuery});});
}
async function api(url:string,body?:unknown) {
  const response=await fetch(`/api${url}`,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();if(!response.ok)throw new Error(result.error || '请求失败');return result;
}
function settings() {return {name:$<HTMLSelectElement>('kb').value,precision:$<HTMLSelectElement>('precision').value as Precision,backend:$<HTMLSelectElement>('mode').value as Backend};}
function setBusy(value:boolean) {busy=value;document.querySelectorAll<HTMLButtonElement|HTMLSelectElement|HTMLInputElement>('button,select,input[type=file]').forEach(e=>e.disabled=value);$<HTMLButtonElement>('export').disabled=value||!rawReport;}
async function task(fn:()=>Promise<void>) {if(busy)return;setBusy(true);try{await fn();}catch(e){$('progress').textContent=`操作未完成：${(e as Error).message}`;}finally{setBusy(false);}}
async function refreshCount() {const s=settings(),v=epoch;try{const r=await api(`/collections/${s.name}?precision=${s.precision}`);if(v===epoch)$('count').textContent=`${r.count} 个文本块`;}catch{if(v===epoch)$('count').textContent='当前精度尚未导入';}}
async function init() {
  try {const health=await api('/health');$('db').textContent=`● seekdb 已连接`;$('db').title=JSON.stringify(health.version);const rows=await api('/collections');const names=[...new Set<string>(['personal',...rows.filter((x:any)=>!x.name.startsWith('bench_')).map((x:any)=>x.name)])];$<HTMLSelectElement>('kb').replaceChildren(...names.map(n=>new Option(n,n)));const saved=localStorage.getItem('edge-kb');if(saved&&names.includes(saved))$<HTMLSelectElement>('kb').value=saved;await refreshCount();}
  catch(e){$('db').textContent='● seekdb 未连接';$('db').classList.add('disconnected');$('progress').textContent=(e as Error).message;}
}
async function hash(text:string) {return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),x=>x.toString(16).padStart(2,'0')).join('');}
async function chunksFor(docs:{title:string,text:string,id?:string}[]):Promise<Chunk[]> {
  const chunks:Chunk[]=[];
  for(const doc of docs) {const docId=doc.id || await hash(`${doc.title}\n${doc.text}`);for(const [index,text] of splitText(doc.text).entries())chunks.push({id:`${docId}:${index}`,docId,title:doc.title,text,index});}
  return [...new Map(chunks.map(c=>[c.id,c])).values()];
}
async function importDocs(docs:{title:string,text:string,id?:string}[]) {
  const s=settings(),chunks=await chunksFor(docs);
  if(!chunks.length)throw new Error('请先输入文本或选择文档');
  if(chunks.length>1000)throw new Error('单次最多导入 1000 个文本块，请分批导入');
  await api('/collections',s);
  const result=await embed(chunks.map(c=>c.text),s.precision,s.backend);
  $('progress').textContent='向量化完成，正在写入 seekdb 并刷新索引…';
  const saved=await api('/import',{...s,chunks,vectors:result.vectors});
  $('progress').textContent=`已就绪：${saved.inserted} 块 · 本地推理 ${result.inferenceMs.toFixed(0)} ms · 写入 ${saved.writeMs.toFixed(0)} ms · 刷新 ${saved.refreshMs.toFixed(0)} ms`;
  await refreshCount();
}
async function loadFiles(files:FileList|File[]) {
  await task(async()=> {const docs=[];for(const file of Array.from(files)){if(!/\.(txt|md)$/i.test(file.name))throw new Error('仅支持 .txt 和 .md 文本文件');if(file.size>2*1024*1024)throw new Error('单个文件不能超过 2 MB');docs.push({title:file.name,text:await file.text()});}await importDocs(docs);});
}
$('import').onclick=()=>void task(async()=>{await importDocs([{title:$<HTMLInputElement>('title').value.trim()||'未命名文档',text:$<HTMLTextAreaElement>('content').value}]);$<HTMLTextAreaElement>('content').value='';});
$('demo').onclick=()=>void task(()=>importDocs(corpus));
$<HTMLInputElement>('files').onchange=e=>void loadFiles((e.target as HTMLInputElement).files!);
$('drop').ondragover=e=>{e.preventDefault();$('drop').classList.add('hover');};
$('drop').ondragleave=()=>$('drop').classList.remove('hover');
$('drop').ondrop=e=>{e.preventDefault();$('drop').classList.remove('hover');if(e.dataTransfer?.files)void loadFiles(e.dataTransfer.files);};
function clearResults() {epoch++;$('results').replaceChildren();$('result-info').textContent='当前知识库尚未检索';void refreshCount();localStorage.setItem('edge-kb',settings().name);}
$('kb').onchange=clearResults;$('precision').onchange=clearResults;
$('new-kb').onclick=()=>$<HTMLDialogElement>('kb-dialog').showModal();
$('kb-dialog').addEventListener('close',()=>{if($<HTMLDialogElement>('kb-dialog').returnValue!=='create')return;void task(async()=>{const name=$<HTMLInputElement>('kb-name').value;await api('/collections',{name,precision:settings().precision});const select=$<HTMLSelectElement>('kb');if(![...select.options].some(x=>x.value===name))select.add(new Option(name,name));select.value=name;clearResults();$('progress').textContent='知识库已创建，可以导入文档。';});});
$('search-form').onsubmit=e=>{e.preventDefault();void task(async()=> {
  const text=$<HTMLInputElement>('query').value.trim();if(!text)throw new Error('请输入检索问题');
  const start=performance.now(),s=settings(),v=epoch;
  const encoded=await embed([text],s.precision,s.backend,1,true);
  const response=await api('/search',{...s,text,vector:encoded.vectors[0],k:5});
  if(v!==epoch)return;
  $('results').replaceChildren();
  for(const [i,r] of response.results.entries()) {
    const card=document.createElement('article');card.className='result-card';
    const head=document.createElement('h3');head.textContent=`${String(i+1).padStart(2,'0')}  ${r.metadata.title || '未命名文档'}`;
    const body=document.createElement('p');body.textContent=r.text;
    const detail=document.createElement('details');const summary=document.createElement('summary');summary.textContent='查看来源与原文';
    const pre=document.createElement('pre');pre.textContent=`文档 ${r.metadata.docId}\n文本块 ${r.metadata.index}\n模型 ${r.metadata.model}\n\n${r.text}`;detail.append(summary,pre);card.append(head,body,detail);$('results').append(card);
  }
  const total=performance.now()-start;
  $('result-info').textContent=`${response.results.length} 条结果 · 本地查询向量 ${encoded.inferenceMs.toFixed(0)} ms · seekdb ${response.dbMs.toFixed(0)} ms · 端到端 ${total.toFixed(0)} ms`;
  if(!response.results.length)$('results').textContent='未找到结果。请确认当前知识库和精度已导入文档并完成索引刷新。';
  $('progress').textContent='检索完成。';
});};
document.querySelectorAll<HTMLButtonElement>('[data-q]').forEach(b=>b.onclick=()=>{$<HTMLInputElement>('query').value=b.dataset.q!;$<HTMLFormElement>('search-form').requestSubmit();});

async function benchmark() {
  rawReport=null;
  const health=await api('/health');
  const chunks=await chunksFor(corpus);
  const report:any={timestamp:new Date().toISOString(),model:MODEL,userAgent:navigator.userAgent,hardwareConcurrency:navigator.hardwareConcurrency,db:health.version,corpus,queries,k:3,repeats:3,rows:[]};
  const configs:{label:string,name:string,precision:Precision,backend:Backend,batch:number,refreshEach:boolean}[]=[
    {label:'FP32 / WASM / batch 1 / 逐块刷新',name:'bench_fp32',precision:'fp32',backend:'wasm',batch:1,refreshEach:true},
    {label:'INT8 / 自动后端 / batch 8 / 批后刷新',name:'bench_q8_auto',precision:'q8',backend:'auto',batch:8,refreshEach:false},
    {label:'INT8 / WASM / batch 8 / 批后刷新',name:'bench_q8_wasm',precision:'q8',backend:'wasm',batch:8,refreshEach:false},
    {label:'INT8 / WASM / batch 1 / 逐块刷新（单项对照）',name:'bench_q8_control',precision:'q8',backend:'wasm',batch:1,refreshEach:true},
  ];
  for(const config of configs) {
    $('benchmark-result').textContent=`正在运行 ${config.label}…\n首次模型加载可能需要几分钟。`;
    await api('/collections',config);
    const imported=[];
    for(let repeat=0;repeat<3;repeat++) {
      const docEmb=await embed(chunks.map(c=>c.text),config.precision,config.backend,config.batch);
      const saved=await api('/import',{...config,chunks,vectors:docEmb.vectors,refreshEach:config.refreshEach});
      imported.push({repeat,backend:docEmb.backend,loadMs:docEmb.loadMs,downloadWallMs:docEmb.downloadWallMs,embeddingMs:docEmb.inferenceMs,writeMs:saved.writeMs,refreshMs:saved.refreshMs,throughput:chunks.length/(docEmb.inferenceMs/1000)});
    }
    const samples=[];
    for(let repeat=-1;repeat<3;repeat++)for(const q of queries) {
      const start=performance.now();
      const encoded=await embed([q.text],config.precision,config.backend,1,true);
      const result=await api('/search',{...config,text:q.text,vector:encoded.vectors[0],k:3});
      const e2eMs=performance.now()-start;
      const ids=result.results.map((r:any)=>r.metadata.docId as string);
      samples.push({repeat,query:q.text,backend:encoded.backend,loadMs:encoded.loadMs,queryEmbeddingMs:encoded.inferenceMs,dbMs:result.dbMs,e2eMs,ids,...quality(ids,q.relevant,3)});
    }
    const warm=samples.filter(s=>s.repeat>=0);
    report.rows.push({config,actualBackend,imported,samples,summary:{loadMs:imported[0].loadMs,throughput:median(imported.map(x=>x.throughput)),writeMs:median(imported.map(x=>x.writeMs)),refreshMs:median(imported.map(x=>x.refreshMs)),queryEmbeddingMs:median(warm.map(x=>x.queryEmbeddingMs)),dbMs:median(warm.map(x=>x.dbMs)),e2eMs:median(warm.map(x=>x.e2eMs)),recall:median(warm.map(x=>x.recall)),meanRecall:warm.reduce((a,b)=>a+b.recall,0)/warm.length,meanNdcg:warm.reduce((a,b)=>a+b.ndcg,0)/warm.length}});
    rawReport=report; // A partial report survives a later configuration failure.
  }
  $('benchmark-result').textContent=report.rows.map((r:any)=>`${r.config.label}\n实际后端 ${r.actualBackend} | ${r.summary.throughput.toFixed(1)} 块/s | DB ${r.summary.dbMs.toFixed(1)} ms | E2E ${r.summary.e2eMs.toFixed(1)} ms | Recall@3 ${r.summary.meanRecall.toFixed(3)} | nDCG@3 ${r.summary.meanNdcg.toFixed(3)}`).join('\n\n');
  $('progress').textContent='对照实验完成。可导出全部原始测量记录。';
}
$('benchmark').onclick=()=>void task(async()=>{try{await benchmark();}catch(e){$('benchmark-result').textContent=`实验未完成：${(e as Error).message}。不会展示未测量的结果。`;throw e;}});
$('export').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(rawReport,null,2)],{type:'application/json'}));a.download=`stepfun-benchmark-${Date.now()}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
$('inference').onclick=()=>void task(async()=>{
  const rows:any[]=[];
  const report:any={scope:'browser-embedding-only; seekdb and retrieval quality NOT tested',timestamp:new Date().toISOString(),model:MODEL,userAgent:navigator.userAgent,hardwareConcurrency:navigator.hardwareConcurrency,corpus,queries,rows};
  for(const config of [{precision:'fp32',backend:'wasm'},{precision:'q8',backend:'auto'},{precision:'q8',backend:'wasm'}] as {precision:Precision,backend:Backend}[]) {
    const samples=[];
    for(let repeat=0;repeat<3;repeat++){
      const docs=await embed(corpus.map(c=>c.text),config.precision,config.backend,8);
      const query=await embed(queries.map(q=>q.text),config.precision,config.backend,8,true);
      const norms=docs.vectors.map((v:number[])=>Math.sqrt(v.reduce((s,x)=>s+x*x,0)));
      samples.push({repeat,actualBackend:docs.backend,loadMs:docs.loadMs,downloadWallMs:docs.downloadWallMs,docMs:docs.inferenceMs,queryMs:query.inferenceMs,dimensions:docs.vectors[0].length,normMin:Math.min(...norms),normMax:Math.max(...norms),docsPerSecond:corpus.length/(docs.inferenceMs/1000)});
    }
    rows.push({config,samples,summary:{warmDocMs:median(samples.slice(1).map(s=>s.docMs)),warmQueryMs:median(samples.slice(1).map(s=>s.queryMs))}});
    rawReport=report;
    $('benchmark-result').textContent=JSON.stringify(report,null,2);
  }
  $('progress').textContent='本地推理验证完成。此结果不包含数据库性能或检索质量。';
});
void init();
