<#
.SYNOPSIS
  Multi-round project debate across three AI agents (claude / gemini / codex).

  Each agent argues a topic about THIS repo; in later rounds each sees the others'
  previous points and can rebut/refine. The result is a single transcript file.
  You then ask the interactive Claude Code session to synthesize it (it has the
  conversation context the headless agents lack).

  Codex always runs --sandbox read-only here: a discussion must never edit code.

.EXAMPLE
  ./discuss.ps1 "Should the survivorship backfill be on by default?" -Rounds 2
  ./discuss.ps1 "How to make checkpoints faster on this OneDrive tree?" -Yes
  ./discuss.ps1 "Topic" -ClaudeModel opus -GeminiModel gemini-3-flash-preview -CodexReasoningEffort high
  ./discuss.ps1 "Topic" -Rounds 2 -UntilConsensus -MaxRounds 6
  # then, in Claude Code:  "synthesize the discussion <path printed below>"
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)][string]$Topic,
    [string]$AgentTopic, # English topic sent to agents when display title uses Chinese
    [int]$Rounds = 2,
    [switch]$UntilConsensus, # continue after minimum rounds until all agents explicitly agree
    [int]$MaxRounds = 6,     # hard cap in consensus mode to prevent unbounded billed calls
    [string]$ClaudeModel = 'opus',
    [ValidateSet('low', 'medium', 'high', 'xhigh', 'max')][string]$ClaudeEffort = 'high',
    [string]$GeminiModel = 'gemini-3-flash-preview',
    [string[]]$GeminiFallbackModels = @('gemini-2.5-flash'),
    [string]$CodexModel = 'gpt-5.5',
    [ValidateSet('low', 'medium', 'high', 'xhigh')][string]$CodexReasoningEffort = 'high',
    [int]$AgentTimeoutSeconds = 180, # maximum duration for one agent response
    [switch]$Yes,       # skip the cost/time confirmation
    [switch]$NoHuman,   # agent-only debate (no human turn each round)
    [switch]$DryRun,    # show model profile without making billed calls
    [string]$OutFile
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
. (Join-Path $Root 'agent_log.ps1')   # Write-AgentEvent for the dashboard (best-effort)
$PromptTopic = if ([string]::IsNullOrWhiteSpace($AgentTopic)) { $Topic } else { $AgentTopic }
if ($Rounds -lt 1) { throw "Rounds must be at least 1." }
if ($UntilConsensus -and $MaxRounds -lt $Rounds) {
    throw "MaxRounds must be greater than or equal to Rounds when -UntilConsensus is enabled."
}
if ($AgentTimeoutSeconds -lt 30) { throw "AgentTimeoutSeconds must be at least 30." }

# Resolve git toplevel for codex --cd and project brief.
function Resolve-Tool([string]$name) {
    # Prefer .cmd shims so Windows execution policy does not block npm .ps1 wrappers.
    $cmdShim = Join-Path $env:APPDATA "npm\$name.cmd"
    if (Test-Path $cmdShim) { return $cmdShim }
    $cmd = Get-Command "$name.cmd" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $c = Get-Command $name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}
$GEMINI = Resolve-Tool 'gemini'
$CLAUDE = Resolve-Tool 'claude'
$CODEX = Resolve-Tool 'codex'
$GIT = Resolve-Tool 'git'
if (-not $GIT) { foreach ($p in @("C:\Program Files\Git\cmd\git.exe", "C:\Program Files\Git\bin\git.exe")) { if (Test-Path $p) { $GIT = $p; break } } }
$TOP = if ($GIT) { (& $GIT rev-parse --show-toplevel 2>$null).Trim() } else { (Get-Location).Path }

# Light role nudges so the three voices differ instead of echoing each other.
$Roles = [ordered]@{
    claude = "Focus on correctness, architecture, edge cases, and risks."
    gemini = "Focus on alternatives, external research angles, and testable hypotheses."
    codex  = "Focus on current implementation, feasible next steps, and engineering cost."
}
$Available = @{}
if ($CLAUDE) { $Available['claude'] = $true }
if ($GEMINI) { $Available['gemini'] = $true }
if ($CODEX) { $Available['codex'] = $true }
$Participants = $Roles.Keys | Where-Object { $Available[$_] }
if (-not $Participants) { throw "None of claude/gemini/codex are on PATH." }

