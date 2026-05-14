package repository

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/6602966029/cuckoo/backend/internal/config"
	"github.com/6602966029/cuckoo/backend/internal/models"
	"github.com/glebarez/sqlite"
	"github.com/google/uuid"
	"golang.org/x/crypto/bcrypt"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

type Repository struct {
	db *gorm.DB
}

var ErrNoCancelableItem = errors.New("no queued or processing item")
var ErrItemNotProcessable = errors.New("job item is not processing")

func Open(cfg config.Config) (*Repository, error) {
	repo, err := openDatabase(cfg.DatabaseDriver, cfg.DatabaseDSN)
	if err == nil {
		return repo, nil
	}
	if !cfg.DatabaseFallback || cfg.DatabaseDriver == "sqlite" || cfg.DatabaseDriver == "" {
		return nil, err
	}

	fallbackDSN := filepath.Join(cfg.DataDir, "cuckoo.db")
	log.Printf("database %s unavailable, falling back to sqlite at %s: %v", cfg.DatabaseDriver, fallbackDSN, err)
	return openDatabase("sqlite", fallbackDSN)
}

func openDatabase(driver, dsn string) (*Repository, error) {
	var dialector gorm.Dialector
	switch driver {
	case "postgres", "postgresql":
		dialector = postgres.Open(dsn)
	case "sqlite", "":
		if err := os.MkdirAll(filepath.Dir(dsn), 0o755); err != nil {
			return nil, err
		}
		dialector = sqlite.Open(dsn)
	default:
		return nil, errors.New("unsupported DATABASE_DRIVER: " + driver)
	}

	db, err := gorm.Open(dialector, &gorm.Config{})
	if err != nil {
		return nil, err
	}
	if err := db.AutoMigrate(&models.Job{}, &models.JobItem{}, &models.JobResult{}, &models.User{}, &models.APIKeyRecord{}); err != nil {
		return nil, err
	}
	repo := &Repository{db: db}
	if err := repo.SeedAdminData(); err != nil {
		return nil, err
	}
	return repo, nil
}

func (r *Repository) CreateJob(job *models.Job) error {
	return r.db.Create(job).Error
}

func (r *Repository) CreateJobWithItems(job *models.Job, items *[]models.JobItem) error {
	return r.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(job).Error; err != nil {
			return err
		}
		if items != nil && len(*items) > 0 {
			if err := tx.Create(items).Error; err != nil {
				return err
			}
		}
		return nil
	})
}

func (r *Repository) GetJob(jobID string) (*models.Job, error) {
	var job models.Job
	if err := r.db.Preload("User").
		Preload("Results").
		Preload("Items", func(db *gorm.DB) *gorm.DB { return db.Order("item_index asc") }).
		First(&job, "id = ?", jobID).Error; err != nil {
		return nil, err
	}
	return &job, nil
}

func (r *Repository) ListJobs(userID string, limit int) ([]models.Job, error) {
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	query := r.db.Preload("User").
		Preload("Results").
		Preload("Items", func(db *gorm.DB) *gorm.DB { return db.Order("item_index asc") }).
		Order("created_at desc").
		Limit(limit)
	if strings.TrimSpace(userID) != "" {
		query = query.Where("user_id = ?", strings.TrimSpace(userID))
	}
	var jobs []models.Job
	err := query.Find(&jobs).Error
	return jobs, err
}

func (r *Repository) SetJobStatus(jobID, status, errorMessage string) error {
	updates := map[string]any{"status": status}
	if errorMessage != "" {
		updates["error_message"] = errorMessage
	}
	return r.db.Model(&models.Job{}).Where("id = ?", jobID).Updates(updates).Error
}

func (r *Repository) GetJobItem(itemID uint) (*models.JobItem, error) {
	var item models.JobItem
	if err := r.db.First(&item, "id = ?", itemID).Error; err != nil {
		return nil, err
	}
	return &item, nil
}

func (r *Repository) SetItemProcessing(itemID uint) (bool, error) {
	now := time.Now()
	result := r.db.Model(&models.JobItem{}).
		Where("id = ? AND status = ?", itemID, models.StatusQueued).
		Updates(map[string]any{
			"status":     models.StatusProcessing,
			"started_at": &now,
		})
	return result.RowsAffected == 1, result.Error
}

