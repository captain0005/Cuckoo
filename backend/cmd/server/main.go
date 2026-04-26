package main

import (
	"log"

	"github.com/6602966029/cuckoo/backend/internal/config"
	"github.com/6602966029/cuckoo/backend/internal/repository"
	"github.com/6602966029/cuckoo/backend/internal/router"
	_ "github.com/joho/godotenv/autoload"
)

func main() {
	cfg := config.Load()

	repo, err := repository.Open(cfg)
	if err != nil {
		log.Fatalf("open repository: %v", err)
	}

	app := router.New(cfg, repo)
	log.Printf("cuckoo backend listening on %s", cfg.ServerAddr)
	if err := app.Run(cfg.ServerAddr); err != nil {
		log.Fatalf("run server: %v", err)
	}
}
