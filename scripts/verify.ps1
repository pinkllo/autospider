$ErrorActionPreference = "Stop"

function Invoke-PytestWithTimeout {
    param(
        [string[]]$Arguments
    )

    $pytestCommand = Get-Command pytest -ErrorAction Stop
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $pytestCommand.Source
    $startInfo.UseShellExecute = $false
    foreach ($argument in $Arguments) {
        $null = $startInfo.ArgumentList.Add($argument)
    }

    $process = [System.Diagnostics.Process]::Start($startInfo)
    if (-not $process.WaitForExit(60000)) {
        $process.Kill($true)
        throw "pytest timed out after 60s: pytest $($Arguments -join ' ')"
    }
    if ($process.ExitCode -ne 0) {
        throw "pytest failed with exit code $($process.ExitCode): pytest $($Arguments -join ' ')"
    }
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    ruff check src tests
    black --check src tests
    mypy src/autospider
    Invoke-PytestWithTimeout -Arguments @("-m", "smoke", "-q")
    Invoke-PytestWithTimeout -Arguments @("tests/contracts", "-q")

    $importLinterCommand = Get-Command lint-imports -ErrorAction SilentlyContinue
    $importLinterConfig = Join-Path $RepoRoot ".importlinter"
    if (Test-Path $importLinterConfig) {
        if (-not $importLinterCommand) {
            throw "lint-imports command is required when .importlinter exists. Install dev dependencies first."
        }
        lint-imports
    }
} finally {
    Pop-Location
}
