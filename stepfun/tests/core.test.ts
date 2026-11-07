import {test} from 'node:test';
import assert from 'node:assert/strict';
import {splitText,physicalName,validateVector,MODEL,quality,median} from '../src/shared';
import {locked,client} from '../server/store';
test('分块保留尾部与重叠，不破坏 Unicode',()=> {
  assert.deepEqual(splitText('  \n '),[]);
  assert.deepEqual(splitText('甲乙丙丁戊己庚',4,1),['甲乙丙丁','丁戊己庚']);
  assert.deepEqual(splitText('😀😀😀😀😀',3,1),['😀😀😀','😀😀😀']);
  assert.throws(()=>splitText('x',1,1));
});
test('知识库与精度隔离，拒绝恶意名称',()=> {
  assert.notEqual(physicalName('a','q8'),physicalName('a','fp32'));
  assert.notEqual(physicalName('a','q8'),physicalName('b','q8'));
  for(const invalid of ['../a','x;DROP TABLE','A','a'.repeat(33),''])assert.throws(()=>physicalName(invalid,'q8'));
});
test('错误维数、NaN、全零向量不进入数据库',()=> {
  assert.throws(()=>validateVector([1,2]));
  assert.throws(()=>validateVector(Array(MODEL.dimension).fill(0)));
  assert.throws(()=>validateVector(Array(MODEL.dimension).fill(NaN)));
  validateVector(Array(MODEL.dimension).fill(1/Math.sqrt(MODEL.dimension)));
});
test('质量指标与中位数有可核算结果',()=> {
  assert.deepEqual(quality(['a','b','c'],['a'],3),{recall:1,ndcg:1});
  assert.equal(quality(['x','a','y'],['a'],3).ndcg,1/Math.log2(3));
  assert.equal(quality(['a','a'],['a','b'],3).recall,.5);
  assert.equal(median([9,1,3]),3);assert.equal(median([4,2]),3);assert.equal(median([]),null);
});
test('同一集合操作串行，失败不会阻塞后续任务',async()=> {
  const order:string[]=[];let release!:()=>void;
  const gate=new Promise<void>(resolve=>release=resolve);
  const first=locked('x',async()=>{order.push('write');await gate;order.push('refresh');throw new Error('failed');}).catch(()=>{});
  const second=locked('x',async()=>order.push('search'));
  const independent=locked('y',async()=>order.push('other'));
  await independent;assert.ok(!order.includes('search'));release();await Promise.all([first,second]);
  assert.ok(order.indexOf('refresh')<order.indexOf('search'));
  await client.close();
});
