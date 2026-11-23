# NCC Sentinel — Location Verification Design Specification

**Version:** 1.0  
**Scope:** Web application pilot for 10 NCC cadets  
**Status:** Design and acceptance specification — not implemented  
**Date:** 2026-11-23

## 1. Goal and limitations

NCC Sentinel assigns duties by regimental number and verifies that an authenticated cadet reports being near an administrator-defined checkpoint during the authorized duty period. The proposed checkpoint radius is **5 metres**, but browser geolocation cannot guarantee actual physical presence within five metres or prevent all GPS spoofing. An accepted GPS estimate must **never** be labelled conclusive proof of presence.

Location verification supplements the established design: cadet registration with approval, password and SMS OTP at every new login, automatic assignment synchronization, randomized duty CAPTCHA followed by duty OTP, and administrator-only incident review.

The pilot is limited to 10 approved cadets and authorized administrators. Location is requested only during an assigned duty or an explicitly initiated check. This is **not** continuous tracking.

## 2. Administrator experience

1. **Checkpoints:** Select a point on a map or enter WGS84 latitude/longitude. Provide checkpoint name, location instructions, and radius (default 5 m). Verify pin placement before saving.
2. **Duties:** Select duty type, checkpoint, start/end date and time in Asia/Kolkata (stored as UTC), capacity, and check-in/check-out requirements.
3. **Verification policy:** Set randomized check interval (suggested 20–40 minutes), required GPS sample count, acquisition timeout, retry allowance, and human-review rules. Keep the 30-second CAPTCHA/OTP timer separate from GPS acquisition.
4. **Assign cadet:** Search by regimental number, resolve to the approved account's stable user ID, validate conflicts and availability, and save the assignment. It appears automatically in the cadet's dashboard.
5. **Live monitor:** View current assignments, check-in and check-out states, last location estimate, reported accuracy, distance to checkpoint, notification state, and alerts.
6. **Review incidents:** Distinguish an estimated outside position, insufficient accuracy, missing response, delivery problems, permission denial, and suspicious samples. Administrators can add a reasoned review decision while retaining the original immutable event history.
7. **Reports:** Restrict precise locations, personal identifiers, raw readings, and exports to authorized administrators within the assigned NCC unit.

Suggested admin screens: Checkpoint Map and List; Edit Checkpoint; Duty Builder; Assign Cadets; Live Duty Monitor; Verification Details; Incident Review; Reports; Verification Policies; Admin Audit.

## 3. Cadet experience

1. Register with full name, regimental number, phone, and password; verify the registered number and wait for administrator approval.
2. For **every new login**, enter regimental number and password, then complete a newly issued SMS OTP.
3. See the assigned duty and its checkpoint name, map, instructions, time, and verification status.
4. At check-in or on a random duty request, open the active verification screen and grant browser location access. Browser geolocation requires HTTPS or an eligible local development context and user permission.
5. The website requests high-accuracy location fixes, preferably multiple samples instead of trusting a single reading.
6. The backend checks freshness, duty and challenge authorization, distance, reported accuracy, and server timestamps. The cadet sees one of the clear outcomes below.
7. If accuracy is insufficient, the cadet may retry within rate and timing limits; suggest moving to open sky.
8. When required, perform check-out verification. The cadet sees their own history, but never another cadet's or private admin records.

**Exceptional paths:**

- Permission denied -> PERMISSION_DENIED; explain browser settings and provide administrator review, not automatic misconduct.
- Location disabled/unavailable -> LOCATION_UNAVAILABLE with a controlled retry.
- Weak GPS -> ACCURACY_INSUFFICIENT; do not invent certainty.
- Offline -> no verified server record; allow reconnect without pretending that an unsent submission was accepted.
- Wrong duty time -> OUTSIDE_DUTY_WINDOW; refuse acceptance.
- Browser minimized, locked, or closed -> background notifications may be delayed or fail; never promise continuous background GPS tracking.
- Stale cached reading -> STALE_SAMPLE; request a fresh reading.

## 4. Device location technology

A smartphone may derive location from GNSS satellites (GPS and other constellations), Wi-Fi positioning, cell signals, and operating-system sensor fusion. In open sky, good receivers may report metre-scale accuracy, but buildings, reflections, weather/environmental conditions, hardware, OS choices, and browser permissions can produce large errors. Indoors, Wi-Fi/cell positioning may dominate and be much less precise.

