// Downloads public artifacts only; does not perform embedding on the server.
import { mkdir, writeFile, readFile, stat } from 'node:fs/promises';
import { createReadStream, createWriteStream } from 'node:fs';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
const model='Xenova/bge-small-zh-v1.5',revision='75c43b069aac4d136ba6bc1122f995fedcfd2781';
const root=path.resolve(import.meta.dirname,'..');
const artifacts=['config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt','quantize_config.json','onnx/model.onnx','onnx/model_quantized.onnx'];
const files=[];
for(const name of artifacts) {
  const target=path.join(root,'public/models',model,name);
  await mkdir(path.dirname(target),{recursive:true});
  let exists=false;try{exists=(await stat(target)).size>0;}catch{}
  if(!exists) {
    const response=await fetch(`https://huggingface.co/${model}/resolve/${revision}/${name}`);
    if(!response.ok||!response.body)throw new Error(`${name}: HTTP ${response.status}`);
    const temp=target+'.download';
    await pipeline(Readable.fromWeb(response.body),createWriteStream(temp));
    const {rename}=await import('node:fs/promises');await rename(temp,target);
  }
  const hash=createHash('sha256');let bytes=0;
  for await(const chunk of createReadStream(target)){hash.update(chunk);bytes+=chunk.length;}
  files.push({name,bytes,sha256:hash.digest('hex')});
  console.log(`${name}: ${bytes} bytes`);
}
const fp32=files.find(f=>f.name==='onnx/model.onnx').bytes,q8=files.find(f=>f.name==='onnx/model_quantized.onnx').bytes;
const shared=files.filter(f=>!f.name.startsWith('onnx/')&&f.name!=='quantize_config.json').reduce((a,b)=>a+b.bytes,0);
const result={measuredAt:new Date().toISOString(),model,revision,method:'Downloaded pinned artifacts; streamed byte count and SHA-256 of local files. Common tokenizer/config assets counted once per configuration.',files,weights:{fp32,q8,ratio:fp32/q8},bundle:{fp32:fp32+shared,q8:q8+shared,ratio:(fp32+shared)/(q8+shared)},quantizeConfig:JSON.parse(await readFile(path.join(root,'public/models',model,'quantize_config.json'),'utf8'))};
await mkdir(path.join(root,'reports'),{recursive:true});await writeFile(path.join(root,'reports/model-manifest.json'),JSON.stringify(result,null,2)+'\n');
console.log(`Weights compression ratio: ${(fp32/q8).toFixed(3)}x`);
