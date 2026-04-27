package repository

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
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
	if err := db.AutoMigrate(&models.Job{}, &models.JobResult{}, &models.User{}, &models.APIKeyRecord{}); err != nil {
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
