package handlers

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/6602966029/cuckoo/backend/internal/config"
	"github.com/6602966029/cuckoo/backend/internal/models"
	"github.com/6602966029/cuckoo/backend/internal/repository"
	"github.com/6602966029/cuckoo/backend/internal/services"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

type Handler struct {
	cfg      config.Config
	repo     *repository.Repository
	aiClient *services.AIClient
}

type uploadedImage struct {
	SourceFilename string
	InputPath      string
	OutputPath     string
	OutputFilename string
	ManualRegions  []services.ManualRegion
}

type exportFolderRequest struct {
	Directory string `json:"directory"`
	Overwrite bool   `json:"overwrite"`
}

type exportFolderResponse struct {
	Directory     string   `json:"directory"`
	ExportedCount int      `json:"exported_count"`
	Files         []string `json:"files"`
}

func New(cfg config.Config, repo *repository.Repository) *Handler {
	return &Handler{
		cfg:      cfg,
		repo:     repo,
		aiClient: services.NewAIClient(cfg.AIServiceURL),
	}
}

func (h *Handler) Health(c *gin.Context) {
	aiStatus, aiDetail := h.aiHealth()
	payload := gin.H{
		"status":     "ok",
		"service":    "backend",
		"ai_service": h.cfg.AIServiceURL,
		"ai_status":  aiStatus,
	}
	if aiDetail != "" {
		payload["ai_error"] = aiDetail
	}
	c.JSON(http.StatusOK, payload)
}

func (h *Handler) aiHealth() (string, string) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, h.cfg.AIServiceURL+"/health", nil)
	if err != nil {
		return "invalid", err.Error()
	}
	resp, err := (&http.Client{Timeout: 2 * time.Second}).Do(req)
	if err != nil {
		return "unreachable", err.Error()
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "unhealthy", resp.Status
	}
	return "ok", ""
}

func (h *Handler) CreateJob(c *gin.Context) {
	user, ok := currentUser(c)
	if !ok {
		c.JSON(http.StatusUnauthorized, gin.H{"detail": "login required"})
		return
	}

	form, err := c.MultipartForm()
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "multipart form is required"})
		return
	}
	files := form.File["files"]
	if len(files) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "at least one image is required"})
		return
	}
	if len(files) > h.cfg.MaxBatchSize {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "batch size exceeds limit"})
		return
	}

	sourceLanguage := firstFormValue(form.Value, "source_language", "zh")
	targetLanguage := firstFormValue(form.Value, "target_language", "en")
	inpaintEngine := firstFormValue(form.Value, "inpaint_engine", "lama")
	manualRegions, err := parseManualRegionsPayload(firstFormValue(form.Value, "manual_regions", ""))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	jobID := uuid.NewString()

	uploads, err := h.saveUploads(c, jobID, files, manualRegions)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}

	job := &models.Job{
		ID:             jobID,
		UserID:         user.ID,
		Status:         models.StatusQueued,
		SourceLanguage: sourceLanguage,
		TargetLanguage: targetLanguage,
		Total:          len(uploads),
		Completed:      0,
	}
	if err := h.repo.CreateJob(job); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	go h.processJob(context.Background(), jobID, sourceLanguage, targetLanguage, inpaintEngine, uploads)
	job.User = *user
	c.JSON(http.StatusAccepted, h.toJobResponse(job))
}

func (h *Handler) ListJobs(c *gin.Context) {
	user, ok := currentUser(c)
	if !ok {
		c.JSON(http.StatusUnauthorized, gin.H{"detail": "login required"})
		return
	}
	jobs, err := h.repo.ListJobs(user.ID, queryInt(c, "limit", 50))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	items := make([]models.JobResponse, 0, len(jobs))
	for _, job := range jobs {
		items = append(items, h.toJobResponse(&job))
	}
	c.JSON(http.StatusOK, gin.H{"jobs": items})
}

func (h *Handler) GetJob(c *gin.Context) {
	job, err := h.repo.GetJob(c.Param("jobID"))
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"detail": "job not found"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	if !h.canAccessJob(c, job) {
		c.JSON(http.StatusForbidden, gin.H{"detail": "job access denied"})
		return
	}
	c.JSON(http.StatusOK, h.toJobResponse(job))
}

