const fs=require('node:fs'),ts=require('typescript'),assert=require('node:assert/strict');
const source=fs.readFileSync('libraries/nestjs-libraries/src/temporal/temporal.module.ts','utf8');
const output=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2021,experimentalDecorators:true,emitDecoratorMetadata:true,esModuleInterop:true},reportDiagnostics:true});
if(output.diagnostics.some(d=>d.category===ts.DiagnosticCategory.Error))throw new Error('Worker module did not compile');
for(const app of ['orchestrator','backend'])fs.writeFileSync(`apps/${app}/dist/libraries/nestjs-libraries/src/temporal/temporal.module.js`,output.outputText);
// Exercise the compiled module with a test TemporalModule to inspect queue registration.
const vm=require('node:vm');let configuration;
const providers=[{identifier:'whatsapp-status',maxConcurrentJob:1},{identifier:'instagram'},{identifier:'instagram-standalone'},{identifier:'facebook'},{identifier:'youtube'}];
const mockModule={exports:{}};const sandbox={exports:mockModule.exports,process:{env:{}},require(name){
 if(name.endsWith('integration.manager'))return{socialIntegrationList:providers};
 if(name==='nestjs-temporal-core')return{TemporalModule:{register:config=>(configuration=config,config)}};
 if(name==='@nestjs/common')return{Module:()=>target=>target};
 if(name.includes('email.queues'))return{emailQueues:{}};
 return require(name);
}};
try{
 vm.runInNewContext(output.outputText,sandbox);
 sandbox.exports.getTemporalModule(true,'fixture',[]);
 assert.deepEqual(Array.from(configuration.workers.map(w=>w.taskQueue)),['main','whatsapp','instagram','facebook','youtube']);
 assert.equal(configuration.workers.find(w=>w.taskQueue==='whatsapp').workerOptions.maxConcurrentActivityTaskExecutions,1);
 sandbox.process.env.EXCLUDE_QUEUE='whatsapp';sandbox.exports.getTemporalModule(true,'fixture',[]);
 assert.equal(configuration.workers.some(w=>w.taskQueue==='whatsapp'),false);
}catch(error){console.error('Worker registration fixture failed:',error.message);process.exit(1);}
console.log('Temporal worker module compiled for backend and orchestrator');
