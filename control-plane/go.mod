module my-agent/control-plane

go 1.25.0

// 依赖在各里程碑落地时通过 `go get` 引入并 `go mod tidy`，避免空 require 块。
// 计划内主要依赖（M1 起逐步引入）：
//   - github.com/go-chi/chi/v5        HTTP 路由
//   - github.com/jackc/pgx/v5         PostgreSQL 驱动（配合 sqlc 生成类型安全查询）
//   - golang.org/x/sync               errgroup / semaphore（有界并发与背压）
//   - google.golang.org/grpc          与 Python 认知面的 gRPC 流式通信
//   - github.com/redis/go-redis/v9    缓存 / 限流 / pub-sub

require (
	github.com/jackc/pgx/v5 v5.10.0
	google.golang.org/grpc v1.81.1
	google.golang.org/protobuf v1.36.11
)

require (
	github.com/jackc/pgpassfile v1.0.0 // indirect
	github.com/jackc/pgservicefile v0.0.0-20240606120523-5a60cdf6a761 // indirect
	github.com/jackc/puddle/v2 v2.2.2 // indirect
	golang.org/x/net v0.51.0 // indirect
	golang.org/x/sync v0.20.0 // indirect
	golang.org/x/sys v0.42.0 // indirect
	golang.org/x/text v0.34.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20260226221140-a57be14db171 // indirect
)
