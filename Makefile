.DEFAULT_GOAL := help

.PHONY: help install db-up db-down dev dev-backend dev-frontend \
	format lint test test-backend test-frontend build build-backend build-frontend

help:
	@echo Available targets:
	@echo   make install         Install backend (uv) and frontend (pnpm) dependencies
	@echo   make db-up           Start the PostgreSQL container
	@echo   make db-down         Stop the PostgreSQL container
	@echo   make dev             Run backend and frontend dev servers together
	@echo   make dev-backend     Run only the FastAPI dev server on http://localhost:8000
	@echo   make dev-frontend    Run only the Vite dev server on http://localhost:5173
	@echo   make format          Format Python (ruff) and TS/TSX (prettier)
	@echo   make lint            Lint Python (ruff) and TS/TSX (eslint)
	@echo   make test            Run backend (pytest) and frontend (vitest) tests
	@echo   make build           Package backend (uv build) and build frontend bundle

install:
	uv sync --directory apps/backend
	pnpm install

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

# 前后端共用一条命令启动；任一进程退出即同时关闭另一方（Ctrl+C 一并退出）
dev:
	pnpm exec concurrently --kill-others --names backend,frontend --prefix-colors blue,magenta "$(MAKE) dev-backend" "$(MAKE) dev-frontend"

dev-backend:
	uv run --directory apps/backend uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	pnpm --filter frontend dev

format:
	uv run --directory apps/backend ruff format src tests migrations
	uv run --directory apps/backend ruff check --fix src tests migrations
	prettier --write .

lint:
	uv run --directory apps/backend ruff format --check src tests migrations
	uv run --directory apps/backend ruff check src tests migrations
	pnpm --filter frontend lint

test: test-backend test-frontend

test-backend:
	uv run --directory apps/backend pytest

test-frontend:
	pnpm --filter frontend test

build: build-backend build-frontend

build-backend:
	uv build --directory apps/backend

build-frontend:
	pnpm --filter frontend build
