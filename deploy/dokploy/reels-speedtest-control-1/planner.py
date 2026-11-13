#!/usr/bin/python3
"""Plan a daily native Postiz Reel pair, with a cooldown after the whole cycle."""
import datetime as dt,fcntl,hashlib,json,os,pathlib,re,sqlite3,subprocess,sys,zoneinfo
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'common'))
from workflow_cancel import cancel_workflow
UTC=dt.timezone.utc

def natural(value):return [int(x) if x.isdigit() else x.casefold() for x in re.split(r'(\d+)',value)]
def instant(value):
 value=dt.datetime.fromisoformat(value)
 return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
def conflict(at,posts,gap):
 for post in posts:
  base=instant(post['publishDate']);repeat=post.get('intervalInDays')
  if repeat:
   period=dt.timedelta(days=repeat);n=max(0,round((at-base)/period));base+=n*period
  if abs((at-base).total_seconds())<gap*60:return True
 return False

def free_slot(day,not_before,posts,timezone,preferred=6,gap=60,reserved=(6,12,18)):
 tz=zoneinfo.ZoneInfo(timezone)
 for hour in list(range(preferred,24))+list(range(6,preferred)):
  at=dt.datetime.combine(day,dt.time(hour),tz).astimezone(UTC)
  if hour in reserved or at<not_before:continue
  if not conflict(at,posts,gap):return at
 return None

def cooldown_ready(completed_at,now,days=60):return completed_at is not None and now>=instant(completed_at)+dt.timedelta(days=days)

