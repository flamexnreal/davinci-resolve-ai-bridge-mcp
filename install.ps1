$ErrorActionPreference = "Stop"
Write-Host "==> Downloading and installing DaVinci Resolve AI Bridge..."

$previousLocation = Get-Location
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("resolve-ai-bridge-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

try {
    $zipPath = Join-Path $tmpDir "repo.zip"
    Invoke-WebRequest -Uri "https://github.com/flamexnreal/davinci-resolve-ai-bridge-mcp/archive/refs/heads/main.zip" -OutFile $zipPath -UseBasicParsing
    # .NET ZIP extraction also handles temporary paths containing brackets.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zipPath, $tmpDir)
    $projectFolders = @(Get-ChildItem -LiteralPath $tmpDir -Directory | Where-Object {
        Test-Path -LiteralPath (Join-Path $_.FullName "install.py") -PathType Leaf
    })
    if ($projectFolders.Count -ne 1) {
        throw "The downloaded archive must contain exactly one project folder with install.py. Please download the complete repository and try again."
    }
    Set-Location -LiteralPath $projectFolders[0].FullName

    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py install.py @args
    } elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
        & python3 install.py @args
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python install.py @args
    } else {
        throw "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ and reopen PowerShell before trying again."
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Resolve AI Bridge installation failed (exit code $LASTEXITCODE). See the installer output above."
    }
} finally {
    Set-Location -LiteralPath $previousLocation.Path
    Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
}
