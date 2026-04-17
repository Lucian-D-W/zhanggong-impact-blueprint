---
id: sql-session-integrity
summary: Session token routines must normalize user input before issuing tokens.
governs:
  - fn:db/functions/session.sql:app.issue_session_token
  - fn:db/functions/session.sql:app.normalize_user_name
---

# SQL Session Integrity

- `app.issue_session_token` must call `app.normalize_user_name`.
- Trigger helpers must not skip token normalization rules.