def run():
 os.umask(0o077);cfg=json.loads(pathlib.Path(os.environ.get('POSTIZ_REELS_CONFIG','/opt/postiz-amssoft/automation/reels-speedtest-control-1/config.json')).read_text());root=pathlib.Path(cfg['state_directory']);root.mkdir(parents=True,exist_ok=True)
 lock=(root/'run.lock').open('w')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:return
 status={'checkedAt':dt.datetime.now(UTC).isoformat(),'timezone':cfg['timezone'],'issues':[],'mediaCount':0,'planned':0};state=None
 try:
  project=cfg['compose_project'];dbc=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service=postiz-postgres'],text=True).strip()
  if not dbc:raise RuntimeError('DatabaseUnavailable')
  def quote(v):return "'"+str(v).replace("'","''")+"'"
  def sql(q):
   r=subprocess.run(['docker','exec','-i',dbc,'sh','-lc','psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1'],input=q,capture_output=True,text=True,timeout=30)
   if r.returncode:raise RuntimeError('DatabaseReadFailed')
   return json.loads(r.stdout)
  org=sql('SELECT row_to_json(x) FROM (SELECT id,"apiKey" FROM "Organization" WHERE "deletedAt" IS NULL LIMIT 1)x;');key=org['apiKey'];assert key and '\n' not in key and '"' not in key
  channels=sql('SELECT coalesce(json_agg(x),\'[]\') FROM (SELECT id,"providerIdentifier","internalId",disabled,"refreshNeeded" FROM "Integration" WHERE "organizationId"='+quote(org['id'])+' AND "deletedAt" IS NULL)x;');selected=[]
  for provider,internal in cfg['channels'].items():
   matches=[p for p in channels if p['providerIdentifier']==provider and p['internalId']==internal];assert provider in ['instagram','facebook'] and len(matches)==1
   if matches[0]['disabled'] or matches[0]['refreshNeeded']:raise RuntimeError('ChannelUnavailable:'+provider)
   selected+=matches
  assert 1<=len(selected)<=2
  def api(path,method='GET',body=None,file=None):
   command=['curl','--silent','--show-error','--max-time','180','--config','-','--request',method,cfg['postiz_url'].rstrip('/')+'/api/public/v1'+path,'--write-out','\n%{http_code}']
   if body is not None:command+=['--header','Content-Type: application/json','--data-binary',json.dumps(body)]
   if file:command+=['--form','file=@"'+str(file).replace('\\','\\\\').replace('"','\\"')+'";type=video/mp4']
   r=subprocess.run(command,input='header = "Authorization: '+key+'"\n',capture_output=True,text=True)
   try:text,code=r.stdout.rsplit('\n',1);code=int(code)
   except ValueError:raise RuntimeError('UnknownApiOutcome')
   if r.returncode or code>=400:raise RuntimeError('PostizHTTP:'+str(code))
   return json.loads(text) if text else None
  state=sqlite3.connect(root/'campaign.sqlite');state.row_factory=sqlite3.Row;state.executescript('CREATE TABLE IF NOT EXISTS assets(hash TEXT PRIMARY KEY,file TEXT,position INTEGER,media TEXT,active INTEGER,probe TEXT);CREATE TABLE IF NOT EXISTS cycles(id INTEGER PRIMARY KEY,state TEXT,created TEXT,completed TEXT,not_before TEXT);CREATE TABLE IF NOT EXISTS items(cycle INTEGER,hash TEXT,position INTEGER,date TEXT,posts TEXT,state TEXT,error TEXT,PRIMARY KEY(cycle,hash));')
  directory=pathlib.Path(cfg['directory']);now=dt.datetime.now(UTC);tz=zoneinfo.ZoneInfo(cfg['timezone']);active=[]
  for p in sorted(directory.iterdir(),key=lambda p:natural(p.name)):
   if p.is_symlink() or not p.is_file() or p.suffix.lower()!='.mp4':continue
   st=p.stat()
   if not 0<st.st_size<=cfg.get('max_bytes',1024**3):status['issues'].append('InvalidSize:'+p.name);continue
   if now.timestamp()-st.st_mtime<45:continue
   fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
   with os.fdopen(fd,'rb') as f:
    head=f.read(64);f.seek(0);digest=hashlib.file_digest(f,'sha256').hexdigest();after=os.fstat(f.fileno())
   if b'ftyp' not in head or (st.st_ino,st.st_size,st.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):status['issues'].append('InvalidOrChangingVideo:'+p.name);continue
   known=state.execute('SELECT * FROM assets WHERE hash=?',(digest,)).fetchone()
   if not known:
    command=['docker','run','--rm','--network','none','--read-only','--user','1000:1000','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','256m','--cpus','.5','--entrypoint','ffprobe','-v',str(directory)+':/candidate:ro',cfg['probe_image'],'-v','error','-show_entries','format=duration:stream=codec_name,codec_type,width,height','-of','json','/candidate/'+p.name];r=subprocess.run(command,capture_output=True,text=True,timeout=30)
    if r.returncode:status['issues'].append('ProbeFailed:'+p.name);continue
    probe=json.loads(r.stdout);video=[s for s in probe['streams'] if s['codec_type']=='video']
    if len(video)!=1 or video[0]['height']<video[0]['width'] or video[0]['codec_name']!='h264':status['issues'].append('UnsupportedReelVideo:'+p.name);continue
    position=state.execute('SELECT coalesce(max(position),-1)+1 FROM assets').fetchone()[0];state.execute('INSERT INTO assets VALUES(?,?,?,NULL,1,?)',(digest,p.name,position,json.dumps(probe)))
   else:state.execute('UPDATE assets SET file=?,active=1 WHERE hash=?',(p.name,digest))
   active.append(digest)
  for row in state.execute('SELECT hash,file FROM assets WHERE active=1').fetchall():
   p=directory/row['file']
   if row['hash'] not in active and (not p.exists() or now.timestamp()-p.stat().st_mtime>45):state.execute('UPDATE assets SET active=0 WHERE hash=?',(row['hash'],))
  state.commit();assets=state.execute('SELECT * FROM assets WHERE active=1 ORDER BY position').fetchall();status['mediaCount']=len(assets)
  def remote_posts(ids):
   if not ids:return []
   return sql('SELECT coalesce(json_agg(x),\'[]\') FROM (SELECT id,state,"publishDate","deletedAt",image,"integrationId" FROM "Post" WHERE id IN ('+','.join(quote(i) for i in ids)+'))x;')
  # Retire source removals before planning; never leave a hidden native execution.
  for row in state.execute("SELECT i.*,a.active FROM items i JOIN assets a ON a.hash=i.hash WHERE a.active=0 AND i.state!='removed'").fetchall():
   posts=json.loads(row['posts']or'[]');remote=remote_posts([p['postId'] for p in posts]);pending=False
   for p in remote:
    if p['state']=='PUBLISHED':continue
    if instant(p['publishDate'])<=now+dt.timedelta(minutes=3):status['issues'].append('RemovalTooCloseOrStarted:'+p['id']);pending=True;continue
    if not p['deletedAt']:api('/posts/'+p['id'],'DELETE')
    cancel_workflow(p['id'],project)
   if row['state']=='creating' and not posts:status['issues'].append('RemovedCreationNeedsReconciliation');pending=True
   if not pending:state.execute("UPDATE items SET state='removed' WHERE cycle=? AND hash=?",(row['cycle'],row['hash']));state.commit()
  cycle=state.execute('SELECT * FROM cycles ORDER BY id DESC LIMIT 1').fetchone()
  if cycle and cycle['state']=='active':
   items=state.execute('SELECT * FROM items WHERE cycle=?',(cycle['id'],)).fetchall()
   for item in items:
    if item['state'] in ['removed','published']:continue
    ids=[p['postId'] for p in json.loads(item['posts']or'[]')];remote=remote_posts(ids)
    if len(remote)==len(selected) and all(p['state']=='PUBLISHED' and not p['deletedAt'] for p in remote):state.execute("UPDATE items SET state='published',error=NULL WHERE cycle=? AND hash=?",(cycle['id'],item['hash']))
    elif any(p['state']=='ERROR' or p['deletedAt'] for p in remote):status['issues'].append('PublicationNeedsReview:'+item['date'])
   state.commit();left=state.execute("SELECT count(*) FROM items WHERE cycle=? AND state NOT IN ('published','removed')",(cycle['id'],)).fetchone()[0]
   existing={p[0] for p in state.execute('SELECT hash FROM items WHERE cycle=?',(cycle['id'],))};new=[a for a in assets if a['hash'] not in existing]
   if items and left==0 and not new:
    completed=now.isoformat();not_before=(now+dt.timedelta(days=cfg['cooldown_days'])).isoformat();state.execute("UPDATE cycles SET state='cooldown',completed=?,not_before=? WHERE id=?",(completed,not_before,cycle['id']));state.commit();cycle=state.execute('SELECT * FROM cycles WHERE id=?',(cycle['id'],)).fetchone()
  if cycle and cycle['state']=='cooldown' and not cooldown_ready(cycle['completed'],now,cfg['cooldown_days']):status['phase']='cooldown';status['notBefore']=cycle['not_before']
  elif assets:
   if not cycle or cycle['state']=='cooldown':
    state.execute("INSERT INTO cycles(state,created) VALUES('active',?)",(now.isoformat(),));state.commit();cycle=state.execute('SELECT * FROM cycles ORDER BY id DESC LIMIT 1').fetchone()
   status['phase']='active';status['cycle']=cycle['id']
   busy=sql('SELECT coalesce(json_agg(x),\'[]\') FROM (SELECT id,"publishDate","intervalInDays" FROM "Post" WHERE "organizationId"='+quote(org['id'])+' AND "deletedAt" IS NULL AND state IN (\'QUEUE\',\'PUBLISHED\') AND ("publishDate">'+quote((now-dt.timedelta(days=1)).isoformat())+' OR "intervalInDays" IS NOT NULL))x;')
   items=state.execute('SELECT * FROM items WHERE cycle=? ORDER BY position',(cycle['id'],)).fetchall();known={x['hash'] for x in items};last=max((instant(x['date']).astimezone(tz).date() for x in items),default=now.astimezone(tz).date()-dt.timedelta(days=1));preferred=instant(items[0]['date']).astimezone(tz).hour if items else 6
   for asset in assets:
    if asset['hash'] in known:continue
    day=max(last+dt.timedelta(days=1),now.astimezone(tz).date());at=None
    for _ in range(366):
     at=free_slot(day,now+dt.timedelta(minutes=10),busy,cfg['timezone'],preferred,cfg['min_gap_minutes'],cfg['reserved_hours'])
     if at:break
     day+=dt.timedelta(days=1)
    if at is None:raise RuntimeError('NoFreeDailySlot')
    if not items and not known:preferred=at.astimezone(tz).hour
    state.execute("INSERT INTO items VALUES(?,?,?,?,NULL,'reserved',NULL)",(cycle['id'],asset['hash'],asset['position'],at.isoformat()));state.commit();known.add(asset['hash']);last=day;busy.append({'id':'reserved','publishDate':at.isoformat(),'intervalInDays':None})
   # Every item is one paired post occurrence, never a daily repeating post.
   for item in state.execute('SELECT i.*,a.media,a.file,a.active FROM items i JOIN assets a ON a.hash=i.hash WHERE cycle=? ORDER BY i.position',(cycle['id'],)).fetchall():
    if item['state'] in ['scheduled','published','removed'] or not item['active']:continue
    if item['state']=='creating':
     media=json.loads(item['media']);rows=sql('SELECT coalesce(json_agg(x),\'[]\') FROM (SELECT id,"integrationId",image FROM "Post" WHERE "organizationId"='+quote(org['id'])+' AND "publishDate"='+quote(instant(item['date']).strftime('%Y-%m-%d %H:%M:%S'))+' AND "deletedAt" IS NULL)x;');matches=[p for p in rows if p['integrationId'] in [c['id'] for c in selected] and any(m.get('id')==media['id'] for m in json.loads(p['image']or'[]'))]
     if len(matches)==len(selected) and len({p['integrationId'] for p in matches})==len(selected):state.execute("UPDATE items SET posts=?,state='scheduled' WHERE cycle=? AND hash=?",(json.dumps([{'postId':p['id'],'integration':p['integrationId']} for p in matches]),cycle['id'],item['hash']));state.commit();continue
     status['issues'].append('CreationNeedsReconciliation:'+item['date']);break
    if instant(item['date'])<=dt.datetime.now(UTC)+dt.timedelta(minutes=3):status['issues'].append('ReservedDateNeedsReview:'+item['date']);break
    media=json.loads(item['media']) if item['media'] else None
    if not media:
     media=api('/upload','POST',file=directory/item['file']);assert media.get('id') and media.get('path');state.execute('UPDATE assets SET media=? WHERE hash=?',(json.dumps(media),item['hash']));state.commit()
    posts=[]
    for c in selected:
     settings={'__type':c['providerIdentifier'],'post_type':'post'}
     if c['providerIdentifier']=='instagram':settings.update({'is_trial_reel':False,'collaborators':[],'share_to_feed':False})
     else:settings['title']=cfg.get('title','')
     posts.append({'integration':{'id':c['id']},'settings':settings,'value':[{'content':cfg.get('caption',''),'image':[{'id':media['id'],'path':media['path']}]}]})
    state.execute("UPDATE items SET state='creating' WHERE cycle=? AND hash=?",(cycle['id'],item['hash']));state.commit()
    try:result=api('/posts','POST',{'type':'schedule','date':item['date'],'shortLink':False,'tags':[],'posts':posts})
    except RuntimeError as error:
     if str(error)=='PostizHTTP:429':
      state.execute("UPDATE items SET state='reserved',error='RateLimited' WHERE cycle=? AND hash=?",(cycle['id'],item['hash']));state.commit();status['issues'].append('RateLimitedRetryOnNextRun');break
     raise
    assert len(result)==len(selected)
    state.execute("UPDATE items SET posts=?,state='scheduled',error=NULL WHERE cycle=? AND hash=?",(json.dumps(result),cycle['id'],item['hash']));state.commit();status['planned']+=1
   status['items']=[{'file':x['file'],'at':x['date'],'localTime':instant(x['date']).astimezone(tz).isoformat(),'state':x['state']} for x in state.execute('SELECT i.*,a.file FROM items i JOIN assets a ON a.hash=i.hash WHERE i.cycle=? ORDER BY i.position',(cycle['id'],))]
  else:status['phase']='waitingForMedia'
 except Exception as error:status['issues'].append(type(error).__name__+':'+str(error))
 finally:
  if state:state.close()
  tmp=root/'status.tmp';tmp.write_text(json.dumps(status,ensure_ascii=False,indent=2));tmp.replace(root/'status.json');lock.close()
 print(json.dumps({k:v for k,v in status.items() if k!='items'},ensure_ascii=False))
 if status['issues']:raise SystemExit(1)
if __name__=='__main__':run()
