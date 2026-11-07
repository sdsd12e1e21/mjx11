// Integration test requires a real seekdb instance. No in-memory substitute.
import assert from 'node:assert/strict';
import { client,create,ingest,search,stats } from '../server/store';
import { MODEL,physicalName } from '../src/shared';
const name=`check_${Date.now()}`;
const vector=Array.from({length:MODEL.dimension},(_,i)=>i===0?1:0);
try {
  await create(name,'q8');
  const chunk={id:'a:0',docId:'a',title:'集成测试',text:'知识库增量写入与索引刷新测试',index:0};
  await ingest(name,'q8',[chunk],[vector]);
  assert.equal((await stats(name,'q8')).count,1);
  assert.equal((await search(name,'q8','增量写入',vector,3)).results[0].id,'a:0');
  await ingest(name,'q8',[chunk],[vector]);
  assert.equal((await stats(name,'q8')).count,1,'重复导入须幂等');
  await create(name+'_b','q8');
  assert.equal((await stats(name+'_b','q8')).count,0,'集合须隔离');
  await ingest(name,'q8',[{...chunk,id:'b:0',docId:'b',text:'第二次新增文档索引刷新验证'}],[vector]);
  assert.equal((await stats(name,'q8')).count,2);
  assert.ok((await search(name,'q8','新增文档',vector,3)).results.some(r=>r.id==='b:0'));
  console.log('PASS: real seekdb write, hybrid search, refresh, idempotence, isolation, incremental import');
} finally {
  // Only this test's uniquely named disposable collections are removed.
  for(const n of [name,name+'_b'])try{await client.deleteCollection(physicalName(n,'q8'));}catch{}
  await client.close();
}
