# Diagnostico do PC - descobre o que da pra usar SEM admin.
# Como rodar: abra esta pasta no VSCode do PC, clique com o botao direito
# neste arquivo -> "Run in Integrated Terminal". Ou no terminal:
#     powershell -ExecutionPolicy Bypass -File "DIAGNOSTICO - rodar no PC.ps1"

$ErrorActionPreference = "SilentlyContinue"

function Titulo($t) {
    Write-Host ""
    Write-Host ("=" * 62) -ForegroundColor DarkGray
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ("=" * 62) -ForegroundColor DarkGray
}

Titulo "1. A MAQUINA"

$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
Write-Host ("  Nome do PC : " + $env:COMPUTERNAME)
Write-Host ("  Windows    : " + $os.Caption)
Write-Host ("  Dominio    : " + $cs.Domain)

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$pr = New-Object Security.Principal.WindowsPrincipal($id)
$admin = $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host ("  Usuario    : " + $id.Name)
if ($admin) {
    Write-Host "  Admin      : SIM" -ForegroundColor Green
} else {
    Write-Host "  Admin      : NAO (esperado)" -ForegroundColor Yellow
}

# Da pra virar admin digitando uma senha? (grupo de administradores local)
$grupo = @()
try {
    $grupo = (Get-LocalGroupMember -Group "Administradores" -EA Stop) |
             ForEach-Object { $_.Name }
} catch {
    try {
        $grupo = (Get-LocalGroupMember -Group "Administrators" -EA Stop) |
                 ForEach-Object { $_.Name }
    } catch { }
}
if ($grupo.Count -gt 0) {
    Write-Host "  Quem e admin neste PC:"
    $grupo | ForEach-Object { Write-Host ("     - " + $_) }
}

# Le os endpoints direto do registro: enxerga ate os que a interface esconde,
# que e justamente o caso do "Mixagem estereo" na maioria das maquinas Realtek.
function Endpoints($tipo) {
    $base = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\$tipo"
    Get-ChildItem $base -EA SilentlyContinue | ForEach-Object {
        $prop = Join-Path $_.PSPath "Properties"
        $pl = Get-ItemProperty $prop -EA SilentlyContinue
        $desc = $pl."{a45c254e-df1c-4efd-8020-67d146a850e0},2"   # ex: "Mixagem estereo"
        $placa = $pl."{b3f8fa53-0004-438e-9003-51a46e139bfc},6"  # ex: "Realtek(R) Audio"
        if (-not $desc) { return }
        $st = (Get-ItemProperty $_.PSPath -EA SilentlyContinue).DeviceState
        # o byte alto (0x10000000) so marca "oculto na interface"
        $real = $st -band 0xFFFF
        $txt = switch ($real) {
            1 { if ($st -band 0x10000000) { "ativo (oculto)" } else { "ativo" } }
            2 { "DESABILITADO" }
            4 { "ausente" }
            8 { "desconectado" }
            default { "estado $st" }
        }
        [pscustomobject]@{ Nome = $desc; Placa = $placa; Estado = $txt; Usavel = ($real -eq 1 -or $real -eq 2) }
    }
}

Titulo "2. MICROFONE VIRTUAL - ja existe algum?"

$entradas = @(Endpoints "Capture")
$temCable = @($entradas | Where-Object { $_.Nome -match "CABLE" -or $_.Placa -match "CABLE" }).Count -gt 0
$mix      = @($entradas | Where-Object { $_.Nome -match "Mixagem|Stereo Mix|What U Hear|Mixage" -and $_.Usavel })

Write-Host "  Entradas (microfones) que este PC conhece:"
$entradas | Where-Object { $_.Estado -notmatch "ausente" } | Sort-Object Nome | ForEach-Object {
    Write-Host ("     [{0,-14}] {1}  ({2})" -f $_.Estado, $_.Nome, $_.Placa)
}

Write-Host ""
if ($temCable) {
    Write-Host "  >> VB-CABLE JA ESTA INSTALADO NESTE PC." -ForegroundColor Green
    Write-Host "     Use o plano original, nao precisa de admin nem de mais nada."
} elseif ($mix.Count -gt 0) {
    Write-Host ("  >> ACHEI '" + $mix[0].Nome + "'.") -ForegroundColor Green
    Write-Host "     Da pra usar como microfone SEM instalar nada e SEM admin."
    Write-Host "     Se estiver oculto ou desabilitado, habilite assim:"
    Write-Host "       1. Botao direito no icone de som -> Configuracoes de som"
    Write-Host "       2. Role ate o fim -> 'Mais configuracoes de som'"
    Write-Host "       3. Aba 'Gravacao' -> botao direito numa area vazia"
    Write-Host "       4. Marque 'Mostrar dispositivos desabilitados'"
    Write-Host "       5. Botao direito em 'Mixagem estereo' -> Habilitar"
    Write-Host ""
    Write-Host "     ATENCAO: sozinho ele causa eco (a outra pessoa se ouve)." -ForegroundColor Yellow
    Write-Host "     A secao 3 diz se este PC tem como evitar isso."
} else {
    Write-Host "  >> Nao achei nem VB-Cable nem Mixagem estereo." -ForegroundColor Yellow
    Write-Host "     Caminho: pedir ao TI (tem um texto pronto no LEIA-ME)."
}

