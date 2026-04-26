package repository

import (
	"errors"
	"os"
	"path/filepath"

	"github.com/6602966029/cuckoo/backend/internal/config"
	"github.com/6602966029/cuckoo/backend/internal/models"
	"github.com/glebarez/sqlite"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

type Repository struct {
	db *gorm.DB
}

func Open(cfg config.Config) (*Repository, error) {
	var dialector gorm.Dialector
	switch cfg.DatabaseDriver {
	case "postgres", "postgresql":
		dialector = postgres.Open(cfg.DatabaseDSN)
	case "sqlite", "":
		if err := os.MkdirAll(filepath.Dir(cfg.DatabaseDSN), 0o755); err != nil {
			return nil, err
		}
		dialector = sqlite.Open(cfg.DatabaseDSN)
	default:
		return nil, errors.New("unsupported DATABASE_DRIVER: " + cfg.DatabaseDriver)
	}

	db, err := gorm.Open(dialector, &gorm.Config{})
	if err != nil {
		return nil, err
	}
	if err := db.AutoMigrate(&models.Job{}, &models.JobResult{}); err != nil {
		return nil, err
	}
	return &Repository{db: db}, nil
}

func (r *Repository) CreateJob(job *models.Job) error {
	return r.db.Create(job).Error
}

func (r *Repository) GetJob(jobID string) (*models.Job, error) {
	var job models.Job
	if err := r.db.Preload("Results").First(&job, "id = ?", jobID).Error; err != nil {
		return nil, err
	}
	return &job, nil
}

func (r *Repository) SetJobStatus(jobID, status, errorMessage string) error {
	updates := map[string]any{"status": status}
	if errorMessage != "" {
		updates["error_message"] = errorMessage
	}
	return r.db.Model(&models.Job{}).Where("id = ?", jobID).Updates(updates).Error
}

func (r *Repository) AddResult(jobID string, result models.JobResult) error {
	return r.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&result).Error; err != nil {
			return err
		}
		return tx.Model(&models.Job{}).Where("id = ?", jobID).
			UpdateColumn("completed", gorm.Expr("completed + ?", 1)).Error
	})
}

func (r *Repository) CompleteJob(jobID string) error {
	return r.db.Model(&models.Job{}).Where("id = ?", jobID).Updates(map[string]any{
		"status":    models.StatusCompleted,
		"completed": gorm.Expr("total"),
	}).Error
}
