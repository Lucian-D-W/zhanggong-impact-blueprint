---
id: auth-session-invariant
summary: Successful login must create a session token.
governs:
  - fn:src/app.py:login
---

# Auth Session Invariant

- Successful login must return a non-empty session token.
- Failed login must not mint a session token.
