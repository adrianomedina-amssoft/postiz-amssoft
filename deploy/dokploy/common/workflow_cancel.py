"""Close native Postiz executions after removing a managed scheduled post."""
import json,subprocess

def cancel_workflow(postid,compose_project):
 if not isinstance(postid,str) or not postid or len(postid)>160:raise RuntimeError('InvalidCancellationIdentity')
 container=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+compose_project,'--filter','label=com.docker.compose.service=postiz'],text=True).strip()
 if not container:raise RuntimeError('CancellationWorkerUnavailable')
 script='const postid='+json.dumps(postid)+''';
const {Connection,Client}=require('@temporalio/client');
(async()=>{const connection=await Connection.connect({address:process.env.TEMPORAL_ADDRESS});try{
 const client=new Client({connection,namespace:'default'});
 async function stop(id){const h=client.workflow.getHandle(id);try{const d=await h.describe();if(d.status.name==='RUNNING')await h.terminate('Origin media removed from managed posting folder');}catch(e){if(!['WorkflowNotFoundError','WorkflowExecutionAlreadyCompletedError'].includes(e.name))throw e}}
 for(let pass=0;pass<3;pass++){
  await stop('post_'+postid);
  for await(const run of client.workflow.list({query:'postId="'+postid.replace(/[^a-zA-Z0-9_-]/g,'')+'" AND ExecutionStatus="Running"'}))await stop(run.workflowId);
  await new Promise(resolve=>setTimeout(resolve,500));
 }
 try{const d=await client.workflow.getHandle('post_'+postid).describe();if(d.status.name==='RUNNING')throw Error('Canceled workflow still running')}catch(e){if(e.name!=='WorkflowNotFoundError')throw e}
 console.log('Workflow cancellation verified');
}finally{await connection.close()}})().catch(e=>{console.error(e.name);process.exitCode=1});'''
 result=subprocess.run(['docker','exec','-i','-w','/app',container,'node'],input=script,capture_output=True,text=True,timeout=35)
 if result.returncode:raise RuntimeError('WorkflowCancellationNotConfirmed')
