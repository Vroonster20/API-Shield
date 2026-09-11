# API-Shield
A compact security layer that detects and blocks malicious API activity using rate limits, IP monitoring, automated bans, and fuzz‑testing, all managed through a central admin panel.

## Rate Limiting 
Restrict the number of requests allowed per IP within a defined time window to prevent overload or brute force attempts.
## Abuse Detection and Auto Ban
Identify suspicious patterns such as repeated failed logins, malformed payloads, replay attacks, or rapid request bursts. Automatically ban IPs that violate defined rules.
## Input Validation and Fuzz Testing
Test the API against malformed, random, or unexpected inputs to uncover vulnerabilities in authentication, authorization, and data handling. 
## Control Panel and UI
Master control panel to manage the program and configure settings
- Run fuzzing test
- View logs
- Configure rate limits and throttling
- Configure and manage bans and durations

## Security Logging
Record security events, including rate limit triggers, bans, and fuzzing results, for later review and analysis.

## Setup
npm dev:ts - start server for front end development
npm build - build frontend
npm start - host frontend
npm typecheck - typecheck frontend

### install dependecies
python -m venv .venv
pip install -r requirements.txt

npm dev:py - run python server in dev mode
npm start:py - run python server in production mode