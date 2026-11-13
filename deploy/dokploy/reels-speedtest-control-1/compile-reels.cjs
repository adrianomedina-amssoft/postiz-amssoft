const fs=require('node:fs'),path=require('node:path'),ts=require('typescript');
const root='/app';const config=ts.readConfigFile(path.join(root,'tsconfig.base.json'),ts.sys.readFile).config;
const converted=ts.convertCompilerOptionsFromJson(config.compilerOptions,root);
if(converted.errors.length)throw Error('Invalid TypeScript options');
const options={...converted.options,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2021,sourceMap:false,inlineSourceMap:false,declaration:false,incremental:false};
const modules=['libraries/nestjs-libraries/src/dtos/posts/providers-settings/instagram.dto.ts','libraries/nestjs-libraries/src/integrations/social/instagram.provider.ts'];
for(const file of modules){
 const input=fs.readFileSync(path.join(root,file),'utf8');const out=ts.transpileModule(input,{fileName:path.join(root,file),compilerOptions:options,reportDiagnostics:true});
 if(out.diagnostics?.some(d=>d.category===ts.DiagnosticCategory.Error))throw Error('Transpilation diagnostics');
 const code=out.outputText.replace(/require\("(@gitroom\/[^"\n]+)"\)/g,function rewrite(match,id){
  for(const [pattern,targets] of Object.entries(config.compilerOptions.paths)){
   if(!pattern.endsWith('*')||!id.startsWith(pattern.slice(0,-1)))continue;
   const target=targets[0].replace('*',id.slice(pattern.length-1));let relative=path.posix.relative(path.posix.dirname(file),target);if(!relative.startsWith('.'))relative='./'+relative;return 'require('+JSON.stringify(relative)+')';
  }
  throw Error('Unresolved application alias');
 });
 for(const service of ['backend','orchestrator']){const output=path.join(root,'apps',service,'dist',file.replace(/\.ts$/,'.js'));if(!fs.existsSync(output))throw Error('Verified runtime module missing');fs.writeFileSync(output,code);fs.rmSync(output+'.map',{force:true})}
}
console.log('Compiled two changed modules into backend and orchestrator runtimes');
