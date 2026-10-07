<#
.SYNOPSIS
    Compile le rapport PIQBIT en PDF.

.DESCRIPTION
    Enchaîne pdflatex -> biber -> pdflatex -> pdflatex, dans cet ordre et ce
    nombre de passes : la première produit les renvois et la liste des
    citations, biber construit la bibliographie, les deux dernières résolvent
    les renvois et stabilisent la table des matières.

    POURQUOI PAS latexmk — qui ferait tout cela seul : latexmk est un script
    Perl, et MiKTeX n'en fournit que le lanceur. Sans interpréteur Perl dans le
    PATH, il échoue sur « MiKTeX could not find the script engine 'perl' ».
    Perl EST présent sur la machine (livré avec Git, dans
    C:\Program Files\Git\usr\bin), mais hors du PATH de PowerShell. Ce script
    évite la dépendance entièrement.

    Le rapport est écrit pour pdfLaTeX. Tectonic ne convient pas : il repose
    sur XeTeX (le tiret cadratin « — » n'a pas de glyphe dans la police
    héritée chargée) et son lot de paquets embarque une biblatex incompatible
    avec le biber de MiKTeX.

.PARAMETER Clean
    Supprime les fichiers auxiliaires avant de compiler. À utiliser quand une
    compilation a laissé un état incohérent, ou après un changement de moteur :
    un .aux n'est pas portable d'un moteur à l'autre.

.PARAMETER Open
    Ouvre le PDF dans VS Code à la fin, si la compilation a réussi.

.EXAMPLE
    .\build.ps1
.EXAMPLE
    .\build.ps1 -Clean -Open
#>
[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$Open
)

Set-Location -LiteralPath $PSScriptRoot

$auxiliaires = @(
    'main.aux', 'main.bbl', 'main.bcf', 'main.blg', 'main.log',
    'main.lof', 'main.lot', 'main.out', 'main.run.xml', 'main.toc'
)

if ($Clean) {
    Write-Host '== Nettoyage des fichiers auxiliaires' -ForegroundColor Cyan
    foreach ($f in $auxiliaires) {
        if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f -Force }
    }
}

# Sous Windows, un lecteur PDF garde le fichier VERROUILLÉ tant qu'il l'affiche.
# pdflatex ne peut alors pas le réécrire et échoue par un message obscur
# (« I can't write on file `main.pdf' »), au bout de quatre passes. On le
# détecte avant de commencer, et on le dit clairement.
if (Test-Path -LiteralPath 'main.pdf') {
    try {
        $verrou = [System.IO.File]::Open(
            (Resolve-Path -LiteralPath 'main.pdf').Path, 'Open', 'ReadWrite', 'None')
        $verrou.Close()
        $verrou.Dispose()
    } catch {
        Write-Host ''
        Write-Host 'main.pdf est ouvert dans une autre application.' -ForegroundColor Red
        Write-Host 'Fermez-le (Acrobat, navigateur, apercu) puis relancez.' -ForegroundColor Red
        exit 1
    }
}

function Invoke-Passe {
    param(
        [string]   $Titre,
        [string]   $Exe,
        [string[]] $Arguments
    )
    Write-Host ''
    Write-Host "== $Titre" -ForegroundColor Cyan
    $sortie = & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host "ECHEC : $Exe a renvoye le code $LASTEXITCODE" -ForegroundColor Red
        Write-Host '--- dernieres lignes ---' -ForegroundColor DarkGray
        $sortie | Select-Object -Last 25
        if (Test-Path -LiteralPath 'main.log') {
            Write-Host ''
            Write-Host '--- erreurs relevees dans main.log ---' -ForegroundColor DarkGray
            Select-String -Path 'main.log' -Pattern '^!' | Select-Object -First 10
        }
        exit $LASTEXITCODE
    }
}

Invoke-Passe 'Passe 1/4 : pdflatex' 'pdflatex' @('-interaction=nonstopmode', 'main.tex')
Invoke-Passe 'Passe 2/4 : biber'    'biber'    @('main')
Invoke-Passe 'Passe 3/4 : pdflatex' 'pdflatex' @('-interaction=nonstopmode', 'main.tex')
Invoke-Passe 'Passe 4/4 : pdflatex' 'pdflatex' @('-interaction=nonstopmode', 'main.tex')

# ── Bilan ────────────────────────────────────────────────────────────────────
# Un code de retour nul ne suffit pas : pdflatex rend 0 en laissant des
# avertissements derriere lui. On relit donc main.log et on compte.
Write-Host ''
Write-Host '== Bilan' -ForegroundColor Cyan

$journal = Get-Content -LiteralPath 'main.log' -ErrorAction SilentlyContinue

function Compter {
    param([string]$Motif)
    return @($journal | Select-String -Pattern $Motif).Count
}

$mesures = [ordered]@{
    'Erreurs (!)'              = Compter '^!'
    'Avertissements LaTeX'     = Compter '^(LaTeX|Package|Class) .*Warning'
    'Overfull \hbox'           = Compter 'Overfull \\hbox'
    'Underfull \hbox'          = Compter 'Underfull \\hbox'
    'Renvois non resolus'      = Compter 'undefined'
    'Recompilation demandee'   = Compter 'Rerun to get'
}

$total = 0
foreach ($cle in $mesures.Keys) {
    $valeur = $mesures[$cle]
    $total += $valeur
    if ($valeur -eq 0) { $couleur = 'Green' } else { $couleur = 'Yellow' }
    Write-Host ("  {0,-26} {1}" -f $cle, $valeur) -ForegroundColor $couleur
}

$pages = $journal | Select-String -Pattern 'Output written on main\.pdf \((\d+) pages'
if ($pages) {
    $nb = $pages[-1].Matches[0].Groups[1].Value
    Write-Host ''
    Write-Host ("  PDF : main.pdf, {0} pages" -f $nb)
}

Write-Host ''
if ($total -eq 0) {
    Write-Host 'Compilation propre.' -ForegroundColor Green
} else {
    Write-Host 'Compilation reussie, mais main.log signale des points a regarder.' -ForegroundColor Yellow
}

if ($Open) {
    if (Test-Path -LiteralPath 'main.pdf') {
        # Invoke-Item et non `code` : VS Code n'affiche pas un PDF sans
        # extension dédiée, il annonce un fichier binaire. Invoke-Item passe
        # le fichier au lecteur associé du système, qui sait l'afficher.
        Invoke-Item -LiteralPath 'main.pdf'
    }
}
