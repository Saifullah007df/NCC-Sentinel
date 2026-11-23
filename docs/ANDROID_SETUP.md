# NCC Sentinel on Android — Pilot setup

NCC Sentinel is a **web app**. You do not need an APK. Android Chrome can add the HTTPS site to your Home Screen.

## What must happen first

**Do not expose the existing development server to the public internet.** Its default DEV_MODE=1 logs OTP codes to the terminal and uses demo CAPTCHA. The repository is public at the time these instructions were written; do not commit any phone numbers, duty locations, .env credentials, or live cadet information.

A hosting provider must be connected and configured, with HTTPS, private persistent storage, backed-up database, strong SESSION_SECRET, real SMS provider, secure cookies, genuine CAPTCHA, restricted admin access, DDoS/WAF protection, rate limits, and security review before real cadets use it. Current SQLite/in-process scheduling is intended for a single-process pilot; do not deploy it using ephemeral storage or multiple worker processes. Configure SMS delivery and phone ownership verification before relying on OTP.

## On your Realme RMX5061 Android 16

1. Once NCC Sentinel has an actual `https://` deployment URL, open the URL in **Chrome** on the phone.
2. Use Chrome's menu (three dots) → **Add to Home screen** / **Install app** (wording depends on browser support).
3. Open the NCC Sentinel shortcut. Log in with your regimental number, password, and the fresh OTP from your registered number.
4. Open your assigned duty; when asked to verify GPS, tap **Allow location and verify**, then grant **precise location** to Chrome/site in Android permissions.
5. Keep the website foregrounded during the challenge. Browser GPS relies on secure context (HTTPS), an enabled device location service, and the browser's permission.
6. The 30-second CAPTCHA + OTP deadline is independent from the 90-second location sampling window.
7. The system logs estimated GPS positions, **not guaranteed 5 m physical presence**.

**Important:** A notification or popup cannot be guaranteed while Chrome is closed or the phone is locked. This initial code uses a foreground polling loop, *not* Android background push delivery. The app is not suitable for unattended duty enforcement yet.

## For a local PC-only test

A local Windows launcher starts `http://127.0.0.1:8000` only on the same PC. That address does **not** point to the PC from the phone. Using the PC's LAN address over HTTP can display the site, but Android browser geolocation generally requires HTTPS; use a secure staging domain/tunnel and do not expose demo mode to outsiders.

## Deployment requirements before pilot

- Private GitHub repository and no sensitive records in code
- Persistent data volume / database backups
- Single process for current in-process scheduler
- HTTPS with protected origin behind WAF/CDN
- Real SMS provider and registration phone proof
- DEV_MODE=0, COOKIE_SECURE=1, configured Turnstile
- Strong random session secret stored only as hosting secret
- Test Android Chrome GPS permissions and repeated sample collection at actual site
- Verification policy for delayed/blocked notifications and uncertain GPS
- Real-device pilot, penetration testing, recovery tests

**Current status:** Android UI/home-screen support prepared. Public hosting, SMS credentials, and real-device access remain external deployment tasks.
