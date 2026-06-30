// Package config 从环境变量加载控制面配置（带合理默认值）。
package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	HTTPAddr          string        // 对外 HTTP/SSE 监听地址
	CognitionAddr     string        // Python 认知面 gRPC 地址
	PGDSN             string        // PostgreSQL DSN
	MaxConcurrentRuns int64         // 并发 run 上限（信号量），满则“繁忙”
	HeartbeatInterval time.Duration // SSE 心跳间隔
	RunTimeout        time.Duration // 单次 run 超时
	MaxSteps          int32         // ReAct 循环上限
}

func Load() Config {
	return Config{
		HTTPAddr:          env("HTTP_ADDR", ":8080"),
		CognitionAddr:     env("COGNITION_ADDR", "localhost:50051"),
		PGDSN:             env("PG_DSN", "postgres://agent:agent_pwd@localhost:55432/my_agent"),
		MaxConcurrentRuns: int64(envInt("MAX_CONCURRENT_RUNS", 16)),
		HeartbeatInterval: time.Duration(envInt("HEARTBEAT_MS", 10000)) * time.Millisecond,
		RunTimeout:        time.Duration(envInt("RUN_TIMEOUT_S", 600)) * time.Second,
		MaxSteps:          int32(envInt("MAX_STEPS", 40)),
	}
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}