Use browser Geolocation API `getCurrentPosition` or `watchPosition` with a high-accuracy request, zero maximum cache age, and bounded timeout. `enableHighAccuracy` is a **hint**, not a guarantee. The browser supplies latitude, longitude, reported horizontal `accuracy` in metres, and a client timestamp; none of these are cryptographically attested. Record the trusted server receipt time independently.

**Pilot sampling policy:** collect approximately five readings over 10–20 seconds when feasible. Require at least three usable, fresh fixes. Reject malformed coordinates, impossible reported values, obviously stale readings, and duplicate metadata. Use a robust representative position (for a tiny area, median coordinates or a local metric projection) while retaining individual sample information for technical review. Averaging multiple readings does not eliminate systematic GPS bias.

## 5. Distance, uncertainty and 5-metre rule

Let:
- `R = 5 m`: administrator-defined checkpoint radius.
- `d`: geodesic distance from representative reported coordinate to checkpoint, using Haversine or another suitable WGS84 geodesic method.
- `a`: representative browser-reported horizontal uncertainty radius in metres.

Conservative illustrative decision boundaries:

- **LOCATION_ESTIMATE_ACCEPTED** when enough fresh valid samples exist and `d + a <= R`.
- **OUTSIDE_LOCATION_ESTIMATE** when `d - a > R`.
- **ACCURACY_INSUFFICIENT / UNCERTAIN** otherwise, especially when estimated uncertainty overlaps the boundary.

These equations provide a conservative *screening policy*, not a statistically calibrated confidence interval. Reported device accuracy is an estimate and must not be interpreted as a guarantee or proof against spoofing.

| Distance d | Reported accuracy a | Radius R | Result | Explanation |
|---:|---:|---:|---|---|
| 1.2 m | 2 m | 5 m | Estimate accepted | 1.2 + 2 = 3.2 <= 5 |
| 12 m | 3 m | 5 m | Outside estimate | 12 - 3 = 9 > 5 |
| 4 m | 6 m | 5 m | Uncertain | Uncertainty overlaps boundary |
| 2 m | 12 m | 5 m | Accuracy insufficient | Cannot confidently resolve 5 m |
| 7 m | 3 m | 5 m | Uncertain | Uncertainty overlaps boundary |

An estimate accepted under this algorithm is still only evidence of the **device-reported location**, not proof that a specific cadet stood at the checkpoint.

## 6. Duty-window verification and scheduling

- Backend stores authoritative UTC duty start/end and maps the schedule to the applicable local timezone.
- Check-in, random checks, and check-out are distinct authorized events.
- The server selects unpredictable random checks, e.g. 20–40 minutes apart; the next scheduled time is not disclosed to the cadet.
- Each issued challenge includes a unique ID, cryptographically unpredictable nonce, bound cadet/session/duty/checkpoint identifiers, issued time, deadline, and single-use state.
- Accept only samples reported as captured after the challenge was issued and received before the relevant deadline; the server receipt timestamp is authoritative. Client timestamps remain untrusted.
- Check active assignment, correct authenticated account, permitted duty window, expiry, nonce, and idempotency before recording outcomes.
- The existing **CAPTCHA then SMS OTP within 30 seconds** rule remains independent from GPS acquisition. A fresh satellite fix may take longer than 30 seconds. For the pilot, test a separate configurable GPS acquisition window (e.g. 45–90 seconds) rather than automatically treating an extended GPS fix as misconduct.
- If the phone is locked or the browser is closed, the website cannot ensure a pop-up or continually request GPS in the background. Browser push is best effort and device dependent.
- Missed checks are logged and presented for review, particularly when notification delivery cannot be confirmed.

Suggested states: `PENDING`, `GPS_ACQUIRING`, `LOCATION_ESTIMATE_ACCEPTED`, `OUTSIDE_LOCATION_ESTIMATE`, `ACCURACY_INSUFFICIENT`, `PERMISSION_DENIED`, `LOCATION_UNAVAILABLE`, `STALE_SAMPLE`, `MISSED`, `DELIVERY_EXCEPTION`, `SUSPICIOUS`, `UNDER_REVIEW`.

## 7. Outdoor, buildings and indoors