# Compact project brief (current, cheap) from CLAUDE.md so agents have context
# without each one crawling the repo.
$brief = ""
$claudeMd = Join-Path $TOP 'CLAUDE.md'
if (Test-Path $claudeMd) { $brief = ((Get-Content $claudeMd -TotalCount 40) -join "`n") }

$plannedRounds = if ($UntilConsensus) { $MaxRounds } else { $Rounds }
$calls = $Participants.Count * $plannedRounds
$humanOn = -not $NoHuman
$seats = if ($humanOn) { "$($Participants -join ', '), you (human)" } else { $Participants -join ', ' }
Write-Host "Display topic : $Topic"
if ($AgentTopic) { Write-Host "Agent topic  : $AgentTopic" }
Write-Host "Participants  : $seats"
if ($UntilConsensus) {
    Write-Host "Rounds        : minimum=$Rounds, until consensus, maximum=$MaxRounds   (up to ~$calls agent calls)"
} else {
    Write-Host "Rounds        : $Rounds   (~$calls agent calls)"
}
Write-Host "Models        : claude=$ClaudeModel (effort=$ClaudeEffort), gemini=$GeminiModel, codex=$CodexModel (reasoning=$CodexReasoningEffort)"
Write-Host "Seat timeout  : $AgentTimeoutSeconds seconds"
if ($humanOn) { Write-Host "You get one steering turn each round (use English; press Enter to skip)." }
if (-not $AgentTopic -and $Topic -match '[^\x00-\x7F]') {
    Write-Warning "Chinese topic text can be corrupted when piped to Claude on this Windows path. Re-run with -AgentTopic '<English topic>'."
}
if ($DryRun) {
    Write-Host "[dry-run] No agent calls or billed usage." -ForegroundColor Yellow
    Write-Host "  claude: claude -p --model $ClaudeModel --effort $ClaudeEffort --permission-mode plan --tools Read,Glob,Grep"
    Write-Host "  gemini: gemini --skip-trust --approval-mode plan -m $GeminiModel -p <prompt> (fallback: $($GeminiFallbackModels -join ', '))"
    Write-Host "  codex : codex exec --cd `"$TOP`" --sandbox read-only -m $CodexModel -c 'model_reasoning_effort=`"$CodexReasoningEffort`"'"
    Write-Host "  timeout: $AgentTimeoutSeconds seconds per agent response"
    if ($UntilConsensus) {
        Write-Host "  stop  : after round $Rounds all seats must emit 'Consensus: Agree'; otherwise stop at round $MaxRounds"
    }
    return
}
if (-not $Yes) {
    $ans = Read-Host "This makes billed agent calls and can take several minutes. Proceed? (y/N)"
    if ($ans -notmatch '^(y|yes)$') { Write-Host "Aborted."; return }
}

