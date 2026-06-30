package store

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// run 状态常量（与迁移里的 CHECK 一致）。
const (
	StatusRunning = "RUNNING"
	StatusSuccess = "SUCCESS"
	StatusFailed  = "FAILED"
	StatusStopped = "STOPPED"
	StatusTimeout = "TIMEOUT"
)

// ErrRunNotFound 表示按 runID 找不到 run。
var ErrRunNotFound = errors.New("store: run not found")

// Run 是 runs 表的一行。
type Run struct {
	RunID            string
	SessionID        string
	OwnerID          string
	EntryAgent       string
	QueryText        string
	Status           string
	FinalSummaryText *string
	ErrorMsg         *string
	CreatedAt        time.Time
	FinishedAt       *time.Time
}

// CreateRunParams 创建 run（状态默认 RUNNING）。
type CreateRunParams struct {
	RunID      string
	SessionID  string
	OwnerID    string
	EntryAgent string
	QueryText  string
}

// FinishRunParams 收口 run。FinalSummaryText/ErrorMsg 为空串时写入 NULL。
type FinishRunParams struct {
	RunID            string
	Status           string
	FinalSummaryText string
	ErrorMsg         string
}

// RunRepository 是 run 生命周期的写读端口。
type RunRepository interface {
	CreateRun(ctx context.Context, p CreateRunParams) error
	FinishRun(ctx context.Context, p FinishRunParams) error
	GetRun(ctx context.Context, runID string) (Run, error)
}

type pgRunRepo struct{ pool *pgxpool.Pool }

// NewRunRepository 返回基于 pgx 的 RunRepository。
func NewRunRepository(pool *pgxpool.Pool) RunRepository { return &pgRunRepo{pool: pool} }

func (r *pgRunRepo) CreateRun(ctx context.Context, p CreateRunParams) error {
	entryAgent := p.EntryAgent
	if entryAgent == "" {
		entryAgent = "react"
	}
	_, err := r.pool.Exec(ctx, `
		INSERT INTO runs (run_id, session_id, owner_id, entry_agent, query_text, status)
		VALUES ($1, $2, $3, $4, $5, 'RUNNING')`,
		p.RunID, p.SessionID, p.OwnerID, entryAgent, p.QueryText)
	if err != nil {
		return fmt.Errorf("store: create run: %w", err)
	}
	return nil
}

func (r *pgRunRepo) FinishRun(ctx context.Context, p FinishRunParams) error {
	tag, err := r.pool.Exec(ctx, `
		UPDATE runs
		   SET status = $2,
		       final_summary_text = NULLIF($3, ''),
		       error_msg = NULLIF($4, ''),
		       finished_at = now()
		 WHERE run_id = $1`,
		p.RunID, p.Status, p.FinalSummaryText, p.ErrorMsg)
	if err != nil {
		return fmt.Errorf("store: finish run: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrRunNotFound
	}
	return nil
}

func (r *pgRunRepo) GetRun(ctx context.Context, runID string) (Run, error) {
	var run Run
	err := r.pool.QueryRow(ctx, `
		SELECT run_id, session_id, owner_id, entry_agent, query_text, status,
		       final_summary_text, error_msg, created_at, finished_at
		  FROM runs WHERE run_id = $1`, runID).
		Scan(&run.RunID, &run.SessionID, &run.OwnerID, &run.EntryAgent, &run.QueryText, &run.Status,
			&run.FinalSummaryText, &run.ErrorMsg, &run.CreatedAt, &run.FinishedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Run{}, ErrRunNotFound
	}
	if err != nil {
		return Run{}, fmt.Errorf("store: get run: %w", err)
	}
	return run, nil
}
