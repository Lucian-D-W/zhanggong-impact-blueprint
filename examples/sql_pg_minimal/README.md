# sql_pg_minimal

Stage5 minimal PostgreSQL supplemental adapter fixture.

This fixture is intentionally SQL-first:

- primary adapter should fall back to `generic`
- supplemental adapter should be `sql_postgres`
- SQL routines still enter the shared graph as `function` nodes
- SQL tests remain lightweight and real, but coverage is allowed to stay unavailable

Use it to validate:

- SQL function seeds
- SQL direct `CALLS`
- SQL `COVERS`
- SQL `GOVERNS`
- generic primary + SQL supplemental cooperation
