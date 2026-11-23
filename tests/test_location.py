"""End-to-end location gate, role isolation and anti-replay tests."""
import os, re, uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from argon2 import PasswordHasher


def test_full_location_flow(monkeypatch):
    import app
    sms=[];monkeypatch.setattr(app,'send_sms',lambda phone,body:sms.append(body))
    app.setup()
    with app.db() as c:
        c.execute('DELETE FROM rate_limit')
        admin='ADM-'+uuid.uuid4().hex[:8].upper();reg='CADET-'+uuid.uuid4().hex[:8].upper()
        aid=app.new_id();uid=app.new_id()
        c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)',(aid,'Test Admin',admin,'+918888888880',PasswordHasher().hash('TestPassword1234'),'admin',1,app.now()))
        c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)',(uid,'Test Cadet',reg,'+918888888881',PasswordHasher().hash('TestPassword1234'),'cadet',1,app.now()))
    with TestClient(app.app) as client:
        def login(account):
            r=client.post('/login',data={'reg_no':account,'password':'TestPassword1234'},follow_redirects=False)
            assert r.status_code==303
            code=re.search(r'(\d{6})',sms[-1]).group(1)
            assert client.post('/verify-login',data={'code':code},follow_redirects=False).status_code==303
            with app.db() as c:
                token=client.cookies['ncc_session']
                return c.execute('SELECT csrf FROM sessions WHERE id_hash=?',(app.digest(token),)).fetchone()['csrf']
        csrf=login(admin)
        r=client.post('/admin/checkpoints',data={'name':'Gate','latitude':12.9716,'longitude':79.1598,'radius_m':5,'csrf':csrf},follow_redirects=False)
        assert r.status_code==303
        with app.db() as c:cp=c.execute('SELECT id FROM checkpoints ORDER BY rowid DESC LIMIT 1').fetchone()['id']
        current=datetime.now(ZoneInfo('Asia/Kolkata'))
        fmt=lambda t:t.strftime('%Y-%m-%dT%H:%M')
        r=client.post('/admin/duty',data={'title':'Gate Duty','location':'Gate','starts':fmt(current-timedelta(minutes=1)),'ends':fmt(current+timedelta(hours=2)),'csrf':csrf},follow_redirects=False)
        assert r.status_code==303
        with app.db() as c:did=c.execute('SELECT id FROM duties ORDER BY rowid DESC LIMIT 1').fetchone()['id']
        assert client.post(f'/admin/duties/{did}/checkpoint',data={'checkpoint_id':cp,'csrf':csrf},follow_redirects=False).status_code==303
        assert client.post('/admin/assign',data={'duty_id':did,'reg_no':reg,'csrf':csrf},follow_redirects=False).status_code==303
        client.post('/logout',data={'csrf':csrf})
        csrf=login(reg)
        assert client.get('/admin').status_code==403
        assert client.get('/api/admin/locations').status_code==403
        with app.db() as c:assignment=c.execute('SELECT id FROM assignments WHERE duty_id=?',(did,)).fetchone()['id']
        assert client.post('/cadet/start/'+assignment,data={'csrf':csrf},follow_redirects=False).status_code==303
        with app.db() as c:c.execute('UPDATE duty_sessions SET next_check=? WHERE assignment_id=?',(app.now()-1,assignment))
        app.tick()
        chall=client.get('/api/challenge').json()['challenge']
        with app.db() as c:ch=c.execute('SELECT * FROM challenges WHERE id=?',(chall['id'],)).fetchone()
        assert client.post('/api/challenge/captcha',json={'id':chall['id'],'answer':ch['captcha_answer'],'csrf':csrf}).json()['ok']
        code=re.search(r'(\d{6})',sms[-1]).group(1)
        resp=client.post('/api/challenge/otp',json={'id':chall['id'],'code':code,'csrf':csrf})
        assert resp.status_code==200 and resp.json()['ok'] and resp.json().get('location')
        token=resp.json()['location'];ts=app.now()*1000
        samples=[{'latitude':12.9716,'longitude':79.1598,'accuracy':2,'timestamp':ts+i} for i in range(3)]
        result=client.post('/api/location/submit',json={'id':token['id'],'nonce':token['nonce'],'samples':samples,'csrf':csrf})
        assert result.status_code==200,result.text
        assert result.json()['status']=='verified_estimate'
        replay=client.post('/api/location/submit',json={'id':token['id'],'nonce':token['nonce'],'samples':samples,'csrf':csrf})
        assert replay.status_code==409
        assert client.get('/api/location/challenge').json()['challenge'] is None
