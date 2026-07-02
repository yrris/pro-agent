.PHONY: help proto proto-tools proto-go proto-py infra-up infra-down cognition control web check

# 读取 deploy/.env 并导出给应用进程（deploy/.env 不提交；含密钥与模型/连接配置）。
LOAD_ENV = set -a; [ -f deploy/.env ] && . ./deploy/.env; set +a;

help: ## 列出可用目标
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

cognition: ## 启动认知面（Python gRPC :50051，读 deploy/.env：DeepSeek + checkpointer）
	@bash -c '$(LOAD_ENV) cd cognition && uv run python -m cognition.server.grpc_server'

control: ## 启动控制面（Go HTTP/SSE :8080，读 deploy/.env）
	@bash -c '$(LOAD_ENV) cd control-plane && go run ./cmd/controlplane'

web: ## 启动前端（Vite :5173，代理到 :8080）
	cd web && npm run dev

check: ## 跑全部测试（Go + Python + 前端纯逻辑）
	cd control-plane && go test ./...
	cd cognition && uv run pytest -q
	cd web && npm run test

proto-tools: ## 安装 Go 的 protobuf 插件（首次/CI 用）
	go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
	go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

proto-go: ## 生成 Go stub（buf + 本地插件）
	PATH="$(shell go env GOPATH)/bin:$$PATH" buf generate

proto-py: ## 生成 Python stub（grpcio-tools）
	mkdir -p cognition/cognition/genproto
	cd cognition && uv run python -m grpc_tools.protoc \
		-I ../proto \
		--python_out=cognition/genproto \
		--grpc_python_out=cognition/genproto \
		--pyi_out=cognition/genproto \
		../proto/agent/v1/agent.proto
	find cognition/cognition/genproto -type d -exec touch {}/__init__.py \;

proto: proto-go proto-py ## 生成双端 stub

infra-up: ## 起本地依赖（postgres/qdrant/redis/minio/nats）
	cd deploy && docker compose up -d

infra-down: ## 停本地依赖
	cd deploy && docker compose down
