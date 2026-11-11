COMPOSE = docker compose -f compose.yaml -f compose.dev.yaml

.PHONY: up down logs ps config setup bucket app-key smoke \
        migrations migrate superuser test test-s3 shell cleanup reset

# --------------------------------------------------
# Development environment
# --------------------------------------------------

up: ## Build and start the development environment
	$(COMPOSE) up --build -d

down: ## Stop the development environment (keeps data)
	$(COMPOSE) down

logs: ## Follow logs from all services
	$(COMPOSE) logs -f --tail=100

ps: ## Show service status
	$(COMPOSE) ps

config: ## Validate the merged development Compose configuration
	$(COMPOSE) config

# --------------------------------------------------
# Silo setup
# --------------------------------------------------

bucket: ## Create the Silo bucket, CORS and lifecycle rules
	$(COMPOSE) run --rm silo-init

app-key: ## Create the application's restricted Silo access key
	$(COMPOSE) exec silo sh /scripts/create_app_key.sh

smoke: ## Run the S3 integration smoke test against Silo
	$(COMPOSE) run --rm --entrypoint python silo-init /scripts/smoke_test.py

setup: ## First-time setup: start dependencies, configure Silo and test it
	$(COMPOSE) up -d --build db silo
	$(MAKE) bucket
	$(MAKE) app-key
	$(MAKE) smoke

# --------------------------------------------------
# Django database
# --------------------------------------------------

migrations: ## Generate Django migration files after model changes
	$(COMPOSE) exec backend python manage.py makemigrations

migrate: ## Apply Django database migrations
	$(COMPOSE) exec backend python manage.py migrate

superuser: ## Create a Django admin user
	$(COMPOSE) exec backend python manage.py createsuperuser

# --------------------------------------------------
# Tests
# --------------------------------------------------

test: ## Run Django backend tests
	$(COMPOSE) exec backend python manage.py test

test-s3: ## Run opt-in tests against the real Silo server
	$(COMPOSE) exec -e RUN_S3_TESTS=1 backend python manage.py test apps.avatars.test_s3_integration

# --------------------------------------------------
# Maintenance
# --------------------------------------------------

cleanup: ## Run Django housekeeping commands once
	$(COMPOSE) exec backend python manage.py cleanup_unverified
	$(COMPOSE) exec backend python manage.py flushexpiredtokens
	$(COMPOSE) exec backend python manage.py purge_deleted

# --------------------------------------------------
# Django shell
# --------------------------------------------------

shell: ## Open the Django shell
	$(COMPOSE) exec backend python manage.py shell

# --------------------------------------------------
# Reset
# --------------------------------------------------

reset: ## DANGER: Stop services and delete all local Docker volumes
	$(COMPOSE) down -v