"""NCC Sentinel: small-unit pilot web application. See README before internet deployment."""
import os, sqlite3, secrets, hmac, hashlib, random, time, json, logging, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager, asynccontextmanager
from typing import Optional

from argon2 import PasswordHasher
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE=Path(__file__).resolve().parent
DB=Path(os.getenv('DATABASE_PATH',str(BASE/'sentinel.db')))
DEV=os.getenv('DEV_MODE','1')=='1'
KEY=os.getenv('SESSION_SECRET','')
if not KEY:
    if not DEV: raise RuntimeError('Set SESSION_SECRET for deployment')
    KEY=secrets.token_urlsafe(32)
COOKIE_SECURE=os.getenv('COOKIE_SECURE','0')=='1'
SMS_MODE=os.getenv('SMS_MODE','demo') # demo or twilio
TWILIO_SID=os.getenv('TWILIO_ACCOUNT_SID','')
TWILIO_TOKEN=os.getenv('TWILIO_AUTH_TOKEN','')
TWILIO_FROM=os.getenv('TWILIO_FROM_NUMBER','')
TURNSTILE_SITE_KEY=os.getenv('TURNSTILE_SITE_KEY','')
TURNSTILE_SECRET=os.getenv('TURNSTILE_SECRET_KEY','')
if not DEV:
    if SMS_MODE!='twilio' or not COOKIE_SECURE or not TURNSTILE_SITE_KEY or not TURNSTILE_SECRET:
        raise RuntimeError('Production requires Twilio SMS, COOKIE_SECURE=1 and Cloudflare Turnstile credentials')
ph=PasswordHasher()
log=logging.getLogger('ncc')
logging.basicConfig(level=logging.INFO)
templates=Jinja2Templates(directory=str(BASE/'templates'))

@contextmanager
def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con=sqlite3.connect(DB, timeout=10, isolation_level=None)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=10000')
    try: yield con
    finally: con.close()

