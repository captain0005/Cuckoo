package handlers

import (
	"context"
	"encoding/base64"
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
}

type jobResponse struct {
	JobID          string                     `json:"job_id"`
	Status         string                     `json:"status"`
	Progress       float64                    `json:"progress"`
	Completed      int                        `json:"completed"`
	Total          int                        `json:"total"`
	SourceLanguage string                     `json:"source_language"`
	TargetLanguage string                     `json:"target_language"`
	Error          string                     `json:"error"`
	CreatedAt      time.Time                  `json:"created_at"`
	UpdatedAt      time.Time                  `json:"updated_at"`
	DownloadURL    *string                    `json:"download_url"`
	Results        []models.JobResultResponse `json:"results"`
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
	c.JSON(http.StatusOK, gin.H{
		"status":     "ok",
		"service":    "backend",
		"ai_service": h.cfg.AIServiceURL,
	})
}

func (h *Handler) CreateJob(c *gin.Context) {
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
	jobID := uuid.NewString()

	uploads, err := h.saveUploads(c, jobID, files)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}

	job := &models.Job{
		ID:             jobID,
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

	go h.processJob(context.Background(), jobID, sourceLanguage, targetLanguage, uploads)
	c.JSON(http.StatusAccepted, h.toJobResponse(job))
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
	c.JSON(http.StatusOK, h.toJobResponse(job))
}

func (h *Handler) DownloadJob(c *gin.Context) {
	jobID := c.Param("jobID")
	job, err := h.repo.GetJob(jobID)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "job not found"})
		return
	}
	if job.Status != models.StatusCompleted {
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
	if job.Status != models.StatusCompleted {
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

func (h *Handler) saveUploads(c *gin.Context, jobID string, files []*multipart.FileHeader) ([]uploadedImage, error) {
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
		uploads = append(uploads, uploadedImage{
			SourceFilename: filename,
			InputPath:      inputPath,
			OutputPath:     filepath.Join(outputDir, outputFilename),
			OutputFilename: outputFilename,
		})
	}
	return uploads, nil
}

func (h *Handler) processJob(ctx context.Context, jobID, sourceLanguage, targetLanguage string, uploads []uploadedImage) {
	if err := h.repo.SetJobStatus(jobID, models.StatusProcessing, ""); err != nil {
		return
	}

	for _, upload := range uploads {
		result, err := h.aiClient.TranslateImage(ctx, upload.InputPath, sourceLanguage, targetLanguage)
		if err != nil {
			_ = h.repo.SetJobStatus(jobID, models.StatusFailed, err.Error())
			return
		}

		rawImage, err := base64.StdEncoding.DecodeString(result.OutputImageBase64)
		if err != nil {
			_ = h.repo.SetJobStatus(jobID, models.StatusFailed, err.Error())
			return
		}
		if err := os.WriteFile(upload.OutputPath, rawImage, 0o644); err != nil {
			_ = h.repo.SetJobStatus(jobID, models.StatusFailed, err.Error())
			return
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
		if err := h.repo.AddResult(jobID, dbResult); err != nil {
			_ = h.repo.SetJobStatus(jobID, models.StatusFailed, err.Error())
			return
		}
	}
	_ = h.repo.CompleteJob(jobID)
}

func (h *Handler) toJobResponse(job *models.Job) jobResponse {
	progress := 0.0
	if job.Total > 0 {
		progress = float64(job.Completed) / float64(job.Total) * 100
	}
	var downloadURL *string
	if job.Status == models.StatusCompleted {
		value := "/api/jobs/" + job.ID + "/download"
		downloadURL = &value
	}

	results := make([]models.JobResultResponse, 0, len(job.Results))
	for _, result := range job.Results {
		results = append(results, result.ToResponse(h.cfg.PublicFileURL(job.ID, result.OutputFilename)))
	}

	return jobResponse{
		JobID:          job.ID,
		Status:         job.Status,
		Progress:       progress,
		Completed:      job.Completed,
		Total:          job.Total,
		SourceLanguage: job.SourceLanguage,
		TargetLanguage: job.TargetLanguage,
		Error:          job.ErrorMessage,
		CreatedAt:      job.CreatedAt,
		UpdatedAt:      job.UpdatedAt,
		DownloadURL:    downloadURL,
		Results:        results,
	}
}

func firstFormValue(values map[string][]string, key, fallback string) string {
	items := values[key]
	if len(items) == 0 || strings.TrimSpace(items[0]) == "" {
		return fallback
	}
	return strings.TrimSpace(items[0])
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
