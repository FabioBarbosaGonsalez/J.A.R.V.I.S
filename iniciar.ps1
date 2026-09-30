# Inicia o assistente: prepara o ambiente (só quando precisa) e abre o painel no navegador.
#
# Uso, na pasta do projeto:
#   .\iniciar.ps1                  inicia e abre o navegador
#   .\iniciar.ps1 -SemNavegador    inicia sem abrir o navegador
#
# Na primeira vez, cria o ambiente virtual (.venv) e instala as dependências.
# Depois, só reinstala quando o requirements.txt muda. Se não houver .env,
# copia o .env.example (o painel abre no modo demonstração).
# Para encerrar o servidor, aperte Ctrl+C nesta janela.

param(
    [switch]$SemNavegador
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Escrever($texto, $cor = 'Cyan') {
    Write-Host $texto -ForegroundColor $cor
}

function Parar($texto) {
    Write-Host ''
    Write-Host $texto -ForegroundColor Red
    Write-Host ''
    # Aberto com duplo clique, a janela fecharia antes de dar para ler
    if ($Host.Name -eq 'ConsoleHost') { Read-Host 'Aperte Enter para fechar' | Out-Null }
    exit 1
}

# --- 1. Python 3.11 ou mais novo ------------------------------------------------

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    $base = $null
    foreach ($candidato in @(@('py', '-3'), @('python'))) {
        $exe = $candidato[0]
        $argsExtras = @($candidato | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $versao = & $exe @argsExtras -c 'import sys; print(sys.version_info >= (3, 11))' 2>$null
        if ($LASTEXITCODE -eq 0 -and $versao -eq 'True') { $base = $candidato; break }
    }
    if (-not $base) {
        Parar 'Python 3.11 ou mais novo não encontrado. Instale em https://www.python.org/downloads/ (marque "Add python.exe to PATH") e rode de novo.'
    }

    Escrever 'Criando o ambiente virtual (.venv)...'
    $exe = $base[0]
    $argsExtras = @($base | Select-Object -Skip 1)
    & $exe @argsExtras -m venv .venv
    if ($LASTEXITCODE -ne 0) { Parar 'Não foi possível criar o ambiente virtual.' }
}

# --- 2. Dependências (só quando o requirements.txt muda) ------------------------------

$marca = Join-Path $PSScriptRoot '.venv\requirements.sha256'
$hashAtual = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'requirements.txt') -Algorithm SHA256).Hash
$hashInstalado = if (Test-Path -LiteralPath $marca) { (Get-Content -LiteralPath $marca -Raw).Trim() } else { '' }

if ($hashAtual -ne $hashInstalado) {
    Escrever 'Instalando as dependências (pode levar alguns minutos na primeira vez)...'
    & $venvPython -m pip install --disable-pip-version-check -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Parar 'A instalação das dependências falhou. Confira a conexão com a internet e rode de novo.' }
    Set-Content -LiteralPath $marca -Value $hashAtual -Encoding ascii
}

# --- 3. Configuração -------------------------------------------------------------------

if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env'))) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.env.example') -Destination (Join-Path $PSScriptRoot '.env')
    Escrever 'Criei o arquivo .env a partir do modelo. O painel abre no modo demonstração;' 'Yellow'
    Escrever 'para usar seus dados, siga o README e mude DEMO_MODE=false no .env.' 'Yellow'
}

# --- 4. Servidor -----------------------------------------------------------------------

$argumentos = @('-m', 'app')
if (-not $SemNavegador) { $argumentos += '--open' }

& $venvPython @argumentos
$codigo = $LASTEXITCODE
if ($codigo -ne 0) { Parar 'O servidor parou com erro. Veja a mensagem acima.' }
