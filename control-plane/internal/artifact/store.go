// Package artifact 提供产物对象的读取（MinIO 后端）。
// 产物由认知面工具产出并上传 MinIO；控制面通过 /artifacts/{key} 代理下载，
// 以便统一鉴权与稳定 URL（取舍见 docs/03：相对 presigned 更稳更安全）。
package artifact

import (
	"context"
	"errors"
	"fmt"
	"io"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

// ErrNotFound 表示对象不存在。
var ErrNotFound = errors.New("artifact: object not found")

// Object 是一个产物对象的可读流与元信息。
type Object struct {
	Body        io.ReadCloser
	ContentType string
	Size        int64
}

// Store 是产物读取端口（便于测试用假实现）。
type Store interface {
	Open(ctx context.Context, key string) (*Object, error)
	EnsureBucket(ctx context.Context) error
}

type minioStore struct {
	client *minio.Client
	bucket string
}

// NewMinioStore 构造 MinIO 后端的产物存储（minio.New 为惰性，不会立刻连接）。
func NewMinioStore(endpoint, accessKey, secretKey, bucket string, useSSL bool) (Store, error) {
	client, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: useSSL,
	})
	if err != nil {
		return nil, fmt.Errorf("artifact: new minio client: %w", err)
	}
	return &minioStore{client: client, bucket: bucket}, nil
}

func (s *minioStore) EnsureBucket(ctx context.Context) error {
	exists, err := s.client.BucketExists(ctx, s.bucket)
	if err != nil {
		return fmt.Errorf("artifact: bucket exists: %w", err)
	}
	if !exists {
		if err := s.client.MakeBucket(ctx, s.bucket, minio.MakeBucketOptions{}); err != nil {
			return fmt.Errorf("artifact: make bucket: %w", err)
		}
	}
	return nil
}

func (s *minioStore) Open(ctx context.Context, key string) (*Object, error) {
	obj, err := s.client.GetObject(ctx, s.bucket, key, minio.GetObjectOptions{})
	if err != nil {
		return nil, fmt.Errorf("artifact: get object: %w", err)
	}
	info, err := obj.Stat()
	if err != nil {
		_ = obj.Close()
		var resp minio.ErrorResponse
		if errors.As(err, &resp) && resp.Code == "NoSuchKey" {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("artifact: stat object: %w", err)
	}
	ct := info.ContentType
	if ct == "" {
		ct = "application/octet-stream"
	}
	return &Object{Body: obj, ContentType: ct, Size: info.Size}, nil
}
