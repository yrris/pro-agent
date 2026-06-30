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
	"my-agent/control-plane/internal/cognition"
	"my-agent/control-plane/internal/config"
	"my-agent/control-plane/internal/dispatch"
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
	events := store.NewEventRepository(pool)
	hub := stream.NewHub(events, cfg.HeartbeatInterval, log)
	dispatcher := dispatch.New(cfg.MaxConcurrentRuns, runs, client, hub, cfg.MaxSteps, log)
	router := api.NewRouter(dispatcher, runs, events, cfg.RunTimeout, log)

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
