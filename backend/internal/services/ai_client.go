package services

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type AIClient struct {
	BaseURL    string
	HTTPClient *http.Client
}

const aiTranslateMaxAttempts = 3
const defaultAIClientTimeout = 15 * time.Minute

type AITranslationResponse struct {
	SourceFilename    string             `json:"source_filename"`
	OutputFilename    string             `json:"output_filename"`
	MimeType          string             `json:"mime_type"`
	OutputImageBase64 string             `json:"output_image_base64"`
	RegionsDetected   int                `json:"regions_detected"`
	RegionsReplaced   int                `json:"regions_replaced"`
	Entries           []TranslationEntry `json:"entries"`
	Warnings          []string           `json:"warnings"`
}

type TranslationEntry struct {
	SourceText     string         `json:"source_text"`
	TranslatedText string         `json:"translated_text"`
	Confidence     float64        `json:"confidence"`
	Box            map[string]int `json:"box"`
}

type ManualRegion struct {
	X      float64 `json:"x"`
	Y      float64 `json:"y"`
	Width  float64 `json:"width"`
	Height float64 `json:"height"`
}

func NewAIClient(baseURL string) *AIClient {
	return &AIClient{
		BaseURL: baseURL,
		HTTPClient: &http.Client{
			Timeout: aiClientTimeout(),
		},
	}
}

func (c *AIClient) TranslateImage(ctx context.Context, imagePath, sourceLanguage, targetLanguage, inpaintEngine string, manualRegions []ManualRegion) (*AITranslationResponse, error) {
	file, err := os.Open(imagePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, err := writer.CreateFormFile("file", filepath.Base(imagePath))
	if err != nil {
		return nil, err
	}
	if _, err := io.Copy(part, file); err != nil {
		return nil, err
	}
	_ = writer.WriteField("source_language", sourceLanguage)
	_ = writer.WriteField("target_language", targetLanguage)
	if strings.TrimSpace(inpaintEngine) != "" {
		_ = writer.WriteField("inpaint_engine", inpaintEngine)
	}
	if len(manualRegions) > 0 {
		rawRegions, err := json.Marshal(manualRegions)
		if err != nil {
			return nil, err
		}
		_ = writer.WriteField("manual_regions", string(rawRegions))
	}
	if err := writer.Close(); err != nil {
		return nil, err
	}

	contentType := writer.FormDataContentType()
	bodyBytes := append([]byte(nil), body.Bytes()...)

	var lastErr error
	for attempt := 1; attempt <= aiTranslateMaxAttempts; attempt++ {
		payload, err := c.postTranslateImage(ctx, bodyBytes, contentType)
		if err == nil {
			return payload, nil
		}
		lastErr = err
		if attempt >= aiTranslateMaxAttempts || !isRetryableAIError(err) {
			break
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(time.Duration(attempt) * 2 * time.Second):
		}
	}
	return nil, lastErr
}

func (c *AIClient) postTranslateImage(ctx context.Context, bodyBytes []byte, contentType string) (*AITranslationResponse, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.BaseURL+"/api/translate-image", bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", contentType)

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("ai-service returned %d: %s", resp.StatusCode, string(raw))
	}

	var payload AITranslationResponse
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, err
	}
	if payload.OutputImageBase64 == "" {
		return nil, fmt.Errorf("ai-service did not return output_image_base64")
	}
	return &payload, nil
}

func isRetryableAIError(err error) bool {
	if err == nil {
		return false
	}
	message := strings.ToLower(err.Error())
	if strings.Contains(message, "context canceled") || strings.Contains(message, "deadline exceeded") {
		return false
	}
	return strings.Contains(message, "eof") ||
		strings.Contains(message, "connection refused") ||
		strings.Contains(message, "connection reset") ||
		strings.Contains(message, "server closed idle connection") ||
		strings.Contains(message, "broken pipe") ||
		strings.Contains(message, "use of closed network connection")
}

func aiClientTimeout() time.Duration {
	raw := strings.TrimSpace(os.Getenv("AI_CLIENT_TIMEOUT_SECONDS"))
	if raw == "" {
		return defaultAIClientTimeout
	}
	seconds, err := strconv.ParseFloat(raw, 64)
	if err != nil || seconds <= 0 {
		return defaultAIClientTimeout
	}
	return time.Duration(seconds * float64(time.Second))
}
