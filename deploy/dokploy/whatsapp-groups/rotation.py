#!/usr/bin/python3
import datetime as dt,fcntl,hashlib,json,os,pathlib,sqlite3,subprocess,sys,zoneinfo
UTC=dt.timezone.utc

def next_slots(now,timezone,count=3):
 tz=zoneinfo.ZoneInfo(timezone);today=now.astimezone(tz).date();result=[]
 for offset in range(4):
  for hour in [6,12,18]:
   at=dt.datetime.combine(today+dt.timedelta(days=offset),dt.time(hour),tz).astimezone(UTC)
   if at>now+dt.timedelta(minutes=3):result.append(at)
 return result[:count]

def choose_asset(assets,last_position):
 if not assets:return None
 return next((a for a in assets if a['position']>last_position),assets[0])

def run():
 os.umask(0o077);cfg=json.loads(pathlib.Path(os.environ.get('POSTIZ_GROUPS_CONFIG','/opt/amssoft-postiz-groups-automation/config.json')).read_text());root=pathlib.Path(cfg.get('state_directory','/var/lib/amssoft-postiz-groups'));root.mkdir(exist_ok=True)
 lock=(root/'run.lock').open('w')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:return
 status={'checkedAt':dt.datetime.now(UTC).isoformat(),'mediaCount':0,'issues':[],'slots':[]};state=None
 try:
  project=cfg['compose_project'];container=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service=postiz-postgres'],text=True).strip()
  if not container:raise RuntimeError('PostizDatabaseUnavailable')
  def quote(v):return "'"+str(v).replace("'","''")+"'"
  def sql(query):
   r=subprocess.run(['docker','exec','-i',container,'sh','-lc','psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1'],input=query,capture_output=True,text=True,timeout=25)
   if r.returncode:raise RuntimeError('DatabaseReadFailed')
   return json.loads(r.stdout)
  org=sql('SELECT row_to_json(x) FROM (SELECT id,"apiKey" FROM "Organization" WHERE "deletedAt" IS NULL LIMIT 1)x;')
  channels=sql('SELECT coalesce(json_agg(x),\'[]\') FROM (SELECT id,disabled,"refreshNeeded" FROM "Integration" WHERE "organizationId"='+quote(org['id'])+' AND "providerIdentifier"=\'whatsapp-groups\' AND "internalId"=\'amssoft-whatsapp-groups-all\' AND "deletedAt" IS NULL)x;')
  if len(channels)!=1 or channels[0]['disabled'] or channels[0]['refreshNeeded']:raise RuntimeError('GroupsChannelUnavailable')
  channel=channels[0]['id'];key=org['apiKey'];assert key and '\n' not in key and '"' not in key
  def api(path,method='GET',body=None,file=None,mime=None):
   command=['curl','--silent','--show-error','--max-time','140','--config','-','--request',method,cfg['postiz_url'].rstrip('/')+'/api/public/v1'+path,'--write-out','\n%{http_code}']
   if body is not None:command+=['--header','Content-Type: application/json','--data-binary',json.dumps(body)]
   if file:command+=['--form','file=@"'+str(file).replace('\\','\\\\').replace('"','\\"')+'";type='+mime]
   r=subprocess.run(command,input='header = "Authorization: '+key+'"\n',capture_output=True,text=True)
   try:body,code=r.stdout.rsplit('\n',1);code=int(code)
   except ValueError:raise RuntimeError('UnknownApiOutcome')
   if r.returncode or code>=400:raise RuntimeError('PostizHTTP:'+str(code))
   return json.loads(body) if body else None
  state=sqlite3.connect(root/'rotation.sqlite');state.row_factory=sqlite3.Row
  state.executescript('CREATE TABLE IF NOT EXISTS assets(hash TEXT PRIMARY KEY,file TEXT,position INTEGER,media TEXT,active INTEGER,mime TEXT);CREATE TABLE IF NOT EXISTS slots(at TEXT PRIMARY KEY,hash TEXT,postid TEXT,state TEXT,error TEXT);CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);')
  directory=pathlib.Path(cfg['directory']);active=[]
  for p in sorted(directory.iterdir()):
   if p.is_symlink() or not p.is_file() or p.suffix.lower() not in ['.mp4','.jpg','.jpeg','.png']:continue
   before=p.stat()
   if before.st_size<=0 or before.st_size>32*1024*1024:status['issues'].append('InvalidSize:'+p.name);continue
   if dt.datetime.now(UTC).timestamp()-before.st_mtime<45:continue
   fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
   with os.fdopen(fd,'rb') as f:head=f.read(64);f.seek(0);digest=hashlib.file_digest(f,'sha256').hexdigest()
   after=p.stat()
   if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):continue
   mime='video/mp4' if p.suffix.lower()=='.mp4' and b'ftyp' in head else 'image/png' if p.suffix.lower()=='.png' and head.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if p.suffix.lower() in ['.jpg','.jpeg'] and head.startswith(b'\xff\xd8\xff') else None
   if not mime:status['issues'].append('InvalidType:'+p.name);continue
   known=state.execute('SELECT * FROM assets WHERE hash=?',(digest,)).fetchone()
   if not known:
    command=['docker','run','--rm','--network','none','--read-only','--user','1000:1000','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','128m','--cpus','.5','--entrypoint','ffprobe','-v',str(directory)+':/candidate:ro',cfg['probe_image'],'-v','error','-show_entries','format=duration:stream=codec_name,codec_type','-of','json','/candidate/'+p.name]
    probe=subprocess.run(command,capture_output=True,text=True,timeout=25)
    if probe.returncode or not any(x.get('codec_type')=='video' for x in json.loads(probe.stdout).get('streams',[])):status['issues'].append('InvalidMedia:'+p.name);continue
    position=state.execute('SELECT coalesce(max(position),-1)+1 FROM assets').fetchone()[0];state.execute('INSERT INTO assets VALUES(?,?,?,NULL,1,?)',(digest,p.name,position,mime))
   else:state.execute('UPDATE assets SET file=?,active=1 WHERE hash=?',(p.name,digest))
   active.append(digest)
  for row in state.execute('SELECT hash,file FROM assets WHERE active=1').fetchall():
   p=directory/row['file']
   if row['hash'] not in active and (not p.exists() or dt.datetime.now(UTC).timestamp()-p.stat().st_mtime>45):state.execute('UPDATE assets SET active=0 WHERE hash=?',(row['hash'],))
  state.commit();assets=state.execute('SELECT * FROM assets WHERE active=1 ORDER BY position').fetchall();status['mediaCount']=len(assets)
  if not assets:status['waitingForMedia']=True
  now=dt.datetime.now(UTC)
  for at in next_slots(now,cfg['timezone']):
   if not assets:break
   anchor=at.isoformat();slot=state.execute('SELECT * FROM slots WHERE at=?',(anchor,)).fetchone()
   if slot and slot['state']=='created':continue
   if slot:
    asset=state.execute('SELECT * FROM assets WHERE hash=?',(slot['hash'],)).fetchone()
   else:
    last=state.execute("SELECT value FROM meta WHERE key='cursor'").fetchone();asset=choose_asset(assets,int(last[0]) if last else -1)
    state.execute("INSERT INTO slots VALUES(?,?,NULL,'prepared',NULL)",(anchor,asset['hash']));state.execute("INSERT INTO meta VALUES('cursor',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(asset['position']),));state.commit();slot=state.execute('SELECT * FROM slots WHERE at=?',(anchor,)).fetchone()
   media=json.loads(asset['media']) if asset['media'] else None
   if not media:
    media=api('/upload','POST',file=directory/asset['file'],mime=asset['mime'])
    if not media.get('id') or not media.get('path'):raise RuntimeError('UploadNotConfirmed')
    state.execute('UPDATE assets SET media=? WHERE hash=?',(json.dumps(media),asset['hash']));state.commit()
   if slot['state']=='creating':
    rows=sql('SELECT coalesce(json_agg(x),\'[]\') FROM (SELECT id,image FROM "Post" WHERE "integrationId"='+quote(channel)+' AND "publishDate"='+quote(at.strftime('%Y-%m-%d %H:%M:%S'))+' AND "deletedAt" IS NULL)x;');matches=[x for x in rows if any(y.get('id')==media['id'] for y in json.loads(x['image']or'[]'))]
    if len(matches)==1:state.execute("UPDATE slots SET postid=?,state='created',error=NULL WHERE at=?",(matches[0]['id'],anchor));state.commit();continue
    status['issues'].append('CreationNeedsReconciliation:'+anchor);break
   body={'type':'schedule','date':anchor,'shortLink':False,'tags':[],'posts':[{'integration':{'id':channel},'settings':{'__type':'whatsapp-groups'},'value':[{'content':'','image':[{'id':media['id'],'path':media['path']}]}]}]}
   state.execute("UPDATE slots SET state='creating' WHERE at=?",(anchor,));state.commit()
   result=api('/posts','POST',body);postid=result[0]['postId'];state.execute("UPDATE slots SET postid=?,state='created',error=NULL WHERE at=?",(postid,anchor));state.commit()
  status['slots']=[dict(x) for x in state.execute('SELECT s.at,s.state,s.postid,a.file FROM slots s JOIN assets a ON a.hash=s.hash WHERE s.at>? ORDER BY s.at',(now.isoformat(),))]
 except Exception as error:status['issues'].append(type(error).__name__+':'+str(error))
 finally:
  if state:state.close()
  temporary=root/'status.tmp';temporary.write_text(json.dumps(status,ensure_ascii=False,indent=2));temporary.replace(root/'status.json');lock.close()
 print(json.dumps(status,ensure_ascii=False))
 if status['issues']:raise SystemExit(1)

if __name__=='__main__':run()