func (r *Repository) MarkItemFailed(jobID string, itemID uint, errorMessage string) error {
	now := time.Now()
	return r.db.Transaction(func(tx *gorm.DB) error {
		result := tx.Model(&models.JobItem{}).
			Where("id = ? AND status = ?", itemID, models.StatusProcessing).
			Updates(map[string]any{
				"status":        models.StatusFailed,
				"error_message": errorMessage,
				"finished_at":   &now,
			})
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return nil
		}
		return tx.Model(&models.Job{}).Where("id = ?", jobID).
			UpdateColumn("processed", gorm.Expr("processed + ?", 1)).Error
	})
}

func (r *Repository) AddResult(jobID string, itemID uint, result models.JobResult, sourceCharacters, translatedCharacters int) error {
	return r.db.Transaction(func(tx *gorm.DB) error {
		now := time.Now()
		itemUpdate := tx.Model(&models.JobItem{}).
			Where("id = ? AND status = ?", itemID, models.StatusProcessing).
			Updates(map[string]any{
				"status":      models.StatusCompleted,
				"finished_at": &now,
			})
		if itemUpdate.Error != nil {
			return itemUpdate.Error
		}
		if itemUpdate.RowsAffected == 0 {
			return ErrItemNotProcessable
		}
		if err := tx.Create(&result).Error; err != nil {
			return err
		}
		return tx.Model(&models.Job{}).Where("id = ?", jobID).
			Updates(map[string]any{
				"processed":             gorm.Expr("processed + ?", 1),
				"completed":             gorm.Expr("completed + ?", 1),
				"regions_detected":      gorm.Expr("regions_detected + ?", result.RegionsDetected),
				"regions_replaced":      gorm.Expr("regions_replaced + ?", result.RegionsReplaced),
				"source_characters":     gorm.Expr("source_characters + ?", sourceCharacters),
				"translated_characters": gorm.Expr("translated_characters + ?", translatedCharacters),
			}).Error
	})
}

func (r *Repository) CompleteJob(jobID string) error {
	return r.db.Model(&models.Job{}).Where("id = ?", jobID).Updates(map[string]any{
		"status":    models.StatusCompleted,
		"processed": gorm.Expr("total"),
		"completed": gorm.Expr("total"),
	}).Error
}

func (r *Repository) FinishJob(jobID, status, errorMessage string) error {
	updates := map[string]any{"status": status}
	if strings.TrimSpace(errorMessage) != "" {
		updates["error_message"] = errorMessage
	}
	return r.db.Model(&models.Job{}).Where("id = ?", jobID).Updates(updates).Error
}

func (r *Repository) CancelCurrentItem(jobID string) (*models.JobItem, error) {
	var item models.JobItem
	err := r.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Where("job_id = ? AND status IN ?", jobID, []string{models.StatusProcessing, models.StatusQueued}).
			Order("CASE WHEN status = 'processing' THEN 0 ELSE 1 END, item_index asc").
			First(&item).Error; err != nil {
			if errors.Is(err, gorm.ErrRecordNotFound) {
				return ErrNoCancelableItem
			}
			return err
		}
		now := time.Now()
		result := tx.Model(&models.JobItem{}).
			Where("id = ? AND status IN ?", item.ID, []string{models.StatusProcessing, models.StatusQueued}).
			Updates(map[string]any{
				"status":        models.StatusCanceled,
				"error_message": "用户取消当前图片",
				"finished_at":   &now,
			})
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return ErrNoCancelableItem
		}
		return tx.Model(&models.Job{}).Where("id = ?", jobID).
			UpdateColumn("processed", gorm.Expr("processed + ?", 1)).Error
	})
	if err != nil {
		return nil, err
	}
	item.Status = models.StatusCanceled
	return &item, nil
}

func (r *Repository) CancelJob(jobID string) error {
	return r.db.Transaction(func(tx *gorm.DB) error {
		var count int64
		if err := tx.Model(&models.JobItem{}).
			Where("job_id = ? AND status IN ?", jobID, []string{models.StatusQueued, models.StatusProcessing}).
			Count(&count).Error; err != nil {
			return err
		}
		now := time.Now()
		if count > 0 {
			if err := tx.Model(&models.JobItem{}).
				Where("job_id = ? AND status IN ?", jobID, []string{models.StatusQueued, models.StatusProcessing}).
				Updates(map[string]any{
					"status":        models.StatusCanceled,
					"error_message": "用户取消整批任务",
					"finished_at":   &now,
				}).Error; err != nil {
				return err
			}
		}
		updates := map[string]any{"status": models.StatusCanceled}
		if count > 0 {
			updates["processed"] = gorm.Expr("processed + ?", count)
		}
		return tx.Model(&models.Job{}).Where("id = ?", jobID).Updates(updates).Error
	})
}