function Ask-Agent([string]$name, [string]$prompt) {
    # Run each native CLI in its own background pipeline so one stalled provider
    # cannot hold the entire meeting open indefinitely.
    $job = Start-Job -ScriptBlock {
        param(
            [string]$Name,
            [string]$Prompt,
            [string]$Top,
            [string]$Claude,
            [string]$Gemini,
            [string]$Codex,
            [string]$ClaudeModel,
            [string]$ClaudeEffort,
            [string]$GeminiModel,
            [string[]]$GeminiFallbackModels,
            [string]$CodexModel,
            [string]$CodexReasoningEffort
        )
        $ErrorActionPreference = 'Continue'
        try {
            switch ($Name) {
                'claude' {
                    Set-Location $Top
                    return ($Prompt | & $Claude -p --model $ClaudeModel --effort $ClaudeEffort --permission-mode plan --tools "Read,Glob,Grep" 2>$null | Out-String).Trim()
                }
                'gemini' {
                    $models = @($GeminiModel) + @($GeminiFallbackModels) | Select-Object -Unique
                    $failures = [System.Collections.Generic.List[string]]::new()
                    foreach ($model in $models) {
                        $stderrFile = Join-Path ([System.IO.Path]::GetTempPath()) ("discuss_gemini_err_" + [guid]::NewGuid().ToString('N') + ".txt")
                        Set-Location $Top
                        $raw = (& $Gemini --skip-trust --approval-mode plan -m $model -p $Prompt 2> $stderrFile | Out-String)
                        $exitCode = $LASTEXITCODE
                        $stderr = if (Test-Path $stderrFile) { Get-Content $stderrFile -Raw } else { "" }
                        Remove-Item $stderrFile -ErrorAction SilentlyContinue
                        $clean = $raw.Trim()
                        $failed = $exitCode -ne 0 -or
                            [string]::IsNullOrWhiteSpace($clean) -or
                            $clean -match 'ModelNotFoundError|Requested entity was not found|unexpected critical error' -or
                            $stderr -match 'ModelNotFoundError|Requested entity was not found|unexpected critical error'
                        if (-not $failed) {
                            if ($model -ne $GeminiModel) {
                                return "<!-- gemini fallback model used: $model (requested: $GeminiModel) -->`n$clean"
                            }
                            return $clean
                        }
                        $failureText = if ($clean) { $clean } else { $stderr }
                        $briefFailure = ($failureText -split "`r?`n" | Select-Object -First 2) -join " "
                        $failures.Add("$model`: $briefFailure")
                    }
                    return "(gemini unavailable; tried $($models -join ', '). $($failures -join ' | '))"
                }
                'codex' {
                    $out = Join-Path ([System.IO.Path]::GetTempPath()) ("discuss_codex_" + [guid]::NewGuid().ToString('N') + ".txt")
                    $reasoningConfig = 'model_reasoning_effort="{0}"' -f $CodexReasoningEffort
                    $Prompt | & $Codex exec --cd $Top --sandbox read-only -m $CodexModel -c $reasoningConfig -o $out *> $null
                    $txt = if (Test-Path $out) { (Get-Content $out -Raw).Trim() } else { "(no output)" }
                    Remove-Item $out -ErrorAction SilentlyContinue
                    return $txt
                }
            }
        } catch {
            return "(error from ${Name}: $($_.Exception.Message))"
        }
    } -ArgumentList @(
        $name, $prompt, $TOP, $CLAUDE, $GEMINI, $CODEX, $ClaudeModel, $ClaudeEffort,
        $GeminiModel, $GeminiFallbackModels, $CodexModel, $CodexReasoningEffort
    )
    try {
        $finished = Wait-Job -Job $job -Timeout $AgentTimeoutSeconds
        if (-not $finished) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue
            return "(timeout from ${name}: exceeded $AgentTimeoutSeconds seconds)"
        }
        $result = (Receive-Job -Job $job -ErrorAction SilentlyContinue | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($result)) { return "(no output from $name)" }
        return $result
    } finally {
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
}

function Test-AgentAgreement([string]$answer) {
    return -not [string]::IsNullOrWhiteSpace($answer) -and
        ($answer -match '(?im)^\s*Consensus:\s*Agree\s*$' -or
         $answer -match '(?im)^\s*共識狀態[：:]\s*同意\s*$' -or
         $answer -match '(?im)^\s*CONSENSUS_STATUS:\s*AGREE\s*$')
}

$transcript = [System.Collections.Generic.List[string]]::new()
$transcript.Add("# Roundtable: $Topic")
$transcript.Add("")
$roundLabel = if ($UntilConsensus) { "minimum $Rounds / maximum $MaxRounds / stop on consensus" } else { "$Rounds" }
$transcript.Add("Participants: $($Participants -join ', ') | Rounds: $roundLabel | Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm')")
$transcript.Add("Models: claude=$ClaudeModel (effort=$ClaudeEffort) | gemini=$GeminiModel | codex=$CodexModel (reasoning=$CodexReasoningEffort)")
if ($AgentTopic) { $transcript.Add("Agent topic: $AgentTopic") }
$transcript.Add("")