func (h *Handler) DownloadJob(c *gin.Context) {
	jobID := c.Param("jobID")
	job, err := h.repo.GetJob(jobID)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "job not found"})
		return
	}
	if !h.canAccessJob(c, job) {
		c.JSON(http.StatusForbidden, gin.H{"detail": "job access denied"})
		return
	}
	if job.Status != models.StatusCompleted && job.Status != models.StatusPartial {
		c.JSON(http.StatusConflict, gin.H{"detail": "job is not completed yet"})
		return
	}

	zipPath := filepath.Join(h.cfg.DataDir, "archives", jobID+".zip")
	if err := services.BuildZip(h.cfg.OutputDir(jobID), zipPath); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.FileAttachment(zipPath, "cuckoo-"+jobID+".zip")
}

func (h *Handler) ExportJobToFolder(c *gin.Context) {
	jobID := c.Param("jobID")
	job, err := h.repo.GetJob(jobID)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "job not found"})
		return
	}
	if !h.canAccessJob(c, job) {
		c.JSON(http.StatusForbidden, gin.H{"detail": "job access denied"})
		return
	}
	if job.Status != models.StatusCompleted && job.Status != models.StatusPartial {
		c.JSON(http.StatusConflict, gin.H{"detail": "job is not completed yet"})
		return
	}

	var req exportFolderRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "invalid export payload"})
		return
	}
	destination := strings.TrimSpace(req.Directory)
	if destination == "" {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "export directory is required"})
		return
	}
	absoluteDestination, err := filepath.Abs(destination)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}

	files, err := services.ExportFilesToDirectory(h.cfg.OutputDir(jobID), absoluteDestination, req.Overwrite)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, exportFolderResponse{
		Directory:     absoluteDestination,
		ExportedCount: len(files),
		Files:         files,
	})
}

func (h *Handler) saveUploads(c *gin.Context, jobID string, files []*multipart.FileHeader, manualRegions [][]services.ManualRegion) ([]uploadedImage, error) {
	uploadDir := h.cfg.UploadDir(jobID)
	outputDir := h.cfg.OutputDir(jobID)
	if err := os.MkdirAll(uploadDir, 0o755); err != nil {
		return nil, err
	}
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return nil, err
	}

	uploads := make([]uploadedImage, 0, len(files))
	for index, file := range files {
		if file.Size > h.cfg.MaxUploadBytes {
			return nil, errors.New("uploaded file exceeds size limit")
		}
		filename := safeFilename(file.Filename)
		if filename == "" {
			filename = "image_" + time.Now().Format("150405") + ".png"
		}
		if index > 0 && hasUploadName(uploads, filename) {
			filename = strings.TrimSuffix(filename, filepath.Ext(filename)) + "_" + uuid.NewString()[:8] + filepath.Ext(filename)
		}

		inputPath := filepath.Join(uploadDir, filename)
		if err := c.SaveUploadedFile(file, inputPath); err != nil {
			return nil, err
		}
		outputFilename := outputName(filename)
		var regions []services.ManualRegion
		if index < len(manualRegions) {
			regions = manualRegions[index]
		}
		uploads = append(uploads, uploadedImage{
			SourceFilename: filename,
			InputPath:      inputPath,
			OutputPath:     filepath.Join(outputDir, outputFilename),
			OutputFilename: outputFilename,
			ManualRegions:  regions,
		})
	}
	return uploads, nil
}

