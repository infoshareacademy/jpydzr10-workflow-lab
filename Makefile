.PHONY: help install dev db-up db-down db-logs test test-cov test-fast e2e lint format check migrate seed run voice voice-repl voice-dev shell superuser clean css css-watch messages compilemessages

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
	@echo "  make e2e          — pytest tests/e2e (Playwright, wymaga `make run`)"
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

# Testy E2E (Playwright) — wymagają działającego serwera dev na :8002
# (`make run` w drugim terminalu). Bez serwera scenariusze skipują się
# (guard ERR_CONNECTION_REFUSED → pytest.skip). Dodaj `--headed`, aby
# zobaczyć przeglądarkę: uv run pytest tests/e2e/ -m e2e --headed
e2e:
	uv run pytest tests/e2e/ -m e2e -v

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

messages:
	uv run python manage.py makemessages -l en --ignore=.venv --ignore=node_modules --ignore=static/vendor --ignore=archive

compilemessages:
	uv run python manage.py compilemessages --ignore=.venv --ignore=node_modules --ignore=archive

run: compilemessages
	uv run python manage.py runserver 0.0.0.0:8002

# Agent głosowy — uvicorn pod dedykowanym modułem ustawień `voice` (DEBUG=False,
# bez debug_toolbar, host tunelu w ALLOWED_HOSTS). Webhook /voice/incoming/ działa;
# żywe gniazdo WS domykane przy uruchomieniu na żywo (patrz chatbot/voice_consumer.py).
voice: compilemessages
	DJANGO_SETTINGS_MODULE=planer_config.settings.voice uv run uvicorn planer_config.asgi:application --host 0.0.0.0 --port 8010

# Lokalny symulator agenta głosowego — iteracja bez telefonu/tunelu/Twilio
# (stdin/stdout zamiast ConversationRelay, prawdziwy Gemini Live). Do szybkiego
# testowania promptu/narzędzi/RBAC. ROLE=admin|kierownik|magazynier|montazysta|guest.
ROLE ?= admin
voice-repl:
	DJANGO_SETTINGS_MODULE=planer_config.settings.voice uv run python manage.py voice_repl --role $(ROLE)

# Serwer głosowy w trybie DEV — uvicorn z hot-reload, bez compilemessages w ścieżce
# krytycznej. Do iterowania kodu mostu (zmiana .py → auto-reload). DEBUG=False zostaje
# (profil voice; NIE przełączać na dev — debug_toolbar wysadza ASGI).
voice-dev:
	DJANGO_SETTINGS_MODULE=planer_config.settings.voice uv run uvicorn planer_config.asgi:application --host 0.0.0.0 --port 8010 --reload --reload-dir chatbot --reload-dir planer_config

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
