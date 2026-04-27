package handlers

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/6602966029/cuckoo/backend/internal/models"
	"github.com/6602966029/cuckoo/backend/internal/repository"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

type adminClaims struct {
	UserID string `json:"sub"`
	Role   string `json:"role"`
	Exp    int64  `json:"exp"`
}

type loginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type userRequest struct {
	Username    string `json:"username"`
	DisplayName string `json:"display_name"`
	Email       string `json:"email"`
	Role        string `json:"role"`
	Status      string `json:"status"`
	Password    string `json:"password"`
}

func (h *Handler) AdminLogin(c *gin.Context) {
	var req loginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "invalid login payload"})
		return
	}

	user, err := h.repo.GetUserByUsername(req.Username)
	if err != nil || user.Status != models.UserStatusActive || !repository.CheckPassword(req.Password, user.PasswordHash) {
		c.JSON(http.StatusUnauthorized, gin.H{"detail": "invalid username or password"})
		return
	}
	if !isAdminRole(user.Role) {
		c.JSON(http.StatusForbidden, gin.H{"detail": "admin privileges required"})
		return
	}

	if err := h.repo.TouchLastLogin(user.ID); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	user.LastLoginAt = ptrTime(time.Now())

	token, err := h.signAdminToken(adminClaims{
		UserID: user.ID,
		Role:   user.Role,
		Exp:    time.Now().Add(12 * time.Hour).Unix(),
	})
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"token": token,
		"user":  user.ToResponse(),
	})
}

func (h *Handler) RequireAdmin() gin.HandlerFunc {
	return func(c *gin.Context) {
		token := strings.TrimSpace(strings.TrimPrefix(c.GetHeader("Authorization"), "Bearer "))
		claims, err := h.verifyAdminToken(token)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "admin login required"})
			return
		}
		if !isAdminRole(claims.Role) {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"detail": "admin privileges required"})
			return
		}
		user, err := h.repo.GetUser(claims.UserID)
		if err != nil || user.Status != models.UserStatusActive || !isAdminRole(user.Role) {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"detail": "admin login required"})
			return
		}
		c.Set("admin_user", user)
		c.Next()
	}
}

func (h *Handler) ListAdminUsers(c *gin.Context) {
	users, err := h.repo.ListUsers()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	items := make([]models.UserResponse, 0, len(users))
	for _, user := range users {
		items = append(items, user.ToResponse())
	}
	c.JSON(http.StatusOK, gin.H{"users": items})
}

func (h *Handler) CreateAdminUser(c *gin.Context) {
	var req userRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "invalid user payload"})
		return
	}
	if err := validateUserRequest(req, true); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}

	hash, err := repository.HashPassword(req.Password)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	user := &models.User{
		ID:           uuid.NewString(),
		Username:     strings.TrimSpace(req.Username),
		DisplayName:  strings.TrimSpace(req.DisplayName),
		Email:        strings.TrimSpace(req.Email),
		Role:         normalizedRole(req.Role),
		Status:       normalizedStatus(req.Status),
		PasswordHash: hash,
	}
	if err := h.repo.CreateUser(user); err != nil {
		c.JSON(http.StatusConflict, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"user": user.ToResponse()})
}

func (h *Handler) UpdateAdminUser(c *gin.Context) {
	userID := c.Param("userID")
	existing, err := h.repo.GetUser(userID)
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"detail": "user not found"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	var req userRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "invalid user payload"})
		return
	}
	if err := validateUserRequest(req, false); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}

	nextRole := normalizedRole(req.Role)
	nextStatus := normalizedStatus(req.Status)
	if existing.Role == models.RoleSuperAdmin && (nextRole != models.RoleSuperAdmin || nextStatus != models.UserStatusActive) {
		count, err := h.repo.CountSuperAdmins(existing.ID)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
			return
		}
		if count == 0 {
			c.JSON(http.StatusBadRequest, gin.H{"detail": "at least one active super admin is required"})
			return
		}
	}

	updates := map[string]any{
		"username":     strings.TrimSpace(req.Username),
		"display_name": strings.TrimSpace(req.DisplayName),
		"email":        strings.TrimSpace(req.Email),
		"role":         nextRole,
		"status":       nextStatus,
	}
	if strings.TrimSpace(req.Password) != "" {
		hash, err := repository.HashPassword(req.Password)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
			return
		}
		updates["password_hash"] = hash
	}

	user, err := h.repo.UpdateUser(userID, updates)
	if err != nil {
		c.JSON(http.StatusConflict, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"user": user.ToResponse()})
}

