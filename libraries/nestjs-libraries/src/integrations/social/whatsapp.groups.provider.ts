import { WhatsappStatusProvider } from './whatsapp.status.provider';
import { BadBody } from '../social.abstract';
import { AuthTokenDetails, PostDetails, PostResponse, PendingCheckResponse } from './social.integrations.interface';
import { Integration } from '@prisma/client';
import { Context } from '@temporalio/activity';
import { createHash } from 'node:crypto';
import striptags from 'striptags';
export class WhatsappGroupsProvider extends WhatsappStatusProvider {
  identifier = 'whatsapp-groups';
  name = 'WhatsApp Grupos';
  async customFields() { return [{ key: 'target', label: 'Destino autorizado (all ou ID do grupo)', type: 'text' as const, defaultValue: 'all', validation: '/^(all|[0-9-]+@g\\.us)$/' }]; }
  async refreshToken(): Promise<AuthTokenDetails> { return { id:'amssoft-whatsapp-groups-all',name:'WhatsApp Grupos autorizados',accessToken:'gateway-managed',refreshToken:'',username:'amssoft-groups',expiresIn:315360000 }; }
  async authenticate(params: { code: string; codeVerifier: string }): Promise<AuthTokenDetails | string> {
    const data = JSON.parse(Buffer.from(params.code,'base64').toString()); const groups = await this.bridge('/automation/groups');
    if (!Array.isArray(groups) || !groups.length) return 'Nenhum grupo autorizado disponível';
    if (data.target === 'all') return this.refreshToken();
    const group = groups.find(g=>g.id===data.target); if(!group)return 'Grupo não autorizado';
    return { ...(await this.refreshToken()),id:'amssoft-whatsapp-group-'+group.id,name:'WhatsApp — '+group.title };
  }
  async checkValidity(posts: Array<{ path:string }[]>): Promise<string|true> { return posts.length===1 && posts[0]?.length===1 && /\.(mp4|png|jpe?g)(?:\?|$)/i.test(posts[0][0].path) ? true : 'Selecione uma mídia MP4, JPEG ou PNG por publicação'; }
  async postPending(id:string,token:string,posts:PostDetails[],integration:Integration):Promise<PostResponse[]> {
    if(posts.length!==1||posts[0].media?.length!==1)throw new BadBody(this.identifier,'{}','{}','Use uma mídia por publicação');
    const first=posts[0];const frontend=new URL(process.env.FRONTEND_URL!);const path=new URL(first.media![0].path,frontend.origin+'/');const prefix=process.env.NEXT_PUBLIC_UPLOAD_DIRECTORY||'/uploads';const pathname=decodeURIComponent(path.pathname);
    if(path.origin!==frontend.origin||!pathname.startsWith(prefix+'/')||!/\.(mp4|png|jpe?g)$/i.test(pathname))throw new BadBody(this.identifier,'{}','{}','Use mídia da biblioteca local do Postiz');
    const execution=Context.current().info.workflowExecution;const occurrence=createHash('sha256').update(first.id+'|'+execution.workflowId+'|'+execution.runId).digest('hex');
    const groupId=integration.internalId.startsWith('amssoft-whatsapp-group-')?integration.internalId.slice('amssoft-whatsapp-group-'.length):undefined;
    if(!groupId&&integration.internalId!=='amssoft-whatsapp-groups-all')throw new Error('Destino de grupo inválido');
    const job=await this.bridge('/automation/group-jobs',{id:occurrence,file:pathname.slice(prefix.length+1),caption:striptags(first.message||''),...(groupId?{groupIds:[groupId]}:{})});
    return [{id:first.id,postId:job.id,releaseURL:'',status:'pending',pendingData:{jobId:job.id}}];
  }
  async checkPostStatus(token:string,data:{jobId:string},integration:Integration):Promise<PendingCheckResponse> {
    if(!/^[a-zA-Z0-9-]+$/.test(data.jobId))throw new Error('Recibo inválido');
    const job=await this.bridge('/automation/group-jobs/'+data.jobId);
    if(['SENT','CONFIRMED'].includes(job.state))return{status:'completed',postId:job.id,releaseURL:process.env.WHATSAPP_STATUS_URL!};
    if(job.state==='FAILED')throw new BadBody(this.identifier,'{}','{}',job.error||'Falha em um ou mais grupos; consulte os recibos antes de repetir');
    return{status:'pending',pendingData:data};
  }
}
