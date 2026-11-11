# Avatar Service

A Gravatar-like avatar service.

Users can register with a verified email address, upload multiple pictures, and select one as their current avatar. Other applications can retrieve the current avatar using the SHA-256 hash of the user's email address.


Part A covers the local development infrastructure, authentication, avatar management, public avatar delivery, CDN caching and invalidation, moderation, soft deletion, and the React frontend.


---

## Table of Contents

- [Requirements](#requirements)
- [First-time Setup](#first-time-setup)
- [Development Architecture](#development-architecture)
- [Where Things Run](#where-things-run)
- [Verify the Installation](#verify-the-installation)
- [Avatar API](#avatar-api)
- [Moderation](#moderation)
- [Soft Delete](#soft-delete)
- [Maintenance](#maintenance)
- [Common Commands](#common-commands)
- [Project Layout](#project-layout)
- [Roadmap](#roadmap)

---

## Requirements

- Docker
- Docker Compose v2 (`docker compose version`)
- `make` (optional; every Makefile target can also be run using Docker Compose commands)

---

## First-time Setup

Clone the repository and move into the project directory.

### 1. Configure environment variables

```bash
cp .env.example .env
```

The `.env` file contains local development settings. Adjust the values if any of the default ports conflict with services already running on your machine.


### 2. Start the services

```bash
make up
```

This builds the application images and starts the development stack.

### 3. Initialize object storage

```bash
make setup
```

This performs the initial S3-compatible storage setup:

- Creates the development bucket.
- Creates a restricted application access key.
- Runs the S3 smoke test to verify storage operations.

The setup is safe to run again if you need to repeat the initialization.

Expect every line of the smoke test to report `PASS`.

### 4. Initialize the database

```bash
make migrations
make migrate
```

`make migrations` generates migration files from model changes.

`make migrate` applies those migrations to PostgreSQL.

### 5. Create an administrator

```bash
make superuser
```

The administrator can log in to Django admin and manage moderation reports.

### 6. Run the tests

```bash
make test
```

---

## Development Architecture

The development environment runs using Docker Compose.

```text
                        Browser
                           |
                           v
                    Nginx :8080
                           |
             +-------------+-------------+
             |             |             |
             v             v             v
          Frontend       Backend       Varnish
          Vite :5173    Django :8000      |
                           |              |
                           v              v
                       PostgreSQL       Django
                                        |
                                        v
                                      Silo
                                   (S3 storage)

Additional services:
- Mailpit: captures outgoing development emails.
- Scheduler: runs periodic maintenance tasks.
```

Nginx is the main browser entry point. It routes requests to the appropriate service:

| Request path | Destination |
|---|---|
| `/` | React frontend through Vite |
| `/api/` | Django API |
| `/admin/` | Django admin |
| `/static/` | Static files served by Nginx |
| `/avatar/` | Varnish cache, with Django as its origin |

Avatar uploads use presigned S3 requests. The browser communicates directly with Silo for the actual file upload; the Django backend handles authorization and generates the presigned upload details.

Varnish caches public avatar responses. When an avatar changes, the backend sends a BAN request to invalidate the corresponding cached entries.

---

## Where Things Run

The normal application entry point is Nginx at `http://localhost:8080`.

| Service | URL |
|---|---|
| Application (React + Vite) | http://localhost:8080 |
| Backend health check | http://localhost:8080/api/health/ |
| API documentation (Swagger) | http://localhost:8080/api/docs/ |
| Django admin | http://localhost:8080/admin/ |
| Public avatars through Varnish | http://localhost:8080/avatar/{email_hash} |
| Silo console | http://localhost:9001 |
| Silo S3 API | http://localhost:9000 |
| Mailpit (captured emails) | http://localhost:8025 |
| PostgreSQL | localhost:5432 |

The Vite development server listens on port `5173` inside the Docker network. During normal use, access the frontend through Nginx rather than opening that internal service directly.

Silo console credentials are the `SILO_ROOT_*` values configured in `.env`.

---

## Verify the Installation

### 1. Check backend health

Open:

http://localhost:8080/api/health/

After storage initialization, the response should report:

```json
{
  "status": "ok"
}
```

### 2. Try the application

Open http://localhost:8080.

1. Create an account.
2. Open Mailpit at http://localhost:8025.
3. Open the account verification link received in the captured email.
4. Log in.
5. Upload a few pictures.
6. Choose one as your current avatar.

<!-- The **"What other apps receive"** section shows the picture as other applications retrieve it through the public avatar endpoint. -->

### 3. Upload a picture using the demo script

You can also upload a picture using the command-line demo.

Use an account whose email has been verified. The superuser account is already verified.

```bash
docker compose run --rm --entrypoint python silo-init \
  /scripts/demo_upload.py EMAIL PASSWORD
```

Replace `EMAIL` and `PASSWORD` with the account credentials.

### 4. Fetch an avatar through the CDN

The public endpoint identifies a user by the SHA-256 hash of their lowercase email address.

Generate the hash:

```bash
HASH=$(printf '%s' 'you@example.com' | shasum -a 256 | cut -d' ' -f1)
```

Fetch the avatar:

```bash
curl -i "http://localhost:8080/avatar/$HASH?s=160"
```

The first request should normally report:

```text
X-Cache: MISS
```

Repeat the same request:

```bash
curl -i "http://localhost:8080/avatar/$HASH?s=160"
```

The second request should normally report:

```text
X-Cache: HIT
```

The `Age` header indicates how long the response has been cached.

Try different sizes:

```bash
curl -i "http://localhost:8080/avatar/$HASH?s=40"
curl -i "http://localhost:8080/avatar/$HASH?s=160"
curl -i "http://localhost:8080/avatar/$HASH?s=640"
```

Try the default-picture behavior for an unknown hash:

```bash
curl -i "http://localhost:8080/avatar/unknownhash?d=identicon"
curl -i "http://localhost:8080/avatar/unknownhash?d=404"
```

### 5. Verify the origin lock

The backend protects the public avatar endpoint so that requests must come through the CDN.

Try accessing Django directly:

```bash
curl -i "http://localhost:8000/avatar/$HASH"
```

The expected result is:

```text
403 Forbidden
```

This verifies that the origin verification mechanism rejects requests that bypass Varnish.

### 6. Verify automatic cache invalidation

Changing or deleting a picture, changing an email address, or deleting an account triggers CDN invalidation through the backend.

Run the invalidation demo:

```bash
docker compose run --rm --entrypoint python silo-init \
  /scripts/demo_invalidation.py EMAIL PASSWORD
```

You can also manually invalidate one email hash:

```bash
curl -i -X BAN \
  -H "X-Ban-Pattern: ^/avatar/$HASH" \
  "http://localhost:8080/avatar/x"
```

The expected response is:

```text
200 Banned
```

This manually invalidates the matching objects in the local Varnish cache.

### 7. Inspect object storage

Open the Silo console:

http://localhost:9001

Log in using the `SILO_ROOT_*` credentials from `.env`.

Browse the `avatars-dev` bucket and inspect:

- `originals/` — uploaded original images.
- `derived/` — resized and processed avatar images.
- `uploads/` — temporary upload objects.

---

## Avatar API

Other applications do not need an account with this service to retrieve public avatars.

They only need the user's email address and the public avatar URL.

### Generate the email hash

Normalize the email address to lowercase and calculate its SHA-256 hash.

```bash
printf '%s' 'you@example.com' | shasum -a 256
```

### Fetch an avatar

```text
GET /avatar/{email_hash}?s=160
```

Parameters:

| Parameter | Description |
|---|---|
| `email_hash` | SHA-256 hash of the normalized email address |
| `s` | Requested avatar size |
| `d` | Default image behavior for users without an avatar |

Supported avatar sizes are:

```text
40, 80, 160, 320, 640
```

Example:

```html
<img
  src="http://localhost:8080/avatar/EMAIL_HASH?s=160"
  width="160"
  height="160"
  alt="User avatar"
/>
```

In production, replace the local development hostname with the deployed service's public domain.

---

## Moderation

Anyone, including an application that consumes public avatars, can report the picture currently displayed for an email hash.

### Submit a report

```bash
curl -X POST "http://localhost:8080/api/reports/" \
  -H "Content-Type: application/json" \
  -d "{\"email_hash\": \"$HASH\", \"reason\": \"This picture is offensive\"}"
```

### Review reports

Open the Django moderation queue:

http://localhost:8080/admin/moderation/report/

An administrator can select reports and perform one of the following actions:

- **Remove pictures:** removes the reported pictures and cleans up their stored files and cached copies.
- **Deactivate users:** deactivates the reported users.
- **Dismiss:** dismisses the selected reports.

Reports are retained even after the associated picture or account is deleted.

---

## Soft Delete

Deleting a picture or account does not immediately remove its data permanently.

Instead, the service uses soft deletion:

1. The resource is hidden immediately.
2. A deleted account can no longer log in, and its refresh tokens stop working.
3. Its public avatar is no longer available.
4. The data is retained for 30 days.
5. The scheduler permanently deletes expired records and associated S3 objects.

### Account behavior

<!-- - A deleted account's email address becomes available for registration immediately. -->
- The original email address is retained so the account can be restored.
- Restoring an account is refused if another account has registered that email address in the meantime.

### Restore a deleted resource

In Django admin:

1. Filter Users or Pictures by `is_deleted`.
2. Select the resources to restore.
3. Choose the **Restore** admin action.

### Permanent deletion

An administrator can permanently delete resources using the **Delete permanently** admin action.

Deleting an already soft-deleted resource also removes it immediately.

### Change the retention period

The default retention period is 30 days.

Change `SOFT_DELETE_RETENTION_DAYS` in:

```text
backend/config/settings/base.py
```

---

## Maintenance

The `scheduler` service periodically runs housekeeping tasks.

It runs once an hour and performs the following operations:

| Task | Purpose |
|---|---|
| `cleanup_unverified` | Deletes sign-ups that have not been verified within 24 hours |
| `flushexpiredtokens` | Removes expired refresh-token records |
| `purge_deleted` | Permanently removes soft-deleted pictures and accounts older than the retention period |

Run all maintenance tasks immediately:

```bash
make cleanup
```

Preview what the permanent-deletion task would remove:

```bash
docker compose exec backend \
  python manage.py purge_deleted --dry-run
```

---

## Common Commands

| Command | Description |
|---|---|
| `make up` | Start the development stack and rebuild images if needed |
| `make down` | Stop services without deleting persistent data |
| `make logs` | Follow service logs |
| `make ps` | Show service status |
| `make config` | Render the effective Compose configuration |
| `make migrations` | Generate database migration files |
| `make migrate` | Apply database migrations |
| `make superuser` | Create a Django administrator |
| `make test` | Run backend tests |
| `make test-s3` | Run opt-in integration tests against Silo |
| `make cleanup` | Run housekeeping tasks immediately |
| `make smoke` | Re-run the S3 storage smoke test |
| `make reset` | Stop services and delete local persistent volumes |

### Rebuild after frontend dependency changes

If you change `frontend/package.json` or `frontend/package-lock.json`, recreate the frontend's `node_modules` volume:

```bash
docker compose up -d --build --renew-anon-volumes frontend
```

### Type-check the frontend

```bash
docker compose exec frontend npx tsc --noEmit
```

### Inspect service logs

```bash
docker compose logs -f --tail=100 backend
docker compose logs -f --tail=100 frontend
docker compose logs -f --tail=100 varnish
```

### Reset the development environment

**Warning:** This removes persistent local data, including PostgreSQL and Silo volumes.

```bash
make reset
```

<!--
---

## Project Layout

```text
.
├── backend/             Django application
│   ├── apps/
│   │   ├── core/
│   │   ├── accounts/
│   │   ├── avatars/
│   │   └── moderation/
│   └── config/
│       └── settings/
├── frontend/            React + TypeScript + Vite application
├── cdn/
│   └── default.vcl      Varnish configuration
├── nginx/               Development and production Nginx configs
├── scripts/             S3 setup, app-key creation and demo scripts
├── docs/                Design and architecture documentation
├── compose.yaml         Shared Docker Compose configuration
├── compose.dev.yaml     Development services
├── compose.prod.yaml    Planned production Compose configuration
└── Makefile             Common development commands
``` -->

<!-- ---

## Roadmap

### Part A — Local development

**Completed**

- [x] Docker Compose development infrastructure
- [x] PostgreSQL database
- [x] S3-compatible local object storage using Silo
- [x] User registration and email verification
- [x] Login, logout, token refresh and password reset
- [x] Avatar upload and management
- [x] Public avatar endpoint using email SHA-256 hashes
- [x] Image resizing and derived image storage
- [x] Varnish caching and automatic invalidation
- [x] React frontend
- [x] Reporting and admin moderation
- [x] Soft deletion and restoration
- [x] Scheduled maintenance tasks
- [x] Backend tests and S3 smoke tests

### Part B — Hosting and AWS

**Planned**

- [ ] Provision a Linux VPS
- [ ] Deploy the application using Docker Compose
- [ ] Configure the production Nginx reverse proxy and HTTPS
- [ ] Configure Cloudflare DNS and edge caching
- [ ] Replace Silo with Amazon S3
- [ ] Configure production S3 bucket permissions and CORS
- [ ] Configure production email delivery
- [ ] Configure PostgreSQL backups and test restoration
- [ ] Verify production cache invalidation and origin protection
- [ ] Add production monitoring, logging and operational checks

Part B will build on the architecture and configurations developed during Part A. -->
