package router

import (
	"net/http"

	"github.com/6602966029/cuckoo/backend/internal/config"
	"github.com/6602966029/cuckoo/backend/internal/handlers"
	"github.com/6602966029/cuckoo/backend/internal/repository"
	"github.com/gin-gonic/gin"
)

func New(cfg config.Config, repo *repository.Repository) *gin.Engine {
	r := gin.Default()
	r.Use(cors(cfg.FrontendOrigin))

	h := handlers.New(cfg, repo)
	r.GET("/health", h.Health)
	r.POST("/api/jobs", h.CreateJob)
	r.GET("/api/jobs/:jobID", h.GetJob)
	r.GET("/api/jobs/:jobID/download", h.DownloadJob)
	r.POST("/api/jobs/:jobID/export-folder", h.ExportJobToFolder)

	r.POST("/api/admin/login", h.AdminLogin)
	admin := r.Group("/api/admin")
	admin.Use(h.RequireAdmin())
	admin.GET("/users", h.ListAdminUsers)
	admin.POST("/users", h.CreateAdminUser)
	admin.PUT("/users/:userID", h.UpdateAdminUser)
	admin.DELETE("/users/:userID", h.DeleteAdminUser)
	admin.GET("/api-keys", h.ListAdminAPIKeys)

	r.Static("/files", cfg.DataDir+"/outputs")
	return r
}

func cors(origin string) gin.HandlerFunc {
	return func(c *gin.Context) {
		allowedOrigin := origin
		if allowedOrigin == "" {
			allowedOrigin = "*"
		}
		c.Header("Access-Control-Allow-Origin", allowedOrigin)
		c.Header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Content-Type,Authorization")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}
