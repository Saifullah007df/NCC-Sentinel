# NCC Sentinel — Full 10-Cadet Local Pilot

Responsive FastAPI web application for NCC guard-duty assignments, OTP login, duty CAPTCHA → OTP and browser GPS checkpoint checks. **This is a local pilot, not a security-certified internet deployment.** Browser GPS estimates can be spoofed and cannot guarantee physical presence within 5 metres.

## Features
- Up to 10 cadet accounts; admin approval; regimental-number/password login followed by a fresh phone OTP **on every login**.
- Administrator creates shifts and assigns cadets by regimental number. Cadets immediately see their own assignments.
- Admin creates named map checkpoints with latitude/longitude and radius (default 5 metres), then attaches a checkpoint to a duty.
- Cadet starts a duty; unpredictable 20–40 minute checks issue a 30-second server-timed CAPTCHA → SMS OTP challenge.
- When a duty has a checkpoint, successfully completing the CAPTCHA and OTP issues a **separate 90-second GPS acquisition challenge**. Browser must submit 3–10 fresh, distinct Geolocation API readings.
- Geofence checks use geodesic distance and reported uncertainty: **verified estimate** if distance + accuracy ≤ radius, **outside location** if distance − accuracy > radius, and **accuracy insufficient** otherwise. Accuracy-insufficient checks can retry before expiration.
- Admin-only location monitoring, duty failure counters, incident records after 2 consecutive or more than 3 total failures, protected endpoints and CSRF checks.
- Production-mode optional Turnstile challenges (required outside demo), Twilio SMS support, secure cookies, OTP hashing, rudimentary request throttling and conservative HTTP security headers.
- Four automated tests including successful assigned-cadet location verification, unauthorized admin access denial, and replay rejection.

## Run on Windows

1. Install Python 3.11 or newer; enable **Add Python to PATH**.
2. Extract the ZIP, open the extracted folder and double-click `start_windows.bat`.
3. Follow prompts to create an administrator account.
4. Visit `http://127.0.0.1:8000` in the **same PC's browser**.
5. Demo login and duty OTP codes are printed in the server console; real SMS is not sent in demo mode.

Or run manually from the project directory (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
$env:DEV_MODE="1"
$env:SMS_MODE="demo"
$env:SESSION_SECRET="local-dev-secret-change-this-before-sharing"
.venv\Scripts\python app.py create-admin
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

On Linux/macOS, use `bash run_linux.sh` or analogous venv commands. Set `DATABASE_PATH` if you want to keep the database outside the working folder.

### Run the tests

```bash
PYTHONPATH=. DATABASE_PATH=/tmp/ncc-sentinel-test.db pytest -q
```

For Windows, use `set PYTHONPATH=.` and set a temporary `DATABASE_PATH` before running `pytest -q`. **Do not run automated tests against your real production database.**

## Admin workflow

1. Log in and approve registered cadets.
2. Create a checkpoint by clicking the map (requires internet for map tiles) or entering coordinates manually; confirm pin and radius.
3. Create a duty slot with start and end in IST, then attach the checkpoint using **Connect checkpoint to duty**.
4. Assign an approved cadet by regimental number.
5. Cadet logs in with password plus fresh OTP, acknowledges the assigned duty and starts the session during the authorized period.
6. Once a random duty challenge appears, cadet completes CAPTCHA then duty OTP **within 30 seconds from challenge issuance**.
7. Cadet then taps **Allow location and verify**, granting browser location permission. GPS readings need a secure browser context. `localhost` is normally allowed for development; use HTTPS to test on another phone.
8. Admin inspects verification history and GPS results. Browser location uncertainty or failures require human review.

## Critical pilot limitations

- The public website **has not been deployed**. On a cadet phone, `127.0.0.1` points to their own phone, not your server; genuine remote access requires HTTPS hosting or a secure local/remote deployment.
- Demo mode uses 6-digit OTP **printed to the server terminal**; `SMS_MODE=twilio` requires your own credentials and approved sender. Real SMS delivery is not guaranteed within 30 seconds. Configuring Twilio SMS does not in itself verify mobile ownership at initial registration.
- `DEV_MODE=0` refuses startup without `SMS_MODE=twilio`, `COOKIE_SECURE=1` and Turnstile credentials, but **this alone does not make the server safe for the public internet**.
- No DoS/DDoS hosting configuration is included. Put your server behind a cloud DDoS/WAF service; restrict origin access; apply edge rate limits, backups, monitoring and a real security audit.
- The local pilot uses SQLite and a single server process with an in-process timer; multiple Uvicorn workers would duplicate scheduling. Use one worker only.
- If the browser page is closed, locked or suspended, immediate verification popups and GPS collection cannot be guaranteed. The user should keep the page foregrounded for testing.
- A client can spoof browser GPS, accuracy, and timestamps. The code checks freshness and authorization, but it **cannot prove actual physical presence or prevent sophisticated spoofing**.
- Phone ownership verification during registration, delivery receipts, audit-log immutability, independent worker scheduling and security penetration testing are still needed before official use.
- Do not add real guard locations, phone numbers or credentials to a public repository. `.gitignore` excludes `.env` and `.db` files.

## Project files

- `app.py`: core FastAPI service, SQLite, authentication and duty scheduler
- `location_extension.py`: checkpoint and GPS geofence endpoints
- `templates/`: admin/cadet/auth web pages
- `static/app.js`: browser challenge and geolocation flow
- `static/admin-map.js`: optional OpenStreetMap checkpoint picker
- `tests/`: four backend integration tests
- `docs/LOCATION_VERIFICATION_DESIGN.md`: detailed feature specification
