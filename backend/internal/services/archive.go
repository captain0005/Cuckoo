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

func ExportFilesToDirectory(sourceDir, destinationDir string, overwrite bool) ([]string, error) {
	if err := os.MkdirAll(destinationDir, 0o755); err != nil {
		return nil, err
	}

	exported := []string{}
	err := filepath.WalkDir(sourceDir, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			return nil
		}

		targetPath := filepath.Join(destinationDir, entry.Name())
		if !overwrite {
			if _, err := os.Stat(targetPath); err == nil {
				targetPath = nextAvailablePath(destinationDir, entry.Name())
			} else if err != nil && !os.IsNotExist(err) {
				return err
			}
		}
		if err := copyFile(path, targetPath); err != nil {
			return err
		}
		exported = append(exported, targetPath)
		return nil
	})
	return exported, err
}

func copyFile(sourcePath, targetPath string) error {
	if err := os.MkdirAll(filepath.Dir(targetPath), 0o755); err != nil {
		return err
	}
	source, err := os.Open(sourcePath)
	if err != nil {
		return err
	}
	defer source.Close()

	target, err := os.Create(targetPath)
	if err != nil {
		return err
	}
	defer target.Close()
	_, err = io.Copy(target, source)
	return err
}

func nextAvailablePath(directory, filename string) string {
	ext := filepath.Ext(filename)
	stem := filename[:len(filename)-len(ext)]
	for index := 1; ; index++ {
		candidate := filepath.Join(directory, stem+"_"+itoa(index)+ext)
		if _, err := os.Stat(candidate); os.IsNotExist(err) {
			return candidate
		}
	}
}

func itoa(value int) string {
	if value == 0 {
		return "0"
	}
	buf := [20]byte{}
	index := len(buf)
	for value > 0 {
		index--
		buf[index] = byte('0' + value%10)
		value /= 10
	}
	return string(buf[index:])
}
