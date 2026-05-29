<#
.SYNOPSIS
  Lightweight, git-isolated working-tree checkpoints with N-step rollback.

  A "checkpoint" snapshots the whole working tree (tracked + untracked, respecting
  .gitignore) into git's object store under a PRIVATE ref chain (refs/checkpoints/auto).
  It does NOT create branch commits and never touches your real history/index — so it
  coexists with the external auto-commit script. Designed to be fired automatically
  before each agent (Codex) action so you can undo a change you don't like.

.DESCRIPTION
  Commands:
    save   [label]   Take a checkpoint of the current working tree.
    list             Show checkpoints, newest first. Index 0 = latest.
    diff   <n>       Show files that differ between now and checkpoint <n>.
    rollback <n>     Restore the working tree to checkpoint <n> (n steps before the
                     latest). A safety snapshot of the CURRENT state is taken first,
                     so `rollback 0` always undoes the last rollback. Nothing is lost.

.EXAMPLE
  ./checkpoint.ps1 save "before codex run"
  ./checkpoint.ps1 list
  ./checkpoint.ps1 rollback 2     # go back to 2 checkpoints ago
  ./checkpoint.ps1 rollback 0     # undo that rollback
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][ValidateSet('save', 'list', 'diff', 'rollback')] [string]$Command = 'list',
    [Parameter(Position = 1)][string]$Arg,
    [switch]$Yes   # skip the rollback confirmation prompt (for scripted use)
)

$ErrorActionPreference = 'Stop'
$REF = 'refs/checkpoints/auto'

function Resolve-Git {
    $c = Get-Command git -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in @("C:\Program Files\Git\cmd\git.exe", "C:\Program Files\Git\bin\git.exe", "C:\Program Files (x86)\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe")) {
        if (Test-Path $p) { return $p }
    }
    throw "git executable not found. Install Git or add it to PATH."
}
$GIT = Resolve-Git

# core.autocrlf/safecrlf off: snapshots store exact worktree bytes (and it
# silences the per-file "LF will be replaced by CRLF" warnings on `add`).
function git_() { & $GIT -c core.quotePath=false -c core.autocrlf=false -c core.safecrlf=false @args }

$TOP = (git_ rev-parse --show-toplevel).Trim()
if (-not $TOP) { throw "Not inside a git repository." }

function Ref-Exists([string]$rev) {
    & $GIT rev-parse --verify -q "$rev" *> $null
    return $LASTEXITCODE -eq 0
}

function New-Snapshot([string]$label) {
    # Snapshot the worktree into a tree using a throwaway index (never touches the real one).
    $tmpIndex = Join-Path ([System.IO.Path]::GetTempPath()) ("ckpt_idx_" + [guid]::NewGuid().ToString('N'))
    try {
        $env:GIT_INDEX_FILE = $tmpIndex
        git_ -C $TOP add -A
        $tree = (git_ -C $TOP write-tree).Trim()
    } finally {
        Remove-Item $env:GIT_INDEX_FILE -ErrorAction SilentlyContinue
        Remove-Item Env:\GIT_INDEX_FILE -ErrorAction SilentlyContinue
    }
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $msg = if ($label) { "$label | $stamp" } else { "checkpoint | $stamp" }
    if (Ref-Exists $REF) {
        $parent = (git_ rev-parse $REF).Trim()
        $commit = (git_ commit-tree $tree -p $parent -m $msg).Trim()
    } else {
        $commit = (git_ commit-tree $tree -m $msg).Trim()
    }
    git_ update-ref $REF $commit
    return $commit
}

function Get-Target([string]$nRaw) {
    if ([string]::IsNullOrWhiteSpace($nRaw)) { throw "Checkpoint index required (e.g. rollback 2)." }
    if (-not (Ref-Exists $REF)) { throw "No checkpoints yet. Run: checkpoint.ps1 save" }
    $n = [int]$nRaw
    $rev = if ($n -eq 0) { $REF } else { "$REF~$n" }
    if (-not (Ref-Exists $rev)) {
        $count = [int](git_ rev-list --count $REF).Trim()
        throw "Only $count checkpoint(s) exist; cannot go back $n."
    }
    return (git_ rev-parse $rev).Trim()
}

function Invoke-Save {
    $sha = New-Snapshot $Arg
    Write-Host ("checkpoint saved: {0}  ({1})" -f $sha.Substring(0, 8), ($(if ($Arg) { $Arg } else { 'no label' }))) -ForegroundColor Green
}

function Invoke-List {
    if (-not (Ref-Exists $REF)) { Write-Host "No checkpoints yet. Run: checkpoint.ps1 save"; return }
    $lines = git_ log $REF --format='%H%x09%cd%x09%s' --date=format:'%Y-%m-%d %H:%M:%S'
    $i = 0
    foreach ($ln in $lines) {
        $parts = $ln -split "`t", 3
        Write-Host ("[{0,2}] {1}  {2}  {3}" -f $i, $parts[0].Substring(0, 8), $parts[1], $parts[2])
        $i++
    }
    Write-Host "`nrollback with: checkpoint.ps1 rollback <index>   (0 = latest)"
}

function Invoke-Diff {
    $target = Get-Target $Arg
    $now = New-Snapshot "diff-probe (transient)"
    Write-Host "Files that differ between NOW and checkpoint [$Arg]:" -ForegroundColor Cyan
    git_ diff --name-status $target $now
}

function Invoke-Rollback {
    $target = Get-Target $Arg
    if (-not $Yes) {
        Write-Host "About to restore the working tree to checkpoint [$Arg] ($($target.Substring(0,8)))." -ForegroundColor Yellow
        Write-Host "A safety snapshot of the current state will be taken first (undo with: rollback 0)."
        $ans = Read-Host "Proceed? (y/N)"
        if ($ans -notmatch '^(y|yes)$') { Write-Host "Aborted."; return }
    }
    # 1. Safety snapshot of current state (becomes the new latest).
    $safety = New-Snapshot "pre-rollback safety"
    # 2. Delete files that exist now but are absent in the target (added since target).
    $toDelete = git_ diff --name-only --diff-filter=A $target $safety
    foreach ($rel in $toDelete) {
        if ([string]::IsNullOrWhiteSpace($rel)) { continue }
        $full = Join-Path $TOP ($rel -replace '/', '\')
        Remove-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
    }
    # 3. Materialize the target's files over the worktree (restores modified + deleted).
    $tmpIndex = Join-Path ([System.IO.Path]::GetTempPath()) ("ckpt_ro_" + [guid]::NewGuid().ToString('N'))
    try {
        $env:GIT_INDEX_FILE = $tmpIndex
        git_ -C $TOP read-tree $target
        git_ -C $TOP checkout-index -a -f
    } finally {
        Remove-Item $env:GIT_INDEX_FILE -ErrorAction SilentlyContinue
        Remove-Item Env:\GIT_INDEX_FILE -ErrorAction SilentlyContinue
    }
    Write-Host ("Rolled back to checkpoint [{0}] ({1})." -f $Arg, $target.Substring(0, 8)) -ForegroundColor Green
    Write-Host ("Pre-rollback state saved as latest ({0}). Undo with: checkpoint.ps1 rollback 0" -f $safety.Substring(0, 8))
}

switch ($Command) {
    'save' { Invoke-Save }
    'list' { Invoke-List }
    'diff' { Invoke-Diff }
    'rollback' { Invoke-Rollback }
}
