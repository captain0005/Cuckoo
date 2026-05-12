package router

import (
	"net/http"
	"net/url"
	"strings"

	"github.com/6602966029/cuckoo/backend/internal/config"
	"github.com/6602966029/cuckoo/backend/internal/handlers"
	"github.com/6602966029/cuckoo/backend/internal/repository"
	"github.com/gin-gonic/gin"
)

func New(cfg config.Config, repo *repository.Repository) *gin.Engine {
	r := gin.Default()
	r.Use(cors(cfg.FrontendOrigin))

	h := handlers.New(cfg, repo)
	r.GET("/", h.Health)
	r.GET("/health", h.Health)

	r.POST("/api/auth/login", h.UserLogin)
	auth := r.Group("/api")
	auth.Use(h.RequireUser())
	auth.GET("/me", h.CurrentUser)
	auth.GET("/jobs", h.ListJobs)
	auth.POST("/jobs", h.CreateJob)
	auth.GET("/jobs/:jobID", h.GetJob)
	auth.GET("/jobs/:jobID/download", h.DownloadJob)
	auth.POST("/jobs/:jobID/export-folder", h.ExportJobToFolder)

	r.POST("/api/admin/login", h.AdminLogin)
	admin := r.Group("/api/admin")
	admin.Use(h.RequireAdmin())
	admin.GET("/users", h.ListAdminUsers)
	admin.POST("/users", h.CreateAdminUser)
	admin.PUT("/users/:userID", h.UpdateAdminUser)
	admin.DELETE("/users/:userID", h.DeleteAdminUser)
	admin.GET("/api-keys", h.ListAdminAPIKeys)
	admin.GET("/usage", h.ListAdminUsage)
	admin.GET("/jobs", h.ListAdminJobs)

	r.Static("/files", cfg.DataDir+"/outputs")
	return r
}

func cors(origin string) gin.HandlerFunc {
	allowedOrigins := parseAllowedOrigins(origin)
	return func(c *gin.Context) {
		requestOrigin := c.GetHeader("Origin")
		allowedOrigin := allowedOriginForRequest(requestOrigin, allowedOrigins)
		if allowedOrigin != "" {
			c.Header("Access-Control-Allow-Origin", allowedOrigin)
		}
		c.Header("Vary", "Origin")
		c.Header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Content-Type,Authorization")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}

func parseAllowedOrigins(origin string) []string {
	const productionFrontendOrigin = "https://cuckoo-black.vercel.app"

	parts := strings.Split(origin, ",")
	origins := make([]string, 0, len(parts))
	for _, part := range parts {
		trimmed := strings.TrimSpace(part)
		if trimmed != "" {
			origins = appendUniqueOrigin(origins, trimmed)
		}
	}
	origins = appendUniqueOrigin(origins, productionFrontendOrigin)
	if len(origins) == 0 {
		return []string{"*"}
	}
	return origins
}

func appendUniqueOrigin(origins []string, origin string) []string {
	for _, existing := range origins {
		if strings.EqualFold(existing, origin) {
			return origins
		}
	}
	return append(origins, origin)
}

func allowedOriginForRequest(requestOrigin string, allowedOrigins []string) string {
	if isCuckooVercelOrigin(requestOrigin) {
		return requestOrigin
	}
	for _, allowedOrigin := range allowedOrigins {
		if allowedOrigin == "*" {
			return "*"
		}
		if requestOrigin != "" && strings.EqualFold(requestOrigin, allowedOrigin) {
			return requestOrigin
		}
	}
	if requestOrigin == "" && len(allowedOrigins) == 1 {
		return allowedOrigins[0]
	}
	return ""
}

func isCuckooVercelOrigin(requestOrigin string) bool {
	if strings.TrimSpace(requestOrigin) == "" {
		return false
	}
	parsed, err := url.Parse(requestOrigin)
	if err != nil {
		return false
	}
	if parsed.Scheme != "https" {
		return false
	}
	host := strings.ToLower(parsed.Hostname())
	return host == "cuckoo-black.vercel.app" ||
		(strings.HasPrefix(host, "cuckoo-") && strings.HasSuffix(host, ".vercel.app"))
}
