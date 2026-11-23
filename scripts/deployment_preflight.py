"""Non-invasive deployment readiness checks for NCC Sentinel.

Run in the prospective hosting environment before exposing any public listener.
Does not connect to external services, mutate the database, or print secret values.
"""
import os
import sys
from pathlib import Path


def check_environment(env=None):
    env = dict(os.environ if env is None else env)
    issues = []
    warnings = []
    if env.get('DEV_MODE', '1') != '0':
        issues.append('DEV_MODE must be explicitly 0; development OTP disclosure is not safe on the internet.')
    if env.get('SMS_MODE', 'demo') != 'twilio':
        issues.append('Set SMS_MODE=twilio with verified credentials; demo OTPs must never be public.')
    if not all(env.get(key) for key in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_FROM_NUMBER')):
        issues.append('Twilio account, token, and approved sender are required for actual OTP messages.')
    if env.get('COOKIE_SECURE') != '1':
        issues.append('COOKIE_SECURE must be 1 behind HTTPS.')
    secret = env.get('SESSION_SECRET', '')
    if len(secret) < 48 or secret in ('REPLACE_WITH_LONG_RANDOM_SECRET', 'local-dev-secret-change-this-before-sharing'):
        issues.append('SESSION_SECRET must be a unique cryptographically random secret (at least 48 characters).')
    if not env.get('TURNSTILE_SITE_KEY') or not env.get('TURNSTILE_SECRET_KEY'):
        issues.append('Cloudflare Turnstile public and secret keys are required.')
    path = env.get('DATABASE_PATH', './sentinel.db')
    if not Path(path).is_absolute():
        issues.append('Use an absolute DATABASE_PATH on an explicitly persistent disk; relative paths risk data loss.')
    if env.get('PERSISTENT_DISK_CONFIRMED') != '1':
        issues.append('Confirm persistent storage and backups for SQLite. Free ephemeral filesystems are not durable.')
    if env.get('ADMIN_PROVISIONED') != '1':
        issues.append('Admin identity must be provisioned securely before opening the service to users.')
    if env.get('PHONE_OWNERSHIP_VERIFIED') != '1':
        issues.append('Confirm registration SMS ownership verification works with the real provider on actual devices; demo codes are insufficient.')
    if env.get('EDGE_PROTECTION_CONFIRMED') != '1':
        issues.append('An HTTPS edge/WAF and locked-down origin must be configured before public access.')
    if env.get('SECURITY_REVIEW_CONFIRMED') != '1':
        issues.append('Independent authorization, registration, OTP abuse, and deployment security tests are required.')
    warnings.append('A 30-second SMS OTP cannot guarantee delivery; missed checks require review.')
    warnings.append('Browser GPS cannot guarantee actual presence within five metres or prevent advanced spoofing.')
    warnings.append('One Uvicorn process only; the current duty scheduler is in-process.')
    return issues, warnings


if __name__ == '__main__':
    issues, warnings = check_environment()
    print('NCC Sentinel production preflight')
    for issue in issues:
        print('BLOCKER:', issue)
    for warning in warnings:
        print('NOTICE:', warning)
    print('RESULT:', 'BLOCKED' if issues else 'ENVIRONMENT CHECKS PASSED (not a security certification)')
    sys.exit(1 if issues else 0)
