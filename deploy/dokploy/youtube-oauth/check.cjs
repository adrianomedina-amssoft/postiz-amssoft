const {createHash}=require('node:crypto');
function fingerprint(channel,env){return createHash('sha256').update([env.YOUTUBE_CLIENT_ID||'',env.YOUTUBE_CLIENT_SECRET||'',channel.refreshToken||''].join('\0')).digest('hex')}
async function checkChannel(channel,deps){
 const {env,fetch,save,now,previous={},force=false}=deps;
 const stamp=new Date(now).toISOString(),fp=fingerprint(channel,env);
 const result={channelKey:channel.id,checkedAt:stamp,expiresAt:channel.tokenExpiration?new Date(channel.tokenExpiration).toISOString():null,fingerprint:fp,renewed:false,ready:false,ownerActionRequired:false};
 if(!env.YOUTUBE_CLIENT_ID||!env.YOUTUBE_CLIENT_SECRET||!channel.refreshToken)return {...result,state:'configuration_missing',ownerActionRequired:true};
 if(!force&&previous.fingerprint===fp&&previous.ownerActionRequired&&channel.refreshNeeded)return {...result,state:previous.state,errorCode:previous.errorCode,errorSubtype:previous.errorSubtype,ownerActionRequired:true,cachedFailure:true};
 const expires=channel.tokenExpiration?new Date(channel.tokenExpiration).getTime():0;
 if(!force&&!channel.refreshNeeded&&expires>now+20*60*1000)return {...result,state:'healthy',ready:true};
 let response,data;
 try{response=await fetch('https://oauth2.googleapis.com/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({client_id:env.YOUTUBE_CLIENT_ID,client_secret:env.YOUTUBE_CLIENT_SECRET,refresh_token:channel.refreshToken,grant_type:'refresh_token'}).toString(),signal:AbortSignal.timeout(20000)});data=await response.json()}
 catch{return {...result,state:'temporary_refresh_error',errorCode:'transport_or_response'}}
 if(!response.ok){
  const terminal=['invalid_grant','invalid_client','unauthorized_client','deleted_client','admin_policy_enforced'].includes(data.error);
  if(terminal)await save(channel,{refreshNeeded:true});
  return {...result,state:terminal?'reauthorization_required':'temporary_refresh_error',errorCode:data.error||'oauth_http_'+response.status,errorSubtype:data.error_subtype||null,ownerActionRequired:terminal};
 }
 if(!data.access_token||!Number.isFinite(data.expires_in)||data.expires_in<60)return {...result,state:'invalid_refresh_response'};
 let account;
 try{const r=await fetch('https://www.googleapis.com/youtube/v3/channels?part=id&mine=true',{headers:{Authorization:'Bearer '+data.access_token},signal:AbortSignal.timeout(20000)});account=await r.json();if(!r.ok)return {...result,state:'channel_validation_failed',errorCode:'youtube_http_'+r.status};}
 catch{return {...result,state:'channel_validation_failed',errorCode:'transport_or_response'}}
 if(!account.items?.some(x=>x.id===channel.internalId)){await save(channel,{refreshNeeded:true});return {...result,state:'channel_mismatch',ownerActionRequired:true}};
 const nextRefresh=data.refresh_token||channel.refreshToken;
 const expiry=new Date(now+data.expires_in*1000);
 const updated=await save(channel,{token:data.access_token,refreshToken:nextRefresh,tokenExpiration:expiry,refreshNeeded:false});
 if(!updated)return {...result,state:'concurrent_change_retry_next_run'};
 return {...result,fingerprint:fingerprint({...channel,refreshToken:nextRefresh},env),state:'healthy',ready:true,renewed:true,matchingChannel:true,expiresAt:expiry.toISOString()};
}
async function main(previous={},force=false){
 const {PrismaClient}=require('@prisma/client');const prisma=new PrismaClient();
 try{const channels=await prisma.integration.findMany({where:{providerIdentifier:'youtube',deletedAt:null,disabled:false}});const results=[];
 for(const channel of channels){const result=await checkChannel(channel,{env:process.env,fetch:globalThis.fetch,now:Date.now(),previous:previous[channel.id]||{},force,save:async(old,data)=>{const r=await prisma.integration.updateMany({where:{id:old.id,token:old.token,refreshToken:old.refreshToken,deletedAt:null},data});return r.count===1}});results.push(result)}
 return {checkedAt:new Date().toISOString(),channels:results,ready:results.length>0&&results.every(x=>x.ready)};
 }finally{await prisma.$disconnect()}
}
module.exports={checkChannel,fingerprint,main};
