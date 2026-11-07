export const MODEL = { id: 'Xenova/bge-small-zh-v1.5', revision: '75c43b069aac4d136ba6bc1122f995fedcfd2781', dimension: 512 } as const;
export type Precision = 'q8' | 'fp32';
export type Backend = 'auto' | 'wasm';
export interface Chunk { id: string; text: string; title: string; docId: string; index: number }
export function splitText(text: string, size = 320, overlap = 40): string[] {
  if (size <= overlap || overlap < 0) throw new Error('无效分块设置');
  const chars = Array.from(text.replace(/\r\n/g, '\n').trim());
  const out: string[] = [];
  for (let i = 0; i < chars.length; i += size - overlap) {
    out.push(chars.slice(i, i + size).join(''));
    if (i + size >= chars.length) break;
  }
  return out.filter(x => x.trim());
}
export function validateVector(vector: unknown): asserts vector is number[] {
  if (!Array.isArray(vector) || vector.length !== MODEL.dimension || !vector.every(x => typeof x === 'number' && Number.isFinite(x)) || !vector.some(x => x !== 0)) throw new Error('向量必须是 512 维有限非零数值');
}
export function physicalName(name: string, precision: Precision) {
  if (!/^[a-z][a-z0-9_]{0,31}$/.test(name)) throw new Error('知识库名称须以小写字母开头，最多 32 位，只含字母、数字和下划线');
  if (!['q8', 'fp32'].includes(precision)) throw new Error('不支持的模型精度');
  return `edge_${name}_${precision}_bge75c43b`;
}
export function median(values: number[]) {
  if (!values.length) return null;
  const v = [...values].sort((a,b) => a-b), i = Math.floor(v.length / 2);
  return v.length % 2 ? v[i] : (v[i-1] + v[i]) / 2;
}
export function quality(ids: string[], relevant: string[], k = 3) {
  const unique = [...new Set(ids)].slice(0,k);
  const hits = unique.filter(id => relevant.includes(id)).length;
  const dcg = unique.reduce((sum,id,i) => sum + (relevant.includes(id) ? 1 / Math.log2(i+2) : 0),0);
  const ideal = Array.from({length: Math.min(k,relevant.length)},(_,i) => 1/Math.log2(i+2)).reduce((a,b)=>a+b,0);
  return { recall: relevant.length ? hits/relevant.length : 0, ndcg: ideal ? dcg/ideal : 0 };
}
