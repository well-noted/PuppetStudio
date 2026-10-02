param([switch]$SetupOnly,[Parameter(ValueFromRemainingArguments=$true)][string[]]$StudioArgs)
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
$env:PYTHONUTF8='1';$env:PYTHONIOENCODING='utf-8'
function Find-StudioPython {
 $candidates=@((Join-Path $PSScriptRoot '.venv\Scripts\python.exe'))
 $command=Get-Command python -ErrorAction SilentlyContinue
 if($command){$candidates+=$command.Source}
 foreach($registry in @('HKCU:\Software\Python\PythonCore','HKLM:\Software\Python\PythonCore')){
  if(Test-Path $registry){Get-ChildItem $registry | ForEach-Object {
   $install=Join-Path $_.PSPath 'InstallPath'
   if(Test-Path $install){$script:registryCandidates+=@((Join-Path (Get-Item $install).GetValue('') 'python.exe'))}
  }}
 }
 $candidates+=$script:registryCandidates
 foreach($candidate in ($candidates | Select-Object -Unique)){
  if(!$candidate -or !(Test-Path $candidate)){continue}
  try{$answer=& $candidate -c "import sys;print('STUDIO_OK' if (3,10)<=sys.version_info[:2]<=(3,12) else 'NO')" 2>$null
   if($LASTEXITCODE -eq 0 -and $answer -eq 'STUDIO_OK'){return $candidate}
  }catch{}
 }
 return $null
}
try {
 $python=Find-StudioPython
 if(!$python){
  if(![Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64'){throw 'This bootstrap requires Windows x64.'}
  $tools=Join-Path $env:LOCALAPPDATA 'PuppetStudio\tools'
  if($env:STUDIO_TOOLS_HOME){$tools=$env:STUDIO_TOOLS_HOME}
  $uv=Join-Path $tools 'uv\uv.exe'
  if(!(Test-Path $uv)){
   New-Item -ItemType Directory -Force (Join-Path $tools 'downloads') | Out-Null
   $archive=Join-Path $tools 'downloads\uv.zip'
   Write-Host 'No suitable Python found. Downloading a private Python manager (uv)...'
   Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/download/0.8.22/uv-x86_64-pc-windows-msvc.zip' -OutFile $archive -UseBasicParsing
   Expand-Archive $archive (Join-Path $tools 'uv') -Force
  }
  Write-Host 'Installing private Python 3.11 for Studio...'
  & $uv python install 3.11
  if($LASTEXITCODE){throw 'Private Python installation failed; check internet access.'}
  $python=(& $uv python find --python-preference only-managed 3.11 | Select-Object -Last 1)
  if($LASTEXITCODE -or !(Test-Path $python)){throw 'Could not locate downloaded Python.'}
 }
 $studio=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
 if($SetupOnly -or !(Test-Path $studio)){
  Write-Host "Setting up Studio with $python"
  & $python setup.py --transcription --anatomy
  if($LASTEXITCODE){throw 'Studio package installation failed. Completed downloads remain available.'}
 }
 if(!$SetupOnly){& $studio studio.py @StudioArgs;exit $LASTEXITCODE}
}catch{Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red;exit 1}
