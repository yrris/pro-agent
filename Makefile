.PHONY: help proto proto-tools proto-go proto-py infra-up infra-down

help: ## 列出可用目标
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

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
