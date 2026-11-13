# Prueba de humo del paquete portable: lo descomprime en <Base>\limpio y corre la CLI y el visor sin el Python del sistema ni PEGCRAFT_*.
# Uso (PowerShell 5.1):  powershell -File tools\empaquetar\prueba_limpia.ps1 -Zip dist\pegcraft-visor-<version>-win64.zip -Base <carpeta temporal>
# Deja en <Base>\cwd: x.png (pegcraft ver), horneado\, analisis*, visor.png. Al final dice si la carpeta del paquete cambió (no debe cambiar).
param([Parameter(Mandatory = $true)][string]$Zip, [Parameter(Mandatory = $true)][string]$Base)
$ErrorActionPreference = 'Continue'
$Zip = (Resolve-Path $Zip).Path
$limpio = Join-Path $Base 'limpio'
$cwd = Join-Path $Base 'cwd'
foreach ($d in $limpio, $cwd) { if (Test-Path $d) { Remove-Item $d -Recurse -Force } }   # carpetas temporales propias de esta prueba
New-Item -ItemType Directory $limpio, $cwd | Out-Null
Expand-Archive -LiteralPath $Zip -DestinationPath $limpio
$pk = Get-ChildItem $limpio | Select-Object -First 1 -ExpandProperty FullName
Write-Output "paquete: $pk"
# entorno reducido: sin Python del sistema ni PEGCRAFT_* / PYTHON*
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
Get-ChildItem Env: | Where-Object { $_.Name -like 'PEGCRAFT_*' -or $_.Name -like 'PYTHON*' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
function Snapshot($d) { Get-ChildItem $d -Recurse -Force -File | ForEach-Object { "$($_.FullName)|$($_.Length)|$($_.LastWriteTimeUtc.Ticks)" } | Sort-Object }
Snapshot $pk | Set-Content (Join-Path $Base 'antes.txt')
$esc = Join-Path $pk 'ejemplos\escena_minima\escena.xstage'
$cli = Join-Path $pk 'pegcraft.cmd'
$py = Join-Path $pk 'python\python.exe'
Set-Location $cwd
$fallos = 0

Write-Output '--- 1. pegcraft.cmd ver'
& $cli ver $esc 1 -o x.png; if ($LASTEXITCODE) { $fallos++ }; Write-Output "exit=$LASTEXITCODE"
& $py -B (Join-Path $PSScriptRoot 'comparar_png.py') x.png (Join-Path $pk 'ejemplos\escena_minima\esperado_f1.png'); if ($LASTEXITCODE) { $fallos++ }

Write-Output '--- 2. pegcraft.cmd hornear-rango'
& $cli hornear-rango $esc (Join-Path $cwd 'horneado') --desde 1 --hasta 2; if ($LASTEXITCODE) { $fallos++ }; Write-Output "exit=$LASTEXITCODE"

Write-Output '--- 3. pegcraft.cmd analizar --compartible'
& $cli analizar (Join-Path $pk 'ejemplos') --log (Join-Path $cwd 'analisis') --compartible; if ($LASTEXITCODE) { $fallos++ }; Write-Output "exit=$LASTEXITCODE"

Write-Output '--- 4. visor --abrir ... --gpu --screenshot'
$p = Start-Process -FilePath (Join-Path $pk 'pegcraft-visor.exe') -ArgumentList @('--abrir', $esc, '--frames', '1:1', '--gpu', '--screenshot', (Join-Path $cwd 'visor.png')) -PassThru -Wait -WindowStyle Hidden
if ($p.ExitCode) { $fallos++ }; Write-Output "exit=$($p.ExitCode)"

Snapshot $pk | Set-Content (Join-Path $Base 'despues.txt')
Write-Output '--- 5. carpeta del paquete (antes vs despues)'
$d = Compare-Object (Get-Content (Join-Path $Base 'antes.txt')) (Get-Content (Join-Path $Base 'despues.txt'))
if ($d) { $fallos++; $d | Select-Object -First 20 | ForEach-Object { "$($_.SideIndicator) $($_.InputObject)" } } else { 'sin cambios' }
Write-Output "=== fallos: $fallos"
exit $fallos
