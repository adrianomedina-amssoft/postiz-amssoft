import { SocialAbstract, BadBody } from '../social.abstract';
import { AuthTokenDetails, PostDetails, PostResponse, PendingCheckResponse, SocialProvider } from './social.integrations.interface';
import { Integration } from '@prisma/client';
import { readFileSync } from 'node:fs';
import { makeSecureId } from '@gitroom/nestjs-libraries/services/make.secure.id';
import striptags from 'striptags';

export class WhatsappStatusProvider extends SocialAbstract implements SocialProvider {
  identifier = 'whatsapp-status';
  name = 'WhatsApp Status';
  isBetweenSteps = false;
  scopes: string[] = [];
  editor = 'normal' as const;
  maxConcurrentJob = 1;
  maxLength() { return 1024; }
  async customFields() { return [{ key: 'account', label: 'Conta gerenciada', type: 'text' as const, defaultValue: 'AMS SOFT', validation: '/^AMS SOFT$/' }]; }
  async generateAuthUrl() { const state = makeSecureId(20); return { url: state, codeVerifier: state, state: state }; }
  async refreshToken(): Promise<AuthTokenDetails> { return { id: 'amssoft-whatsapp-status', name: 'WhatsApp Status AMS SOFT', accessToken: 'gateway-managed', refreshToken: '', username: 'amssoft-status', expiresIn: 315360000 }; }
  async authenticate(params: { code: string; codeVerifier: string }): Promise<AuthTokenDetails | string> {
    const data = JSON.parse(Buffer.from(params.code, 'base64').toString());
    if (data.account !== 'AMS SOFT') return 'Conta não autorizada';
    const account = await this.bridge('/automation/account');
    if (!account.ready) return 'Conecte o WhatsApp no painel de Status antes de adicionar o canal';
    return this.refreshToken();
  }
  private async bridge(path: string, body?: unknown) {
    const base = process.env.WHATSAPP_STATUS_URL;
    const file = process.env.WHATSAPP_STATUS_TOKEN_FILE;
    if (!base || !file) throw new BadBody(this.identifier, '{}', '{}', 'Conexão com o serviço de Status não configurada');
    const url = new URL(base); if (url.protocol !== 'https:') throw new Error('Status service must use HTTPS');
    const response = await fetch(url.origin + path, { method: body === undefined ? 'GET' : 'POST', redirect: 'error', signal: AbortSignal.timeout(30000), headers: { Authorization: 'Bearer ' + readFileSync(file, 'utf8').trim(), Origin: url.origin, 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (!response.ok) throw new BadBody(this.identifier, '{}', '{}', 'Serviço de Status indisponível (HTTP ' + response.status + ')');
    return response.json();
  }
  async checkValidity(posts: Array<{ path: string }[]>): Promise<string | true> {
    if (posts.length !== 1 || posts[0]?.length !== 1 || !posts[0][0].path.split('?')[0].toLowerCase().endsWith('.mp4')) return 'Status do WhatsApp exige um único vídeo MP4 por publicação';
    return true;
  }
  async postPending(id: string, accessToken: string, posts: PostDetails[], integration: Integration): Promise<PostResponse[]> {
    if (posts.length !== 1 || posts[0].media?.length !== 1) throw new BadBody(this.identifier, '{}', '{}', 'Selecione um vídeo MP4 por Status');
    const first = posts[0]; const media = first.media![0];
    const frontend = new URL(process.env.FRONTEND_URL!); const path = new URL(media.path, frontend.origin + '/');
    const prefix = process.env.NEXT_PUBLIC_UPLOAD_DIRECTORY || '/uploads';
    const pathname = decodeURIComponent(path.pathname);
    if (path.origin !== frontend.origin || !pathname.startsWith(prefix + '/') || !pathname.toLowerCase().endsWith('.mp4')) throw new BadBody(this.identifier, '{}', '{}', 'Use um vídeo MP4 da biblioteca local do Postiz');
    const job = await this.bridge('/automation/jobs', { id: first.id, file: pathname.slice(prefix.length + 1), caption: striptags(first.message || '') });
    return [{ id: first.id, postId: job.id, releaseURL: '', status: 'pending', pendingData: { jobId: job.id } }];
  }
  async post(id: string, accessToken: string, posts: PostDetails[], integration: Integration): Promise<PostResponse[]> { return this.postPending(id, accessToken, posts, integration); }
  override async checkPostStatus(accessToken: string, data: { jobId: string }, integration: Integration): Promise<PendingCheckResponse> {
    if (!/^[a-zA-Z0-9-]+$/.test(data.jobId)) throw new Error('Invalid status job');
    const job = await this.bridge('/automation/jobs/' + data.jobId);
    if (job.state === 'SENT' || job.state === 'CONFIRMED') return { status: 'completed', postId: job.messageId || job.id, releaseURL: process.env.WHATSAPP_STATUS_URL! };
    if (job.state === 'FAILED') throw new BadBody(this.identifier, '{}', '{}', job.error || 'Falha na publicação de Status');
    return { status: 'pending', pendingData: data };
  }
}
