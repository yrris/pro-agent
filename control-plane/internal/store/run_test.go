package store_test

import (
	"context"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"my-agent/control-plane/internal/store"
)

// mkRun 建一个 run 并把 created_at 精确改成给定时刻（微秒精度，供 keyset 页边界断言）。
func mkRun(t *testing.T, pool *pgxpool.Pool, runID, owner string, createdAt time.Time) {
	t.Helper()
	ctx := context.Background()
	runs := store.NewRunRepository(pool)
	if err := runs.CreateRun(ctx, store.CreateRunParams{
		RunID: runID, SessionID: "s-" + runID, OwnerID: owner, QueryText: "q", EntryAgent: "react",
	}); err != nil {
		t.Fatalf("CreateRun %s: %v", runID, err)
	}
	if _, err := pool.Exec(ctx, `UPDATE runs SET created_at = $1 WHERE run_id = $2`, createdAt, runID); err != nil {
		t.Fatalf("set created_at %s: %v", runID, err)
	}
}

func pagerOf(t *testing.T, pool *pgxpool.Pool) store.AllRunsPager {
	t.Helper()
	p, ok := store.NewRunRepository(pool).(store.AllRunsPager)
	if !ok {
		t.Fatal("pgRunRepo 应实现 AllRunsPager")
	}
	return p
}

// #10：同一 created_at 的多 run 在 keyset 页边界不得静默丢失。
// 旧实现 `WHERE created_at < before` 缺 run_id 平手项，第 2 页会把同时刻但 run_id 更小者整段排除。
// 复合游标 (created_at, run_id) < ($1, $2) 修复：第 2 页应精确接续、一条不丢。
func TestListAllRunsPagedTieBreaker(t *testing.T) {
	pool := testPool(t)
	ctx := context.Background()
	ts := time.Date(2026, 7, 5, 10, 0, 0, 0, time.UTC)
	// 三个 run 同一时刻；ORDER BY created_at DESC, run_id DESC → run-c, run-b, run-a。
	mkRun(t, pool, "run-a", "u1", ts)
	mkRun(t, pool, "run-b", "u2", ts)
	mkRun(t, pool, "run-c", "u1", ts)

	pager := pagerOf(t, pool)

	// 第 1 页（limit=2）：run-c, run-b。
	page1, err := pager.ListAllRunsPaged(ctx, 2, time.Time{}, "")
	if err != nil {
		t.Fatalf("page1: %v", err)
	}
	if got := runIDs(page1); len(got) != 2 || got[0] != "run-c" || got[1] != "run-b" {
		t.Fatalf("第 1 页应为 [run-c run-b]，得 %v", got)
	}

	// 第 2 页游标 = 上一页末项（run-b）的全精度 created_at + run_id。
	last := page1[len(page1)-1]
	page2, err := pager.ListAllRunsPaged(ctx, 2, last.CreatedAt, last.RunID)
	if err != nil {
		t.Fatalf("page2: %v", err)
	}
	if got := runIDs(page2); len(got) != 1 || got[0] != "run-a" {
		t.Fatalf("第 2 页应精确接续为 [run-a]（同时刻的 run-a 不丢），得 %v", got)
	}

	// 对照：旧 3 参 ListAllRuns（无 run_id tie-breaker）在同一时刻游标下会丢掉 run-a。
	lister := store.NewRunRepository(pool).(store.AllRunsLister)
	old, err := lister.ListAllRuns(ctx, 2, last.CreatedAt)
	if err != nil {
		t.Fatalf("old lister: %v", err)
	}
	if len(old) != 0 {
		t.Fatalf("对照：旧 created_at<before 在同时刻应丢掉 run-a（返回空），得 %v", runIDs(old))
	}
}

// #10：微秒精度 created_at 在同一毫秒内的多 run，用全精度复合游标不丢
// （admin.go 的毫秒截断是 API 层的另一半，本层保证收到全精度 before 时正确接续）。
func TestListAllRunsPagedSubMillisecond(t *testing.T) {
	pool := testPool(t)
	ctx := context.Background()
	base := time.Date(2026, 7, 5, 10, 0, 0, 0, time.UTC)
	// 同一毫秒内两条：hi=+600µs（较新）、lo=+100µs（较旧）。
	mkRun(t, pool, "run-lo", "u1", base.Add(100*time.Microsecond))
	mkRun(t, pool, "run-hi", "u1", base.Add(600*time.Microsecond))

	pager := pagerOf(t, pool)

	page1, err := pager.ListAllRunsPaged(ctx, 1, time.Time{}, "")
	if err != nil || len(page1) != 1 || page1[0].RunID != "run-hi" {
		t.Fatalf("第 1 页应为 [run-hi]，得 %v err=%v", runIDs(page1), err)
	}
	// 全精度游标续拉：同一毫秒内更旧的 run-lo 必须出现（不被亚毫秒截断吞掉）。
	last := page1[0]
	page2, err := pager.ListAllRunsPaged(ctx, 10, last.CreatedAt, last.RunID)
	if err != nil {
		t.Fatalf("page2: %v", err)
	}
	if got := runIDs(page2); len(got) != 1 || got[0] != "run-lo" {
		t.Fatalf("同毫秒内更旧的 run-lo 不应被丢，第 2 页应为 [run-lo]，得 %v", got)
	}
}
