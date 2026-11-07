import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as store from './store';
import { MODEL, physicalName, type Precision } from '../src/shared';
const app=express();
app.use((req,res,next)=> {
  const origin=req.headers.origin;
  if (origin && !/^http:\/\/(localhost|127\.0\.0\.1):(5173|3001)$/.test(origin)) {res.status(403).json({error:'仅允许本地同源访问'});return;}
  next();
});
app.use(express.json({limit:'35mb'}));
app.get('/api/health',async(_req,res)=> {
  try { const version=await store.client.execute('SELECT VERSION() AS version'); res.json({ok:true,version,model:MODEL}); }
  catch {res.status(503).json({error:'seekdb 尚未连接。请先运行 npm run db:up，并核对 SEEKDB_* 连接配置。'});}
});
app.get('/api/collections',async(_req,res)=>res.json(await store.list()));
app.post('/api/collections',async(req,res)=> {
  const {name,precision}=req.body; physicalName(name,precision);res.json(await store.create(name,precision));
});
app.get('/api/collections/:name',async(req,res)=> {
  const precision=(req.query.precision || 'q8') as Precision;physicalName(req.params.name,precision);res.json(await store.stats(req.params.name,precision));
});
app.post('/api/import',async(req,res)=> {
  const {name,precision,chunks,vectors,refreshEach}=req.body;
  physicalName(name,precision);
  if(!Array.isArray(chunks)||!Array.isArray(vectors)) throw new Error('缺少文本块或向量');
  res.json(await store.ingest(name,precision,chunks,vectors,refreshEach===true));
});
app.post('/api/search',async(req,res)=> {
  const {name,precision,text,vector,k=5}=req.body;physicalName(name,precision);
  if(typeof text!=='string'||!text.trim()||text.length>500||!Number.isInteger(k)||k<1||k>20) throw new Error('查询须为 1–500 字，结果数量为 1–20');
  res.json(await store.search(name,precision,text.trim(),vector,k));
});
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
app.use(express.static(path.join(root,'dist')));
app.get('/{*path}',(_req,res)=>res.sendFile(path.join(root,'dist/index.html')));
app.use((err:any,_req:express.Request,res:express.Response,_next:express.NextFunction)=> {
  console.error(err.message);
  res.status(400).json({error:String(err.message || '操作失败')});
});
const server=app.listen(3001,'127.0.0.1',()=>console.log('Local app / API: http://127.0.0.1:3001'));
process.on('SIGINT',()=>server.close(()=>{void store.client.close().finally(()=>process.exit(0));}));
