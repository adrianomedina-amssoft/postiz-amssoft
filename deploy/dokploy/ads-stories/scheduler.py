#!/usr/bin/python3
import datetime as dt,fcntl,hashlib,json,os,pathlib,sqlite3,subprocess,sys,uuid,zoneinfo,urllib.parse
os.umask(0o077)
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'common'))
from workflow_cancel import cancel_workflow
ROOT=pathlib.Path('/var/lib/amssoft-ads-stories');ROOT.mkdir(exist_ok=True)
lock=(ROOT/'run.lock').open('w')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:sys.exit(0)
cfg=json.loads(pathlib.Path('/opt/postiz-amssoft/automation/ads-stories/config.json').read_text());TZ=zoneinfo.ZoneInfo(cfg['timezone']);UTC=dt.timezone.utc
now=lambda:dt.datetime.now(UTC)
run={'checkedAt':now().isoformat(),'created':[],'cancelled':[],'errors':[]}
def container(service):
 value=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+cfg['compose_project'],'--filter','label=com.docker.compose.service='+service],text=True).strip()
 if not value:raise RuntimeError('ContainerUnavailable:'+service)
 return value
DB_CONTAINER=container('postiz-postgres')
def sql(query):
 r=subprocess.run(['docker','exec','-i',DB_CONTAINER,'sh','-lc','psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1'],input=query,capture_output=True,text=True,timeout=30)
 if r.returncode:raise RuntimeError('DatabaseReadFailed')
 return json.loads(r.stdout)
def quote(value):return "'"+str(value).replace("'","''")+"'"
organization=sql('SELECT row_to_json(x) FROM (SELECT id,"apiKey" FROM "Organization" WHERE "deletedAt" IS NULL LIMIT 1) x;')
channels=sql('SELECT coalesce(json_agg(x),\'[]\') FROM (SELECT id,name,"internalId","providerIdentifier",disabled,"refreshNeeded" FROM "Integration" WHERE "organizationId"='+quote(organization['id'])+' AND "deletedAt" IS NULL) x;')
selected={}
for provider,account in cfg['channels'].items():
 matches=[c for c in channels if c['providerIdentifier']==provider and c['internalId']==account]
 if len(matches)!=1 or matches[0]['disabled'] or matches[0]['refreshNeeded']:raise RuntimeError('ChannelUnavailable:'+provider)
 selected[provider]=matches[0]
key=organization['apiKey'];assert key and '\n' not in key and '"' not in key
headers='header = "Authorization: '+key+'"\n'
def api(path,method='GET',body=None,file=None):
 args=['curl','--silent','--show-error','--max-time','150','--config','-','--request',method,'https://postiz.amssoft.com.br/api/public/v1'+path,'--write-out','\n%{http_code}']
 if body is not None:args+=['--header','Content-Type: application/json','--data-binary',json.dumps(body)]
 if file:
  # Paths are data, never shell commands. Quote curl form filenames explicitly.
  escaped=str(file).replace('\\','\\\\').replace('"','\\"')
  args+=['--form','file=@"'+escaped+'";type=video/mp4']
 r=subprocess.run(args,input=headers,capture_output=True,text=True)
 try:text,status=r.stdout.rsplit('\n',1);status=int(status)
 except ValueError:raise RuntimeError('APITransportUnknown')
 if r.returncode or status>=400:
  (ROOT/'last-api-error.json').write_text(json.dumps({'status':status,'body':text[:6000],'path':path,'at':now().isoformat()}))
  raise RuntimeError('APIRequestFailed:'+str(status))
 return json.loads(text) if text else None
state=sqlite3.connect(ROOT/'state.sqlite3');state.row_factory=sqlite3.Row
state.executescript('''
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assets (hash TEXT PRIMARY KEY,name TEXT,path TEXT,position INTEGER,active INTEGER,media TEXT);
CREATE TABLE IF NOT EXISTS cycles (day TEXT PRIMARY KEY,start TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS slots (day TEXT,hash TEXT,slot INTEGER,PRIMARY KEY(day,hash),UNIQUE(day,slot));
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,day TEXT,hash TEXT,provider TEXT,date TEXT,state TEXT,error TEXT,UNIQUE(day,hash,provider));
''')
def meta(k):
 r=state.execute('SELECT value FROM meta WHERE key=?',(k,)).fetchone();return r[0] if r else None
def setmeta(k,v):state.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(k,v));state.commit()
if 'postid' not in [x[1] for x in state.execute('PRAGMA table_info(jobs)')]:
 state.execute('ALTER TABLE jobs ADD COLUMN postid TEXT');state.commit()
if 'interval' not in [x[1] for x in state.execute('PRAGMA table_info(cycles)')]:
 state.execute('ALTER TABLE cycles ADD COLUMN interval INTEGER NOT NULL DEFAULT 60');state.commit()
