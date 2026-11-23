import re
from fastapi.testclient import TestClient

def test_registration_code_required_and_single_use(monkeypatch):
    import app
    sent=[]
    monkeypatch.setattr(app,'send_sms',lambda phone,body:sent.append(body))
    with TestClient(app.app) as client:
        r=client.post('/register',data={
            'name':'Phone Test Cadet','reg_no':'PHONE-CHECK-01',
            'phone':'+919000000321','password':'CorrectPassword5678'
        },follow_redirects=False)
        assert r.status_code==303
        with app.db() as c:
            assert c.execute('SELECT id FROM users WHERE reg_no=?',('PHONE-CHECK-01',)).fetchone() is None
        wrong=client.post('/verify-registration',data={'code':'000000'})
        assert 'Incorrect code' in wrong.text or 'Phone verified' in wrong.text
        with app.db() as c:
            assert c.execute('SELECT id FROM users WHERE reg_no=?',('PHONE-CHECK-01',)).fetchone() is None
        code=re.search(r'(\d{6})',sent[-1]).group(1)
        assert 'Phone verified' in client.post('/verify-registration',data={'code':code}).text
        with app.db() as c:
            user=c.execute('SELECT approved FROM users WHERE reg_no=?',('PHONE-CHECK-01',)).fetchone()
            assert user is not None and user['approved']==0
        assert 'expired' in client.post('/verify-registration',data={'code':code}).text.lower()
