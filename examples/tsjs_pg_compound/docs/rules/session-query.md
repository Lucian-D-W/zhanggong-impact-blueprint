---
id: tsjs-sql-session-query
summary: Application session label queries must target the canonical SQL routine.
governs:
  - fn:src/sessionQueries.js:fetchSessionLabel
  - fn:db/functions/session_label.sql:app.get_session_label
---

# Session Query Rule

- `fetchSessionLabel` should call `app.get_session_label`.
- SQL helpers should normalize user names before formatting labels.
