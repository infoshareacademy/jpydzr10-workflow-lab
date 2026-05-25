.PHONY: help install dev db-up db-down db-logs migrate seed run shell superuser test test-cov lint format check clean

help:
	@echo "Planer Maszyn Budowlanych (kursowy) — Makefile common tasks"
	@echo ""
	@echo "Porty (Sebastian's lokalny dev):"
	@echo "  Postgres:  localhost:5434  (container: kursowe-repo-8002)"
	@echo "  Django:    http://localhost:8002"
	@echo ""
	@echo "Setup:"
	@echo "  make install      — uv sync (instalacja deps)"
	@echo "  make db-up        — docker compose up -d (Postgres na 5434)"
	@echo "  make db-down      — docker compose down (dane zachowane w volume)"
	@echo "  make db-logs      — docker compose logs -f postgres"
	@echo "  make migrate      — manage.py migrate"
	@echo "  make superuser    — manage.py createsuperuser"
	@echo ""
	@echo "Dev:"
	@echo "  make run          — runserver 0.0.0.0:8002  → http://localhost:8002"
	@echo "  make shell        — manage.py shell"
	@echo ""
	@echo "Quality:"
	@echo "  make test         — pytest -n auto"
	@echo "  make test-cov     — pytest --cov"
	@echo "  make lint         — ruff check"
	@echo "  make format       — ruff format"
	@echo "  make check        — django check"
	@echo "  make clean        — usuwa __pycache__ / .pytest_cache / .ruff_cache"

install:
	uv sync

dev: install
	uv run pre-commit install || true

db-up:
	docker compose up -d
	@echo ""
	@echo "✓ Postgres uruchomiony: localhost:5434 (container: kursowe-repo-8002)"
	@echo "  TablePlus: host=localhost port=5434 user=planer pass=planer_dev_2026 db=planer_kursowy"

db-down:
	docker compose down

db-logs:
	docker compose logs -f postgres

migrate:
	uv run python manage.py migrate

superuser:
	uv run python manage.py createsuperuser

run:
	uv run python manage.py runserver 0.0.0.0:8002

shell:
	uv run python manage.py shell

test:
	uv run pytest -n auto --tb=short

test-cov:
	uv run pytest --cov=. --cov-report=term-missing

lint:
	uv run ruff check .

format:
	uv run ruff format .

check:
	uv run python manage.py check

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
