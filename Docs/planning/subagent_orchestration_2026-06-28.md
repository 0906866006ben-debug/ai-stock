# 多代理編排設計 — Claude 當大腦,gemini/codex/NotebookLM 各司其職

**版本:** v1(2026-06-28)
**決策:** 啟動方式 = Claude Code 原生子代理為主;本文件 = 規劃,代理檔尚未建立。
**前置設施:** `Docs/research-pipeline/`(run_pipeline.ps1 / discuss.ps1 / checkpoint.ps1)已存在且三 CLI 已實測在 PATH + 已登入。

---

## 0. 一條鐵律(整個設計的地基)

> **省 token 的真正機制不是「讓別人去讀寫檔案」,而是「讓別人在自己的 context 裡做完,只把結論回給 Claude」。**

Claude Code 的原生子代理(`.claude/agents/*.md`)是一個**獨立 context window 的 Claude**,有自己的工具集與系統提示。它跑完後,**只有最終訊息**回到主 session——中間讀的檔案、跑的指令輸出、外部 CLI 的長報告,全部留在子代理的 context,不污染你主對話的大腦。

這就是為什麼「Claude 只負責想」可行:
- 主 session 的 Claude = 總指揮,context 保持精簡,專心做規劃與決策。
- 子代理 = 髒活累活的隔離艙,把大量輸出消化成摘要再回報。

**但要誠實:** 子代理不是免費的。它會燒 Claude 子代理的 token(在隔離艙裡),外加被它呼叫的 gemini(免費 OAuth)/codex。省的是**主 session 的 context**,不是總花費。所以:

| 工作量 | 該怎麼做 |
|--------|---------|
| 外部呼叫**輸出很大**(研究報告、大批檔案、長 log) | 派子代理包起來 → 只回摘要 ✅ |
| 外部呼叫**輸出很小**(問一句、跑一個檢查) | 主 session 直接 Bash 叫 CLI 就好,別為小事派代理 |
| **重型批次 / 多輪辯論** | 用現成的 `run_pipeline.ps1` / `discuss.ps1`,終端機跑 |

---

## 1. 角色矩陣(你的分工 → 真實機制)

| 代理 | 你給的定位 | 真實機制 | 啟動方式 | token 歸屬 |
|------|-----------|---------|---------|-----------|
| **Claude(主)** | 只負責大腦想的部分 | 本 session,總指揮 + 規劃 + 決策 + 派工 | 你直接跟它講話 | 主 context(要省的就是這個) |
| **researcher**(包 Gemini) | 研究、收集資料 | Claude 子代理 → Bash 叫 `gemini` 收資料 → distill 成有來源的摘要 | session 內「用 researcher 研究 X」 | 子代理隔離艙 |
| **grunt**(包 Gemini) | 雜務:讀寫大量檔案 | Claude 子代理 → 用自己的工具(或 gemini)做檔案級苦工 → 回精簡結果 | session 內「用 grunt 處理 X」 | 子代理隔離艙 |
| **coder**(包 Codex) | 只負責寫程式 | Claude 子代理 → 叫 `run_pipeline.ps1 codex`(或直接 codex exec)→ 回 diff 摘要 | session 內「用 coder 實作 X」 | 子代理隔離艙 |
| **NotebookLM** | (你未明指) | 🔴 **無法自動化**;網頁版文件接地問答 | **人工**,瀏覽器 | 不進管線 |

### 為什麼 researcher / grunt 都包 Gemini,卻分兩個代理
同一個 CLI,**兩種任務性質**,提示與工具集不同:
- **researcher** = 對外探索(web、收資料),系統提示強調「列來源、標時點、區分事實與假設、不捏造」——延續你 research-pipeline 的紀律。
- **grunt** = 對內苦工(掃 repo、批次讀檔、整理格式),系統提示強調「只回需要的、不要把整批內容貼回來」。

混成一個代理會讓提示自相矛盾(對外要謹慎引用 vs 對內要快速消化)。

---

## 2. NotebookLM 的誠實定位(人工知識座)

NotebookLM 沒有可編排的 CLI/API,**不能當管線的一個自動腳色**。它真正值錢的用法是你的**研究語料知識庫**:

**建置(一次性,你手動):**
1. 開一個 Notebook,上傳這些來源:
   - `長期投資量化選股策略研究.txt`(原始研究)
   - `Docs/planning/*.md`(三份策略書 + 總路線圖)
   - 未來每份 Gemini Deep Research 報告(網頁版產出的)
   - 跑出來的 `value_cohort_*_summary.md` 驗證報告
2. 之後它就是一個**有引用、接地於你自己語料**的問答座。

**日常用法(人工,非自動):**
- 「研究裡對台股 Shareholder Yield 的三大盲點是什麼?」→ 它回答 + 標出處。
- 「我的總路線圖 Stage 2 的決策閘門條件?」→ 接地引用,不會幻覺。
- 「把這份 60 頁 DR 報告講成 5 分鐘 audio overview」→ 通勤聽。

**它在編排裡的位置:** Gemini Deep Research(網頁)產報告 → 你存檔 → **同時餵 NotebookLM(供你日後問答)+ 餵 `1-research.md`(供管線實作)**。一份來源,兩個去處。

---

## 3. 兩條路徑如何共存(原生代理 vs 現有腳本)

你已經有的 pipeline 不廢棄,它和新的原生代理是**不同場景**:

