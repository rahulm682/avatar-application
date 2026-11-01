# Avatar Service

A Gravatar-like service (learning project). Users register with a verified email, upload several
pictures, and choose one as the current avatar. Other apps fetch it by the SHA-256 hash of the email.

**Current status: Part A of the roadmap is complete** (infrastructure, accounts and authentication, avatar upload and
management, the public `/avatar/{email_hash}` endpoint, automatic CDN invalidation, the React frontend, and reports
with admin moderation, and soft delete). Planned next: Part B (hosting and AWS).

## Requirements

- Docker with Compose v2 (`docker compose version`)
- `make` (optional; every target is just a `docker compose` command, see the Makefile)

## First-time setup

```bash
cp .env.example .env          # local dev values; adjust if ports clash
docker compose up --build -d  # starts all services
make setup                    # creates the bucket, the app's access key, and runs the S3 smoke test
make migrations && make migrate
make superuser                # an admin who can log in right away
make test
```

`make setup` can be re-run safely. Expect every line of the smoke test to say `PASS`.

## Where things run

| What | URL |
|---|---|
| Frontend (React, Vite) | http://localhost:5173 |
| Backend health check | http://localhost:8000/api/health/ |
| API docs (Swagger) | http://localhost:8000/api/docs/ |
| Django admin (moderation) | http://localhost:8000/admin/ |
| CDN (Varnish): public avatars | http://localhost:8080/avatar/{email_hash} |
| Silo console (browse buckets) | http://localhost:9001 (login with the `SILO_ROOT_*` values from `.env`) |
| Silo S3 API | http://localhost:9000 |
| Mailpit (caught emails) | http://localhost:8025 |
| Postgres | `localhost:5432` |

## Check that everything works

1. **Health:** open http://localhost:8000/api/health/. After `make setup` you should see `"status": "ok"`.
   **Try the app** at http://localhost:5173: create an account, open the confirmation link in Mailpit
   (http://localhost:8025), log in, add a few pictures, and choose one. The "What other apps receive" strip shows the
   picture exactly as the CDN serves it.
2. **Upload a picture** with an account that is verified (the superuser is):
   ```bash
   docker compose run --rm silo-init python /scripts/demo_upload.py EMAIL PASSWORD
   ```
3. **Fetch it through the CDN.** The hash is the SHA-256 of the lowercase email:
   ```bash
   HASH=$(printf '%s' 'you@example.com' | shasum -a 256 | cut -d' ' -f1)
   curl -i "http://localhost:8080/avatar/$HASH?s=160"    # X-Cache: MISS
   curl -i "http://localhost:8080/avatar/$HASH?s=160"    # X-Cache: HIT, Age grows
   ```
   Open the same URL in a browser to see the picture. Try `s=40`, `s=640`, and an unknown hash with `d=identicon`
   or `d=404`.
4. **Origin lock:** the backend refuses `/avatar/*` requests that skip the CDN:
   ```bash
   curl -i "http://localhost:8000/avatar/$HASH"          # 403 Forbidden
   ```
5. **Invalidation is automatic.** Changing or deleting a picture, changing an email, or deleting an account makes the
   API ask Varnish to forget the cached copies. Watch it happen:
   ```bash
   docker compose run --rm silo-init python /scripts/demo_invalidation.py EMAIL PASSWORD
   ```
   To clear one hash by hand:
   ```bash
   curl -i -X BAN -H "X-Ban-Pattern: ^/avatar/$HASH" http://localhost:8080/avatar/x   # 200 Banned
   ```
6. **S3:** open the Silo console and look at `originals/`, `derived/` and (briefly) `uploads/` in `avatars-dev`.

## Moderation

Anyone (or any app) can report the picture currently shown for an email hash:

```bash
curl -X POST http://localhost:8000/api/reports/ -H 'Content-Type: application/json' \
  -d "{\"email_hash\": \"$HASH\", \"reason\": \"This picture is offensive\"}"
```

Then open the queue at http://localhost:8000/admin/moderation/report/, select reports, and choose an action:
remove the reported pictures (files and CDN copies are cleaned up too), deactivate the reported users, or dismiss.
Reports are kept even after the picture or account is deleted.

## Soft delete

Deleting a picture or an account does not remove anything straight away. It is hidden at once (an account can no longer
log in, its tokens stop working, and its public picture disappears), kept for **30 days**, and then removed for good,
S3 files included.

- A deleted account's email address is free again immediately; the real address is kept so the account can be restored.
- Restore from the Django admin: filter Users or Pictures by `is_deleted`, select, and use **Restore**.
  Restoring an account is refused if someone registered its email address in the meantime.
- **Delete permanently** (admin action), or deleting something that is already soft-deleted, removes it immediately.
- Change the retention with `SOFT_DELETE_RETENTION_DAYS` in `backend/config/settings/base.py`.

## Maintenance

The `scheduler` service runs once an hour: it deletes sign-ups that were never verified (older than 24 hours) and
expired refresh-token records, and removes soft-deleted pictures and accounts older than 30 days. Run all three right
now with `make cleanup` (`docker compose exec backend python manage.py purge_deleted --dry-run` shows what it would remove).

## Common commands

```bash
make up           # start (and rebuild if needed)
make down         # stop, keep data
make logs         # follow logs
make migrations   # generate migration files after model changes
make migrate      # apply migrations
make superuser    # create an admin user
make test         # run the backend tests
make test-s3      # the opt-in tests against the real Silo server
make cleanup      # run the housekeeping commands once
make smoke        # re-run the S3 smoke test
make reset        # DANGER: stop and delete all local data (database and Silo)

# after changing frontend/package.json (the old node_modules volume must be replaced)
docker compose up -d --build --renew-anon-volumes frontend

# type-check the frontend
docker compose exec frontend npx tsc --noEmit

```

## Layout

```
cdn/default.vcl     Varnish configuration (local CDN)
scripts/            S3 bucket setup, app key creation, smoke test, upload demo
backend/            Django project (apps: core, accounts, avatars, moderation)
frontend/           React + Vite app (sign-up, log-in, account and picture manager)
docs/               Design document
```
