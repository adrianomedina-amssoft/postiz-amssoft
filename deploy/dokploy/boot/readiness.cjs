// Read-only dependency and worker checks. Never log connection strings or tokens.
const {createRequire}=require('node:module');const appRequire=createRequire('/app/package.json');
const {Connection}=appRequire('@temporalio/client');
const workerMode=process.argv.includes('--workers');
const failed=[];
async function check(name,fn){try{await fn();}catch{failed.push(name);}}
let connection,db,redis;
(async()=>{
  const tasks=[check('temporal',async()=>{
    connection=await Connection.connect({address:process.env.TEMPORAL_ADDRESS||'temporal:7233',connectTimeout:'4s'});
    await connection.workflowService.getSystemInfo({});
    if(workerMode){
      const namespace=process.env.TEMPORAL_NAMESPACE||'default';
      for(const [name,type] of [['main',1],['main',2],['instagram',2],['facebook',2],['youtube',2]]){
        await check('worker_'+name+'_'+type,async()=>{
          const r=await connection.workflowService.describeTaskQueue({namespace,taskQueue:{name},taskQueueType:type});
          const current=r.pollers?.some(p=>p.identity?.endsWith('@'+process.env.HOSTNAME) &&
            Date.now()/1000-Number(p.lastAccessTime?.seconds||0)<120);
          if(!current)throw Error('No recent poller from this container');
        });
      }
    }
  })];
  if(workerMode){for(const url of ['http://localhost:5000/','http://localhost:5000/api/auth/can-register'])tasks.push(check('http_'+new URL(url).pathname,async()=>{
    const r=await fetch(url,{redirect:'manual',signal:AbortSignal.timeout(4000)});if(r.status>=400)throw Error('HTTP failed');
  }));}
  else {
    tasks.push(check('postgres',async()=>{const {PrismaClient}=appRequire('@prisma/client');db=new PrismaClient();await db.$queryRawUnsafe('SELECT 1');}));
    tasks.push(check('redis',async()=>{const Redis=appRequire('ioredis');redis=new Redis(process.env.REDIS_URL,{lazyConnect:true,connectTimeout:3000,retryStrategy:()=>null,maxRetriesPerRequest:0});redis.on('error',()=>{});await redis.connect();if(await redis.ping()!=='PONG')throw Error('Redis unavailable');}));
  }
  await Promise.race([Promise.all(tasks),new Promise((_,reject)=>setTimeout(()=>reject(Error('timeout')),8000))]);
  console.log(JSON.stringify({ready:failed.length===0,mode:workerMode?'workers':'dependencies',failed}));
  process.exit(failed.length?1:0);
})().catch(()=>{console.log(JSON.stringify({ready:false,mode:workerMode?'workers':'dependencies',failed:['probe_timeout_or_initialization']}));process.exit(1);});
