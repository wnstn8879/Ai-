"""Fallback sync when Sites helper files are absent. Credentials stay in memory."""
import base64,getpass,json,os,subprocess,sys
cred=json.loads(getpass.getpass('Sites source credential (hidden): '));branch=cred['branch'];env=dict(os.environ,GIT_TERMINAL_PROMPT='0')
def git(*args,check=True):return subprocess.run(['git',*args],env=env,text=True,capture_output=True,check=check)
if not os.path.isdir('.git'):
 git('init','-b',branch);git('remote','add','origin',cred['remote_url'])
if cred.get('token'):env.update(GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='http.extraHeader',GIT_CONFIG_VALUE_0='Authorization: Bearer '+cred['token'])
probe=git('ls-remote','origin','refs/heads/'+branch,check=False)
if probe.returncode and cred.get('token'):
 env['GIT_CONFIG_VALUE_0']='Authorization: Basic '+base64.b64encode(('x-access-token:'+cred['token']).encode()).decode();probe=git('ls-remote','origin','refs/heads/'+branch,check=False)
if probe.returncode:print('Source authentication failed',file=sys.stderr);raise SystemExit(1)
if probe.stdout.strip() and git('rev-parse','--verify','HEAD',check=False).returncode:git('fetch','origin',branch);git('reset','--mixed','FETCH_HEAD')
git('config','user.name','IMAGINE development');git('config','user.email','imagine-dev@users.noreply.local');git('add','.')
if git('diff','--cached','--quiet',check=False).returncode:git('commit','-m','Deploy IMAGINE online novel creation and branching')
r=git('push','origin','HEAD:'+branch,check=False)
if r.returncode:print('Source push failed: '+r.stderr,file=sys.stderr);raise SystemExit(1)
print(json.dumps({'commit_sha':git('rev-parse','HEAD').stdout.strip(),'branch':branch}))
