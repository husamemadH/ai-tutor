# AGENTS.md

Context and operating instructions for any agent (or human) continuing development
on a new device. Read this first.

## What this is

A dialect-aware (Jordanian Arabic) AI tutor. It ingests textbook PDFs, then answers
student questions grounded in that book via RAG, replying in Jordanian dialect.
Target eventually: grades KG–12, integrated into a larger e-learning platform.
Current status: working POC (text-only) for grade 8 (OCR books) + grade 4 (text-layer books).

## Stack (locked)

- Python 3.12, managed with **uv**
- FastAPI + Uvicorn
- SQLAlchemy 2.0 + Postgres 17 + **pgvector** (Docker, container `ai-tutor-db`, host port **5434**)
- OpenRouter for chat and embeddings (`OPENROUTER_API_KEY`)
  - chat: `deepseek/deepseek-v4.1-flash` (vision-capable, used for OCR too)
  - embeddings: `baai/bge-m3`, **1024-dim**
- Groq for speech-to-text (`GROQ_API_KEY`, optional — typing still works without it)
  - STT: `whisper-large-v3-turbo`, `language=ar`, 30s max clip
- Azure Speech for text-to-speech (`AZURE_SPEECH_KEY` + `AZURE_SPEECH_REGION`, optional)
  - TTS: neural voice `ar-SA-HamedNeural`, REST API via httpx (no SDK)

## Get it running on a fresh device

```bash
git clone https://github.com/husamemadH/ai-tutor.git
cd ai-tutor
cp .env.example .env          # OPENROUTER_API_KEY required; GROQ_API_KEY for the mic
docker compose up -d          # starts pgvector on localhost:5434
uv sync                       # installs deps (dev group included)
uv run ai-tutor init-db       # creates the vector extension + tables

# optional but strongly recommended: restore prebuilt books + chunks,
# skipping a slow OCR + embedding run
bash scripts/pull_db.sh

uv run ai-tutor books         # sanity check: should list 5 books
```

If `uv run ai-tutor books` shows nothing, the pull failed or wasn't run — see Ingestion.

### Docker permission gotcha

The user typically is **not** in the `docker` group. Docker commands fail with a
permission error unless run through a fresh group shell:

```bash
newgrp docker <<'EOF'
docker compose up -d
EOF
```

`sudo` requires a TTY here, so it cannot be used non-interactively. Prefer the
`newgrp docker` wrapper for every docker invocation.

### Release asset vs. tracked data

The extracted book text + embeddings live in Postgres, not in git. They are shipped
as a GitHub **release asset** (`db-data` tag, `ai_tutor_data.sql.gz`, data-only dump
of `books` + `chunks`). `scripts/pull_db.sh` downloads and restores it.

- `scripts/dump_db.sh` regenerates `dist/ai_tutor_data.sql.gz` from the local DB
  (`dist/` is gitignored).
- After any (re-)ingest, republish so other clones/agents stay current:
  `bash scripts/dump_db.sh && gh release upload db-data dist/ai_tutor_data.sql.gz --clobber`

The PDFs themselves are gitignored (`data/books/*`) and are **not** in the release.

## Running

```bash
# Web UI (RTL, streaming) — UI is served at "/"
uv run uvicorn ai_tutor.api.main:app --reload --port 8090

# CLI chat (interactive; /exit to quit)
uv run ai-tutor chat --book "العلوم"

# other CLI
uv run ai-tutor settings      # effective config, secrets masked
uv run ai-tutor books         # list ingested books
```

## Ingestion

```bash
# OCR is the default (needed for scanned/presentation-form Arabic PDFs)
uv run scripts/ingest.py /path/to/book.pdf --grade 8 --subject science

# skip OCR only for PDFs with a clean, extractable text layer
uv run scripts/ingest.py /path/to/book.pdf --grade 4 --subject math --no-ocr
```

Grade-8 books on the original machine live at `/home/husamemad/Work/grade8/`
(`arabic82.pdf`, `math82.pdf`, `science82.pdf`). They are not in the repo; to
re-ingest from scratch you need the PDFs, or just `pull_db.sh`.

## Evals

Fixed eval set: `data/eval/grade8.json` (30 held-out questions with ground-truth pages).

```bash
uv run scripts/eval_retrieval.py    # recall@k vs. ground-truth pages
uv run scripts/eval_answers.py      # grounded / dialect / page_ok (single-turn, n=30)
uv run scripts/eval_multiturn.py    # 21 conversations x 4 turns: retention, caps, judge
```

Current green results: single-turn recall@6 0.967, grounded 0.967, dialect 1.000,
page_ok 1.000; multi-turn retention 1.000, grounded 1.000, dialect 1.000,
max_chunks 15 (at the cap).

**Eval noise:** answers are generated at temperature 0.4. On a 30-question run, ~2–3
questions can flip between runs, so a single-run delta below ~0.1 is noise. Don't
chase small movements.

## Testing & lint

```bash
uv run pytest          # offline unit tests, no API/DB needed
uv run ruff check .    # must pass before committing
```

## Architecture map

