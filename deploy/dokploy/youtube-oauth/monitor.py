#!/usr/bin/python3
import fcntl,json,os,pathlib,subprocess,sys
os.umask(0o077);root=pathlib.Path('/var/lib/amssoft-youtube-oauth');root.mkdir(exist_ok=True);lock=(root/'run.lock').open('w')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:sys.exit(0)
cfg=json.loads(pathlib.Path('/opt/postiz-amssoft/automation/youtube-oauth/config.json').read_text());container=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+cfg['compose_project'],'--filter','label=com.docker.compose.service=postiz'],text=True).strip()
if not container:raise SystemExit('PostizUnavailable')
previous={}
if (root/'private-state.json').exists():previous={x['channelKey']:x for x in json.loads((root/'private-state.json').read_text())['channels']}
script=pathlib.Path(__file__).with_name('check.cjs').read_text()+'\nmain('+json.dumps(previous)+','+('true' if '--force-refresh' in sys.argv else 'false')+').then(x=>console.log(JSON.stringify(x))).catch(e=>{console.error(e.name);process.exitCode=1});'
r=subprocess.run(['docker','exec','-i','-w','/app',container,'node'],input=script,capture_output=True,text=True,timeout=90)
if r.returncode:raise SystemExit('YouTubeCheckFailed; inspect private service logs')
data=json.loads(r.stdout);temp=root/'private-state.tmp';temp.write_text(json.dumps(data,indent=2));temp.replace(root/'private-state.json')
public={**data,'channels':[{k:v for k,v in c.items() if k not in ['fingerprint','channelKey']} for c in data['channels']]};temp=root/'status.tmp';temp.write_text(json.dumps(public,indent=2));temp.replace(root/'status.json');print(json.dumps(public));
if not data['ready']:sys.exit(1)