```
場景 A:session 內、即時、輕量            場景 B:重型批次 / 多輪辯論
────────────────────────────            ────────────────────────────
你跟 Claude 主 session 對話               你在終端機自己跑
  「用 researcher 查 X」                   ./run_pipeline.ps1 research <task>
  「用 coder 改 Y」                        ./run_pipeline.ps1 codex <task>
Claude 派原生子代理,回摘要                ./discuss.ps1 "辯論題目" -Rounds 2
                                          (claude+gemini+codex+你 圓桌)
```

- **原生代理**:你想留在跟 Claude 的對話裡、即時派個小活、要它消化完只回重點時用。
- **pipeline 腳本**:正式的「研究→規劃→實作」三段接力,有 checkpoint、有 guardrails、有回滾,正式改 code 走這條。
- **discuss.ps1**:要三個 AI 加你互相辯論一個決策時用。

原生代理裡的 **coder** 其實就是去呼叫 `run_pipeline.ps1 codex`,所以兩條路徑在實作腿是**同一套 guardrails + checkpoint**,不會出現「繞過保護直接改 code」的漏洞。

---

## 4. 範例工作流(端到端)

**情境:你想驗證「台股回購文化是否強到值得納入 Shareholder Yield」**

1. **你 → Claude 主**:「我想搞清楚台股回購文化對 SY 因子的影響,規劃一下。」
   Claude(只動腦)拆解成:研究現況 → 看我方資料能不能算 → 決定要不要改因子。
2. **Claude → researcher 子代理**:「用 gemini 收集台股 2010 後庫藏股回購的規模、是否多為員工選擇權、學術上對 SY 在台股有效性的證據。列來源。」
   researcher 在隔離艙跑完,**只回**:3 點發現 + 來源 + 1 句可信度評估。主 context 沒被長報告灌爆。
3. **你**(平行):把同一主題丟 NotebookLM,問你自己的研究語料怎麼說,交叉比對。
4. **Claude → grunt 子代理**(若需要):「掃 `pit_fundamentals.db` 看 CapitalStock 回購欄位的覆蓋率,只回統計數字。」
5. **Claude 綜合**:寫決策(改 / 不改 / 待驗證),若要改 code →
6. **Claude → coder 子代理** 或 你直接 `run_pipeline.ps1`:codex 實作,guardrails + checkpoint 自動掛上,你 review diff。

每一步,Claude 主 session 的 context 只進「摘要與決策」,大量原始資料都在子代理/腳本/NotebookLM 那側被消化掉。

---

## 5. 待建清單(你 greenlight 後我做)

照你選的「先出規劃」,以下**還沒建**,確認方向後再動手:

| 產出 | 內容 | 預估 |
|------|------|------|
| `.claude/agents/researcher.md` | Claude 子代理,工具限 Bash+Read+Grep+Glob;系統提示=包 gemini 收資料、列來源、不捏造、只回摘要 | 小 |
| `.claude/agents/grunt.md` | Claude 子代理,工具=檔案類;系統提示=批次苦工、只回需要的結果 | 小 |
| `.claude/agents/coder.md` | Claude 子代理,系統提示=透過 `run_pipeline.ps1 codex` 走 guardrails+checkpoint 實作、回 diff 摘要 | 小 |
| `Docs/research-pipeline/` 微調 | (選用)若要把 gemini 研究腿也腳本化成 `run_pipeline.ps1 research` | 中 |
| NotebookLM 建置 SOP | 一頁:要上傳哪些來源、怎麼維護 | 你手動,我寫 SOP |

**注意:** 原生子代理目前在這台是空的(`.claude/agents/` 不存在),所以這是純新增,不動任何現有功能。

---

## 6. 失效模式與誠實警語

1. **子代理不是省錢,是省主 context**。小活別派代理(派工本身有固定成本),會比直接 Bash 還貴。判準在 §0 的表。
2. **Gemini CLI ≠ 網頁 Deep Research**。CLI 是 agentic chat+web,重型 DR 報告品質仍以網頁版為準 → 人工貼回。researcher 代理適合「中量級查證」,不是取代網頁 DR。
3. **headless gemini 兩個門檻**(記憶已記、今日實測 auth 檔都在):需 `--skip-trust` + `~/.gemini/settings.json` 宣告 OAuth,否則報「未設 Auth / 非信任目錄」。researcher 代理的提示要內建這兩個旗標。
4. **headless `claude -p` 是全新無記憶的 agent**——所以「綜合/決策」這種需要對話脈絡的事**留給主 session**,不要外包給無狀態的 headless claude。
5. **codex 一定走 guardrails + checkpoint**(經 run_pipeline.ps1),不讓 coder 代理裸呼叫 codex 改 code。
6. **NotebookLM 是人工座**,別期待它被腳本驅動;它的價值在你「問」它,不在它「做」事。

---

## 7. 一句話總結

你要的分工是對的,而且**地基已經有八成**(pipeline + 三 CLI 已通)。要補的只是:把角色用 Claude 原生子代理「包」起來(讓 Claude 主 session 永遠只吃摘要),加上把 NotebookLM 擺到它唯一合理的位置——你的人工知識庫,而不是管線的齒輪。確認方向後,§5 那三個小代理檔我可以很快建好。

---

### 紀律聲明
本文件為工具編排設計,非投資建議。所有代理輸出仍受既有 guardrails 約束(additive-only、no-action-verb、不捏造數據);實作腿一律經 checkpoint 可回滾。