func (r *Repository) JobStatus(jobID string) (string, error) {
	var job models.Job
	if err := r.db.Select("status").First(&job, "id = ?", jobID).Error; err != nil {
		return "", err
	}
	return job.Status, nil
}

func (r *Repository) FinalizeJobFromItems(jobID string) error {
	var items []models.JobItem
	if err := r.db.Where("job_id = ?", jobID).Find(&items).Error; err != nil {
		return err
	}
	if len(items) == 0 {
		return r.CompleteJob(jobID)
	}

	completed := 0
	failed := 0
	canceled := 0
	messages := make([]string, 0)
	for _, item := range items {
		switch item.Status {
		case models.StatusCompleted:
			completed++
		case models.StatusFailed:
			failed++
			if strings.TrimSpace(item.ErrorMessage) != "" {
				messages = append(messages, item.SourceFilename+": "+item.ErrorMessage)
			}
		case models.StatusCanceled:
			canceled++
		}
	}

	status := models.StatusCompleted
	errorMessage := ""
	switch {
	case canceled == len(items) && completed == 0 && failed == 0:
		status = models.StatusCanceled
		errorMessage = "任务已取消"
	case failed > 0 || canceled > 0:
		if completed > 0 {
			status = models.StatusPartial
		} else if failed > 0 {
			status = models.StatusFailed
		} else {
			status = models.StatusCanceled
		}
		errorMessage = strings.Join(messages, "; ")
		if canceled > 0 {
			if errorMessage != "" {
				errorMessage += "; "
			}
			errorMessage += "部分图片已取消"
		}
	default:
		status = models.StatusCompleted
	}

	return r.db.Model(&models.Job{}).Where("id = ?", jobID).Updates(map[string]any{
		"status":        status,
		"processed":     len(items),
		"completed":     completed,
		"error_message": errorMessage,
	}).Error
}

func (r *Repository) SeedAdminData() error {
	users := []struct {
		username    string
		displayName string
		email       string
		role        string
		password    string
	}{
		{"superadmin", "Cuckoo Super Admin", "superadmin@cuckoo.local", models.RoleSuperAdmin, "Cuckoo@2026!"},
		{"admin", "Cuckoo Admin", "admin@cuckoo.local", models.RoleAdmin, "Admin@2026!"},
		{"user", "Demo User", "user@cuckoo.local", models.RoleUser, "User@2026!"},
	}

	for _, item := range users {
		var count int64
		if err := r.db.Model(&models.User{}).Where("username = ?", item.username).Count(&count).Error; err != nil {
			return err
		}
		if count > 0 {
			continue
		}
		hash, err := HashPassword(item.password)
		if err != nil {
			return err
		}
		user := models.User{
			ID:           uuid.NewString(),
			Username:     item.username,
			DisplayName:  item.displayName,
			Email:        item.email,
			Role:         item.role,
			Status:       models.UserStatusActive,
			PasswordHash: hash,
		}
		if err := r.db.Create(&user).Error; err != nil {
			return err
		}
	}

	return r.seedDefaultAPIKeyRecord()
}

func (r *Repository) seedDefaultAPIKeyRecord() error {
	var admin models.User
	if err := r.db.First(&admin, "username = ?", "superadmin").Error; err != nil {
		return err
	}

	var count int64
	if err := r.db.Model(&models.APIKeyRecord{}).Where("user_id = ? AND provider = ? AND key_name = ?", admin.ID, "qwen-mt", "Qwen MT Plus").Count(&count).Error; err != nil {
		return err
	}
	if count > 0 {
		return nil
	}

	now := time.Now()
	record := models.APIKeyRecord{
		ID:              uuid.NewString(),
		UserID:          admin.ID,
		Provider:        "qwen-mt",
		KeyName:         "Qwen MT Plus",
		MaskedKey:       "sk-****d22a",
		KeyFingerprint:  fingerprint("qwen-mt-plus-local"),
		Status:          models.UserStatusActive,
		TotalRequests:   0,
		TotalCharacters: 0,
		LastUsedAt:      &now,
	}
	return r.db.Create(&record).Error
}

func (r *Repository) GetUserByUsername(username string) (*models.User, error) {
	var user models.User
	if err := r.db.First(&user, "username = ?", strings.TrimSpace(username)).Error; err != nil {
		return nil, err
	}
	return &user, nil
}