$prevRound = [ordered]@{}   # participant (incl. "you") -> last contribution
$consensusReached = $false
$completedRounds = 0
$RunId = New-AgentRunId
for ($r = 1; $r -le $plannedRounds; $r++) {
    $completedRounds = $r
    Write-Host "`n=== Round $r ===" -ForegroundColor Cyan
    $thisRound = [ordered]@{}
    foreach ($name in $Participants) {
        Write-Host "  詢問 $name..." -NoNewline
        if ($prevRound.Count -eq 0) {
            $p = @"
You are "$name", one participant in a project roundtable with other AI agents and one human.
$($Roles[$name])
Reply in concise English, no more than 100 words. This is a discussion, not an implementation task.
You may inspect the repository read-only to verify facts, but do not write a plan, modify files, or fill another seat.
Use exactly this format:
Position: <one sentence>
Reasons: <up to two points separated by semicolons>
Recommendation: <one next-step sentence>

PROJECT BRIEF:
$brief

TOPIC:
$PromptTopic

Give your initial position.
"@
        } else {
            $others = ($prevRound.Keys | Where-Object { $_ -ne $name } | ForEach-Object { "### $_ previous view:`n$($prevRound[$_])" }) -join "`n`n"
            $p = @"
You are "$name" in round $r of a project roundtable with other AI agents and one human.
Give careful weight to the human's steering input.
$($Roles[$name])
Reply in concise English, no more than 100 words. This is a discussion, not an implementation task.
You may verify facts read-only, but do not write a plan, edit files, or rewrite earlier rounds.
After reading the previous views, use exactly this format:
Position: <Agree/Partly agree/Disagree, then one-sentence conclusion>
Reasons: <up to two points separated by semicolons>
Recommendation: <one next-step sentence>

TOPIC:
$PromptTopic

OTHER PARTICIPANTS' PREVIOUS VIEWS:
$others

YOUR RESPONSE:
"@
        }
        if ($UntilConsensus) {
            $p += @"

CONSENSUS MODE:
Only if you accept the current shared conclusion, have no material objection,
and no additional evidence is required before stating the next step, end with:
Consensus: Agree
Otherwise end with:
Consensus: Continue
and identify the unresolved issue in Reasons.
"@
        }
        Write-AgentEvent -Agent $name -Role roundtable -Event start -Task $Topic -Round $r -RunId $RunId
        $answer = Ask-Agent $name $p
        $thisRound[$name] = $answer
        $firstLine = ($answer -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
        Write-AgentEvent -Agent $name -Role roundtable -Event end -Task $Topic -Round $r -RunId $RunId -Detail $firstLine
        Write-Host " done."
    }

    # Show the agents' answers so the human can react this round.
    $transcript.Add("## Round $r")
    $transcript.Add("")
    foreach ($name in $Participants) {
        $transcript.Add("### $name")
        $transcript.Add("")
        $transcript.Add($thisRound[$name])
        $transcript.Add("")
        Write-Host "`n--- $name ---" -ForegroundColor DarkCyan
        Write-Host $thisRound[$name]
    }

    # Human turn: the user is a participant, gets the last word each round.
    $humanAddedSteer = $false
    if ($humanOn) {
        Write-Host "`n--- Your steer (round $r) ---" -ForegroundColor Yellow
        if ($UntilConsensus -and $r -ge $Rounds -and ($Participants | Where-Object { -not (Test-AgentAgreement $thisRound[$_]) }).Count -eq 0) {
            Write-Host "All agent seats agree. Press Enter to accept consensus, or enter new steering to continue." -ForegroundColor Green
        }
        $you = Read-Host "Your view in English (Enter to skip)"
        if (-not [string]::IsNullOrWhiteSpace($you)) {
            $humanAddedSteer = $true
            $thisRound['you'] = $you
            $transcript.Add("### you")
            $transcript.Add("")
            $transcript.Add($you)
            $transcript.Add("")
        }
    }
    $prevRound = $thisRound
    if ($UntilConsensus -and $r -ge $Rounds) {
        $agentAgreement = ($Participants | Where-Object { Test-AgentAgreement $thisRound[$_] }).Count
        if ($agentAgreement -eq $Participants.Count -and -not $humanAddedSteer) {
            $consensusReached = $true
            Write-Host "`nConsensus reached in round $r." -ForegroundColor Green
            break
        }
    }
}

if ($UntilConsensus) {
    $transcript.Add("## Consensus Result")
    $transcript.Add("")
    if ($consensusReached) {
        $transcript.Add("Consensus reached in round ${completedRounds}: every agent answered `Consensus: Agree`, and the human added no further steering in the final round.")
    } else {
        $transcript.Add("Consensus was not reached by round $completedRounds (maximum reached). Remaining objections stay unresolved and do not represent an approved conclusion.")
    }
    $transcript.Add("")
}

if (-not $OutFile) {
    $slug = ($Topic -replace '[^\w\- ]', '' -replace '\s+', '-').ToLower()
    if ($slug.Length -gt 50) { $slug = $slug.Substring(0, 50) }
    $dir = Join-Path $Root 'discussions'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $OutFile = Join-Path $dir ("{0}_{1}.md" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $slug)
}
[System.IO.File]::WriteAllText($OutFile, ($transcript -join "`n"), (New-Object System.Text.UTF8Encoding($false)))

Write-Host "`nTranscript written: $OutFile" -ForegroundColor Green
Write-Host "Next, in Claude Code, enter:"
Write-Host "  synthesize the discussion $OutFile"
exit 0