func (h *Handler) DeleteAdminUser(c *gin.Context) {
	userID := c.Param("userID")
	user, err := h.repo.GetUser(userID)
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"detail": "user not found"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	if user.Role == models.RoleSuperAdmin {
		count, err := h.repo.CountSuperAdmins(user.ID)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
			return
		}
		if count == 0 {
			c.JSON(http.StatusBadRequest, gin.H{"detail": "at least one active super admin is required"})
			return
		}
	}
	if err := h.repo.DeleteUser(user.ID); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.Status(http.StatusNoContent)
}

func (h *Handler) ListAdminAPIKeys(c *gin.Context) {
	records, err := h.repo.ListAPIKeys(c.Query("user_id"))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	items := make([]models.APIKeyRecordResponse, 0, len(records))
	for _, record := range records {
		items = append(items, record.ToResponse())
	}
	c.JSON(http.StatusOK, gin.H{"api_keys": items})
}

func validateUserRequest(req userRequest, requirePassword bool) error {
	if strings.TrimSpace(req.Username) == "" {
		return errors.New("username is required")
	}
	if strings.TrimSpace(req.Email) == "" {
		return errors.New("email is required")
	}
	if !validRole(normalizedRole(req.Role)) {
		return errors.New("role must be super_admin, admin, or user")
	}
	if !validStatus(normalizedStatus(req.Status)) {
		return errors.New("status must be active or disabled")
	}
	if requirePassword && len(req.Password) < 8 {
		return errors.New("password must be at least 8 characters")
	}
	if strings.TrimSpace(req.Password) != "" && len(req.Password) < 8 {
		return errors.New("password must be at least 8 characters")
	}
	return nil
}

func (h *Handler) signAdminToken(claims adminClaims) (string, error) {
	payload, err := json.Marshal(claims)
	if err != nil {
		return "", err
	}
	encodedPayload := base64.RawURLEncoding.EncodeToString(payload)
	signature := h.signTokenPayload(encodedPayload)
	return encodedPayload + "." + signature, nil
}

func (h *Handler) verifyAdminToken(token string) (adminClaims, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return adminClaims{}, errors.New("invalid token")
	}
	expected := h.signTokenPayload(parts[0])
	if !hmac.Equal([]byte(expected), []byte(parts[1])) {
		return adminClaims{}, errors.New("invalid token signature")
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return adminClaims{}, err
	}
	var claims adminClaims
	if err := json.Unmarshal(raw, &claims); err != nil {
		return adminClaims{}, err
	}
	if claims.Exp < time.Now().Unix() {
		return adminClaims{}, errors.New("token expired")
	}
	return claims, nil
}

func (h *Handler) signTokenPayload(payload string) string {
	mac := hmac.New(sha256.New, []byte(h.cfg.AdminTokenSecret))
	mac.Write([]byte(payload))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

func normalizedRole(role string) string {
	role = strings.TrimSpace(role)
	if role == "" {
		return models.RoleUser
	}
	return role
}

func normalizedStatus(status string) string {
	status = strings.TrimSpace(status)
	if status == "" {
		return models.UserStatusActive
	}
	return status
}

func validRole(role string) bool {
	return role == models.RoleSuperAdmin || role == models.RoleAdmin || role == models.RoleUser
}

func validStatus(status string) bool {
	return status == models.UserStatusActive || status == models.UserStatusDisabled
}

func isAdminRole(role string) bool {
	return role == models.RoleSuperAdmin || role == models.RoleAdmin
}

func ptrTime(value time.Time) *time.Time {
	return &value
}
