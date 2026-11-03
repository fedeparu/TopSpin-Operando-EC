# Run from PowerShell: .\scripts\install_windows.ps1
# Creates a local venv. No administrator rights or vendor modifications required.
param(
    [string]$Python = "py",
    [string]$TopSpinUserScriptDirectory = ""
)
$ErrorActionPreference = "Stop"
$ProjectDirectory = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectDirectory
Write-Host "EC-NMR installation assistant: Offline and Simulation"
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install 64-bit Python 3.10-3.13 from python.org, enable the Python launcher, and run this assistant again."
}
if ($Python -eq "py") { $PythonArguments = @("-3") } else { $PythonArguments = @() }
& $Python @PythonArguments -c "import sys; assert (3,10) <= sys.version_info[:2] < (3,14), 'Use Python 3.10-3.13'"
if ($LASTEXITCODE -ne 0) { throw "Unsupported Python environment." }
& $Python @PythonArguments -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
$VirtualPython = Join-Path $ProjectDirectory ".venv\Scripts\python.exe"
& $VirtualPython -m pip install -e ".[test]"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Check network access and retry." }
$ReportPath = Join-Path $ProjectDirectory "work\installation-diagnostics.json"
& $VirtualPython scripts\diagnose.py --output $ReportPath
if ($LASTEXITCODE -ne 0) { throw "Diagnostics failed." }
Write-Host "Diagnostic report: $ReportPath"
Write-Host "EC-Lab and OLE-COM are optional. The assistant did not instantiate COM or change vendor software."
Write-Host "If needed, activate OLE-COM within EC-Lab following your installed vendor documentation."
if ($TopSpinUserScriptDirectory) {
    if (-not (Test-Path $TopSpinUserScriptDirectory -PathType Container)) {
        throw "Select an existing user script directory documented by your TopSpin installation."
    }
    Write-Host "Requested launcher destination: $TopSpinUserScriptDirectory"
    Write-Host "The launcher starts this external Python environment: $VirtualPython"
    $Answer = Read-Host "Copy only ecnmr_launcher.py to that user script directory? Type YES to authorize"
    if ($Answer -ceq "YES") {
        $TargetPath = Join-Path $TopSpinUserScriptDirectory "ecnmr_launcher.py"
        if (Test-Path $TargetPath) { throw "Launcher exists. Back up and review it before replacing it manually." }
        Copy-Item (Join-Path $ProjectDirectory "topspin\ecnmr_launcher.py") $TargetPath
        Write-Host "Copied launcher. Configure ECNMR_HOME=$ProjectDirectory before starting TopSpin."
        Write-Host "Set ECNMR_PYTHON=$VirtualPython if required. No system environment variables were changed."
    } else { Write-Host "Launcher copy skipped." }
} else {
    Write-Host "TopSpin launcher is provided in topspin\ecnmr_launcher.py."
    Write-Host "Optional: rerun with -TopSpinUserScriptDirectory <documented user script directory>."
}
Write-Host "Installation finished. Double-click scripts\launch_windows.cmd."
