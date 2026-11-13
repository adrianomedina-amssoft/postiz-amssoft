#!/usr/bin/python3
import datetime as dt,fcntl,hashlib,json,os,pathlib,sqlite3,subprocess,sys,uuid,zoneinfo
os.umask(0o077)
ROOT=pathlib.Path('/var/lib/amssoft-postiz-status');ROOT.mkdir(exist_ok=True)
lock=(ROOT/'recurrence.lock').open('w')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:sys.exit(0)
UTC=dt.timezone.utc
cfg=json.loads(pathlib.Path(os.environ.get('POSTIZ_RECURRENCE_CONFIG','/opt/amssoft-postiz-status-automation/config.json')).read_text())
def container(service):
 x=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+cfg['compose_project'],'--filter','label=com.docker.compose.service='+service],text=True).strip()
 if not x:raise RuntimeError('PostizUnavailable')
 return x
DBC=container('postiz-postgres')
def sql(q):
 r=subprocess.run(['docker','exec','-i',DBC,'sh','-lc','psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1'],input=q,capture_output=True,text=True,timeout=25)
 if r.returncode:raise RuntimeError('DatabaseReadFailed')
 return json.loads(r.stdout)
def quote(v):return "'"+str(v).replace("'","''")+"'"
org=sql('SELECT row_to_json(x) FROM (SELECT id,"apiKey" FROM "Organization" WHERE "deletedAt" IS NULL LIMIT 1)x;')
channels=sql('SELECT coalesce(json_agg(x),\'[]\') FROM (SELECT id,disabled,"refreshNeeded" FROM "Integration" WHERE "providerIdentifier"=\'whatsapp-status\' AND "organizationId"='+quote(org['id'])+' AND "deletedAt" IS NULL)x;')
if len(channels)!=1 or channels[0]['disabled'] or channels[0]['refreshNeeded']:raise RuntimeError('WhatsAppChannelUnavailable')
channel=channels[0]['id'];api_key=org['apiKey'];assert api_key and '\n' not in api_key and '"' not in api_key
headers='header = "Authorization: '+api_key+'"\n'
def api(path,method='GET',body=None,file=None):
 args=['curl','--silent','--show-error','--max-time','140','--config','-','--request',method,cfg['postiz_url'].rstrip('/')+'/api/public/v1'+path,'--write-out','\n%{http_code}']
 if body is not None:args+=['--header','Content-Type: application/json','--data-binary',json.dumps(body)]
 if file:args+=['--form','file=@"'+str(file).replace('\\','\\\\').replace('"','\\"')+'";type=video/mp4']
 r=subprocess.run(args,input=headers,capture_output=True,text=True)
 try:text,status=r.stdout.rsplit('\n',1);status=int(status)
 except ValueError:raise RuntimeError('UnknownApiOutcome')
 if r.returncode or status>=400:raise RuntimeError('PostizHTTP:'+str(status))
 return json.loads(text) if text else None
TZ=zoneinfo.ZoneInfo(cfg['timezone'])
state=sqlite3.connect(ROOT/'recurrence.sqlite');state.row_factory=sqlite3.Row
state.executescript('CREATE TABLE IF NOT EXISTS series(hash TEXT PRIMARY KEY,file TEXT,media TEXT,postid TEXT,config TEXT,due TEXT,state TEXT,error TEXT);')
now=dt.datetime.now(UTC);assets=[];issues=[];agenda=[]
for p in sorted(pathlib.Path(cfg['directory']).iterdir()):
 if p.is_symlink() or not p.is_file() or p.suffix.lower()!='.mp4':continue
 st=p.stat()
 if not 0<st.st_size<=32*1024*1024 or now.timestamp()-st.st_mtime<45:continue
 with p.open('rb') as f:
  if b'ftyp' not in f.read(64):continue
  f.seek(0);digest=hashlib.file_digest(f,'sha256').hexdigest()
 after=p.stat()
 if (st.st_size,st.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):continue
 if any(a['hash']==digest for a in assets):continue
 assets.append({'hash':digest,'file':p.name,'path':p})
known=state.execute('SELECT * FROM series').fetchall()
managed=[r['postid'] for r in known if r['postid']]
remote={}
if managed:
 rows=sql('SELECT coalesce(json_agg(x),\'[]\') FROM (SELECT id,state,"deletedAt" FROM "Post" WHERE id IN ('+','.join(quote(v) for v in managed)+'))x;')
 remote={r['id']:r for r in rows}
for row in known:
 if cfg['enabled'] and any(a['hash']==row['hash'] for a in assets):continue
 if row['postid']:
  api('/posts/'+row['postid'],'DELETE')
 state.execute('DELETE FROM series WHERE hash=?',(row['hash'],));state.commit()