func (h *Handler) processJob(ctx context.Context, jobID, sourceLanguage, targetLanguage, inpaintEngine string, uploads []uploadedImage) {
	if err := h.repo.SetJobStatus(jobID, models.StatusProcessing, ""); err != nil {
		return
	}

	successes := 0
	failures := make([]string, 0)
	for _, upload := range uploads {
		result, err := h.aiClient.TranslateImage(ctx, upload.InputPath, sourceLanguage, targetLanguage, inpaintEngine, upload.ManualRegions)
		if err != nil {
			failures = append(failures, upload.SourceFilename+": "+err.Error())
			continue
		}

		rawImage, err := base64.StdEncoding.DecodeString(result.OutputImageBase64)
		if err != nil {
			failures = append(failures, upload.SourceFilename+": "+err.Error())
			continue
		}
		if err := os.WriteFile(upload.OutputPath, rawImage, 0o644); err != nil {
			failures = append(failures, upload.SourceFilename+": "+err.Error())
			continue
		}

		entries := make([]models.TranslationEntry, 0, len(result.Entries))
		for _, entry := range result.Entries {
			entries = append(entries, models.TranslationEntry{
				SourceText:     entry.SourceText,
				TranslatedText: entry.TranslatedText,
				Confidence:     entry.Confidence,
				Box:            entry.Box,
			})
		}
		dbResult := models.JobResult{
			JobID:           jobID,
			SourceFilename:  upload.SourceFilename,
			OutputFilename:  upload.OutputFilename,
			RegionsDetected: result.RegionsDetected,
			RegionsReplaced: result.RegionsReplaced,
			EntriesJSON:     models.EncodeJSON(entries),
			WarningsJSON:    models.EncodeJSON(result.Warnings),
		}
		sourceCharacters, translatedCharacters := countEntryCharacters(entries)
		if err := h.repo.AddResult(jobID, dbResult, sourceCharacters, translatedCharacters); err != nil {
			_ = h.repo.SetJobStatus(jobID, models.StatusFailed, err.Error())
			return
		}
		successes++
	}
	if len(failures) > 0 {
		message := strings.Join(failures, "; ")
		if successes > 0 {
			_ = h.repo.FinishJob(jobID, models.StatusPartial, "部分图片失败："+message)
			return
		}
		_ = h.repo.SetJobStatus(jobID, models.StatusFailed, message)
		return
	}
	_ = h.repo.CompleteJob(jobID)
}

func (h *Handler) toJobResponse(job *models.Job) models.JobResponse {
	return job.ToResponse(h.cfg.PublicFileURL)
}

func (h *Handler) canAccessJob(c *gin.Context, job *models.Job) bool {
	user, ok := currentUser(c)
	if !ok {
		return false
	}
	return job.UserID == user.ID || isAdminRole(user.Role)
}

func countEntryCharacters(entries []models.TranslationEntry) (int, int) {
	source := 0
	translated := 0
	for _, entry := range entries {
		source += len([]rune(entry.SourceText))
		translated += len([]rune(entry.TranslatedText))
	}
	return source, translated
}

func firstFormValue(values map[string][]string, key, fallback string) string {
	items := values[key]
	if len(items) == 0 || strings.TrimSpace(items[0]) == "" {
		return fallback
	}
	return strings.TrimSpace(items[0])
}

func parseManualRegionsPayload(raw string) ([][]services.ManualRegion, error) {
	value := strings.TrimSpace(raw)
	if value == "" {
		return nil, nil
	}
	var payload [][]services.ManualRegion
	if err := json.Unmarshal([]byte(value), &payload); err != nil {
		return nil, errors.New("invalid manual_regions payload")
	}
	for fileIndex := range payload {
		regions := payload[fileIndex]
		cleaned := regions[:0]
		for _, region := range regions {
			if region.Width <= 0 || region.Height <= 0 {
				continue
			}
			region.X = clamp01(region.X)
			region.Y = clamp01(region.Y)
			region.Width = clamp01(region.Width)
			region.Height = clamp01(region.Height)
			if region.X+region.Width > 1 {
				region.Width = 1 - region.X
			}
			if region.Y+region.Height > 1 {
				region.Height = 1 - region.Y
			}
			if region.Width <= 0 || region.Height <= 0 {
				continue
			}
			cleaned = append(cleaned, region)
		}
		payload[fileIndex] = cleaned
	}
	return payload, nil
}

func clamp01(value float64) float64 {
	if value < 0 {
		return 0
	}
	if value > 1 {
		return 1
	}
	return value
}

var unsafeName = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

func safeFilename(filename string) string {
	name := filepath.Base(strings.TrimSpace(filename))
	name = unsafeName.ReplaceAllString(name, "_")
	return strings.Trim(name, "._-")
}

func outputName(filename string) string {
	ext := filepath.Ext(filename)
	stem := strings.TrimSuffix(filename, ext)
	if stem == "" {
		stem = "image"
	}
	return stem + "_en.png"
}

func hasUploadName(uploads []uploadedImage, filename string) bool {
	for _, upload := range uploads {
		if upload.SourceFilename == filename {
			return true
		}
	}
	return false
}
