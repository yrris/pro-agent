// Package cognition 是控制面到 Python 认知面的 gRPC 客户端。
// 它把 proto 流式响应解码为规范 event.Envelope，并把取消语义透传给 Python（取消图执行）。
package cognition

import (
	"context"
	"fmt"
	"io"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	"my-agent/control-plane/internal/event"
	agentv1 "my-agent/control-plane/internal/genproto/agent/v1"
)

// RunRequest 是发起一次认知 run 的入参。
type RunRequest struct {
	RunID     string
	SessionID string
	Query     string
	AgentType string
	MaxSteps  int32
}

// Stream 是一次 run 的事件流；Recv 在流结束时返回 io.EOF。
type Stream interface {
	Recv() (event.Envelope, error)
}

// Client 是认知面客户端。
type Client interface {
	RunAgent(ctx context.Context, req RunRequest) (Stream, error)
	Close() error
}

type grpcClient struct {
	conn *grpc.ClientConn
	svc  agentv1.CognitionServiceClient
}

// Dial 连接认知面（明文，内网服务）。
func Dial(addr string) (Client, error) {
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, fmt.Errorf("cognition: dial %s: %w", addr, err)
	}
	return &grpcClient{conn: conn, svc: agentv1.NewCognitionServiceClient(conn)}, nil
}

// NewClient 基于已有连接构造客户端（用于依赖注入/测试，如 bufconn）。
func NewClient(cc grpc.ClientConnInterface) Client {
	return &grpcClient{svc: agentv1.NewCognitionServiceClient(cc)}
}

func (c *grpcClient) RunAgent(ctx context.Context, req RunRequest) (Stream, error) {
	agentType := req.AgentType
	if agentType == "" {
		agentType = "react"
	}
	s, err := c.svc.Run(ctx, &agentv1.RunRequest{
		RunId:         req.RunID,
		SessionId:     req.SessionID,
		Query:         req.Query,
		AgentType:     agentType,
		MaxSteps:      req.MaxSteps,
		SchemaVersion: event.SchemaVersion,
	})
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
