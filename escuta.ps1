# "Olá, Jarvis": escuta em segundo plano que abre o painel quando você diz a frase.
#
# Uso, na pasta do projeto:
#   .\escuta.ps1 -Instalar   prepara tudo, baixa o modelo de voz (31 MB), liga a escuta
#                            ao entrar no Windows e já começa a ouvir
#   .\escuta.ps1 -Testar     mostra ao vivo o que o microfone está ouvindo (para conferir)
#   .\escuta.ps1 -Parar      para de ouvir agora (volta no próximo login, se instalada)
#   .\escuta.ps1 -Iniciar    volta a ouvir agora, sem abrir janela
#   .\escuta.ps1 -Remover    para de ouvir e não liga mais sozinha
#   .\escuta.ps1 -Status     mostra se está instalada e ouvindo
#   .\escuta.ps1 -PararServidor  fecha o servidor que a escuta abriu (ele roda sem janela)
#
# O reconhecimento é todo local: o áudio não é gravado nem sai do computador.
# Enquanto a escuta roda, o Windows mostra o ícone de microfone em uso.

param(
    [switch]$Instalar,
    [switch]$Testar,
    [switch]$Parar,
    [switch]$Iniciar,
    [switch]$Remover,
    [switch]$Status,
    [switch]$PararServidor
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$pythonw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$modelo = Join-Path $PSScriptRoot 'data\modelos\vosk-model-small-pt-0.3\final.mdl'
$atalho = Join-Path ([Environment]::GetFolderPath('Startup')) 'Jarvis - escuta.lnk'

function Escrever($texto, $cor = 'Cyan') { Write-Host $texto -ForegroundColor $cor }

function Parar-ComErro($texto) {
    Write-Host $texto -ForegroundColor Red
    exit 1
}

# Processos da escuta (e não o servidor, nem o modo de teste)
function Get-Escuta {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
        Where-Object { $_.CommandLine -match '-m app\.wake' -and $_.CommandLine -notmatch '--teste|--arquivo|--baixar' }
}

function Stop-Escuta {
    $processos = @(Get-Escuta)
    foreach ($p in $processos) { Stop-Process -Id $p.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue }
    return $processos.Count
}

function Start-Escuta {
    if (Get-Escuta) { Escrever 'A escuta já está ligada.'; return }
    if (-not (Test-Path -LiteralPath $pythonw)) { Parar-ComErro 'Ambiente não preparado. Rode: .\escuta.ps1 -Instalar' }
    if (-not (Test-Path -LiteralPath $modelo)) { Parar-ComErro 'Modelo de voz não encontrado. Rode: .\escuta.ps1 -Instalar' }
    Start-Process -FilePath $pythonw -ArgumentList '-m', 'app.wake' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    Escrever 'Escuta ligada. Diga "Olá, Jarvis" para abrir o painel.' 'Green'
}

if ($Instalar) {
    & (Join-Path $PSScriptRoot 'iniciar.ps1') -SomentePreparar
    if ($LASTEXITCODE -ne 0) { exit 1 }

    if (-not (Test-Path -LiteralPath $modelo)) {
        Escrever 'Baixando o modelo de voz em português (31 MB)...'
        & $python -m app.wake --baixar-modelo
        if ($LASTEXITCODE -ne 0) { Parar-ComErro 'Não foi possível baixar o modelo de voz. Confira a internet e rode de novo.' }
    }

    # Atalho na pasta Inicializar: liga a escuta sempre que você entra no Windows
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($atalho)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = '-m app.wake'
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.WindowStyle = 7
    $lnk.Description = 'Escuta "Olá, Jarvis" e abre o painel do assistente'
    $lnk.Save()
    Escrever 'A escuta vai ligar sozinha sempre que você entrar no Windows.'

    Start-Escuta
    Escrever 'Dica: rode .\escuta.ps1 -Testar para ver como o microfone ouve a sua voz.' 'DarkGray'
    exit 0
}

if ($Testar) {
    if (-not (Test-Path -LiteralPath $modelo)) { Parar-ComErro 'Modelo de voz não encontrado. Rode: .\escuta.ps1 -Instalar' }
    # Libera o microfone da escuta em segundo plano enquanto testa
    $parados = Stop-Escuta
    & $python -m app.wake --teste
    if ($parados -gt 0) { Start-Escuta }
    exit 0
}

if ($Parar) {
    $n = Stop-Escuta
    if ($n -gt 0) { Escrever 'Escuta desligada. O microfone está livre.' 'Green' } else { Escrever 'A escuta não estava ligada.' }
    exit 0
}

if ($Iniciar) {
    Start-Escuta
    exit 0
}

if ($Remover) {
    Stop-Escuta | Out-Null
    if (Test-Path -LiteralPath $atalho) { Remove-Item -LiteralPath $atalho -Force }
    Escrever 'Escuta removida: está desligada e não liga mais ao entrar no Windows.' 'Green'
    exit 0
}

if ($PararServidor) {
    # O servidor é "python -m app" (e não "-m app.wake", que é a escuta)
    $servidores = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match '-m app(\s|"|$)' -and $_.CommandLine -notmatch 'app\.wake' })
    foreach ($p in $servidores) { Stop-Process -Id $p.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue }
    if ($servidores.Count) { Escrever 'Servidor do assistente fechado.' 'Green' } else { Escrever 'O servidor não estava rodando.' }
    exit 0
}

if ($Status) {
    $instalada = Test-Path -LiteralPath $atalho
    $ligada = [bool](Get-Escuta)
    Escrever ("Liga ao entrar no Windows: " + $(if ($instalada) { 'sim' } else { 'não' }))
    Escrever ("Ouvindo agora:             " + $(if ($ligada) { 'sim' } else { 'não' }))
    Escrever ("Modelo de voz:             " + $(if (Test-Path -LiteralPath $modelo) { 'baixado' } else { 'não baixado' }))
    Escrever 'Registro da escuta: data\logs\escuta.log' 'DarkGray'
    exit 0
}

Get-Content -LiteralPath $PSCommandPath -TotalCount 12 -Encoding UTF8 | Select-Object -Skip 2 | ForEach-Object { $_ -replace '^# ?', '' }
