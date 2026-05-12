param(
  [string]$Source = "",
  [string]$Url = "",
  [string]$Destination = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $Destination) {
  $Destination = Join-Path $repoRoot "ai-service\models\big-lama\big-lama.pt"
}

$destinationPath = [System.IO.Path]::GetFullPath($Destination)
$modelDir = [System.IO.Path]::GetDirectoryName($destinationPath)
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null

if ((Test-Path $destinationPath) -and -not $Force) {
  Write-Host "LAMA model already exists: $destinationPath"
  exit 0
}

$candidateSources = @()
if ($Source) {
  $candidateSources += $Source
}
$candidateSources += @(
  (Join-Path $repoRoot "ai-service\models\big-lama\big-lama.pt"),
  "D:\GitHub\video-subtitle-remover\video-subtitle-remover\backend\models\big-lama\big-lama.pt"
)

$sourcePath = ""
foreach ($candidate in $candidateSources) {
  if (-not $candidate) {
    continue
  }
  $fullCandidate = [System.IO.Path]::GetFullPath($candidate)
  if ($fullCandidate -ne $destinationPath -and (Test-Path $fullCandidate)) {
    $sourcePath = $fullCandidate
    break
  }
}

if (-not $sourcePath) {
  if ($Url) {
    Write-Host "Downloading LAMA model from $Url"
    Invoke-WebRequest -Uri $Url -OutFile $destinationPath
    Write-Host "Installed LAMA model:"
    Write-Host "  Source:      $Url"
    Write-Host "  Destination: $destinationPath"
    exit 0
  }
  throw "Could not find big-lama.pt. Pass -Source C:\path\to\big-lama.pt, pass -Url https://..., or put the file at $destinationPath."
}

Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
Write-Host "Installed LAMA model:"
Write-Host "  Source:      $sourcePath"
Write-Host "  Destination: $destinationPath"