```
src/ai_tutor/
  config.py        env-driven settings (pydantic-settings)
  db.py            engine, session_scope, init_db
  models.py        Book / Chunk (vector 1024) / ChatSession (pinned_chunk_ids) / Message
  openrouter.py    shared httpx client
  embeddings.py    batched embeddings
  llm.py           chat completions + streaming
  stt.py           Groq Whisper transcription (push-to-talk)
  api/main.py      FastAPI app + SSE /api/chat + POST /api/stt; serves static/index.html
  cli.py           `ai-tutor` entrypoint (init-db, settings, books, chat)
  ingest/
    parse.py       PDF text extraction (PyMuPDF)
    ocr.py         vision OCR: strip header/footer crops, PAGE:<n> output, range guard
    chunk.py       normalize_arabic (NFKC), page-bounded chunking
    pipeline.py    parse/ocr -> chunk -> embed -> store
  rag/retrieve.py  retrieve() cosine, book-scoped; retrieve_by_pages() printed-then-physical
  memory/session.py create_session, get_context, append_message(source_chunk_ids=...)
  tutor/prompt.py  system prompt (dialect + grounding policy)
  tutor/service.py orchestration: _prepare, answer, answer_stream, extract_pages
```

## Conventions & gotchas

- **No code comments** unless explicitly asked. Keep the existing style (ruff, line-length 100).
- **Arabic normalization** (`chunk.py`): NFKC is essential; presentation-form PDFs are
  otherwise garbled. Extraction is lossy (broken lam-alef, dropped letters) — this is
  why OCR is the default.
- **Grounded, not confined:** the prompt treats the book as primary and cited, but allows
  general knowledge, flagged inline. Don't change this casually.
- **Page-anchored retrieval:** when a message names a page (`extract_pages`), that page's
  text is split into per-line sub-queries and unioned via `retrieve_multi` (`rag/retrieve.py`);
  each chunk is ranked by its best distance across queries (`tutor/service.py:_page_queries`).
  A whole review page embeds diffusely and misses the lesson page, so per-question queries are
  what surface the content that answers each item. Short prompts like "حل أسئلة صفحة 154"
  otherwise embed to generic review sections and the model can't ground its answers.
- **Sessions are single-book.** Changing the book in the UI rebinds the session; there is
  intentionally no cross-book conversation handling.
- **Context/carry caps** in `tutor/service.py`: `_CARRIED_LIMIT=12`, `_PINNED_LIMIT=8`,
  `_CONTEXT_LIMIT=15`; `memory_window_turns=8`. These bound the prompt (measured plateau
  ~5.4k prompt tokens). `max_chunks` hits the 15 cap on busy turns — watch this if
  retention ever regresses.
- **Cost is negligible** (~$0.002/turn); latency tracks output length, not context size.
  No auto-compaction is needed — history + context are already bounded.
- `إشي` is valid Jordanian and must NOT be flagged. Banned Levantine markers: `هلق`, `هلقيت`.
- **Tutor dialect is configurable:** `TUTOR_DIALECT=jordanian` (default) or `msa`; `prompt.py`
  selects the instruction block. MSA mode writes **full tashkeel** (diacritics) so Azure TTS
  pronounces ambiguous words correctly (e.g. أخبِرني vs أخبرني), and omits inline page citations
  (the UI shows a sources footer). It invalidates the `dialect` eval metric (it checks Jordanian
  markers) — run evals in `jordanian` mode.
- **Voice (STT + TTS):** UI mic is press-to-start / press-to-stop, auto-stop at 30s, then
  `POST /api/stt` and auto-send the transcript through `/api/chat`. Audio is not stored.
  TTS is opt-in via the header 🔊 toggle (persisted in `localStorage`): after a reply streams,
  the UI `POST`s it to `/api/tts` and plays the returned MP3. In MSA mode the reply is vocalized;
  the UI strips Arabic diacritics for display but sends the **vocalized** text to TTS, so the
  student sees clean text while pronunciation stays correct. A header speed selector sends a
  `rate` (SSML `prosody`, e.g. `-25%`/`+25%`, default `AZURE_TTS_RATE=0%`). TTS text is
  normalized (`tts.py:normalize_math`): math symbols and single-letter variables (س→سين,
  = → يساوي, - → ناقص/سالب) become spoken Arabic; the displayed text is unaffected. Page
  citations (parentheses/brackets), emoticons and emoji are stripped before synthesis. The
  service splits long text at sentence boundaries (`tts.py:split_for_tts`,
  `AZURE_TTS_MAX_CHARS=2000` per Azure request), concatenates the MP3s, and returns one file —
  so any client can just POST the whole reply. Needs `GROQ_API_KEY` (STT) and
  `AZURE_SPEECH_KEY`/`AZURE_SPEECH_REGION` (TTS).

## Optimization protocol (agreed)

When tuning, follow this: fix the eval set + metrics + thresholds **before** iterating;
change **one thing per round**; hard caps on rounds (single-turn 5, multi-turn 3). Frozen
tuning surface: chunking, top_k, retrieval query, prompt, OCR/ingestion internals. No new
dependencies or components without approval. Stop when thresholds pass, on plateau, or at
the cap.

## Git

- Remote is private: `https://github.com/husamemadH/ai-tutor` (`origin`, branch `main`).
- `gh` is authenticated. Only commit when asked; run `uv run ruff check .` first.
- Keep the repo private (the `db-data` release asset contains extracted book text).
