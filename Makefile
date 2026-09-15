.PHONY: dev test lint migrate seed logs down
dev:
	docker compose up -d --build
test:
	docker compose run --rm api pytest -q
lint:
	docker compose run --rm api ruff check app tests
	docker compose run --rm web pnpm lint
migrate:
	docker compose run --rm api alembic upgrade head
seed:
	docker compose run --rm api python -m app.seed
logs:
	docker compose logs -f api worker web
down:
	docker compose down
