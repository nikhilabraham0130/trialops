# Database migrations

Alembic migration files provide the ordered, version-controlled history of the
TrialOps PostgreSQL schema. Apply all available migrations from `backend/` with:

```powershell
python -m alembic upgrade head
```

Do not edit a migration after it has been shared. Create a new migration for
subsequent schema changes so existing databases can follow the same history.
