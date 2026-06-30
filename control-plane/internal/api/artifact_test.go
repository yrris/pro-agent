package api_test

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"my-agent/control-plane/internal/api"
	"my-agent/control-plane/internal/artifact"
	"my-agent/control-plane/internal/store"
)

// 假 RunRepository（仅 GetRun 用于产物 ownership 校验）。
type fakeRuns struct{ runs map[string]store.Run }

func (f *fakeRuns) CreateRun(context.Context, store.CreateRunParams) error { return nil }
func (f *fakeRuns) FinishRun(context.Context, store.FinishRunParams) error { return nil }
func (f *fakeRuns) GetRun(_ context.Context, id string) (store.Run, error) {
	r, ok := f.runs[id]
	if !ok {
		return store.Run{}, store.ErrRunNotFound
	}
	return r, nil
}

type fakeArtifacts struct{ objs map[string][]byte }

func (f *fakeArtifacts) EnsureBucket(context.Context) error { return nil }
func (f *fakeArtifacts) Open(_ context.Context, key string) (*artifact.Object, error) {
	b, ok := f.objs[key]
	if !ok {
		return nil, artifact.ErrNotFound
	}
	return &artifact.Object{Body: io.NopCloser(bytes.NewReader(b)), ContentType: "text/markdown", Size: int64(len(b))}, nil
}

func TestArtifactProxy_Ownership(t *testing.T) {
	runs := &fakeRuns{runs: map[string]store.Run{"run1": {RunID: "run1", OwnerID: "u1"}}}
	arts := &fakeArtifacts{objs: map[string][]byte{"run1/tc1/report.md": []byte("# 报告\n14")}}
	router := api.NewRouter(nil, runs, nil, arts, time.Minute, discardLogger())

	do := func(path, user string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		req.Header.Set("X-User-Id", user)
		rec := httptest.NewRecorder()
		router.ServeHTTP(rec, req)
		return rec
	}

	if rec := do("/artifacts/run1/tc1/report.md", "u1"); rec.Code != http.StatusOK || rec.Body.String() != "# 报告\n14" {
		t.Fatalf("owner: expected 200+body, got %d %q", rec.Code, rec.Body.String())
	}
	if rec := do("/artifacts/run1/tc1/report.md", "intruder"); rec.Code != http.StatusForbidden {
		t.Fatalf("other owner: expected 403, got %d", rec.Code)
	}
	if rec := do("/artifacts/nope/x/y", "u1"); rec.Code != http.StatusNotFound {
		t.Fatalf("missing run: expected 404, got %d", rec.Code)
	}
	if rec := do("/artifacts/run1/tc1/missing.md", "u1"); rec.Code != http.StatusNotFound {
		t.Fatalf("missing object: expected 404, got %d", rec.Code)
	}
}
