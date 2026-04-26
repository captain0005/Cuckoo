package services

import (
	"archive/zip"
	"io"
	"os"
	"path/filepath"
)

func BuildZip(sourceDir, outputPath string) error {
	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil {
		return err
	}

	archive, err := os.Create(outputPath)
	if err != nil {
		return err
	}
	defer archive.Close()

	writer := zip.NewWriter(archive)
	defer writer.Close()

	return filepath.WalkDir(sourceDir, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			return nil
		}

		relative, err := filepath.Rel(sourceDir, path)
		if err != nil {
			return err
		}
		target, err := writer.Create(filepath.ToSlash(relative))
		if err != nil {
			return err
		}
		source, err := os.Open(path)
		if err != nil {
			return err
		}
		defer source.Close()
		_, err = io.Copy(target, source)
		return err
	})
}
