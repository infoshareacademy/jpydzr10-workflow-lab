.PHONY: help install dev db-up db-down db-logs test test-cov test-fast lint format check migrate seed run shell superuser clean css css-watch

help:
	@echo "Planer Maszyn — Reference repo — Makefile common tasks"
	@echo ""
	@echo "Porty (Sebastian's lokalny dev):"
	@echo "  Postgres:  localhost:5434  (container: kursowe-repo-8002)"
	@echo "  Django:    http://localhost:8002"
	@echo ""
	@echo "Setup:"
	@echo "  make install      — uv sync (dev group auto-install via [tool.uv] default-groups)"
	@echo "  make db-up        — docker compose up -d (Postgres na 5434)"
	@echo "  make db-down      — docker compose down (dane zachowane)"
	@echo "  make db-logs      — docker compose logs -f postgres"
	@echo "  make migrate      — manage.py migrate"
	@echo "  make superuser    — manage.py createsuperuser"
	@echo "  make seed         — manage.py seed_demo"
	@echo ""
	@echo "Dev:"
	@echo "  make run          — runserver 0.0.0.0:8002  → http://localhost:8002"
	@echo "  make shell        — manage.py shell"
	@echo ""
	@echo "Quality:"
	@echo "  make test         — pytest -n auto"
	@echo "  make test-cov     — pytest --cov"
	@echo "  make test-fast    — pytest -q --no-cov (najszybsze)"
	@echo "  make lint         — ruff check"
	@echo "  make format       — ruff format"
	@echo "  make check        — django check --deploy"
	@echo ""
	@echo "Frontend (Tailwind):"
	@echo "  make css          — npm run css:build (one-shot, minified)"
	@echo "  make css-watch    — npm run css:watch (rebuild on save)"

install:
	uv sync

dev: install
	uv run pre-commit install

db-up:
	docker compose up -d
	@echo ""
	@echo "✓ Postgres uruchomiony: localhost:5434 (container: kursowe-repo-8002)"

db-down:
	docker compose down

db-logs:
	docker compose logs -f postgres

test:
	uv run pytest -n auto --tb=short

test-cov:
	uv run pytest --cov=. --cov-report=term-missing --cov-report=html

test-fast:
	uv run pytest -q --no-cov --tb=line

lint:
	uv run ruff check .

format:
	uv run ruff format .

check:
	uv run python manage.py check --deploy --fail-level WARNING

migrate:
	uv run python manage.py migrate

superuser:
	uv run python manage.py createsuperuser

seed:
	uv run python manage.py seed_demo

run:
	uv run python manage.py runserver 0.0.0.0:8002

shell:
	uv run python manage.py shell

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage

css:
	npm run css:build

css-watch:
	npm run css:watch
