# CLAUDE.md

> Project-level rules for Claude Code in this repo. Progress source of truth: root `TODO.md`. Full context in `docs/` (gitignored, local-only): `PRD.md` (product core: positioning / feature list / user flows / delivery plan), `IELTS.md` (IELTS mode A/B detail), `SCENARIO.md` (scenario mode detail), `FRONTEND.md` (frontend design + WS/HTTP event contract), `SCHEMA.md` (tech stack / directory / architecture / **full API surface** / data model), `PR.md` (PR rules), `TEST.md` (known hazards).

## What this is

AI English speaking coach — a solo, 24h-deliverable **local demo**. Fills the gap between Duolingo (no real speaking) and human tutors (costly, stressful): zero-pressure, on-demand, immersive speaking practice.

**One engine, two modes.** The evaluation pipeline (whisper → objective signals → structured LLM judge → report) is fully shared and runs incrementally during the session — report visible ≤5s after session end. Modes differ only in persona prompt, flow, and whether a band is produced.

| Mode | Flow | Output |
|---|---|---|
| **IELTS** | A: mock exam (live, P1→P2→P3, director state machine) / B: per-Part recording, multi-question, one report per Part | A: official 4-dim band + diagnostics; B: descriptor-aligned diagnostics, **no band** |
| **Scenario** | Multiple cases (ordering, meeting), **live conversation**, manual End; one persona + judge prompt each | Diagnostic text feedback, **no band** |

Frontend: top nav **Practice** (hover dropdown IELTS/Scenario) / **Library** (session history) / **Review** (progress panel), hidden during sessions; processing state and report share one route (`/report/{id}`). Buttons in simple English. See `FRONTEND.md`.

## Architecture

```
mic (16k PCM)
  ├─ live path (IELTS Mode A + Scenario): browser ⇄ WS /ws/live ⇄ FastAPI proxy ⇄ Gemini Live
  │                                   └─ tee user audio + frame timestamps → per-turn clips
  └─ recording path (Mode B only, NO Live): POST /sessions → per-question
                     POST /sessions/{id}/recordings → POST /sessions/{id}/review (Get Review)
                          ↓
   evaluation pipeline — shared by all 3 entries; whisper + signals run incrementally
   per turn/question DURING the session, clips pre-uploaded to Files API:
     faster-whisper (word timestamps) → objective signals (deterministic)
     → structured judge (ONE call after session end: 2–3 longest user clips
       + signals JSON + transcript + mode prompt)
     → report visible ≤5s (+ 4-dim band, IELTS Mode A only) → progress curve (SQLite)
```

Key judgments: only Mode B is Live-independent — if Live fails, Mode A and Scenario **error out (no fallback)**; Mode B + the full evaluation pipeline still work end-to-end. We wrap Live ourselves so we can tee raw mic audio for scoring. Full API surface (sessions / reports / progress / settings / questions, plus the `ielts_questions` extension) lives in `SCHEMA.md` §6–§7; WS events (incl. `session_started` / `interrupted` / `turn_complete`) in `FRONTEND.md` §5.

## Tech stack

- **Backend**: Python **3.12** (managed by **uv**), FastAPI, `google-genai` async SDK (Gemini Live / judge / TTS), `faster-whisper` for transcription.
- **Frontend**: React + Vite (charts via recharts).
- **Storage**: SQLite, **single hardcoded demo user** (no accounts / multi-user).
- **Audio** (fixed, no transcoding): mic in **16kHz / 16-bit / mono PCM**; Live out **24kHz PCM**.
- **TTS**: Gemini TTS **pre-generated** question audio (via seed script), zero runtime calls.

## Commands

```bash
uv sync                        # install deps
uv run python main.py          # run entrypoint
uv run python gemini_live.py   # minimal Gemini Live round-trip demo
uv run pytest                  # tests
cp .env.example .env           # set GEMINI_API_KEY (required), GEMINI_PROXY (optional)
cd frontend && npm run dev     # frontend dev server (proxy /api → :8000); npm test / npm run build
```

Secrets live in `.env` (gitignored) only — **never** commit keys or write them into code.

## Workflow (per PR)

The main session is **orchestrator + implementer**. It owns the plan and the tight edit→test loop; it only hands off for independent review (`code-reviewer`) and noisy searches (`Explore`). `TODO.md` is the single source of truth for progress.

1. **READ**      open `TODO.md`; confirm the task and **scope it to one PR** (one thing only) — if the item spans multiple features, propose a split first and do them as separate PRs (`docs/PR.md`) → state "上次进度 + 本次 PR 做什么" (1–2 句)
2. **EXPLORE**   (only if needed) spawn `Explore` agent for "where does X live / conventions"
3. **BUILD**     code the ONE feature + unit tests — tight loop, main thread
4. **SELF-TEST** `uv run pytest` until green
5. **REVIEW**    `@agent-code-reviewer` (read-only) → PASS / NEEDS-FIX + findings
6. **FIX**       fix findings on main thread; re-review only if NEEDS-FIX
7. **CHECK**     user check — confirm all clean (not on `main` / `code-reviewer` PASS / tests green / one focused change, no unrelated edits / title + 两段正文 ready / main still runs after merge); tell user the edge cases + how to self-test → **wait for user OK**
8. **PR**        `/pr` — drafts 标题 + 两段 body, then auto push → create PR → merge to main → sync (no second confirm)
9. **LOG**       tick `TODO.md` + append 进度日志 line `YYYY-MM-DD — what / blocker / where to resume`

