package config

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type Config struct {
	ServerAddr       string
	AIServiceURL     string
	DataDir          string
	MaxBatchSize     int
	MaxUploadBytes   int64
	FrontendOrigin   string
	DatabaseDriver   string
	DatabaseDSN      string
	AdminTokenSecret string
}

func Load() Config {
	dataDir := env("DATA_DIR", "data")
	return Config{
		ServerAddr:       env("SERVER_ADDR", "127.0.0.1:8080"),
		AIServiceURL:     strings.TrimRight(env("AI_SERVICE_URL", "http://127.0.0.1:9000"), "/"),
		DataDir:          dataDir,
		MaxBatchSize:     envInt("MAX_BATCH_SIZE", 30),
		MaxUploadBytes:   int64(envInt("MAX_UPLOAD_MB", 30)) * 1024 * 1024,
		FrontendOrigin:   env("FRONTEND_ORIGIN", "http://127.0.0.1:3000"),
		DatabaseDriver:   strings.ToLower(env("DATABASE_DRIVER", "sqlite")),
		DatabaseDSN:      env("DATABASE_DSN", filepath.Join(dataDir, "cuckoo.db")),
		AdminTokenSecret: env("ADMIN_TOKEN_SECRET", "cuckoo-local-admin-secret"),
	}
}

func (c Config) UploadDir(jobID string) string {
	return filepath.Join(c.DataDir, "uploads", jobID)
}

func (c Config) OutputDir(jobID string) string {
	return filepath.Join(c.DataDir, "outputs", jobID)
}

func (c Config) PublicFileURL(jobID, filename string) string {
	return "/files/" + jobID + "/" + filename
}

func env(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func envInt(key string, fallback int) int {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value <= 0 {
		return fallback
	}
	return value
}