def existing(jobs):
 if not jobs:return {}
 dates=[dt.datetime.fromisoformat(j['date']).astimezone(UTC) for j in jobs]
 low=(min(dates)-dt.timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S');high=(max(dates)+dt.timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
 rows=sql('SELECT coalesce(json_agg(x),\'[]\') FROM (SELECT id,state,"publishDate","deletedAt","releaseURL","integrationId",image,(error IS NOT NULL AND error<>\'\') AS has_error FROM "Post" WHERE "integrationId" IN ('+','.join(quote(c['id']) for c in selected.values())+') AND "publishDate" BETWEEN '+quote(low)+' AND '+quote(high)+') x;')
 result={}
 for job in jobs:
  media=json.loads(job['media']);matches=[]
  for row in rows:
   date=dt.datetime.fromisoformat(row['publishDate'])
   if date.tzinfo is None:date=date.replace(tzinfo=UTC)
   attachments=json.loads(row['image'] or '[]')
   if row['integrationId']==selected[job['provider']]['id'] and date==dt.datetime.fromisoformat(job['date']) and any(x.get('id')==media['id'] or x.get('path')==media['path'] for x in attachments):matches.append(row)
  if len(matches)>1:raise RuntimeError('AmbiguousPostRecovery:'+job['id'])
  if matches:result[job['id']]=matches[0]
 return result
try:
 if not cfg['enabled']:raise RuntimeError('AutomationDisabled')
 paths=sorted(p for p in pathlib.Path(cfg['directory']).iterdir() if p.is_file() and p.suffix.lower()=='.mp4')
 active=[]
 for p in paths:
  if p.is_symlink():
   run['errors'].append('SymlinkSkipped:'+p.name);continue
  with p.open('rb') as stream:header=stream.read(64)
  if b'ftyp' not in header:
   run['errors'].append('InvalidMP4:'+p.name);continue
  stat=p.stat()
  if not stat.st_size or now().timestamp()-stat.st_mtime<45:continue
  with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
  after=p.stat()
  if (after.st_size,after.st_mtime_ns)!=(stat.st_size,stat.st_mtime_ns):continue
  row=state.execute('SELECT * FROM assets WHERE hash=?',(digest,)).fetchone()
  if not row:
   pos=state.execute('SELECT coalesce(max(position),-1)+1 FROM assets').fetchone()[0]
   state.execute('INSERT INTO assets VALUES (?,?,?,?,1,NULL)',(digest,p.name,str(p),pos))
  else:state.execute('UPDATE assets SET name=?,path=?,active=1 WHERE hash=?',(p.name,str(p),digest))
  active.append(digest)
 # Don't retire files still being copied; only retire entries whose original path vanished or changed stably.
 for row in state.execute('SELECT * FROM assets WHERE active=1').fetchall():
  p=pathlib.Path(row['path'])
  if row['hash'] not in active and (not p.exists() or now().timestamp()-p.stat().st_mtime>45):state.execute('UPDATE assets SET active=0 WHERE hash=?',(row['hash'],))
 state.commit()
 assets=state.execute('SELECT * FROM assets WHERE active=1 ORDER BY position').fetchall()
 for row in assets:
  if not row['media']:
   media=api('/upload','POST',file=pathlib.Path(row['path']))
   if not media.get('id') or not media.get('path'):raise RuntimeError('InvalidUploadResponse')
   state.execute('UPDATE assets SET media=? WHERE hash=?',(json.dumps(media),row['hash']));state.commit()
 assets=state.execute('SELECT * FROM assets WHERE active=1 ORDER BY position').fetchall()
 if assets and not meta('initial_day'):
  first=(now()+dt.timedelta(seconds=120)).replace(second=0,microsecond=0)
  setmeta('initial_day',first.astimezone(TZ).date().isoformat());setmeta('initial_start',first.isoformat())
 today=now().astimezone(TZ).date();interval=int(cfg['interval_minutes']);assert interval in [30,60]
 capacity=1440//interval
 if len(assets)>capacity:run['errors'].append('DailyCapacityExceeded: change interval_minutes; extra videos remain pending')
 for day in [today-dt.timedelta(days=1),today,today+dt.timedelta(days=1)]:
  daykey=day.isoformat()
  if daykey==meta('initial_day'):start=dt.datetime.fromisoformat(meta('initial_start'))
  else:start=dt.datetime.combine(day,dt.time(cfg['start_hour']),TZ).astimezone(UTC)
  initial_day=meta('initial_day')
  if not initial_day or daykey<initial_day:continue
  state.execute('INSERT OR IGNORE INTO cycles (day,start,interval) VALUES (?,?,?)',(daykey,start.isoformat(),interval))
  cycle=state.execute('SELECT start,interval FROM cycles WHERE day=?',(daykey,)).fetchone()
  start=dt.datetime.fromisoformat(cycle['start']);cycle_interval=cycle['interval'];cycle_capacity=1440//cycle_interval
  for asset in assets:
   slot=state.execute('SELECT slot FROM slots WHERE day=? AND hash=?',(daykey,asset['hash'])).fetchone()
   if slot is None:
    idx=state.execute('SELECT coalesce(max(slot),-1)+1 FROM slots WHERE day=?',(daykey,)).fetchone()[0]
    if idx>=cycle_capacity:continue
    state.execute('INSERT INTO slots VALUES (?,?,?)',(daykey,asset['hash'],idx));slot=(idx,)
   at=start+dt.timedelta(minutes=cycle_interval*slot[0]);date=at.isoformat()
   for provider,c in selected.items():
    postid=str(uuid.uuid5(uuid.NAMESPACE_URL,'amssoft/ads-storys/'+daykey+'/'+asset['hash']+'/'+provider+'/'+c['internalId']))
    if at<now()+dt.timedelta(seconds=10) and not state.execute('SELECT 1 FROM jobs WHERE id=?',(postid,)).fetchone():continue
    state.execute('INSERT OR IGNORE INTO jobs (id,day,hash,provider,date,state,error) VALUES (?,?,?,?,?,\'prepared\',NULL)',(postid,daykey,asset['hash'],provider,date))
  state.commit()
 jobs=state.execute('SELECT j.*,a.active,a.media,a.name FROM jobs j JOIN assets a ON a.hash=j.hash WHERE day>=? ORDER BY date,provider',((today-dt.timedelta(days=1)).isoformat(),)).fetchall()
 remote=existing(jobs)
 for j in jobs:
  j=dict(j);fresh=state.execute('SELECT date,state FROM jobs WHERE id=?',(j['id'],)).fetchone();j.update(dict(fresh))
  found=remote.get(j['id']);at=dt.datetime.fromisoformat(j['date'])
  if not j['active']:
   if j['state']=='removed':continue
   if found and found['state']=='QUEUE' and at>now()+dt.timedelta(minutes=2):
    if not found['deletedAt']:api('/posts/'+found['id'],'DELETE')
    cancel_workflow(found['id'],cfg['compose_project']);run['cancelled'].append(j['id'])
   state.execute('UPDATE jobs SET state=\'removed\' WHERE id=?',(j['id'],));state.commit();continue
  if found:
   status='deleted' if found['deletedAt'] else found['state']
   state.execute('UPDATE jobs SET state=?,error=?,postid=? WHERE id=?',(status,'PostizPublicationError' if found['has_error'] else None,found['id'],j['id']));state.commit();continue
  if j['state'] in ['removed','deleted','PUBLISHED']:continue
  if at<now()+dt.timedelta(seconds=10):
   if j['day']==meta('initial_day') and (now()-at).total_seconds()<600 and j['state'] in ['prepared','submitting']:
    newat=(now()+dt.timedelta(seconds=90)).replace(second=0,microsecond=0);delta=newat-at
    for other in state.execute('SELECT id,date FROM jobs WHERE day=? AND provider=? AND state IN (\'prepared\',\'submitting\')',(j['day'],j['provider'])).fetchall():
     shifted=dt.datetime.fromisoformat(other['date'])+delta;state.execute('UPDATE jobs SET date=? WHERE id=?',(shifted.isoformat(),other['id']))
    state.commit();at=newat;j['date']=newat.isoformat()
   else:
    state.execute('UPDATE jobs SET state=\'missed\' WHERE id=?',(j['id'],));state.commit();continue
  media=json.loads(j['media']);provider=j['provider'];c=selected[provider]
  body={'type':'schedule','date':j['date'],'shortLink':False,'tags':[],'posts':[{'integration':{'id':c['id']},'settings':{'__type':provider,'post_type':'story'},'value':[{'content':'','image':[{'id':media['id'],'path':media['path']}]}]}]}
  try:
   state.execute('UPDATE jobs SET state=\'submitting\' WHERE id=?',(j['id'],));state.commit()
   result=api('/posts','POST',body)
   if not result or not result[0].get('postId'):raise RuntimeError('InvalidPostResponse')
   state.execute('UPDATE jobs SET state=\'QUEUE\',error=NULL,postid=? WHERE id=?',(result[0]['postId'],j['id']));state.commit();run['created'].append({'id':j['id'],'file':j['name'],'provider':provider,'local_time':at.astimezone(TZ).isoformat()})
  except Exception as e:
   # Unknown HTTP results are reconciled by the deterministic Postiz ID before any retry.
   state.execute('UPDATE jobs SET error=? WHERE id=?',(type(e).__name__+':'+str(e),j['id']));state.commit();run['errors'].append({'id':j['id'],'kind':str(e)});break
 run['active_videos']=len(assets);run['interval_minutes']=interval
 run['jobs']=[dict(x) for x in state.execute('SELECT day,provider,date,state,error,id,postid FROM jobs WHERE day>=? ORDER BY date,provider', (today.isoformat(),))]
except Exception as e:run['errors'].append(type(e).__name__+':'+str(e))
finally:
 state.close();temp=ROOT/'status.tmp';temp.write_text(json.dumps(run,indent=2,ensure_ascii=False));temp.replace(ROOT/'status.json')
 with (ROOT/'history.jsonl').open('a') as f:f.write(json.dumps({k:v for k,v in run.items() if k!='jobs'},ensure_ascii=False)+'\n')
 print(json.dumps({k:v for k,v in run.items() if k!='jobs'},ensure_ascii=False))
if run['errors']:sys.exit(1)
