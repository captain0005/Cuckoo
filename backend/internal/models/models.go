package models

import (
	"encoding/json"
	"time"
)

const (
	StatusQueued     = "queued"
	StatusProcessing = "processing"
	StatusCompleted  = "completed"
	StatusPartial    = "partial"
	StatusFailed     = "failed"
	StatusCanceled   = "canceled"
)

const (
	RoleSuperAdmin = "super_admin"
	RoleAdmin      = "admin"
	RoleUser       = "user"
)

const (
	UserStatusActive   = "active"
	UserStatusDisabled = "disabled"
)

type Job struct {
	ID                   string `gorm:"primaryKey"`
	UserID               string `gorm:"index"`
	Status               string `gorm:"index"`
	RecognitionMode      string
	SourceLanguage       string
	TargetLanguage       string
	InpaintEngine        string
	Total                int
	Processed            int
	Completed            int
	RegionsDetected      int
	RegionsReplaced      int
	SourceCharacters     int
	TranslatedCharacters int
	ErrorMessage         string
	CreatedAt            time.Time
	UpdatedAt            time.Time
	User                 User        `gorm:"foreignKey:UserID"`
	Results              []JobResult `gorm:"foreignKey:JobID;constraint:OnDelete:CASCADE"`
	Items                []JobItem   `gorm:"foreignKey:JobID;constraint:OnDelete:CASCADE"`
}

type JobItem struct {
	ID                uint `gorm:"primaryKey"`
	JobID             string
	ItemIndex         int
	SourceFilename    string
	InputPath         string
	OutputPath        string
	OutputFilename    string
	Status            string `gorm:"index"`
	ManualRegionsJSON string `gorm:"type:text"`
	ErrorMessage      string
	StartedAt         *time.Time
	FinishedAt        *time.Time
	CreatedAt         time.Time
	UpdatedAt         time.Time
}

type User struct {
	ID           string `gorm:"primaryKey"`
	Username     string `gorm:"uniqueIndex;not null"`
	DisplayName  string
	Email        string `gorm:"uniqueIndex"`
	Role         string `gorm:"index;not null"`
	Status       string `gorm:"index;not null"`
	PasswordHash string `gorm:"not null"`
	LastLoginAt  *time.Time
	CreatedAt    time.Time
	UpdatedAt    time.Time
	APIKeys      []APIKeyRecord `gorm:"foreignKey:UserID;constraint:OnDelete:CASCADE"`
}

type APIKeyRecord struct {
	ID              string `gorm:"primaryKey"`
	UserID          string `gorm:"index;not null"`
	Provider        string `gorm:"index;not null"`
	KeyName         string
	MaskedKey       string
	KeyFingerprint  string `gorm:"index"`
	Status          string `gorm:"index;not null"`
	TotalRequests   int
	TotalCharacters int
	LastUsedAt      *time.Time
	CreatedAt       time.Time
	UpdatedAt       time.Time
	User            User `gorm:"foreignKey:UserID"`
}

type JobResult struct {
	ID              uint `gorm:"primaryKey"`
	JobID           string
	SourceFilename  string
	OutputFilename  string
	RegionsDetected int
	RegionsReplaced int
	EntriesJSON     string `gorm:"type:text"`
	WarningsJSON    string `gorm:"type:text"`
	CreatedAt       time.Time
}

type UserResponse struct {
	ID          string     `json:"id"`
	Username    string     `json:"username"`
	DisplayName string     `json:"display_name"`
	Email       string     `json:"email"`
	Role        string     `json:"role"`
	Status      string     `json:"status"`
	LastLoginAt *time.Time `json:"last_login_at"`
	CreatedAt   time.Time  `json:"created_at"`
	UpdatedAt   time.Time  `json:"updated_at"`
}

type UserUsageResponse struct {
	UserID               string     `json:"user_id"`
	Username             string     `json:"username"`
	DisplayName          string     `json:"display_name"`
	Role                 string     `json:"role"`
	Status               string     `json:"status"`
	Jobs                 int        `json:"jobs"`
	Images               int        `json:"images"`
	CompletedImages      int        `json:"completed_images"`
	RegionsDetected      int        `json:"regions_detected"`
	RegionsReplaced      int        `json:"regions_replaced"`
	SourceCharacters     int        `json:"source_characters"`
	TranslatedCharacters int        `json:"translated_characters"`
	LastJobAt            *time.Time `json:"last_job_at"`
}