func (r *Repository) GetUser(userID string) (*models.User, error) {
	var user models.User
	if err := r.db.First(&user, "id = ?", userID).Error; err != nil {
		return nil, err
	}
	return &user, nil
}

func (r *Repository) ListUsers() ([]models.User, error) {
	var users []models.User
	err := r.db.Order("created_at asc").Find(&users).Error
	return users, err
}

func (r *Repository) ListUserUsage(userID string) ([]models.UserUsageResponse, error) {
	userID = strings.TrimSpace(userID)
	query := r.db.Table("users").
		Select(`
			users.id AS user_id,
			users.username,
			users.display_name,
			users.role,
			users.status,
			COUNT(jobs.id) AS jobs,
			COALESCE(SUM(jobs.total), 0) AS images,
			COALESCE(SUM(jobs.completed), 0) AS completed_images,
			COALESCE(SUM(jobs.regions_detected), 0) AS regions_detected,
			COALESCE(SUM(jobs.regions_replaced), 0) AS regions_replaced,
			COALESCE(SUM(jobs.source_characters), 0) AS source_characters,
			COALESCE(SUM(jobs.translated_characters), 0) AS translated_characters,
			MAX(jobs.updated_at) AS last_job_at`).
		Joins("LEFT JOIN jobs ON jobs.user_id = users.id").
		Group("users.id, users.username, users.display_name, users.role, users.status").
		Order("users.created_at asc")
	if userID != "" {
		query = query.Where("users.id = ?", userID)
	}
	var items []models.UserUsageResponse
	if err := query.Scan(&items).Error; err != nil {
		return nil, err
	}
	if userID != "" {
		return items, nil
	}

	var unassigned models.UserUsageResponse
	if err := r.db.Table("jobs").
		Select(`
			'' AS user_id,
			'未归属' AS username,
			'未归属任务' AS display_name,
			'legacy' AS role,
			'active' AS status,
			COUNT(id) AS jobs,
			COALESCE(SUM(total), 0) AS images,
			COALESCE(SUM(completed), 0) AS completed_images,
			COALESCE(SUM(regions_detected), 0) AS regions_detected,
			COALESCE(SUM(regions_replaced), 0) AS regions_replaced,
			COALESCE(SUM(source_characters), 0) AS source_characters,
			COALESCE(SUM(translated_characters), 0) AS translated_characters`).
		Where("user_id = '' OR user_id IS NULL").
		Scan(&unassigned).Error; err != nil {
		return nil, err
	}
	if unassigned.Jobs > 0 {
		var lastJob models.Job
		if err := r.db.Where("user_id = '' OR user_id IS NULL").Order("updated_at desc").First(&lastJob).Error; err == nil {
			lastJobAt := lastJob.UpdatedAt
			unassigned.LastJobAt = &lastJobAt
		}
		items = append(items, unassigned)
	}
	return items, nil
}

func (r *Repository) CreateUser(user *models.User) error {
	return r.db.Create(user).Error
}

func (r *Repository) UpdateUser(userID string, updates map[string]any) (*models.User, error) {
	if err := r.db.Model(&models.User{}).Where("id = ?", userID).Updates(updates).Error; err != nil {
		return nil, err
	}
	return r.GetUser(userID)
}

func (r *Repository) DeleteUser(userID string) error {
	return r.db.Delete(&models.User{}, "id = ?", userID).Error
}

func (r *Repository) CountSuperAdmins(exceptUserID string) (int64, error) {
	query := r.db.Model(&models.User{}).Where("role = ? AND status = ?", models.RoleSuperAdmin, models.UserStatusActive)
	if exceptUserID != "" {
		query = query.Where("id <> ?", exceptUserID)
	}
	var count int64
	err := query.Count(&count).Error
	return count, err
}

func (r *Repository) TouchLastLogin(userID string) error {
	now := time.Now()
	return r.db.Model(&models.User{}).Where("id = ?", userID).Update("last_login_at", &now).Error
}

func (r *Repository) ListAPIKeys(userID string) ([]models.APIKeyRecord, error) {
	query := r.db.Preload("User").Order("updated_at desc")
	if strings.TrimSpace(userID) != "" {
		query = query.Where("user_id = ?", strings.TrimSpace(userID))
	}
	var records []models.APIKeyRecord
	err := query.Find(&records).Error
	return records, err
}

func HashPassword(password string) (string, error) {
	raw, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	return string(raw), err
}

func CheckPassword(password, hash string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) == nil
}

func fingerprint(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])[:16]
}
