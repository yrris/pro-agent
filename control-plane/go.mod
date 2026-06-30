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
	google.golang.org/grpc v1.81.1
	google.golang.org/protobuf v1.36.11
)

require (
	golang.org/x/net v0.51.0 // indirect
	golang.org/x/sys v0.42.0 // indirect
	golang.org/x/text v0.34.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20260226221140-a57be14db171 // indirect
)
