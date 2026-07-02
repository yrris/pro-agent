package store

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// ListSessions 的 limit 边界：<=0 用默认值，超上限截断（防一次拉全表）。
const (
	defaultSessionLimit = 50
	maxSessionLimit     = 200
)

// SessionSummary 是 GET /sessions 的一行：runs 表按 (owner_id, session_id) 聚合的
// 只读投影。会话没有独立表——标题/entryAgent 取会话首条 run（M7 取舍：零新表、
// 单一事实源；将来要"重命名会话"再建覆盖表，见 docs/08 §2）。
type SessionSummary struct {
	SessionID    string
	Title        string // 会话首条 run 的 query_text（展示截断由前端做）
	EntryAgent   string // 会话首条 run 的 entry_agent
	RunCount     int
	CreatedAt    time.Time // 首条 run 时间
	LastActiveAt time.Time // 最近一条 run 时间
}

// SessionRepository 是会话只读投影端口（与 RunRepository 分开：调用方只依赖读能力，
// 既有 RunRepository 的 fake 实现不受影响）。
type SessionRepository interface {
	ListSessions(ctx context.Context, ownerID string, limit int) ([]SessionSummary, error)
	ListRunsBySession(ctx context.Context, ownerID, sessionID string) ([]Run, error)
}

type pgSessionRepo struct{ pool *pgxpool.Pool }

// NewSessionRepository 返回基于 pgx 的 SessionRepository。
func NewSessionRepository(pool *pgxpool.Pool) SessionRepository { return &pgSessionRepo{pool: pool} }

func (r *pgSessionRepo) ListSessions(ctx context.Context, ownerID string, limit int) ([]SessionSummary, error) {
	if limit <= 0 {
		limit = defaultSessionLimit
	}
	if limit > maxSessionLimit {
		limit = maxSessionLimit
	}
	// title/entry_agent 取会话内 created_at 最早一行（run_id 决平局保证确定性）。
	rows, err := r.pool.Query(ctx, `
		SELECT session_id,
		       (array_agg(query_text  ORDER BY created_at ASC, run_id ASC))[1] AS title,
		       (array_agg(entry_agent ORDER BY created_at ASC, run_id ASC))[1] AS entry_agent,
		       count(*)::int   AS run_count,
		       min(created_at) AS created_at,
		       max(created_at) AS last_active_at
		  FROM runs
		 WHERE owner_id = $1
		 GROUP BY session_id
		 ORDER BY last_active_at DESC
		 LIMIT $2`, ownerID, limit)
	if err != nil {
		return nil, fmt.Errorf("store: list sessions: %w", err)
	}
	defer rows.Close()

	out := make([]SessionSummary, 0, limit)
	for rows.Next() {
		var s SessionSummary
		if err := rows.Scan(&s.SessionID, &s.Title, &s.EntryAgent, &s.RunCount, &s.CreatedAt, &s.LastActiveAt); err != nil {
			return nil, fmt.Errorf("store: scan session: %w", err)
		}
		out = append(out, s)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("store: list sessions rows: %w", err)
	}
	return out, nil
}

func (r *pgSessionRepo) ListRunsBySession(ctx context.Context, ownerID, sessionID string) ([]Run, error) {
	// owner 过滤写进 SQL：他人会话与不存在的会话同样返回空，上层统一 404，不泄露存在性。
	rows, err := r.pool.Query(ctx, `
		SELECT `+runColumns+`
		  FROM runs
		 WHERE owner_id = $1 AND session_id = $2
		 ORDER BY created_at ASC, run_id ASC`, ownerID, sessionID)
	if err != nil {
		return nil, fmt.Errorf("store: list runs by session: %w", err)
	}
	defer rows.Close()

	var out []Run
	for rows.Next() {
		run, err := scanRun(rows)
		if err != nil {
			return nil, fmt.Errorf("store: scan run: %w", err)
		}
		out = append(out, run)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("store: list runs by session rows: %w", err)
	}
	return out, nil
}