def now(): return int(time.time())
def new_id(): return secrets.token_hex(16)
def digest(value): return hmac.new(KEY.encode(),str(value).encode(),hashlib.sha256).hexdigest()
def setup():
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, name TEXT NOT NULL, reg_no TEXT UNIQUE NOT NULL, phone TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','cadet')), approved INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(id_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires INTEGER NOT NULL, csrf TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS otps(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), purpose TEXT NOT NULL, code_hash TEXT NOT NULL, expires INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS duties(id TEXT PRIMARY KEY, title TEXT NOT NULL, location TEXT NOT NULL, starts INTEGER NOT NULL, ends INTEGER NOT NULL, created_by TEXT NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL, CHECK(ends>starts));
        CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY, duty_id TEXT NOT NULL REFERENCES duties(id), user_id TEXT NOT NULL REFERENCES users(id), acknowledged INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'assigned', UNIQUE(duty_id,user_id));
        CREATE TABLE IF NOT EXISTS duty_sessions(id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL UNIQUE REFERENCES assignments(id), started INTEGER NOT NULL, ended INTEGER, next_check INTEGER NOT NULL, consecutive_fail INTEGER NOT NULL DEFAULT 0, total_fail INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES duty_sessions(id), issued INTEGER NOT NULL, deadline INTEGER NOT NULL, captcha_answer TEXT NOT NULL, captcha_text TEXT NOT NULL, captcha_passed INTEGER NOT NULL DEFAULT 0, otp_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', failure_reason TEXT, finished INTEGER);
        CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, challenge_id TEXT NOT NULL REFERENCES challenges(id), step TEXT NOT NULL, outcome TEXT NOT NULL, at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES duty_sessions(id), challenge_id TEXT NOT NULL REFERENCES challenges(id), name_snapshot TEXT NOT NULL, reg_snapshot TEXT NOT NULL, duty_title TEXT NOT NULL, reason TEXT NOT NULL, at INTEGER NOT NULL, consecutive INTEGER NOT NULL, total INTEGER NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0, UNIQUE(challenge_id));
        CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY, actor TEXT, action TEXT NOT NULL, target TEXT, at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS rate_limit(bucket TEXT NOT NULL, at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS rate_bucket ON rate_limit(bucket,at);
        CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS challenges_session ON challenges(session_id,status);
        ''')

def audit(c,actor,action,target=''):
    c.execute('INSERT INTO audit VALUES(?,?,?,?,?)',(new_id(),actor,action,target,now()))

def rate(c,bucket,maximum,seconds):
    t=now()
    c.execute('DELETE FROM rate_limit WHERE at<?',(t-86400,))
    if c.execute('SELECT COUNT(*) FROM rate_limit WHERE bucket=? AND at>=?',(bucket,t-seconds)).fetchone()[0]>=maximum:
        raise HTTPException(429,'Too many requests. Try again later.')
    c.execute('INSERT INTO rate_limit VALUES(?,?)',(bucket,t))

def clientip(req): return req.client.host if req.client else 'unknown'
def otp_code(): return f'{secrets.randbelow(1000000):06d}'

def send_sms(phone,body):
    if SMS_MODE=='demo':
        log.warning('DEMO SMS for %s: %s',phone,body)
        return
    if SMS_MODE!='twilio': raise RuntimeError('Unsupported SMS_MODE')
    if not all([TWILIO_SID,TWILIO_TOKEN,TWILIO_FROM]): raise RuntimeError('Twilio credentials missing')
    import httpx
    resp=httpx.post(f'https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json',auth=(TWILIO_SID,TWILIO_TOKEN),data={'From':TWILIO_FROM,'To':phone,'Body':body},timeout=8)
    resp.raise_for_status()

def make_otp(c,user,purpose):
    code=otp_code(); oid=new_id()
    c.execute('UPDATE otps SET used=1 WHERE user_id=? AND purpose=? AND used=0',(user['id'],purpose))
    c.execute('INSERT INTO otps VALUES(?,?,?,?,?,?,?,?)',(oid,user['id'],purpose,digest(oid+code),now()+180,0,0,now()))
    send_sms(user['phone'],f'NCC Sentinel {purpose} OTP: {code}. Valid for 3 minutes. Do not share it.')
    return oid

def check_otp(c,oid,code,purpose):
    r=c.execute('SELECT * FROM otps WHERE id=? AND purpose=?',(oid,purpose)).fetchone()
    if not r or r['used'] or r['expires']<now() or r['attempts']>=5: return None
    c.execute('UPDATE otps SET attempts=attempts+1 WHERE id=?',(oid,))
    if not hmac.compare_digest(r['code_hash'],digest(oid+code)): return None
    c.execute('UPDATE otps SET used=1 WHERE id=?',(oid,))
    return r['user_id']

def get_user(request):
    token=request.cookies.get('ncc_session','')
    if not token:return None
    with db() as c:
        s=c.execute('SELECT user_id,csrf FROM sessions WHERE id_hash=? AND expires>?',(digest(token),now())).fetchone()
        if not s:return None
        u=c.execute('SELECT id,name,reg_no,phone,role,approved FROM users WHERE id=?',(s['user_id'],)).fetchone()
        return dict(u)|{'csrf':s['csrf']} if u else None

def requires(request,role=None):
    u=get_user(request)
    if not u:raise HTTPException(401,'Login required')
    if not u['approved']:raise HTTPException(403,'Account pending approval')
    if role and u['role']!=role:raise HTTPException(403,'Not authorized')
    return u

def csrf_check(req,u,token):
    if not token or not hmac.compare_digest(token,u['csrf']):raise HTTPException(403,'Invalid form token')

def page(request,name,**ctx):
    u=get_user(request)
    return templates.TemplateResponse(request,name,{'user':u,'dev':DEV,'now':now(),'turnstile_key':TURNSTILE_SITE_KEY,**ctx},headers={'Cache-Control':'no-store'})

def redirect(path):return RedirectResponse(path,status_code=303)

def parse_local(s):
    # input format from HTML datetime-local; pilot operates with administrator-selected local UTC offset through TZ_OFFSET_MINUTES
    dt=datetime.strptime(s,'%Y-%m-%dT%H:%M')
    offset=int(os.getenv('TZ_OFFSET_MINUTES','330'))*60
    return int(dt.replace(tzinfo=timezone.utc).timestamp())-offset

def fail_challenge(c,ch,reason):
    if ch['status']!='pending':return
    c.execute('UPDATE challenges SET status=?, failure_reason=?,finished=? WHERE id=? AND status="pending"',('failed',reason,now(),ch['id']))
    sess=c.execute('SELECT * FROM duty_sessions WHERE id=?',(ch['session_id'],)).fetchone()
    if not sess:return
    cons=sess['consecutive_fail']+1;total=sess['total_fail']+1
    c.execute('UPDATE duty_sessions SET consecutive_fail=?,total_fail=? WHERE id=?',(cons,total,sess['id']))
    if cons>=2 or total>3:
        info=c.execute('''SELECT u.name,u.reg_no,d.title FROM duty_sessions s JOIN assignments a ON a.id=s.assignment_id JOIN users u ON u.id=a.user_id JOIN duties d ON d.id=a.duty_id WHERE s.id=?''',(sess['id'],)).fetchone()
        c.execute('INSERT OR IGNORE INTO incidents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(new_id(),sess['id'],ch['id'],info['name'],info['reg_no'],info['title'],reason,now(),cons,total,0))

def tick():
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        t=now()
        for ch in c.execute('SELECT * FROM challenges WHERE status="pending" AND deadline<?',(t,)).fetchall():fail_challenge(c,ch,'timeout')
        active=c.execute('''SELECT s.*,d.ends,u.phone FROM duty_sessions s JOIN assignments a ON a.id=s.assignment_id JOIN duties d ON d.id=a.duty_id JOIN users u ON u.id=a.user_id WHERE s.ended IS NULL''').fetchall()
        for s in active:
            if s['ends']<=t:
                c.execute('UPDATE duty_sessions SET ended=? WHERE id=?',(t,s['id']))
                continue
            if s['next_check']<=t:
                pending=c.execute('SELECT id FROM challenges WHERE session_id=? AND status="pending"',(s['id'],)).fetchone()
                if pending:continue
                a,b=secrets.randbelow(8)+2,secrets.randbelow(8)+2
                code=otp_code(); cid=new_id()
                c.execute('INSERT INTO challenges VALUES(?,?,?,?,?,?,?,?,?,?,?)',(cid,s['id'],t,t+30,str(a+b),f'{a} + {b} = ?',0,digest(cid+code),'pending',None,None))
                c.execute('UPDATE duty_sessions SET next_check=? WHERE id=?',(t+random.SystemRandom().randint(1200,2400),s['id']))
                try:send_sms(s['phone'],f'NCC Sentinel duty OTP: {code}. Complete CAPTCHA and OTP within 30 seconds of challenge issuance.')
                except Exception:
                    log.exception('Duty SMS failed; recording delivery exception')
                    ch=c.execute('SELECT * FROM challenges WHERE id=?',(cid,)).fetchone()
                    fail_challenge(c,ch,'delivery_exception')
        c.execute('COMMIT')

async def scheduler():
    import asyncio
    while True:
        try:tick()
        except Exception: log.exception('Scheduler error')
        await asyncio.sleep(2)

@asynccontextmanager
async def lifespan(app):
    setup()
    import asyncio
    task=asyncio.create_task(scheduler())
    yield
    task.cancel()
    try:await task
    except asyncio.CancelledError:pass

app=FastAPI(title='NCC Sentinel',lifespan=lifespan,docs_url=None,redoc_url=None)
app.mount('/static',StaticFiles(directory=str(BASE/'static')),name='static')
# Use a single Uvicorn worker for built-in scheduling in this small-unit pilot.
@app.middleware('http')
async def headers(req,call_next):
    resp=await call_next(req)
    resp.headers['X-Content-Type-Options']='nosniff'
    resp.headers['X-Frame-Options']='DENY'
    resp.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    resp.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' https://unpkg.com https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; img-src 'self' data: https://*.tile.openstreetmap.org; style-src 'self' 'unsafe-inline' https://unpkg.com; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    if COOKIE_SECURE:resp.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    return resp

@app.get('/sw.js', include_in_schema=False)
def service_worker():
    return FileResponse(BASE/'static'/'sw.js', media_type='application/javascript', headers={'Cache-Control':'no-cache','Service-Worker-Allowed':'/'})

@app.get('/health')
def health():return {'status':'ok'}

@app.get('/',response_class=HTMLResponse)
def index(request:Request):
    u=get_user(request)
    return redirect('/admin' if u and u['role']=='admin' else '/cadet' if u else '/login')

@app.get('/register',response_class=HTMLResponse)
def register_page(request:Request):return page(request,'register.html')

@app.post('/register')
def register(request:Request,name:str=Form(...),reg_no:str=Form(...),phone:str=Form(...),password:str=Form(...)):
    name=name.strip()[:90];reg_no=reg_no.strip().upper()[:40];phone=phone.strip()
    if not name or len(reg_no)<3 or not phone.startswith('+') or not phone[1:].isdigit() or len(phone)>16 or len(password)<12:
        return page(request,'register.html',error='Use a valid regimental number, E.164 phone (+91...), and password of at least 12 characters.')
    try:
        with db() as c:
            rate(c,'register:'+clientip(request),5,3600)
            if c.execute('SELECT COUNT(*) FROM users WHERE role="cadet"').fetchone()[0]>=10:
                return page(request,'register.html',error='Pilot capacity reached (10 cadets). Contact the administrator.')
            c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)',(new_id(),name,reg_no,phone,ph.hash(password),'cadet',0,now()))
    except sqlite3.IntegrityError:return page(request,'register.html',error='Regimental number or phone number already registered.')
    return page(request,'message.html',message='Registration submitted. An administrator must approve your account before login.')

@app.get('/login',response_class=HTMLResponse)
def login_page(request:Request):return page(request,'login.html')

@app.post('/login')
def login(request:Request,reg_no:str=Form(...),password:str=Form(...)):
    with db() as c:
        rate(c,'login-ip:'+clientip(request),25,900)
        rate(c,'login-account:'+digest(reg_no.upper()),6,900)
        u=c.execute('SELECT * FROM users WHERE reg_no=?',(reg_no.strip().upper(),)).fetchone()
        ok=False
        if u:
            try:ok=ph.verify(u['password_hash'],password)
            except Exception:pass
        if not ok or not u['approved']:
            return page(request,'login.html',error='Invalid credentials or account not approved.')
        rate(c,'send-otp:'+u['id'],3,900)
        try: oid=make_otp(c,u,'login')
        except Exception:
            log.exception('SMS error')
            return page(request,'login.html',error='OTP delivery unavailable. Contact administrator.')
    r=redirect('/verify-login');r.set_cookie('pending_login',oid,max_age=180,httponly=True,secure=COOKIE_SECURE,samesite='strict');return r

@app.get('/verify-login',response_class=HTMLResponse)
def verify_login_page(request:Request):return page(request,'verify.html')

@app.post('/verify-login')
def verify_login(request:Request,code:str=Form(...)):
    oid=request.cookies.get('pending_login','')
    with db() as c:
        rate(c,'otp-verify:'+clientip(request),25,900)
        uid=check_otp(c,oid,code.strip(),'login')
        if not uid:return page(request,'verify.html',error='Incorrect or expired OTP.')
        u=c.execute('SELECT role FROM users WHERE id=?',(uid,)).fetchone()
        token=secrets.token_urlsafe(32)
        c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(digest(token),uid,now()+28800,secrets.token_urlsafe(24)))
        audit(c,uid,'login')
    r=redirect('/admin' if u['role']=='admin' else '/cadet')
    r.set_cookie('ncc_session',token,max_age=28800,httponly=True,secure=COOKIE_SECURE,samesite='lax')
    r.delete_cookie('pending_login');return r

@app.post('/logout')
def logout(request:Request,csrf:str=Form(...)):
    u=requires(request);csrf_check(request,u,csrf)
    with db() as c:c.execute('DELETE FROM sessions WHERE id_hash=?',(digest(request.cookies.get('ncc_session','')),))
    r=redirect('/login');r.delete_cookie('ncc_session');return r

@app.get('/cadet',response_class=HTMLResponse)
def cadet_page(request:Request):
    u=requires(request,'cadet')
    with db() as c:
        duties=c.execute('''SELECT d.*,a.id assignment_id,a.acknowledged,s.id session_id,s.started,s.ended,s.total_fail,s.consecutive_fail FROM assignments a JOIN duties d ON d.id=a.duty_id LEFT JOIN duty_sessions s ON s.assignment_id=a.id WHERE a.user_id=? AND a.status='assigned' ORDER BY d.starts DESC LIMIT 40''',(u['id'],)).fetchall()
    return page(request,'cadet.html',duties=duties)

@app.post('/cadet/ack/{aid}')
def acknowledge(aid:str,request:Request,csrf:str=Form(...)):
    u=requires(request,'cadet');csrf_check(request,u,csrf)
    with db() as c:c.execute('UPDATE assignments SET acknowledged=1 WHERE id=? AND user_id=?',(aid,u['id']))
    return redirect('/cadet')

@app.post('/cadet/start/{aid}')
def start(aid:str,request:Request,csrf:str=Form(...)):
    u=requires(request,'cadet');csrf_check(request,u,csrf)
    with db() as c:
        a=c.execute('''SELECT a.id,d.starts,d.ends FROM assignments a JOIN duties d ON d.id=a.duty_id WHERE a.id=? AND a.user_id=? AND a.status='assigned' ''',(aid,u['id'])).fetchone()
        if not a:raise HTTPException(404,'Duty not found')
        if not (a['starts']-900<=now()<a['ends']):raise HTTPException(400,'Duty can start 15 minutes before the scheduled start, until its end.')
        c.execute('INSERT OR IGNORE INTO duty_sessions VALUES(?,?,?,?,?,?,?)',(new_id(),aid,now(),None,now()+random.SystemRandom().randint(1200,2400),0,0))
    return redirect('/cadet')

@app.post('/cadet/end/{sid}')
def end(sid:str,request:Request,csrf:str=Form(...)):
    u=requires(request,'cadet');csrf_check(request,u,csrf)
    with db() as c:
        c.execute('''UPDATE duty_sessions SET ended=? WHERE id=? AND ended IS NULL AND assignment_id IN (SELECT id FROM assignments WHERE user_id=?)''',(now(),sid,u['id']))
        audit(c,u['id'],'end-duty',sid)
    return redirect('/cadet')

@app.get('/api/challenge')
def challenge_status(request:Request):
    u=requires(request,'cadet')
    with db() as c:
        ch=c.execute('''SELECT ch.id,ch.captcha_text,ch.captcha_passed,ch.deadline,ch.status,d.title FROM challenges ch JOIN duty_sessions s ON s.id=ch.session_id JOIN assignments a ON a.id=s.assignment_id JOIN duties d ON d.id=a.duty_id WHERE a.user_id=? AND ch.status='pending' AND s.ended IS NULL ORDER BY ch.issued DESC LIMIT 1''',(u['id'],)).fetchone()
    return {'challenge':dict(ch) if ch else None,'server_time':now()}

@app.post('/api/challenge/captcha')
async def submit_captcha(request:Request):
    u=requires(request,'cadet');data=await request.json()
    if data.get('csrf')!=u['csrf']:raise HTTPException(403,'Invalid form token')
    cid=str(data.get('id',''));answer=str(data.get('answer',''))
    turnstile_ok=False
    if TURNSTILE_SITE_KEY:
        token=str(data.get('turnstile_token',''))
        if token:
            import httpx
            try:
                response=httpx.post('https://challenges.cloudflare.com/turnstile/v0/siteverify',
                    data={'secret':TURNSTILE_SECRET,'response':token,'remoteip':clientip(request)},timeout=6)
                turnstile_ok=bool(response.json().get('success'))
            except Exception: log.exception('Turnstile verification unavailable')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        ch=c.execute('''SELECT ch.* FROM challenges ch JOIN duty_sessions s ON s.id=ch.session_id JOIN assignments a ON a.id=s.assignment_id WHERE ch.id=? AND a.user_id=?''',(cid,u['id'])).fetchone()
        if not ch or ch['status']!='pending' or now()>ch['deadline']:raise HTTPException(400,'Expired or invalid challenge')
        correct=turnstile_ok if TURNSTILE_SITE_KEY else hmac.compare_digest(ch['captcha_answer'],answer.strip())
        c.execute('INSERT INTO attempts VALUES(?,?,?,?,?)',(new_id(),cid,'captcha','pass' if correct else 'fail',now()))
        if correct:c.execute('UPDATE challenges SET captcha_passed=1 WHERE id=?',(cid,))
        c.execute('COMMIT')
    return {'ok':correct}

@app.post('/api/challenge/otp')
async def submit_duty_otp(request:Request):
    u=requires(request,'cadet');data=await request.json()
    if data.get('csrf')!=u['csrf']:raise HTTPException(403,'Invalid form token')
    cid=str(data.get('id',''));code=str(data.get('code',''))
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        ch=c.execute('''SELECT ch.* FROM challenges ch JOIN duty_sessions s ON s.id=ch.session_id JOIN assignments a ON a.id=s.assignment_id WHERE ch.id=? AND a.user_id=?''',(cid,u['id'])).fetchone()
        if not ch or ch['status']!='pending' or now()>ch['deadline'] or not ch['captcha_passed']:
            raise HTTPException(400,'CAPTCHA required or challenge expired')
        correct=hmac.compare_digest(ch['otp_hash'],digest(cid+code))
        c.execute('INSERT INTO attempts VALUES(?,?,?,?,?)',(new_id(),cid,'otp','pass' if correct else 'fail',now()))
        if correct:
            c.execute('UPDATE challenges SET status="passed",finished=? WHERE id=?',(now(),cid))
            c.execute('UPDATE duty_sessions SET consecutive_fail=0 WHERE id=?',(ch['session_id'],))
        else:
            attempts=c.execute('SELECT COUNT(*) FROM attempts WHERE challenge_id=? AND step="otp" AND outcome="fail"',(cid,)).fetchone()[0]
            if attempts>=3:fail_challenge(c,ch,'invalid_otp')
        c.execute('COMMIT')
    result={'ok':correct}
    if correct:
        with db() as c:
            ch2=c.execute('SELECT * FROM challenges WHERE id=?',(cid,)).fetchone()
            location=create_location_challenge(c,ch2)
            if location:result['location']=location
    return result

@app.get('/admin',response_class=HTMLResponse)
def admin_page(request:Request):
    u=requires(request,'admin')
    with db() as c:
        cadets=c.execute('SELECT id,name,reg_no,phone,approved FROM users WHERE role="cadet" ORDER BY created_at DESC').fetchall()
        duties=c.execute('''SELECT d.*, (SELECT COUNT(*) FROM assignments a WHERE a.duty_id=d.id AND a.status='assigned') assigned FROM duties d ORDER BY starts DESC LIMIT 40''').fetchall()
        assignments=c.execute('''SELECT d.title,d.starts,d.ends,u.name,u.reg_no,a.id FROM assignments a JOIN duties d ON a.duty_id=d.id JOIN users u ON u.id=a.user_id ORDER BY d.starts DESC LIMIT 100''').fetchall()
        incidents=c.execute('SELECT * FROM incidents ORDER BY at DESC LIMIT 100').fetchall()
        attempts=c.execute('''SELECT ch.issued,ch.deadline,ch.status,ch.failure_reason,u.name,u.reg_no,d.title FROM challenges ch JOIN duty_sessions s ON ch.session_id=s.id JOIN assignments a ON a.id=s.assignment_id JOIN users u ON u.id=a.user_id JOIN duties d ON d.id=a.duty_id ORDER BY ch.issued DESC LIMIT 100''').fetchall()
    with db() as c:
        checkpoints=c.execute('SELECT * FROM checkpoints ORDER BY created_at DESC').fetchall()
        locations=c.execute('''SELECT lc.*,cp.name checkpoint,u.name cadet,u.reg_no FROM location_challenges lc JOIN checkpoints cp ON cp.id=lc.checkpoint_id JOIN duty_sessions s ON s.id=lc.session_id JOIN assignments a ON a.id=s.assignment_id JOIN users u ON u.id=a.user_id ORDER BY lc.issued_at DESC LIMIT 100''').fetchall()
    return page(request,'admin.html',cadets=cadets,duties=duties,assignments=assignments,incidents=incidents,attempts=attempts,checkpoints=checkpoints,locations=locations)

@app.post('/admin/approve/{uid}')
def approve(uid:str,request:Request,csrf:str=Form(...)):
    u=requires(request,'admin');csrf_check(request,u,csrf)
    with db() as c:
        c.execute('UPDATE users SET approved=1 WHERE id=? AND role="cadet"',(uid,))
        audit(c,u['id'],'approve',uid)
    return redirect('/admin')

@app.post('/admin/duty')
def duty_create(request:Request,title:str=Form(...),location:str=Form(...),starts:str=Form(...),ends:str=Form(...),csrf:str=Form(...)):
    u=requires(request,'admin');csrf_check(request,u,csrf)
    s,e=parse_local(starts),parse_local(ends)
    if e<=s or e-s>86400 or len(title.strip())<3:raise HTTPException(400,'Invalid duty schedule')
    with db() as c:
        did=new_id();c.execute('INSERT INTO duties(id,title,location,starts,ends,created_by,created_at) VALUES(?,?,?,?,?,?,?)',(did,title.strip()[:100],location.strip()[:100],s,e,u['id'],now()))
        audit(c,u['id'],'create-duty',did)
    return redirect('/admin')

@app.post('/admin/assign')
def assign(request:Request,duty_id:str=Form(...),reg_no:str=Form(...),csrf:str=Form(...)):
    u=requires(request,'admin');csrf_check(request,u,csrf)
    with db() as c:
        cadet=c.execute('SELECT id FROM users WHERE reg_no=? AND role="cadet" AND approved=1',(reg_no.strip().upper(),)).fetchone()
        duty=c.execute('SELECT id FROM duties WHERE id=?',(duty_id,)).fetchone()
        if not cadet or not duty:raise HTTPException(400,'Approved cadet or duty not found')
        try:c.execute('INSERT INTO assignments(id,duty_id,user_id) VALUES(?,?,?)',(new_id(),duty_id,cadet['id']))
        except sqlite3.IntegrityError:raise HTTPException(409,'This cadet is already assigned to this duty')
        audit(c,u['id'],'assign-duty',cadet['id']+':'+duty_id)
    return redirect('/admin')

@app.post('/admin/review/{incident_id}')
def review(incident_id:str,request:Request,csrf:str=Form(...)):
    u=requires(request,'admin');csrf_check(request,u,csrf)
    with db() as c:
        c.execute('UPDATE incidents SET reviewed=1 WHERE id=?',(incident_id,))
        audit(c,u['id'],'review-incident',incident_id)
    return redirect('/admin')

@app.get('/api/admin/summary')
def summary(request:Request):
    requires(request,'admin')
    with db() as c:
        return {'pending_cadets':c.execute('SELECT COUNT(*) FROM users WHERE role="cadet" AND approved=0').fetchone()[0],'incidents':c.execute('SELECT COUNT(*) FROM incidents WHERE reviewed=0').fetchone()[0],'duties':c.execute('SELECT COUNT(*) FROM duties').fetchone()[0]}

# Register location routes and tables before CLI startup.
import sys
from location_extension import register as register_location
setup()
location_tools=register_location(app,sys.modules[__name__])
create_location_challenge=location_tools['create_location_challenge']

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['create-admin']);parser.add_argument('--name');parser.add_argument('--reg');parser.add_argument('--phone');args=parser.parse_args()
    setup()
    from getpass import getpass
    name=args.name or input('Admin name: ');reg=args.reg or input('Admin login ID: ');phone=args.phone or input('Admin phone (+91...): ')
    password=getpass('Admin password (12+ chars): ')
    if len(password)<12:raise SystemExit('Password must be at least 12 characters')
    with db() as c:c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)',(new_id(),name,reg.upper(),phone,ph.hash(password),'admin',1,now()))
    print('Admin created')