type APIKeyRecordResponse struct {
	ID              string     `json:"id"`
	UserID          string     `json:"user_id"`
	Username        string     `json:"username"`
	Provider        string     `json:"provider"`
	KeyName         string     `json:"key_name"`
	MaskedKey       string     `json:"masked_key"`
	KeyFingerprint  string     `json:"key_fingerprint"`
	Status          string     `json:"status"`
	TotalRequests   int        `json:"total_requests"`
	TotalCharacters int        `json:"total_characters"`
	LastUsedAt      *time.Time `json:"last_used_at"`
	CreatedAt       time.Time  `json:"created_at"`
	UpdatedAt       time.Time  `json:"updated_at"`
}

type TranslationEntry struct {
	SourceText     string         `json:"source_text"`
	TranslatedText string         `json:"translated_text"`
	Confidence     float64        `json:"confidence"`
	Box            map[string]int `json:"box"`
}

type JobResultResponse struct {
	SourceFilename  string             `json:"source_filename"`
	OutputFilename  string             `json:"output_filename"`
	FileURL         string             `json:"file_url"`
	RegionsDetected int                `json:"regions_detected"`
	RegionsReplaced int                `json:"regions_replaced"`
	Entries         []TranslationEntry `json:"entries"`
	Warnings        []string           `json:"warnings"`
}

type ManualRegion struct {
	X      float64 `json:"x"`
	Y      float64 `json:"y"`
	Width  float64 `json:"width"`
	Height float64 `json:"height"`
}

type JobItemResponse struct {
	ID             uint           `json:"id"`
	Index          int            `json:"index"`
	SourceFilename string         `json:"source_filename"`
	OutputFilename string         `json:"output_filename"`
	FileURL        string         `json:"file_url"`
	Status         string         `json:"status"`
	ManualRegions  []ManualRegion `json:"manual_regions"`
	Error          string         `json:"error"`
	StartedAt      *time.Time     `json:"started_at"`
	FinishedAt     *time.Time     `json:"finished_at"`
}

type JobResponse struct {
	JobID                string              `json:"job_id"`
	UserID               string              `json:"user_id"`
	Username             string              `json:"username"`
	Status               string              `json:"status"`
	Progress             float64             `json:"progress"`
	RecognitionMode      string              `json:"recognition_mode"`
	InpaintEngine        string              `json:"inpaint_engine"`
	Processed            int                 `json:"processed"`
	Completed            int                 `json:"completed"`
	Total                int                 `json:"total"`
	CurrentItemIndex     int                 `json:"current_item_index"`
	SourceLanguage       string              `json:"source_language"`
	TargetLanguage       string              `json:"target_language"`
	RegionsDetected      int                 `json:"regions_detected"`
	RegionsReplaced      int                 `json:"regions_replaced"`
	SourceCharacters     int                 `json:"source_characters"`
	TranslatedCharacters int                 `json:"translated_characters"`
	Error                string              `json:"error"`
	CreatedAt            time.Time           `json:"created_at"`
	UpdatedAt            time.Time           `json:"updated_at"`
	DownloadURL          *string             `json:"download_url"`
	Results              []JobResultResponse `json:"results"`
	Items                []JobItemResponse   `json:"items"`
}

func (u User) ToResponse() UserResponse {
	return UserResponse{
		ID:          u.ID,
		Username:    u.Username,
		DisplayName: u.DisplayName,
		Email:       u.Email,
		Role:        u.Role,
		Status:      u.Status,
		LastLoginAt: u.LastLoginAt,
		CreatedAt:   u.CreatedAt,
		UpdatedAt:   u.UpdatedAt,
	}
}

func (r APIKeyRecord) ToResponse() APIKeyRecordResponse {
	return APIKeyRecordResponse{
		ID:              r.ID,
		UserID:          r.UserID,
		Username:        r.User.Username,
		Provider:        r.Provider,
		KeyName:         r.KeyName,
		MaskedKey:       r.MaskedKey,
		KeyFingerprint:  r.KeyFingerprint,
		Status:          r.Status,
		TotalRequests:   r.TotalRequests,
		TotalCharacters: r.TotalCharacters,
		LastUsedAt:      r.LastUsedAt,
		CreatedAt:       r.CreatedAt,
		UpdatedAt:       r.UpdatedAt,
	}
}

