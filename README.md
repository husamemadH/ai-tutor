# AI Tutor

Arabic AI tutor grounded in textbooks, with text chat, Groq speech transcription,
and Azure speech playback. Output supports MSA with diacritics or Jordanian Arabic.

Deferred features and design notes are saved in [Feature ideas](FEATURE_IDEAS.md).

## Stack

- Python 3.12 (uv), FastAPI, SQLAlchemy
- Postgres + pgvector (Docker)
- OpenRouter for chat (`deepseek/deepseek-v4.1-flash`) and embeddings (`baai/bge-m3`)
- Groq Whisper STT and Azure Speech TTS (optional credentials)

## Setup

```bash
cp .env.example .env      # add OPENROUTER_API_KEY
docker compose up -d
uv sync
uv run ai-tutor init-db

# optional: restore prebuilt books + chunks, skipping OCR and embedding
bash scripts/pull_db.sh
```

`scripts/pull_db.sh` downloads a data-only dump of `books` + `chunks` from the
`db-data` GitHub release and restores it into the local DB. This avoids re-running
OCR + embedding after a fresh clone. Note the dump contains the extracted book
text, so it is distributed as a release asset rather than tracked in git.

To regenerate and publish the dump after (re-)ingesting books:

```bash
bash scripts/dump_db.sh
gh release upload db-data dist/ai_tutor_data.sql.gz --clobber
```

## Health

```bash
uv run uvicorn ai_tutor.api.main:app --reload
curl localhost:8000/health
```

## Futurix integration

Futurix now owns the tutor web page. The FastAPI service exposes authenticated
book, conversation, history, streaming chat, settings, STT, and TTS APIs; the standalone HTML page is
not served. CLI chat remains available.

Set `TUTOR_SERVICE_TOKEN` in this service and the Futurix backend to the same long
random credential. Set the backend's `TUTOR_SERVICE_URL` to this API's base URL.
Remote connections require HTTPS; loopback HTTP is supported for development.

Apply the additive migration before using an existing database:

```bash
uv run scripts/migrate_lms.py
uv run uvicorn ai_tutor.api.main:app --host 127.0.0.1 --port 8092
```

The LMS backend supplies authenticated `X-Tutor-Student`, `X-Tutor-Tenant`, and
`X-Tutor-Grade` headers with the service credential. Conversations are owned by
both student and school, and books must match the student's grade. Existing
ownerless conversations are excluded. The health endpoint returns 503 when the
required schema is unavailable.

Use one worker for the pilot's process-level limit (`TUTOR_MAX_CONCURRENT=4`).
`TUTOR_GENERATION_TIMEOUT=120` bounds generation time; provider requests also have
I/O timeouts. PostgreSQL locks reject simultaneous turns within a conversation.
Only completed turns are committed; citations are persisted for history reloads.

## Voice and Arabic output

The Futurix preview and `.env.example` use `TUTOR_DIALECT=msa`. The Python fallback
remains `jordanian` when the setting is omitted. MSA answers retain full diacritics
in saved history and TTS requests; the frontend removes them only for display.
The upstream page-based multi-query retrieval and TTS math normalization remain intact.

Speech conversion skips Markdown headings, emphasis, list bullets, and separators.
Tutor instructions preserve the textbook's mathematical variables and notation;
student-provided equations retain the student's symbols throughout the solution
and follow-up questions.
Common LaTeX algebra inside `$...$`, `$$...$$`, `\(...\)`, and `\[...\]` is spoken
as Arabic fractions, roots, powers, indices, and operators. Decimal fractional
digits are read individually to preserve leading zeros. Fraction and root endings
are announced to make nested expressions unambiguous. Unsupported LaTeX commands
return a speech error rather than silently dropping part of an equation.

Set `GROQ_API_KEY` for transcription, and `AZURE_SPEECH_KEY` plus
`AZURE_SPEECH_REGION` for playback. The default voice is `ar-SA-HamedNeural`.
The authenticated `/api/settings` endpoint reports feature availability without
exposing credentials. Typing works when speech credentials are absent.

Futurix provides microphone start/stop (30 seconds maximum), optional automatic
reading, per-answer playback, and reading speed controls. It sends recorded audio
to the authenticated backend as audio bytes; the backend forwards multipart data
to `/api/stt`. `/api/tts` returns MP3. Audio uploads are capped at 1,500,000 bytes
and TTS text at 12,000 characters. The backend rate-limits speech requests and
aborts downstream audio requests when the browser disconnects. Changing the book,
conversation, or account stops recordings and playback. Microphone use requires
HTTPS or localhost.

## Usage

```bash
# ingest a textbook (M1)
uv run scripts/ingest.py data/books/your-book.pdf --grade 4 --subject science

# chat (M2/M3)
uv run ai-tutor chat
```

## Testing

To compare stored math equations with the local PDFs without paid OCR or provider
calls, run:

```bash
uv run scripts/audit_textbooks.py
uv run scripts/audit_textbooks.py --book-title math91 --output dist/math91-audit
```

The script uses a read-only database transaction and writes `SUMMARY.md` plus
`audit.json` under the output directory (default `dist/textbook-audit`, ignored by
Git). It flags likely missing numbers, negative terms, variables, and operators
in similar equality expressions. PDF word positions help recover superscripts;
formatting differences and Arabic/Latin digits are normalized for comparison.

Review candidates against the rendered PDF before correcting anything. The PDF
text layer can also be wrong, and the audit does not establish semantic
equivalence or validate every equation. Missing PDFs, scanned pages, complex
fraction layouts, and equations without a similar stored candidate need separate
review. No books, chunks, embeddings, or runtime retrieval settings are changed.

```bash
uv run pytest                 # offline unit tests (no API/DB)

# end-to-end without a real PDF:
uv run scripts/ingest_sample.py   # clean Arabic sample book
uv run ai-tutor books
uv run ai-tutor chat
```

The PostgreSQL integration tests run when `TUTOR_TEST_DATABASE_URL` is set. They
create and remove isolated schemas and mock provider responses; they do not
modify the main book catalog or call paid models. The test database must already
have the vector extension. Without that variable, database tests are skipped.

Note: `scripts/make_sample_book.py` generates a PDF, but Arabic shaped-text
extraction from it is garbled (presentation forms, no ToUnicode map). Real books
must either extract cleanly or need OCR. `ingest_sample.py` bypasses extraction
so the rest of the pipeline can be tested.

## Layout

```
src/ai_tutor/
  config.py        env-driven settings
  db.py            engine + session
  models.py        books / chunks / sessions / messages
  openrouter.py    shared HTTP client
  embeddings.py    batched embeddings
  llm.py           chat completions
  stt.py           Groq Whisper transcription (push-to-talk)
  tts.py           Azure Speech synthesis (auto-play toggle)
  api/main.py      FastAPI app
  cli.py           CLI entry point
  ingest/          parse -> chunk -> embed -> store   (M1)
  rag/             filtered vector retrieval           (M2)
  memory/          get_context / append seam           (M3)
  tutor/           prompt builder + service            (M2)
```

## Roadmap

- **M0** scaffold (done)
- **M1** ingestion pipeline (done)
- **M2** retrieval + tutor answer (done)
- **M3** sessions + last-N memory + metadata scoping (done)
- **M4** *(optional)* teaching-card generation at ingest
- **M5** STT/TTS voice loop (done; MSA output via `TUTOR_DIALECT=msa`)
