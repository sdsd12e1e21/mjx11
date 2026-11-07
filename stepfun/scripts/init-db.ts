import '../server/env';
import { SeekdbAdminClient } from 'seekdb';
const client=new SeekdbAdminClient({host:process.env.SEEKDB_HOST||'127.0.0.1',port:Number(process.env.SEEKDB_PORT||2881),user:process.env.SEEKDB_USER||'root',password:process.env.SEEKDB_PASSWORD||''});
try {
  const name=process.env.SEEKDB_DATABASE||'test';
  if(!/^[a-zA-Z][a-zA-Z0-9_]{0,63}$/.test(name))throw new Error('无效数据库名');
  const dbs=await client.listDatabases();
  if(!dbs.some(db=>db.name===name))await client.createDatabase(name);
  console.log(`Database ready: ${name}`);
}finally{await client.close();}
