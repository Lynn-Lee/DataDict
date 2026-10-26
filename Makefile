.DEFAULT_GOAL := help
.PHONY: help install up down logs psql run lint format typecheck test test-gate check clean

help: ## 显示可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## 安装依赖（含开发依赖）
	pip install -e ".[dev]"
	pre-commit install

up: ## 启动本地依赖（PostgreSQL + Redis），等待健康后返回
	docker compose up -d --wait
	@echo "PostgreSQL -> localhost:15432   Redis -> localhost:16379"

down: ## 停止本地依赖（保留数据卷）
	docker compose down

clean: ## 停止并删除数据卷（会清空本地数据）
	docker compose down -v

logs: ## 查看依赖服务日志
	docker compose logs -f

psql: ## 用超级用户连本地库
	docker compose exec postgres psql -U postgres -d datadict

run: ## 启动开发服务器
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

lint: ## 静态检查
	ruff check app tests

format: ## 格式化
	ruff format app tests
	ruff check --fix app tests

typecheck: ## 类型检查
	mypy app

test: ## 运行全部测试
	pytest -v

test-gate: ## 只跑 CI 门禁测试（DEV-TASKS §6，不允许 skip）
	./scripts/run-gate-tests.sh

check: lint typecheck test ## 提交前本地全量检查