Titulo "3. SAIDAS DE AUDIO - da pra evitar o eco?"

$saidas = @(Endpoints "Render" | Where-Object { $_.Estado -notmatch "ausente" })
Write-Host "  Saidas que este PC conhece:"
$saidas | Sort-Object Nome | ForEach-Object {
    Write-Host ("     [{0,-14}] {1}  ({2})" -f $_.Estado, $_.Nome, $_.Placa)
}

# placas de som fisicamente distintas: e o que permite separar os caminhos
$placas = @($saidas | Where-Object { $_.Estado -match "ativo" } |
            Select-Object -ExpandProperty Placa -Unique)
Write-Host ""
Write-Host ("  Placas de som independentes e ativas: " + $placas.Count)
$placas | ForEach-Object { Write-Host ("     - " + $_) }

if ($placas.Count -ge 2) {
    Write-Host ""
    Write-Host "  >> BOM: com 2+ placas da pra separar os caminhos de audio" -ForegroundColor Green
    Write-Host "     e usar o Stereo Mix sem eco. O Claude te passa o ajuste."
} elseif ($mix.Count -gt 0) {
    Write-Host ""
    Write-Host "  >> So uma placa ativa. O Stereo Mix vai captar tambem o audio" -ForegroundColor Yellow
    Write-Host "     da ligacao, e a outra pessoa vai se ouvir. Pode ate funcionar"
    Write-Host "     se o programa de ligacao tiver cancelamento de eco bom, mas"
    Write-Host "     o caminho confiavel aqui e o VB-Cable pelo TI."
}

Titulo "4. PYTHON - da pra rodar o AudioLink aqui?"

$py = $null
foreach ($c in @("python", "py", "python3")) {
    $v = & $c --version 2>&1
    if ($LASTEXITCODE -eq 0) { $py = "$c -> $v"; break }
}
if ($py) {
    Write-Host ("  Python OK: " + $py) -ForegroundColor Green
} else {
    Write-Host "  Python nao encontrado." -ForegroundColor Yellow
    Write-Host "  Sem admin, instale so pra voce (nao pede senha):"
    Write-Host "     https://python.org/downloads  -> marque 'Install for me only'"
    Write-Host "  Ou, se o PC tiver loja: winget install Python.Python.3.12"
}

Titulo "5. O QUE O TI BLOQUEIA"

$pol = "HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services"
$audioIn = (Get-ItemProperty $pol -Name fDisableAudioCapture -EA SilentlyContinue).fDisableAudioCapture
if ($audioIn -eq 1) {
    Write-Host "  Redirecionamento de microfone por RDP: BLOQUEADO por politica" -ForegroundColor Yellow
} elseif ($null -eq $audioIn) {
    Write-Host "  Redirecionamento de microfone por RDP: sem politica definida"
} else {
    Write-Host "  Redirecionamento de microfone por RDP: permitido" -ForegroundColor Green
}

$deny = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server" -Name fDenyTSConnections -EA SilentlyContinue).fDenyTSConnections
if ($deny -eq 0) {
    Write-Host "  Servidor RDP neste PC: LIGADO" -ForegroundColor Green
    Write-Host "     Se o Windows aqui for Pro/Enterprise, talvez nem precise do AudioLink:"
    Write-Host "     o RDP leva seu microfone nativamente."
} else {
    Write-Host "  Servidor RDP neste PC: desligado"
}

Titulo "RESUMO - mande este resultado inteiro pro Claude"

if ($temCable) {
    Write-Host "  CAMINHO: VB-Cable ja existe -> usar o plano original." -ForegroundColor Green
} elseif ($admin) {
    Write-Host "  CAMINHO: voce E admin aqui -> instalar o VB-Cable normalmente." -ForegroundColor Green
} elseif ($mix.Count -gt 0 -and $placas.Count -ge 2) {
    Write-Host "  CAMINHO: Stereo Mix + saidas separadas. Funciona sem admin." -ForegroundColor Green
} elseif ($mix.Count -gt 0) {
    Write-Host "  CAMINHO: Stereo Mix existe, mas com risco de eco." -ForegroundColor Yellow
    Write-Host "           Da pra tentar; o certo e o VB-Cable pelo TI."
} else {
    Write-Host "  CAMINHO: pedir ao TI pra instalar o VB-Cable (gratuito, 1.3 MB)." -ForegroundColor Yellow
}

Write-Host ""
Read-Host "Pressione ENTER para fechar"
