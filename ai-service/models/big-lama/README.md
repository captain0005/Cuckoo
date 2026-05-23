# Big-Lama Model

Place `big-lama.pt` in this directory to enable Cuckoo's high-quality LAMA inpainting mode.

The model file is intentionally not tracked in Git because it is about 200 MB. Use:

```powershell
scripts\install-lama-model.ps1
```

or set `LAMA_MODEL_PATH` in `ai-service/.env` to an absolute `big-lama.pt` path.

For Railway/server deployments, set `LAMA_MODEL_URL` to an accessible model URL; `scripts/start-railway.sh` will download it to `LAMA_MODEL_PATH` on startup.