| Environment | Location behavior | Recommendation |
|---|---|---|
| Open ground | Best chance of useful high-accuracy fixes | Multi-sample browser GPS, retries, human review |
| Next to gates / walls / buildings | Reflections and blocked satellite signals may shift location | Add rotating on-site QR or supervisor check |
| Inside classrooms / corridors | Browser GNSS may be weak; network location may be coarse | Rotating QR, supervised check, or suitable physical proximity hardware |

**Rotating QR:** show a short-lived server-signed QR at a checkpoint. Cadet scans it using browser camera permission. Validate signature, expiry, challenge binding and one-use status. Screenshots can be relayed, so QR supplements but does not conclusively prove location.

**NFC:** Web NFC support is limited (commonly Android/Chromium); cannot be promised across all browsers and iOS devices.

**Bluetooth beacons:** Web Bluetooth and background scanning have inconsistent mobile-browser support. Stronger proximity verification requires managed hardware and often a native app.

## 8. Security, threat model and anti-spoofing

Browser-submitted location data is untrusted. A person controlling their own device can fabricate coordinates and accuracy using developer tools, mock location, modified operating systems, browser automation, or GPS spoofing. HTTPS secures the communication channel but does not prove the sensor data is true.

**Mitigations:** verified cadet roster, administrator-approved registration, password + SMS OTP at every new login, secure session cookies, strict backend access control, request-specific nonces, server-side expiry, bounded retries, rate limiting, impossible-speed and jump detection, metadata consistency checks, optional rotating QR, and manual supervisor spot checks. Label suspicious results for review; do not equate an anomaly with intentional fraud.

**Replay defense:** bind every location submission to its user, session, duty, checkpoint, unique server-issued nonce and challenge. Reject previously accepted nonces, expired challenges, stale client measurements and duplicate submissions. This protects against many simple replays, but cannot reliably stop a compromised browser from inventing a fresh-looking location.

**DoS/DDoS:** deploy behind a reputable CDN/WAF (e.g. Cloudflare), restrict direct origin access, enforce HTTPS, cap request rates at the edge and per user, bound request sizes and database work, limit OTP sends, log anomalies, and maintain backups and an incident response plan. Do not claim the service is DDoS-proof.

**Privacy:** explain purpose and limitations before asking for geolocation; collect only during authorized duties and individual verification events; use least-privilege role access and protect precise checkpoints. Example pilot retention: raw samples for 30 days and summarized incidents for 90 days, subject to the NCC unit's approved policy. Log privileged access and allow correction/review of incident conclusions. Do not publish real cadet or guard-post information in a public repository.

## 9. Admin monitoring dashboard

Recommended columns: cadet name, regimental number, duty, assigned checkpoint, shift window, check-in status, last verification server time, reported GPS accuracy (m), distance from checkpoint (m), current status, notification delivery state, and incident-review link.

| Status | Meaning |
|---|---|
| Verified (estimate) | Device-reported location passed conservative geofence policy |
| Outside Location | Estimated position outside checkpoint with a margin |
| Accuracy Insufficient | Sensor uncertainty prevents a 5 m decision |
| Pending | Challenge still active |
| Missed | Deadline expired without accepted response |
| Delivery Exception | Notification/provider/network exception detected |
| Suspicious | Replay, implausible motion or other anomalous signal |
| Under Review | Administrator investigating an event |

The administrator sees the **recorded estimate and its limitations**, not a declaration of absolute physical presence.

## 10. Database extensions (design only)

- `checkpoints`: id, unit_id, name, latitude, longitude, radius_m, instructions, created_by, created_at.
- `duty_location_policy`: duty_id, checkin_required, checkout_required, random_min_minutes, random_max_minutes, min_samples, acquisition_timeout_seconds, location_retry_limit.
- `location_challenges`: id, assignment_id, session_id, checkpoint_id, nonce_hash, issued_at, expires_at, status, completed_at.
- `location_samples`: id, challenge_id, reported_lat, reported_lon, reported_accuracy_m, reported_captured_at, server_received_at, accepted_for_aggregation, rejection_reason.
- `location_verifications`: id, challenge_id, representative_lat, representative_lon, distance_m, uncertainty_m, status, evaluated_at, algorithm_version.
- `location_incidents`: id, verification_id, reason, review_status, reviewer_user_id, review_notes, updated_at.
- `audit_logs`: record checkpoint creation/changes, assignment edits, verification overrides, incident reviews, and privileged data exports.

Use foreign keys, unique challenge-result constraints, UTC timestamps, append-only event history and database transactions.

