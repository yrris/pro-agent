// Package cognition 是控制面到 Python 认知面的 gRPC 客户端。
// 它把 proto 流式响应解码为规范 event.Envelope，并把取消语义透传给 Python（取消图执行）。
package cognition

import (
	"context"
	"fmt"
	"io"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/health/grpc_health_v1"

	"my-agent/control-plane/internal/event"
	agentv1 "my-agent/control-plane/internal/genproto/agent/v1"
)

// Attachment 是已上传附件的引用（归属校验在 api 层完成）。
type Attachment struct {
	ResourceKey string
	FileName    string
	MimeType    string
	Size        int64
}

// RunRequest 是发起一次认知 run 的入参。
type RunRequest struct {
	RunID        string
	SessionID    string
	Query        string
	AgentType    string
	MaxSteps     int32
	OwnerID      string // 经 proto metadata["owner_id"] 传认知面（owner 级知识库归属）
	OutputFormat string // M9：经 metadata["output_format"] 传认知面（html/docs/ppt/table，空=不注入）
	ImageGen     bool   // 生图开关：经 metadata["image_gen"]="1" 传认知面（false=不注入）
	// M11 HITL 审批恢复（经 metadata 三键传认知面；认知面据此走 Command(resume) 分支）。
	ApprovalResumeID string
	ApprovalDecision string
	ApprovalComment  string
	// docs/14 会话分叉（经 metadata 两键传认知面，零 proto 改动——循审批三键先例）：
	// 认知面用 fork_from_run_id 在父 thread 的 checkpoint 历史中定位"该轮结束时"的
	// 快照，把 messages 通道播种进新 thread（本请求的 SessionID）。
	ForkFromSessionID string
	ForkFromRunID     string
	Attachments       []Attachment
}

// Stream 是一次 run 的事件流；Recv 在流结束时返回 io.EOF。
type Stream interface {
	Recv() (event.Envelope, error)
}

// Client 是认知面客户端。
type Client interface {
	RunAgent(ctx context.Context, req RunRequest) (Stream, error)
	// IngestDocument：Files 面板"上传即入库"（UX-1）。入库必须走认知面
	//（embedding/分块是认知域能力）；ok=false 时 message 携带原因（非文本类等）。
	IngestDocument(ctx context.Context, ownerID string, att Attachment) (ok bool, kbID, message string, err error)
	// HealthCheck 探认知面「业务就绪」（标准 grpc.health.v1，非仅通道连通）。
	HealthCheck(ctx context.Context) error
	Close() error
}

type grpcClient struct {
	conn *grpc.ClientConn
	cc   grpc.ClientConnInterface // 供 health client 复用（Dial 与 NewClient 两条路径都填）
	svc  agentv1.CognitionServiceClient
}

// Dial 连接认知面（明文，内网服务）。
func Dial(addr string) (Client, error) {
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, fmt.Errorf("cognition: dial %s: %w", addr, err)
	}
	return &grpcClient{conn: conn, cc: conn, svc: agentv1.NewCognitionServiceClient(conn)}, nil
}

// NewClient 基于已有连接构造客户端（用于依赖注入/测试，如 bufconn）。
func NewClient(cc grpc.ClientConnInterface) Client {
	return &grpcClient{cc: cc, svc: agentv1.NewCognitionServiceClient(cc)}
}

func (c *grpcClient) HealthCheck(ctx context.Context) error {
	resp, err := grpc_health_v1.NewHealthClient(c.cc).Check(ctx, &grpc_health_v1.HealthCheckRequest{Service: ""})
	if err != nil {
		return fmt.Errorf("cognition: health check: %w", err)
	}
	if resp.GetStatus() != grpc_health_v1.HealthCheckResponse_SERVING {
		return fmt.Errorf("cognition: not serving (status=%s)", resp.GetStatus())
	}
	return nil
}

func (c *grpcClient) IngestDocument(ctx context.Context, ownerID string, att Attachment) (bool, string, string, error) {
	resp, err := c.svc.IngestDocument(ctx, &agentv1.IngestDocumentRequest{
		OwnerId: ownerID,
		Attachment: &agentv1.Attachment{
			ResourceKey: att.ResourceKey, FileName: att.FileName, MimeType: att.MimeType, Size: att.Size,
		},
	}, grpc.WaitForReady(true))
	if err != nil {
		return false, "", "", err
	}
	return resp.GetOk(), resp.GetKbId(), resp.GetMessage(), nil
}

func (c *grpcClient) RunAgent(ctx context.Context, req RunRequest) (Stream, error) {
	agentType := req.AgentType
	if agentType == "" {
		agentType = "react"
	}
	// metadata：先建 map 再条件填（owner_id / output_format），全空则保持 nil。
	metadata := map[string]string{}
	if req.OwnerID != "" {
		metadata["owner_id"] = req.OwnerID
	}
	if req.OutputFormat != "" {
		metadata["output_format"] = req.OutputFormat
	}
	if req.ImageGen {
		metadata["image_gen"] = "1"
	}
	if req.ApprovalResumeID != "" {
		metadata["approval_resume_id"] = req.ApprovalResumeID
		metadata["approval_decision"] = req.ApprovalDecision
		metadata["approval_comment"] = req.ApprovalComment
	}
	if req.ForkFromSessionID != "" {
		metadata["fork_from_session_id"] = req.ForkFromSessionID
		metadata["fork_from_run_id"] = req.ForkFromRunID
	}
	if len(metadata) == 0 {
		metadata = nil
	}
	atts := make([]*agentv1.Attachment, 0, len(req.Attachments))
	for _, a := range req.Attachments {
		atts = append(atts, &agentv1.Attachment{
			ResourceKey: a.ResourceKey, FileName: a.FileName, MimeType: a.MimeType, Size: a.Size,
		})
	}
	s, err := c.svc.Run(ctx, &agentv1.RunRequest{
		RunId:         req.RunID,
		SessionId:     req.SessionID,
		Query:         req.Query,
		AgentType:     agentType,
		MaxSteps:      req.MaxSteps,
		Metadata:      metadata,
		SchemaVersion: event.SchemaVersion,
		Attachments:   atts,
	}, grpc.WaitForReady(true)) // 容忍认知面短暂未就绪/重连，在 run 超时内等待
	if err != nil {
		return nil, fmt.Errorf("cognition: open run stream: %w", err)
	}
	return &grpcStream{s: s}, nil
}

func (c *grpcClient) Close() error {
	if c.conn != nil {
		return c.conn.Close()
	}
	return nil
}

type grpcStream struct {
	s grpc.ServerStreamingClient[agentv1.Event]
}

func (g *grpcStream) Recv() (event.Envelope, error) {
	p, err := g.s.Recv()
	if err == io.EOF {
		return event.Envelope{}, io.EOF
	}
	if err != nil {
		return event.Envelope{}, err
	}
	return event.FromProto(p)
}
