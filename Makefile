.PHONY: up down logs ps setup bucket app-key smoke reset migrations migrate superuser test test-s3 shell cleanup

up:            ## start everything (build if needed)
	docker compose up --build -d

down:          ## stop everything (keeps data)
	docker compose down

logs:          ## follow logs
	docker compose logs -f --tail=100

ps:            ## show service status
	docker compose ps

bucket:        ## create bucket + CORS + lifecycle rules in Silo
	docker compose run --rm silo-init

app-key:       ## create the application's restricted access key in Silo
	docker compose exec silo sh /scripts/create_app_key.sh

smoke:         ## run the S3 smoke test
	docker compose run --rm silo-init python /scripts/smoke_test.py

setup:         ## first-time setup: bucket, app key, smoke test
	docker compose up -d --build db silo
	$(MAKE) bucket
	$(MAKE) app-key
	$(MAKE) smoke

migrations:    ## generate Django migration files after model changes
	docker compose exec backend python manage.py makemigrations

migrate:       ## apply database migrations
	docker compose exec backend python manage.py migrate

superuser:     ## create an admin user (asks for email and password)
	docker compose exec backend python manage.py createsuperuser

test:          ## run the backend tests
	docker compose exec backend python manage.py test

test-s3:       ## run the opt-in tests against the real Silo server
	docker compose exec -e RUN_S3_TESTS=1 backend python manage.py test apps.avatars.test_s3_integration

cleanup:       ## run the housekeeping commands once, right now
	docker compose exec backend python manage.py cleanup_unverified
	docker compose exec backend python manage.py flushexpiredtokens
	docker compose exec backend python manage.py purge_deleted

shell:         ## open a Django shell in the backend container
	docker compose exec backend python manage.py shell

reset:         ## DANGER: stop everything and delete all local data volumes
	docker compose down -v