if cfg['enabled']:
 for i,a in enumerate(assets):
  if i*cfg['interval_minutes']>=(24-cfg['start_hour'])*60:issues.append('Vídeos excedem a janela diária; reduza o intervalo.');break
  signature=json.dumps([cfg['timezone'],cfg['start_hour'],cfg['interval_minutes'],i])
  row=state.execute('SELECT * FROM series WHERE hash=?',(a['hash'],)).fetchone()
  if row and row['postid'] and row['config']==signature:
   post=remote.get(row['postid'])
   if not post or post['deletedAt'] or post['state']=='ERROR':
    warning='Agenda exige revisão no Postiz: '+a['file'];issues.append(warning);agenda.append({'file':warning,'localTime':'verificar publicação '+row['postid'],'repeat':True,'postId':row['postid']});continue
   anchor=dt.datetime.fromisoformat(row['due']);today=now.astimezone(TZ).date();at=dt.datetime.combine(today,anchor.astimezone(TZ).timetz().replace(tzinfo=None),TZ)
   if at.astimezone(UTC)<now:at+=dt.timedelta(days=1)
   agenda.append({'file':a['file'],'localTime':at.strftime('%d/%m %H:%M')+' (Rondônia)','repeat':True,'postId':row['postid']});continue
  if row and row['postid']:api('/posts/'+row['postid'],'DELETE');state.execute('UPDATE series SET postid=NULL,state=\'prepared\' WHERE hash=?',(a['hash'],));state.commit()
  media=json.loads(row['media']) if row and row['media'] else None
  if not media:
   previous=pathlib.Path('/var/lib/amssoft-ads-stories/state.sqlite3')
   if previous.exists():
    old=sqlite3.connect('file:'+str(previous)+'?mode=ro',uri=True)
    cached=old.execute('SELECT media FROM assets WHERE hash=?',(a['hash'],)).fetchone();old.close()
    if cached and cached[0]:media=json.loads(cached[0])
   if not media:media=api('/upload','POST',file=a['path'])
  if not media.get('id') or not media.get('path'):raise RuntimeError('UploadNotConfirmed')
  # Start the permanent recurring series at the next daily slot. Initial one-off posts are handled separately.
  day=now.astimezone(TZ).date();at=dt.datetime.combine(day,dt.time(cfg['start_hour']),TZ)+dt.timedelta(minutes=i*cfg['interval_minutes'])
  if at.astimezone(UTC)<now+dt.timedelta(minutes=2):at+=dt.timedelta(days=1)
  due=at.astimezone(UTC).isoformat()
  if row and row['state']=='creating' and row['due']:
   due=row['due'];at=dt.datetime.fromisoformat(due).astimezone(TZ)
   matches=sql('SELECT coalesce(json_agg(x),\'[]\') FROM (SELECT id,image,"publishDate" FROM "Post" WHERE "integrationId"='+quote(channel)+' AND "deletedAt" IS NULL AND "publishDate"='+quote(dt.datetime.fromisoformat(due).strftime('%Y-%m-%d %H:%M:%S'))+')x;')
   matches=[p for p in matches if any(m.get('id')==media['id'] for m in json.loads(p['image']or'[]'))]
   if len(matches)==1:
    state.execute('UPDATE series SET postid=?,state=\'active\',error=NULL WHERE hash=?',(matches[0]['id'],a['hash']));state.commit();continue
   issues.append('Resultado de criação pendente; verificar agenda no Postiz: '+a['file']);continue
  state.execute('INSERT INTO series VALUES(?,?,?,NULL,?,?,\'creating\',NULL) ON CONFLICT(hash) DO UPDATE SET file=excluded.file,media=excluded.media,config=excluded.config,due=excluded.due,state=\'creating\',error=NULL',(a['hash'],a['file'],json.dumps(media),signature,due));state.commit()
  body={'type':'schedule','date':due,'inter':1,'shortLink':False,'tags':[],'posts':[{'integration':{'id':channel},'settings':{'__type':'whatsapp-status'},'value':[{'content':'','image':[{'id':media['id'],'path':media['path']}]}]}]}
  try:
   response=api('/posts','POST',body);postid=response[0]['postId'];state.execute('UPDATE series SET postid=?,state=\'active\' WHERE hash=?',(postid,a['hash']));state.commit();agenda.append({'file':a['file'],'localTime':at.strftime('%d/%m %H:%M')+' (Rondônia)','repeat':True,'postId':postid})
  except Exception as error:
   state.execute('UPDATE series SET error=? WHERE hash=?',(str(error),a['hash']));state.commit();issues.append(str(error));break
state.close()
(ROOT/'agenda.json').write_text(json.dumps(agenda,ensure_ascii=False))
(ROOT/'recurrence-status.json').write_text(json.dumps({'checkedAt':now.isoformat(),'assets':len(assets),'agenda':agenda,'issues':issues},ensure_ascii=False,indent=2));print(json.dumps({'assets':len(assets),'series':len(agenda),'issues':issues},ensure_ascii=False))
if issues:sys.exit(1)