## 11. API contracts (design only)

| Method | Endpoint | Access / purpose |
|---|---|---|
| POST | /api/v1/admin/checkpoints | Admin creates checkpoint |
| GET | /api/v1/admin/checkpoints | Admin lists authorized checkpoints |
| PATCH | /api/v1/admin/checkpoints/{id} | Admin edits checkpoint with audit |
| POST | /api/v1/admin/duties/{id}/location-policy | Admin configures verification |
| GET | /api/v1/cadet/duties/{id}/checkpoint | Assigned cadet views own checkpoint |
| POST | /api/v1/location/challenges/{id}/samples | Assigned cadet submits fresh samples |
| GET | /api/v1/location/challenges/{id}/result | Assigned cadet retrieves own outcome |
| GET | /api/v1/admin/location/verifications | Admin monitors authorized unit |
| PATCH | /api/v1/admin/location/incidents/{id} | Admin reviews incident |

Each endpoint checks authentication, cadet/duty ownership or admin unit scope, rate limits, input validity, and authoritative server time. The submission should have a one-use challenge binding and be safely idempotent.

## 12. Complete example: Main Gate, 08:00–10:00 IST

1. Admin creates **Main Gate** checkpoint and confirms coordinates on the map. Radius is 5 m.
2. Admin creates **Main Gate Duty** for 08:00–10:00 IST, enables check-in, randomized checks and check-out, then assigns an approved cadet by regimental number.
3. Cadet logs in with regimental number/password and receives the mandatory phone OTP. The duty appears automatically.
4. At 08:00 the cadet starts duty and permits location access. Five readings are collected. Representative point is **1.2 m** from checkpoint with **2 m** reported accuracy; the backend records an accepted location estimate at server time 08:01.
5. At a randomized on-duty check, the site sends a notification. Fresh GPS reads **4 m** from the checkpoint with **6 m** reported accuracy. This is **uncertain**, not a proven absence. The cadet retries near open sky.
6. On a subsequent check, reported distance is **12 m** with **3 m** accuracy; the backend marks **Outside Location Estimate**, records evidence and makes it available for authorized review.
7. Existing random CAPTCHA→OTP checks remain independently timed at 30 seconds; their two-consecutive/four-total failure threshold remains intact. Location uncertainty alone does not automatically increment that disciplinary-style failure counter.
8. At 10:00 the cadet checks out, if required; the server records check-out time, outcome and any exception.
9. Admin reviews check-in, all random results, notification history, reported uncertainty, and any incident, then records a reasoned review decision.

## 13. Final capability matrix

| Capability | Standard HTTPS website | Extra hardware/native app | Guarantee? |
|---|---|---|---|
| Map checkpoint and 5 m nominal radius | Yes | No | Configurable, not guaranteed accurate |
| Browser GPS samples in foreground | Yes, with permission | No | Depends on device/environment |
| Duty-window and server-time checks | Yes | No | Server-enforceable |
| Random verification and OTP | Yes | SMS provider for actual delivery | Delivery timing not guaranteed |
| Multi-sample uncertainty handling | Yes | No | Estimate only |
| Background/closed-browser continuous GPS | Not reliable | Native app may help | Still platform constrained |
| Rotating QR | Yes with camera and on-site code | On-site display/sign | Relay remains possible |
| NFC / Bluetooth proximity across all phones | No | Usually yes | Hardware and OS limitations |
| Defeat all fabricated GPS | No | Device attestation may reduce some abuse | Not guaranteed |
| Absolute proof of presence within 5 m | No | Multiple factors can improve assurance | Cannot guarantee |

## 14. Pilot acceptance tests and rollout

Test with consent at the real duty site using multiple Android/iOS models, clear sky, gate walls, and indoor locations. Measure median and worst-case reported error, time-to-first-fix, sample rejection rates, notification delays, false outside classifications, and user permission failures. Verify the zero-trust server design: stale/replayed/nonced requests rejected, admin permissions isolated, and identical submissions counted once.

**Rollout decision:** only use strict 5 m automatic acceptance if measured conditions support it; otherwise retain an uncertainty state and use a QR/supervisor cross-check. **No automatic punishment based solely on GPS or missed browser notifications.**

---
**Documentation only:** This file specifies the feature; it does not implement GPS tracking, deploy NCC Sentinel, or certify 5 m accuracy.