func (r JobResult) ToResponse(fileURL string) JobResultResponse {
	return JobResultResponse{
		SourceFilename:  r.SourceFilename,
		OutputFilename:  r.OutputFilename,
		FileURL:         fileURL,
		RegionsDetected: r.RegionsDetected,
		RegionsReplaced: r.RegionsReplaced,
		Entries:         decodeEntries(r.EntriesJSON),
		Warnings:        decodeStrings(r.WarningsJSON),
	}
}

func (item JobItem) ToResponse(fileURL func(jobID, filename string) string) JobItemResponse {
	itemFileURL := ""
	if item.OutputFilename != "" && item.Status == StatusCompleted {
		itemFileURL = fileURL(item.JobID, item.OutputFilename)
	}
	return JobItemResponse{
		ID:             item.ID,
		Index:          item.ItemIndex,
		SourceFilename: item.SourceFilename,
		OutputFilename: item.OutputFilename,
		FileURL:        itemFileURL,
		Status:         item.Status,
		ManualRegions:  decodeManualRegions(item.ManualRegionsJSON),
		Error:          item.ErrorMessage,
		StartedAt:      item.StartedAt,
		FinishedAt:     item.FinishedAt,
	}
}

func (j Job) ToResponse(fileURL func(jobID, filename string) string) JobResponse {
	processed := j.Processed
	if processed == 0 && len(j.Items) == 0 {
		processed = j.Completed
	}
	progress := 0.0
	if j.Total > 0 {
		progress = float64(processed) / float64(j.Total) * 100
	}
	var downloadURL *string
	if j.Status == StatusCompleted || j.Status == StatusPartial {
		value := "/api/jobs/" + j.ID + "/download"
		downloadURL = &value
	}
	currentItemIndex := 0
	items := make([]JobItemResponse, 0, len(j.Items))
	for _, item := range j.Items {
		if item.Status == StatusProcessing {
			currentItemIndex = item.ItemIndex
		}
		items = append(items, item.ToResponse(fileURL))
	}
	results := make([]JobResultResponse, 0, len(j.Results))
	for _, result := range j.Results {
		results = append(results, result.ToResponse(fileURL(j.ID, result.OutputFilename)))
	}
	return JobResponse{
		JobID:                j.ID,
		UserID:               j.UserID,
		Username:             j.User.Username,
		Status:               j.Status,
		Progress:             progress,
		RecognitionMode:      j.RecognitionMode,
		InpaintEngine:        j.InpaintEngine,
		Processed:            processed,
		Completed:            j.Completed,
		Total:                j.Total,
		CurrentItemIndex:     currentItemIndex,
		SourceLanguage:       j.SourceLanguage,
		TargetLanguage:       j.TargetLanguage,
		RegionsDetected:      j.RegionsDetected,
		RegionsReplaced:      j.RegionsReplaced,
		SourceCharacters:     j.SourceCharacters,
		TranslatedCharacters: j.TranslatedCharacters,
		Error:                j.ErrorMessage,
		CreatedAt:            j.CreatedAt,
		UpdatedAt:            j.UpdatedAt,
		DownloadURL:          downloadURL,
		Results:              results,
		Items:                items,
	}
}

func EncodeJSON(value any) string {
	raw, err := json.Marshal(value)
	if err != nil {
		return "[]"
	}
	return string(raw)
}

func decodeEntries(raw string) []TranslationEntry {
	var entries []TranslationEntry
	if err := json.Unmarshal([]byte(raw), &entries); err != nil {
		return []TranslationEntry{}
	}
	return entries
}

func decodeStrings(raw string) []string {
	var items []string
	if err := json.Unmarshal([]byte(raw), &items); err != nil {
		return []string{}
	}
	return items
}

func decodeManualRegions(raw string) []ManualRegion {
	var items []ManualRegion
	if err := json.Unmarshal([]byte(raw), &items); err != nil {
		return []ManualRegion{}
	}
	return items
}
