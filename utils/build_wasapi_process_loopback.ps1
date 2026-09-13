param(
    [string]$Compiler = "g++"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Source = Join-Path $ProjectRoot "native\wasapi_process_loopback\main.cpp"
$OutputDirectory = Join-Path $ProjectRoot "build\native"
$Output = Join-Path $OutputDirectory "wasapi_process_loopback.exe"

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
& $Compiler -std=c++17 -O2 -Wall -Wextra `
    -static -static-libgcc -static-libstdc++ `
    $Source -o $Output -lole32 -lmmdevapi -luuid -lwinmm
if ($LASTEXITCODE -ne 0) {
    throw "WASAPI process-loopback helper build failed with exit code $LASTEXITCODE"
}

Write-Output $Output
