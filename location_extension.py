"""NCC Sentinel location-verification extension for the ten-cadet pilot.
Device-submitted GPS is untrusted; outcomes are estimated positions, never proof of presence.
"""
import math, statistics, sqlite3, time, secrets
from fastapi import Request, Form, HTTPException
from fastapi.responses import JSONResponse


def register(app, m):
    def create_tables():
        with m.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS checkpoints(
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                latitude REAL NOT NULL CHECK(latitude BETWEEN -90 AND 90),
                longitude REAL NOT NULL CHECK(longitude BETWEEN -180 AND 180),
                radius_m REAL NOT NULL DEFAULT 5 CHECK(radius_m BETWEEN 1 AND 1000),
                created_by TEXT NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS location_challenges(
                id TEXT PRIMARY KEY, duty_challenge_id TEXT NOT NULL UNIQUE REFERENCES challenges(id),
                session_id TEXT NOT NULL REFERENCES duty_sessions(id),
                checkpoint_id TEXT NOT NULL REFERENCES checkpoints(id),
                nonce_hash TEXT NOT NULL, issued_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                distance_m REAL, accuracy_m REAL, evaluated_at INTEGER, detail TEXT);
            CREATE TABLE IF NOT EXISTS location_samples(
                id TEXT PRIMARY KEY, location_challenge_id TEXT NOT NULL REFERENCES location_challenges(id),
                lat REAL NOT NULL, lon REAL NOT NULL, accuracy_m REAL NOT NULL,
                client_ts_ms INTEGER NOT NULL, received_at INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS location_session ON location_challenges(session_id,issued_at);
            ''')
            fields=[r['name'] for r in c.execute('PRAGMA table_info(duties)').fetchall()]
            if 'checkpoint_id' not in fields:
                c.execute('ALTER TABLE duties ADD COLUMN checkpoint_id TEXT REFERENCES checkpoints(id)')
    create_tables()

    def distance_m(lat1,lon1,lat2,lon2):
        R=6371008.8
        p1,p2=math.radians(lat1),math.radians(lat2)
        dp=p2-p1; dl=math.radians(lon2-lon1)
        a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return R*2*math.atan2(math.sqrt(a),math.sqrt(max(0,1-a)))

    def create_location_challenge(c,ch):
        # Triggered only after CAPTCHA + SMS OTP pass. GPS acquisition gets its own 90 s window.
        data=c.execute('''SELECT s.id session_id,d.checkpoint_id FROM duty_sessions s
              JOIN assignments a ON a.id=s.assignment_id JOIN duties d ON d.id=a.duty_id
              WHERE s.id=?''',(ch['session_id'],)).fetchone()
        if not data or not data['checkpoint_id']:return
        if c.execute('SELECT id FROM location_challenges WHERE duty_challenge_id=?',(ch['id'],)).fetchone():return
        nonce=secrets.token_urlsafe(24)
        lid=m.new_id()
        c.execute('''INSERT INTO location_challenges(id,duty_challenge_id,session_id,checkpoint_id,
               nonce_hash,issued_at,expires_at,status) VALUES(?,?,?,?,?,?,?,?)''',
               (lid,ch['id'],ch['session_id'],data['checkpoint_id'],m.digest(nonce),m.now(),m.now()+90,'pending'))
        # The nonce is sent once after OTP success. It is never stored in cleartext.
        return {'id':lid,'nonce':nonce,'expires_at':m.now()+90}

    m.create_location_challenge=create_location_challenge

    @app.post('/admin/checkpoints')
    def admin_checkpoint(request:Request,name:str=Form(...),latitude:float=Form(...),longitude:float=Form(...),radius_m:float=Form(5),csrf:str=Form(...)):
        u=m.requires(request,'admin');m.csrf_check(request,u,csrf)
        if not name.strip() or len(name)>100 or not (-90<=latitude<=90 and -180<=longitude<=180) or not (1<=radius_m<=1000):
            raise HTTPException(400,'Invalid checkpoint name, coordinate or radius')
        with m.db() as c:
            cid=m.new_id()
            c.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?,?)',(cid,name.strip(),latitude,longitude,radius_m,u['id'],m.now()))
            m.audit(c,u['id'],'create-checkpoint',cid)
        return m.redirect('/admin')

    @app.post('/admin/duties/{duty_id}/checkpoint')
    def set_checkpoint(duty_id:str,request:Request,checkpoint_id:str=Form(...),csrf:str=Form(...)):
        u=m.requires(request,'admin');m.csrf_check(request,u,csrf)
        with m.db() as c:
            c.execute('BEGIN IMMEDIATE')
            cp=c.execute('SELECT id FROM checkpoints WHERE id=?',(checkpoint_id,)).fetchone()
            duty=c.execute('SELECT id FROM duties WHERE id=?',(duty_id,)).fetchone()
            if not cp or not duty:raise HTTPException(404,'Duty or checkpoint not found')
            active=c.execute('''SELECT 1 FROM duty_sessions s JOIN assignments a ON a.id=s.assignment_id
                     WHERE a.duty_id=? AND s.ended IS NULL LIMIT 1''',(duty_id,)).fetchone()
            if active:raise HTTPException(409,'Cannot change checkpoint during an active duty')
            c.execute('UPDATE duties SET checkpoint_id=? WHERE id=?',(checkpoint_id,duty_id))
            m.audit(c,u['id'],'assign-checkpoint',duty_id+':'+checkpoint_id)
            c.execute('COMMIT')
        return m.redirect('/admin')

    def cadet_location(c,uid):
        row=c.execute('''SELECT lc.*,cp.name checkpoint_name,cp.radius_m,cp.latitude checkpoint_lat,
               cp.longitude checkpoint_lon,d.title duty_title FROM location_challenges lc
               JOIN checkpoints cp ON cp.id=lc.checkpoint_id
               JOIN duty_sessions s ON s.id=lc.session_id
               JOIN assignments a ON a.id=s.assignment_id JOIN duties d ON d.id=a.duty_id
               WHERE a.user_id=? AND lc.status='pending' AND s.ended IS NULL
               ORDER BY lc.issued_at DESC LIMIT 1''',(uid,)).fetchone()
        return row

    @app.get('/api/location/challenge')
    def current_location(request:Request):
        u=m.requires(request,'cadet')
        with m.db() as c:
            row=cadet_location(c,u['id'])
            if row and row['expires_at']<m.now():
                c.execute('UPDATE location_challenges SET status=?,evaluated_at=?,detail=? WHERE id=? AND status=?',
                          ('missed',m.now(),'Location not received before deadline',row['id'],'pending'))
                row=None
            # nonce is initially delivered through OTP success response, not this endpoint.
            return {'challenge':({'id':row['id'],'checkpoint_name':row['checkpoint_name'],
                 'radius_m':row['radius_m'],'expires_at':row['expires_at']} if row else None),
                 'server_time':m.now()}

    @app.post('/api/location/submit')
    async def submit_location(request:Request):
        u=m.requires(request,'cadet')
        body=await request.json()
        m.csrf_check(request,u,str(body.get('csrf','')))
        lid=str(body.get('id',''))
        nonce=str(body.get('nonce',''))
        samples=body.get('samples',[])
        if not isinstance(samples,list) or not 3<=len(samples)<=10:raise HTTPException(400,'3–10 GPS samples required')
        with m.db() as c:
            c.execute('BEGIN IMMEDIATE')
            lc=c.execute('''SELECT lc.*,cp.latitude cp_lat,cp.longitude cp_lon,cp.radius_m,
                       d.starts duty_starts,d.ends duty_ends,s.ended
                       FROM location_challenges lc
                       JOIN checkpoints cp ON cp.id=lc.checkpoint_id
                       JOIN duty_sessions s ON s.id=lc.session_id
                       JOIN assignments a ON a.id=s.assignment_id JOIN duties d ON d.id=a.duty_id
                       WHERE lc.id=? AND a.user_id=?''',(lid,u['id'])).fetchone()
            if not lc:raise HTTPException(404,'Unknown location challenge')
            if lc['status']!='pending':raise HTTPException(409,'Challenge already completed')
            m.rate(c,'gps-submit:'+u['id']+':'+lid,5,120)
            if not nonce or not secrets.compare_digest(lc['nonce_hash'],m.digest(nonce)):
                raise HTTPException(403,'Invalid challenge nonce')
            t=m.now()
            if t>lc['expires_at']:
                c.execute('UPDATE location_challenges SET status=?,evaluated_at=? WHERE id=?',('missed',t,lid))
                raise HTTPException(410,'Location challenge expired')
            if lc['ended'] or not (lc['duty_starts']-900<=t<=lc['duty_ends']):
                raise HTTPException(403,'Outside authorized duty window')
            processed=[]
            for item in samples:
                try:
                    la=float(item['latitude']);lo=float(item['longitude'])
                    accuracy=float(item['accuracy']);ts=int(item['timestamp'])
                except (ValueError,KeyError,TypeError,OverflowError):raise HTTPException(400,'Invalid sample format')
                if not all(map(math.isfinite,[la,lo,accuracy])) or not(-90<=la<=90 and -180<=lo<=180) or not(0<accuracy<=100000):
                    raise HTTPException(400,'Invalid GPS reading')
                # Device timestamps are not trusted; stale data must still be rejected.
                if ts < (lc['issued_at']-5)*1000 or ts>(t+5)*1000 or t*1000-ts>35000:
                    raise HTTPException(400,'Stale or future location reading')
                processed.append((la,lo,accuracy,ts))
            if len({v[3] for v in processed})<3:raise HTTPException(400,'Need 3 distinct location measurements')
            for la,lo,acc,ts in processed:
                c.execute('INSERT INTO location_samples VALUES(?,?,?,?,?,?,?)',
                          (m.new_id(),lid,la,lo,acc,ts,t))
            lat=statistics.median(p[0] for p in processed)
            lon=statistics.median(p[1] for p in processed)
            accuracy=statistics.median(p[2] for p in processed)
            d=distance_m(lat,lon,lc['cp_lat'],lc['cp_lon'])
            if d+accuracy<=lc['radius_m']:status='verified_estimate'
            elif d-accuracy>lc['radius_m']:status='outside_location'
            else:status='accuracy_insufficient'
            saved_status='pending' if status=='accuracy_insufficient' else status
            c.execute('''UPDATE location_challenges SET status=?,distance_m=?,accuracy_m=?,
                         evaluated_at=?,detail=? WHERE id=? AND status='pending' ''',
                         (saved_status,d,accuracy,t,status+': Untrusted browser-reported GPS estimate',lid))
            m.audit(c,u['id'],'location-'+status,lid)
            c.execute('COMMIT')
        return {'status':status,'distance_m':round(d,2),'accuracy_m':round(accuracy,2),
                'radius_m':lc['radius_m'],'warning':'Browser geolocation is an estimate, not proof of physical presence.'}

    @app.post('/api/location/report-error')
    async def report_location_error(request:Request):
        u=m.requires(request,'cadet');body=await request.json()
        m.csrf_check(request,u,str(body.get('csrf','')))
        lid=str(body.get('id',''))
        reason=str(body.get('reason',''))
        if reason not in ('permission_denied','location_unavailable','timeout'):
            raise HTTPException(400,'Invalid location failure reason')
        with m.db() as c:
            c.execute('BEGIN IMMEDIATE')
            lc=cadet_location(c,u['id'])
            if not lc or lc['id']!=lid:raise HTTPException(404,'No pending location challenge')
            # Client-originated errors can be fabricated, so retain for human review.
            c.execute('UPDATE location_challenges SET detail=? WHERE id=?',
                      ('client_reported_'+reason,lid))
            m.audit(c,u['id'],'client-reported-location-error',lid+':'+reason)
            c.execute('COMMIT')
        return {'ok':True,'review_required':True}

    @app.get('/api/admin/locations')
    def admin_locations(request:Request):
        m.requires(request,'admin')
        with m.db() as c:
            rows=c.execute('''SELECT lc.id,lc.status,lc.distance_m,lc.accuracy_m,lc.issued_at,lc.evaluated_at,
                    cp.name checkpoint,u.name cadet,u.reg_no,d.title duty
                    FROM location_challenges lc JOIN checkpoints cp ON cp.id=lc.checkpoint_id
                    JOIN duty_sessions s ON s.id=lc.session_id JOIN assignments a ON a.id=s.assignment_id
                    JOIN duties d ON d.id=a.duty_id JOIN users u ON u.id=a.user_id
                    ORDER BY lc.issued_at DESC LIMIT 100''').fetchall()
        return {'results':[dict(x) for x in rows]}

    return {'distance_m':distance_m,'create_location_challenge':create_location_challenge}
