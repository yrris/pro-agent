// 控制面入口：装配存储/认知客户端/泵/调度/HTTP，并优雅启停。
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"my-agent/control-plane/internal/api"
	"my-agent/control-plane/internal/artifact"
	"my-agent/control-plane/internal/cognition"
	"my-agent/control-plane/internal/config"
	"my-agent/control-plane/internal/dispatch"
	"my-agent/control-plane/internal/health"
	"my-agent/control-plane/internal/store"
	"my-agent/control-plane/internal/stream"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	cfg := config.Load()

	ctx := context.Background()
	pool, err := store.NewPool(ctx, cfg.PGDSN)
	if err != nil {
		log.Error("connect postgres", "err", err)
		os.Exit(1)
	}
	defer pool.Close()
	if err := store.Migrate(ctx, pool); err != nil {
		log.Error("migrate", "err", err)
		os.Exit(1)
	}

	client, err := cognition.Dial(cfg.CognitionAddr)
	if err != nil {
		log.Error("dial cognition", "err", err)
		os.Exit(1)
	}
	defer client.Close()

	runs := store.NewRunRepository(pool)
	sessions := store.NewSessionRepository(pool)
	events := store.NewEventRepository(pool)

	artStore, err := artifact.NewMinioStore(cfg.MinioEndpoint, cfg.MinioAccessKey, cfg.MinioSecretKey, cfg.MinioBucket, cfg.MinioUseSSL)
	if err != nil {
		log.Error("minio client", "err", err)
		os.Exit(1)
	}
	// 桶不可用不致命：仅 /artifacts 受影响，ReAct/Plan-Execute 主链路照常。
	if err := artStore.EnsureBucket(ctx); err != nil {
		log.Warn("minio bucket ensure failed; artifacts unavailable", "err", err)
	}

	hub := stream.NewHub(events, cfg.HeartbeatInterval, log)
	dispatcher := dispatch.New(cfg.MaxConcurrentRuns, runs, client, hub, cfg.MaxSteps, log)
	// 健康检查：PG ping + 认知面 grpc.health.v1（业务就绪）。
	healthChecks := map[string]health.Check{
		"postgres":  func(ctx context.Context) error { return pool.Ping(ctx) },
		"cognition": client.HealthCheck,
	}
	router := api.NewRouter(dispatcher, runs, sessions, events, artStore, healthChecks, cfg.RunTimeout, cfg.WebDir, log)

	srv := &http.Server{Addr: cfg.HTTPAddr, Handler: router}

	go func() {
		log.Info("control-plane listening", "addr", cfg.HTTPAddr, "cognition", cfg.CognitionAddr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("http server", "err", err)
			os.Exit(1)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	log.Info("shutting down")
	shutCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutCtx)
}
