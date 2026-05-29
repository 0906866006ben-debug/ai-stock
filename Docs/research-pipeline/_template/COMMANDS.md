# Pipeline Commands

> 在專案根目錄 `ai-stock` 執行以下 PowerShell 指令。由於 Windows
> 可能封鎖 `.ps1`，範例統一使用 `-ExecutionPolicy Bypass`。
>
> 如果命令列目前已位於 `Docs\research-pipeline>`，請把指令中的
> `.\Docs\research-pipeline\` 改成 `.\`。例如：
>
> ```powershell
> powershell -NoProfile -ExecutionPolicy Bypass -File .\discuss.ps1 "test" -DryRun
> ```

## 1. 圓桌會議：Claude + Gemini + Codex + 你

兩輪討論，使用目前高品質預設模型：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\discuss.ps1 "請在此填入討論議題" -Rounds 2
```

預設模型：

```text
Claude: opus / high effort
Gemini: gemini-3-flash-preview (fallback: gemini-2.5-flash)
Codex: gpt-5.5 / high reasoning
```

只檢查模型與指令，不呼叫 agent、不消耗額度：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\discuss.ps1 "test" -DryRun
```

不加入你的每輪回應，讓三個 agent 自行辯論：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\discuss.ps1 "請在此填入討論議題" -Rounds 2 -NoHuman
```

至少討論兩回合，之後持續到三席都明確同意，最多六回合：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\discuss.ps1 "請在此填入討論議題" -Rounds 2 -UntilConsensus -MaxRounds 6
```

若你目前已在 `Docs\research-pipeline>` 資料夾：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\discuss.ps1 "請在此填入討論議題" -Rounds 2 -UntilConsensus -MaxRounds 6
```

共識模式判定方式：

```text
每個 agent 必須在同一回合結尾寫出 CONSENSUS_STATUS: AGREE。
若任何一席寫 CONTINUE、呼叫失敗、回覆空白，或你在該回合追加意見，會議繼續。
達到 MaxRounds 仍未一致時會停止並標記 Not reached，避免無上限消耗額度。
```

圓桌席位可唯讀檢查 repo 以確認事實，但只應輸出本輪意見；它們不會被
要求修改逐字稿或撰寫實作計畫。
若舊逐字稿中已出現工具錯誤或空白席位，請重新跑一場新會議，不要把
舊檔視為完成的討論結果。

指定更高推理設定：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\discuss.ps1 "請在此填入討論議題" -Rounds 2 -ClaudeModel opus -ClaudeEffort high -GeminiModel gemini-3-flash-preview -GeminiFallbackModels gemini-2.5-flash -CodexModel gpt-5.5 -CodexReasoningEffort xhigh
```

圓桌紀錄輸出位置：

```text
Docs\research-pipeline\discussions\
```

輸出格式為繁體中文短摘要，每位 agent 每回合只會輸出：

```text
立場：...
理由：...
建議：...
共識狀態：同意 / 繼續   # 僅共識模式
```

## 2. Gemini CLI Research：快速研究報告

這是 Gemini CLI research，不是 Gemini 網頁版 Deep Research。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\research.ps1 "請在此填入研究問題"
```

指定輸出檔案：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\research.ps1 "請在此填入研究問題" -Out ".\Docs\research-pipeline\research\my-research.md"
```

## 3. 正式 Deep Research → Claude → Codex 流程

### 3.1 建立新任務

把 `<task-id>` 改成英數短名稱，把 `<title>` 改成任務標題：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\run_pipeline.ps1 new <task-id> "<title>"
```

範例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\run_pipeline.ps1 new canslim-filter-review "CANSLIM 篩選品質研究"
```

建立後，將下列模板交給 Gemini Deep Research 填寫：

```text
Docs\research-pipeline\tasks\<task-id>\1-research.md
```

### 3.2 給 Gemini Deep Research 的提示詞

將 `<task-id>` 和 `<研究問題>` 換成你的內容：

```text
請根據以下固定格式完成 Deep Research 報告：
Docs/research-pipeline/tasks/<task-id>/1-research.md

研究問題：
<研究問題>

要求：
1. 嚴格依照模板章節輸出，不省略 Evidence Register、Hypotheses And Falsification Tests、Data Integrity And Overfitting Review。
2. 外部事實需附來源連結與日期。
3. 不直接要求修改程式；只提出 evidence-supported 的下一步分類。
4. 完成後我會將結果交給 Claude Code 驗證 repository 現況並決定是否進入 Codex 實作。
```

### 3.3 給 Claude Code 的提示詞

Gemini 報告已存回 `1-research.md` 後，貼給 Claude Code：

```text
請讀取：
1. Docs/research-pipeline/tasks/<task-id>/1-research.md
2. Docs/research-pipeline/_template/2-plan.md
3. Docs/research-pipeline/_template/3-codex-prompt.md

請先檢查目前 repository 與相關測試/artifacts，驗證 Gemini 報告中的
repository-relevant claims。然後依照 2-plan.md 的固定格式，填寫：
Docs/research-pipeline/tasks/<task-id>/2-plan.md

只有當 Decision 允許進入實作，且範圍已明確收斂後，才依照
3-codex-prompt.md 的固定格式填寫：
Docs/research-pipeline/tasks/<task-id>/3-codex-prompt.md

不得將尚未被 repository 或資料驗證的假說直接轉成 production 改動。
完成後停下來讓我審核 scope，不要自行執行 Codex。
```

### 3.4 檢查任務進度

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\run_pipeline.ps1 status
```

### 3.5 預覽 Codex 指令，不實際改程式

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\run_pipeline.ps1 codex <task-id> -DryRun
```

### 3.6 執行 Codex 實作

預設使用 `gpt-5.5` + `high` reasoning：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\run_pipeline.ps1 codex <task-id>
```

使用 `xhigh` reasoning：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\run_pipeline.ps1 codex <task-id> -CodexModel gpt-5.5 -CodexReasoningEffort xhigh
```

## 4. 將現有研究或圓桌紀錄匯入 Pipeline

用 Gemini research 報告建立任務：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\run_pipeline.ps1 new <task-id> "<title>" -Research ".\Docs\research-pipeline\research\<research-file>.md"
```

用圓桌逐字稿建立任務：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\run_pipeline.ps1 new <task-id> "<title>" -Research ".\Docs\research-pipeline\discussions\<discussion-file>.md"
```

## 5. Checkpoint 與復原

列出 checkpoint：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\checkpoint.ps1 list
```

Codex 實作後不滿意，復原到執行前：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Docs\research-pipeline\checkpoint.ps1 rollback 0
```

## 6. 建議工作順序

```text
研究型問題：
Gemini Deep Research → Claude 驗證/決策 → 你審核 → Codex 實作

存在多種爭議路線的問題：
圓桌會議 → 你決定方向 → 建立 task → Claude 收斂 → Codex 實作

只需快速查背景資料：
research.ps1 → 人工閱讀，不急著轉成實作
```
