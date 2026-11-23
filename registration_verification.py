"""Verify a cadet's phone before creating an account; administrator approval remains mandatory."""
import hmac
import sqlite3
from fastapi import Form, Request
from fastapi.responses import HTMLResponse

def register_routes(app,host):
    with host.db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS pending_registrations (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, reg_no TEXT UNIQUE NOT NULL,
          phone TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
          otp_hash TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0)""")
        c.execute("CREATE INDEX IF NOT EXISTS pending_reg_expiry ON pending_registrations(expires_at)")

    def initiate(request,name,reg_no,phone,password):
        name=name.strip()[:90]; reg_no=reg_no.strip().upper()[:40]; phone=phone.strip()
        if not name or len(reg_no)<3 or not phone.startswith('+') or not phone[1:].isdigit() or not 10<=len(phone)<=16 or len(password)<12:
            return host.page(request,'register.html',error='Use a valid name, regimental number, international phone number and password of at least 12 characters.')
        with host.db() as c:
            host.rate(c,'register:'+host.clientip(request),5,3600)
            host.rate(c,'register-number:'+host.digest(phone),3,3600)
            c.execute('DELETE FROM pending_registrations WHERE expires_at<?',(host.now(),))
            if c.execute('SELECT COUNT(*) FROM users WHERE role="cadet"').fetchone()[0]>=10:
                return host.page(request,'register.html',error='Pilot capacity reached (10 cadets). Contact the administrator.')
            if c.execute('SELECT id FROM users WHERE reg_no=? OR phone=?',(reg_no,phone)).fetchone():
                return host.page(request,'register.html',error='This regimental number or phone is already registered.')
            if c.execute('SELECT id FROM pending_registrations WHERE reg_no=? OR phone=?',(reg_no,phone)).fetchone():
                return host.page(request,'register.html',error='Verification is already pending for this number. Complete it or retry after expiry.')
            rid=host.new_id(); code=host.otp_code()
            c.execute('INSERT INTO pending_registrations VALUES(?,?,?,?,?,?,?,?,0)',
                (rid,name,reg_no,phone,host.ph.hash(password),host.digest('register:'+rid+':'+code),host.now(),host.now()+300))
            try:
                host.send_sms(phone,'NCC Sentinel registration verification code: '+code+'. Expires in 5 minutes. Do not share it.')
            except Exception:
                c.execute('DELETE FROM pending_registrations WHERE id=?',(rid,))
                return host.page(request,'register.html',error='Unable to send verification code. Registration not created.')
        response=host.redirect('/verify-registration')
        response.set_cookie('pending_registration',rid,max_age=300,httponly=True,secure=host.COOKIE_SECURE,samesite='strict')
        return response

    @app.get('/verify-registration',response_class=HTMLResponse)
    def verify_registration_page(request:Request):
        return host.page(request,'verify_registration.html')

    @app.post('/verify-registration')
    def verify_registration(request:Request,code:str=Form(...)):
        rid=request.cookies.get('pending_registration','')
        if not rid or len(rid)>64:
            return host.page(request,'verify_registration.html',error='Registration session expired. Start registration again.')
        with host.db() as c:
            c.execute('BEGIN IMMEDIATE')
            host.rate(c,'verify-register-ip:'+host.clientip(request),20,900)
            pending=c.execute('SELECT * FROM pending_registrations WHERE id=?',(rid,)).fetchone()
            if not pending or pending['expires_at']<host.now() or pending['attempts']>=5:
                c.execute('COMMIT')
                return host.page(request,'verify_registration.html',error='Code expired or too many attempts. Please register again.')
            c.execute('UPDATE pending_registrations SET attempts=attempts+1 WHERE id=?',(rid,))
            valid=(len(code.strip())==6 and code.strip().isdigit() and
                   hmac.compare_digest(pending['otp_hash'],host.digest('register:'+rid+':'+code.strip())))
            if not valid:
                c.execute('COMMIT')
                return host.page(request,'verify_registration.html',error='Incorrect code. Try again before expiry.')
            if c.execute('SELECT COUNT(*) FROM users WHERE role="cadet"').fetchone()[0]>=10:
                c.execute('COMMIT')
                return host.page(request,'verify_registration.html',error='Cadet pilot capacity reached. Contact administrator.')
            try:
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)',
                    (host.new_id(),pending['name'],pending['reg_no'],pending['phone'],pending['password_hash'],'cadet',0,host.now()))
            except sqlite3.IntegrityError:
                c.execute('COMMIT')
                return host.page(request,'verify_registration.html',error='This account is already registered.')
            c.execute('DELETE FROM pending_registrations WHERE id=?',(rid,))
            host.audit(c,None,'registration-phone-verified',pending['reg_no'])
            c.execute('COMMIT')
        response=host.page(request,'message.html',message='Phone verified. Registration submitted for administrator approval.')
        response.delete_cookie('pending_registration')
        return response
    return initiate
