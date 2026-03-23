.PHONY: dev setup-dev build up down logs

# ─── Local development ────────────────────────────────────────────────────────
test:
	python -m pytest tests/ -v

test-cov:
	python -m pytest tests/ --cov=app --cov-report=term-missing

setup-dev:
	@echo "Downloading frontend vendor libraries..."
	mkdir -p static
	wget -q -O static/htmx.min.js https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js
	wget -q -O static/alpine.min.js https://cdn.jsdelivr.net/npm/alpinejs@3.14.8/dist/cdn.min.js
	pip install -r requirements.txt
	@echo "Done. Copy .env.example to .env and edit it, then run: make dev"

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

# ─── Docker ───────────────────────────────────────────────────────────────────
build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f taglab
