/// <reference lib="webworker" />
import { pipeline, env } from '@huggingface/transformers';
import { MODEL, type Precision, type Backend } from './shared';
env.allowLocalModels = true;
env.localModelPath = '/models/';
env.useBrowserCache = true;
let extractor: any;
let current = '';
let actualBackend = '';
let initMs = 0;
let downloadWallMs = 0;
const emit = (data: unknown) => self.postMessage(data);
async function load(precision: Precision, backend: Backend) {
  const key = `${precision}:${backend}`;
  if (extractor && current === key) return;
  if (extractor) { await extractor.dispose(); extractor = null; }
  const start = performance.now();
  let firstDownload=Infinity,lastDownload=0;
  const create = (device: 'webgpu' | 'wasm') => pipeline('feature-extraction', MODEL.id, {
    revision: MODEL.revision, dtype: precision, device,
    progress_callback: (p: any) => {
      if(p.status==='download'||p.status==='progress')firstDownload=Math.min(firstDownload,performance.now());
      if(p.status==='done')lastDownload=performance.now();
      emit({event:'progress', progress:p});
    },
  });
  let reason = '';
  if (backend === 'auto' && 'gpu' in navigator) {
    try { extractor = await create('webgpu'); actualBackend = 'WebGPU'; }
    catch (e) { reason = `WebGPU 初始化失败：${String(e)}`; }
  } else reason = backend === 'wasm' ? '已选择 WASM 验证模式' : '浏览器不支持 WebGPU';
  if (!extractor) { extractor = await create('wasm'); actualBackend = 'WASM'; }
  current = key;
  initMs = performance.now() - start;
  downloadWallMs=Number.isFinite(firstDownload)?Math.max(0,lastDownload-firstDownload):0;
  emit({event:'backend', backend:actualBackend, precision, reason, loadMs:initMs, model:MODEL});
}
async function run(data: any) {
  const {id, texts, precision = 'q8', backend = 'auto', batchSize = 8, isQuery = false} = data;
  try {
    const before = current;
    await load(precision, backend);
    const loadMs = before === current ? 0 : initMs;
    const prepared: string[] = isQuery ? texts.map((x:string) => `为这个句子生成表示以用于检索相关文章：${x}`) : texts;
    const vectors: number[][] = [];
    const start = performance.now();
    for (let i=0; i<prepared.length; i+=batchSize) {
      let result;
      try { result = await extractor(prepared.slice(i,i+batchSize), {pooling:'cls', normalize:true, truncation:true, max_length:512}); }
      catch(e) {
        if (actualBackend !== 'WebGPU') throw e;
        await extractor.dispose(); extractor = null;
        await load(precision,'wasm');
        // Keep this request's auto profile reusable after device loss.
        current = `${precision}:${backend}`;
        emit({event:'backend', backend:'WASM', precision, reason:`WebGPU 推理失败，已降级：${String(e)}`, loadMs:initMs, model:MODEL});
        result = await extractor(prepared.slice(i,i+batchSize), {pooling:'cls', normalize:true, truncation:true, max_length:512});
      }
      vectors.push(...result.tolist());
      emit({event:'encoded', done:vectors.length, total:texts.length});
    }
    emit({id, vectors, backend:actualBackend, loadMs, downloadWallMs:loadMs?downloadWallMs:0, inferenceMs:performance.now()-start});
  } catch(e) { emit({id, error:String(e)}); }
}
// Serialize pipeline access; overlapping UI requests cannot mutate an active model.
let queue = Promise.resolve();
self.onmessage = ({data}) => { queue = queue.then(() => run(data)); };
