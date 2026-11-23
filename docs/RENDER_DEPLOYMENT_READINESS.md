# NCC Sentinel — Render deployment readiness (10-cadet pilot)

**Assessment date:** 2026-11-23. **Status: NOT DEPLOYED / NOT SAFE FOR PUBLIC USE YET.**

## Confirmed Render account

- Workspace: `tea-dc21qv6q1p3s73bhc450` (user-confirmed)
- Web services: none
- Render Postgres instances: none
- Render Key Value instances: none
- Region preference: Singapore
- Budget: free plans only; do not provision paid services

## Deployment blockers

1. The application defaults to `DEV_MODE=1` and `SMS_MODE=demo`, where phone OTPs are logged to the server console. **Never expose this configuration publicly.**
2. Real SMS needs approved sender/recipient verification, Twilio credentials, delivery-cost control and phone ownership verification at **registration**, which the present application has not implemented.
3. The current SQLite database needs durable storage with tested backups. Render's ephemeral free web filesystem must not be used to hold cadet accounts, duty records or incidents. A persistent disk or managed durable database with appropriate schema migration is required; do not assume free Postgres is a durable long-term option.
4. The scheduler runs inside a single FastAPI process. The app must run with **one Uvicorn worker only** until its scheduler is extracted to a durable worker and locking is implemented.
5. HTTPS, origin access controls, WAF/rate limits, audit monitoring, threat-model review and recovery procedures are not verified. A default `onrender.com` HTTPS address alone is not sufficient DDoS hardening or origin lockdown.
6. Public GitHub repository: make private before adding any operational checkpoint, phone number, password or other sensitive NCC information. Do not commit `.env`, `.db`, SQLite journal files, or secret keys.
7. Browser push notifications and locked-screen duty popups are not reliable/implemented as guaranteed delivery. Real-world GPS sampling and 30-second SMS timings need in-person validation.

## Recommended safe approach

**Stage A — local test:** use the current demo only on a developer's own trusted machine. Keep `DEV_MODE=1` and never use real cadet information in demo mode.

**Stage B — private security staging:** move to durable database; implement verified phone registration, provider integration, hardened sessions, logging without OTP disclosure, and an isolated testing environment. Run the preflight checks below and verify they fail when requirements are missing.

**Stage C — internet pilot (only after review):** deploy a single-process service with configured HTTPS, WAF, correct secrets, verified sender and phone registration, persistent storage and backup restore. Test Android Chrome on actual phones before admitting the ten cadets. Set spend limits at the SMS provider.

For no-cost development, use local Docker / developer machine, or non-sensitive test-only staging protected by independent access controls. Do not advertise a demo site as an operational check-in service.

## Preflight command

```bash
python scripts/deployment_preflight.py
```

This does **not** replace code audit or prove the actual backend services work. It only checks declared configuration gates and returns a nonzero exit code while any blocker is present. `PERSISTENT_DISK_CONFIRMED`, `ADMIN_PROVISIONED`, `PHONE_OWNERSHIP_VERIFIED`, `EDGE_PROTECTION_CONFIRMED`, and `SECURITY_REVIEW_CONFIRMED` are explicit deployment approval flags; **do not set them to 1 unless the corresponding work is genuinely complete**.

## Candidate Render settings when ready

- Git repository: `https://github.com/Saifullah007df/NCC-Sentinel.git`
- Branch: `main`
- Runtime: Python
- Region: Singapore
- Build: `pip install -r requirements.txt`
- Start: `python scripts/deployment_preflight.py && uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1`
- Health endpoint: `/health`
- Secrets: Render environment variables, never in source control
- Initial traffic: disabled or gated until end-to-end readiness is confirmed

**No Render resources have been created by these preparations.**
