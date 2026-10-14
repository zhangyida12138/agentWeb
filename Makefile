.DEFAULT_GOAL := help

.PHONY: help install db-up db-down db-test-up db-test-down dev dev-backend dev-frontend \
	format lint test test-backend test-frontend build build-backend build-frontend

help:
	@echo Available targets:
	@echo   make install         Install backend (uv) and frontend (pnpm) dependencies
	@echo   make db-up           Start the PostgreSQL and pgAdmin containers
	@echo   make db-down         Stop the PostgreSQL and pgAdmin containers
	@echo   make db-test-up      Start the dedicated test PostgreSQL container (port 5433)
	@echo   make db-test-down    Stop the dedicated test PostgreSQL container
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
	docker compose up -d postgres pgadmin

db-down:
	docker compose down

# 测试库：docker-compose.yml 里的 postgres-test（独立实例 / 独立数据卷，5433）。
# --wait：等 healthcheck 通过再返回，省掉 pytest 那边因为库还在初始化而白等的几秒。
# 命令前的 `-` 表示失败不中断 make：Docker 没启动时不至于直接报错退出，
# pytest 在会话开始时会自己探测，探不到会打印「先执行 make db-test-up」的明确提示。
db-test-up:
	-@docker compose up -d --wait postgres-test

db-test-down:
	-@docker compose stop postgres-test

# 直接复用下面两条命令字符串，避免嵌套调用 $(MAKE)：
# Windows 上 make 的完整路径可能含空格（如 "C:/Program Files (x86)/GnuWin32/bin/make"），
# 嵌进 concurrently 的命令串后会被 cmd.exe 误拆，导致 "'C:/Program' is not recognized"。
BACKEND_DEV_CMD := uv run --directory apps/backend uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir src
FRONTEND_DEV_CMD := pnpm --filter frontend dev

# 前后端共用一条命令启动；任一进程退出即同时关闭另一方（Ctrl+C 一并退出）
dev:
	pnpm exec concurrently --kill-others --names backend,frontend --prefix-colors blue,magenta "$(BACKEND_DEV_CMD)" "$(FRONTEND_DEV_CMD)"

dev-backend:
	$(BACKEND_DEV_CMD)

dev-frontend:
	$(FRONTEND_DEV_CMD)

format:
	uv run --directory apps/backend ruff format src tests migrations ../../packages/backend
	uv run --directory apps/backend ruff check --fix src tests migrations ../../packages/backend
	pnpm exec prettier --write .

lint:
	uv run --directory apps/backend ruff format --check src tests migrations ../../packages/backend
	uv run --directory apps/backend ruff check src tests migrations ../../packages/backend
	pnpm lint

test: test-backend test-frontend

# 依赖 db-test-up：跑测试和启动测试库不该是两个需要记住的步骤。
# 测试用的环境变量（含测试库地址）都在 apps/backend/.env.test，不在命令里。
test-backend: db-test-up
	uv run --directory apps/backend pytest

test-frontend:
	pnpm --filter frontend test

build: build-backend build-frontend

build-backend:
	uv build --directory apps/backend

build-frontend:
	pnpm --filter frontend build
