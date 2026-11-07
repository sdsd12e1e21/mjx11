import './env';
import { SeekdbClient, Schema, VectorIndexConfig, FulltextIndexConfig } from 'seekdb';
import { MODEL, physicalName, validateVector, type Chunk, type Precision } from '../src/shared';
export const client = new SeekdbClient({host:process.env.SEEKDB_HOST || '127.0.0.1',port:Number(process.env.SEEKDB_PORT || 2881), user:process.env.SEEKDB_USER || 'root',password:process.env.SEEKDB_PASSWORD || '',database:process.env.SEEKDB_DATABASE || 'test',queryTimeout:60000});
const locks = new Map<string,Promise<unknown>>();
export async function locked<T>(key:string, fn:()=>Promise<T>):Promise<T> {
  const previous = locks.get(key) || Promise.resolve();
  const task = previous.catch(()=>{}).then(fn);
  locks.set(key,task);
  try { return await task; } finally { if (locks.get(key)===task) locks.delete(key); }
}
async function collection(name:string, precision:Precision) {
  return client.getCollection({name:physicalName(name,precision),embeddingFunction:null});
}
export async function create(name:string, precision:Precision) {
  const key=physicalName(name,precision);
  return locked(key, async()=> {
    if (!await client.hasCollection(key)) await client.createCollection({name:key,embeddingFunction:null,schema:new Schema({
      vectorIndex:new VectorIndexConfig({hnsw:{dimension:MODEL.dimension,distance:'cosine'},embeddingFunction:null}),
      fulltextIndex:new FulltextIndexConfig('ngram',{ngram_token_size:2}),
    })});
    return {name,precision};
  });
}
export async function list() {
  const all = await client.listCollections({withEmbeddingFunction:false});
  return all.flatMap(c=> {
    const match=/^edge_([a-z][a-z0-9_]{0,31})_(q8|fp32)_bge75c43b$/.exec(c.name);
    return match ? [{name:match[1],precision:match[2]}] : [];
  });
}
export async function stats(name:string, precision:Precision) { return locked(physicalName(name,precision),async()=>({count:await (await collection(name,precision)).count()})); }
export async function ingest(name:string,precision:Precision,chunks:Chunk[],vectors:number[][],refreshEach=false) {
  chunks.forEach(c=> { if (!c.id || !c.docId || !c.text?.trim() || c.text.length>2000 || typeof c.title!=='string' || !Number.isInteger(c.index)) throw new Error('无效文本块'); });
  if (!chunks.length || chunks.length>1000 || chunks.length!==vectors.length) throw new Error('文本块与向量数量不匹配或超过 1000 块');
  vectors.forEach(validateVector);
  if (new Set(chunks.map(c=>c.id)).size !== chunks.length) throw new Error('请求中包含重复块 ID');
  return locked(physicalName(name,precision),async()=> {
    const c = await collection(name,precision), start=performance.now();
    let refreshMs=0;
    const size=refreshEach ? 1 : 64;
    for(let i=0;i<chunks.length;i+=size) {
      const part=chunks.slice(i,i+size);
      await c.upsert({ids:part.map(x=>x.id),documents:part.map(x=>x.text),embeddings:vectors.slice(i,i+size),metadatas:part.map(x=>({title:x.title,docId:x.docId,index:x.index,model:MODEL.id,revision:MODEL.revision,precision}))});
      if(refreshEach) { const t=performance.now(); await c.refresh_index(); refreshMs+=performance.now()-t; }
    }
    const writeMs=performance.now()-start-refreshMs;
    if(!refreshEach) {const t=performance.now();await c.refresh_index();refreshMs+=performance.now()-t;}
    return {writeMs,refreshMs,count:await c.count(),inserted:chunks.length};
  });
}
export async function search(name:string,precision:Precision,text:string,vector:number[],k:number) {
  validateVector(vector);
  return locked(physicalName(name,precision),async()=> {
    const c=await collection(name,precision),start=performance.now();
    // Both recall paths and RRF execute inside seekdb. Never merge in JavaScript.
    const result=await c.hybridSearch({query:{whereDocument:{$contains:text},nResults:30},knn:{queryEmbeddings:[vector],nResults:30},rank:{rrf:{rankWindowSize:30,rankConstant:60}},nResults:k,include:['documents','metadatas','distances']});
    return {dbMs:performance.now()-start,results:(result.ids[0] || []).map((id,i)=>({id,text:result.documents?.[0]?.[i] || '',metadata:result.metadatas?.[0]?.[i] || {},score:result.distances?.[0]?.[i] ?? null}))};
  });
}
