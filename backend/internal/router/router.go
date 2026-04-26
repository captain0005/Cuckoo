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
		c.Header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Content-Type,Authorization")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}
