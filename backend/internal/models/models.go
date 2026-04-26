package models

import (
	"encoding/json"
	"time"
)

const (
	StatusQueued     = "queued"
	StatusProcessing = "processing"
	StatusCompleted  = "completed"
	StatusFailed     = "failed"
)

type Job struct {
	ID             string `gorm:"primaryKey"`
	Status         string `gorm:"index"`
	SourceLanguage string
	TargetLanguage string
	Total          int
	Completed      int
	ErrorMessage   string
	CreatedAt      time.Time
	UpdatedAt      time.Time
	Results        []JobResult `gorm:"foreignKey:JobID;constraint:OnDelete:CASCADE"`
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
