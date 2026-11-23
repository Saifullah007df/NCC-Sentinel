from fastapi.testclient import TestClient
from argon2 import PasswordHasher
import time, re

def test_full_admin_cadet_assignment_and_challenge(monkeypatch):
    import app
    sms=[]
    monkeypatch.setattr(app,'send_sms',lambda phone,body:sms.append(body))
    app.setup()
    with app.db() as c:
        c.execute('DELETE FROM rate_limit')
        c.execute('INSERT OR IGNORE INTO users VALUES(?,?,?,?,?,?,?,?)',('admin_test','Admin','ADMIN-TEST','+919999999990',PasswordHasher().hash('TestPassword1234'),'admin',1,app.now()))
    with TestClient(app.app) as client:
        r=client.post('/register',data={'name':'Test Cadet','reg_no':'NCC-TEST','phone':'+919999999991','password':'TestPassword1234'})
        assert r.status_code==200
        r=client.post('/login',data={'reg_no':'ADMIN-TEST','password':'TestPassword1234'},follow_redirects=False)
        assert r.status_code==303
        code=re.search(r'(\d{6})',sms[-1]).group(1)
        assert client.post('/verify-login',data={'code':code},follow_redirects=False).status_code==303
        r=client.get('/admin');assert r.status_code==200
        with app.db() as c:
            cadet=c.execute('SELECT id FROM users WHERE reg_no="NCC-TEST"').fetchone()['id']
        with app.db() as c:csrf=c.execute('SELECT csrf FROM sessions JOIN users ON users.id=sessions.user_id WHERE users.reg_no="ADMIN-TEST"').fetchone()['csrf']
        assert client.post(f'/admin/approve/{cadet}',data={'csrf':csrf},follow_redirects=False).status_code==303
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        # current time is set to IST in the web form
        current=datetime.now(ZoneInfo('Asia/Kolkata'))
        fmt=lambda d:d.strftime('%Y-%m-%dT%H:%M')
        r=client.post('/admin/duty',data={'csrf':csrf,'title':'Main Gate Guard','location':'Gate A','starts':fmt(current-timedelta(minutes=1)),'ends':fmt(current+timedelta(hours=2))},follow_redirects=False)
        assert r.status_code==303
        with app.db() as c:did=c.execute('SELECT id FROM duties ORDER BY created_at DESC LIMIT 1').fetchone()['id']
        r=client.post('/admin/assign',data={'csrf':csrf,'duty_id':did,'reg_no':'NCC-TEST'},follow_redirects=False)
        assert r.status_code==303
        client.post('/logout',data={'csrf':csrf})
        r=client.post('/login',data={'reg_no':'NCC-TEST','password':'TestPassword1234'},follow_redirects=False)
        assert r.status_code==303
        code=re.search(r'(\d{6})',sms[-1]).group(1)
        assert client.post('/verify-login',data={'code':code},follow_redirects=False).status_code==303
        assert 'Main Gate Guard' in client.get('/cadet').text
        with app.db() as c:
            aid=c.execute('SELECT id FROM assignments WHERE duty_id=?',(did,)).fetchone()['id']
            csrf=c.execute('SELECT csrf FROM sessions WHERE user_id=? ORDER BY rowid DESC LIMIT 1',(cadet,)).fetchone()['csrf']
        assert client.post('/cadet/start/'+aid,data={'csrf':csrf},follow_redirects=False).status_code==303
        with app.db() as c:
            c.execute('UPDATE duty_sessions SET next_check=? WHERE assignment_id=?',(app.now()-1,aid))
        app.tick()
        status=client.get('/api/challenge').json()['challenge']
        assert status and status['title']=='Main Gate Guard'
        with app.db() as c:ch=c.execute('SELECT * FROM challenges WHERE id=?',(status['id'],)).fetchone()
        r=client.post('/api/challenge/captcha',json={'csrf':csrf,'id':status['id'],'answer':ch['captcha_answer']})
        assert r.json()['ok'] is True
        code=re.search(r'(\d{6})',sms[-1]).group(1)
        r=client.post('/api/challenge/otp',json={'csrf':csrf,'id':status['id'],'code':code})
        assert r.json()['ok'] is True
        assert client.get('/api/challenge').json()['challenge'] is None
