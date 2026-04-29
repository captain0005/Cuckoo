package config

import (
	"net"
	"net/url"
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
	databaseDriver, databaseDSN := databaseConfig(dataDir)
	return Config{
		ServerAddr:       serverAddr(),
		AIServiceURL:     strings.TrimRight(env("AI_SERVICE_URL", "http://127.0.0.1:9000"), "/"),
		DataDir:          dataDir,
		MaxBatchSize:     envInt("MAX_BATCH_SIZE", 30),
		MaxUploadBytes:   int64(envInt("MAX_UPLOAD_MB", 30)) * 1024 * 1024,
		FrontendOrigin:   env("FRONTEND_ORIGINS", env("FRONTEND_ORIGIN", "http://127.0.0.1:3000")),
		DatabaseDriver:   databaseDriver,
		DatabaseDSN:      databaseDSN,
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

func serverAddr() string {
	if port := strings.TrimSpace(os.Getenv("BACKEND_PORT")); port != "" {
		return "0.0.0.0:" + port
	}
	if value := strings.TrimSpace(os.Getenv("SERVER_ADDR")); value != "" {
		return value
	}
	if port := strings.TrimSpace(os.Getenv("PORT")); port != "" {
		return "0.0.0.0:" + port
	}
	return "127.0.0.1:8080"
}

func databaseConfig(dataDir string) (string, string) {
	driver := strings.ToLower(strings.TrimSpace(os.Getenv("DATABASE_DRIVER")))
	dsn := strings.TrimSpace(os.Getenv("DATABASE_DSN"))
	if dsn == "" {
		dsn = supabasePostgresDSN()
	}
	if dsn == "" {
		dsn = filepath.Join(dataDir, "cuckoo.db")
	}
	if driver == "" {
		driver = inferDatabaseDriver(dsn)
	}
	return driver, dsn
}

func supabasePostgresDSN() string {
	projectRef := strings.TrimSpace(os.Getenv("SUPABASE_PROJECT_REF"))
	password := strings.TrimSpace(os.Getenv("SUPABASE_DB_PASSWORD"))
	if projectRef == "" || password == "" {
		return ""
	}

	user := env("SUPABASE_DB_USER", "postgres")
	database := env("SUPABASE_DB_NAME", "postgres")
	host := env("SUPABASE_DB_HOST", "db."+projectRef+".supabase.co")
	port := env("SUPABASE_DB_PORT", "5432")
	sslMode := env("SUPABASE_DB_SSLMODE", "require")

	// Resolve host to IPv4 to avoid IPv6 connectivity issues in environments
	// that do not support outbound IPv6 (e.g., Railway).
	if resolved := resolveIPv4(host); resolved != "" {
		host = resolved
	}

	connectionURL := url.URL{
		Scheme: "postgres",
		User:   url.UserPassword(user, password),
		Host:   net.JoinHostPort(host, port),
		Path:   database,
	}
	query := connectionURL.Query()
	query.Set("sslmode", sslMode)
	connectionURL.RawQuery = query.Encode()
	return connectionURL.String()
}

func resolveIPv4(host string) string {
	ips, err := net.LookupIP(host)
	if err != nil {
		return ""
	}
	for _, ip := range ips {
		if ipv4 := ip.To4(); ipv4 != nil {
			return ipv4.String()
		}
	}
	return ""
}

func inferDatabaseDriver(dsn string) string {
	lower := strings.ToLower(strings.TrimSpace(dsn))
	if strings.HasPrefix(lower, "postgres://") || strings.HasPrefix(lower, "postgresql://") {
		return "postgres"
	}
	return "sqlite"
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
