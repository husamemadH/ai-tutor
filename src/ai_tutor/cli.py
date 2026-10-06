from typing import Annotated

import httpx
import typer
from rich.console import Console
from sqlalchemy.exc import SQLAlchemyError

from ai_tutor.books import find_book, list_books
from ai_tutor.config import get_settings
from ai_tutor.db import init_db, session_scope
from ai_tutor.memory import session as memory
from ai_tutor.models import Book
from ai_tutor.tutor.service import answer_stream

app = typer.Typer(help="AI Tutor CLI", no_args_is_help=True)
console = Console()


@app.command("init-db")
def init_db_cmd() -> None:
    """Create the vector extension and all tables."""
    init_db()
    console.print("[green]Database initialised.[/green]")


@app.command()
def settings() -> None:
    """Show effective settings (secrets masked)."""
    s = get_settings()
    console.print(f"chat_model:      {s.chat_model}")
    console.print(f"embedding_model: {s.embedding_model} (dim={s.embedding_dim})")
    console.print(f"database_url:    {s.database_url}")
    key = "[green]set[/green]" if s.openrouter_api_key else "[red]missing[/red]"
    groq = "[green]set[/green]" if s.groq_api_key else "[red]missing[/red]"
    azure = "[green]set[/green]" if s.azure_speech_key else "[red]missing[/red]"
    console.print(f"openrouter_key:  {key}")
    console.print(f"groq_key:        {groq}")
    console.print(f"stt_model:       {s.stt_model} (max {s.stt_max_seconds}s)")
    console.print(f"azure_key:       {azure} (region={s.azure_speech_region or 'missing'})")
    console.print(f"tts_voice:       {s.azure_tts_voice}")
    console.print(f"tutor_dialect:   {s.tutor_dialect}")


@app.command()
def books() -> None:
    """List ingested books."""
    with session_scope() as db:
        items = list_books(db)
        if not items:
            console.print("[yellow]No books yet. Run scripts/ingest.py first.[/yellow]")
            return
        for book in items:
            console.print(f"[cyan]{book.id}[/cyan]  {book.title}  (grade {book.grade}, {book.subject})")


def _select_book(db, ref: str | None) -> Book | None:
    items = list_books(db)
    if ref:
        chosen = find_book(db, ref)
        if chosen is None:
            console.print(f"[red]No book matches '{ref}'.[/red]")
            raise typer.Exit(1)
        return chosen
    if not items:
        console.print("[yellow]No books ingested; running without retrieval.[/yellow]")
        return None
    console.print("Choose a book:")
    for index, book in enumerate(items, start=1):
        console.print(f"  [cyan]{index}[/cyan]. {book.title} (grade {book.grade}, {book.subject})")
    choice = typer.prompt("Number", default="1")
    try:
        return items[int(choice) - 1]
    except (ValueError, IndexError):
        console.print("[red]Invalid choice.[/red]")
        raise typer.Exit(1) from None


@app.command()
def chat(
    book: Annotated[str | None, typer.Option(help="Book id or title substring")] = None,
    grade: Annotated[str, typer.Option(help="Grade (used when no book is selected)")] = "غير محدد",
    subject: Annotated[str, typer.Option(help="Subject (used when no book is selected)")] = "عام",
    sources: Annotated[bool, typer.Option(help="Show retrieved page references")] = True,
) -> None:
    """Interactive tutor chat (type /exit to quit)."""
    with session_scope() as db:
        selected = _select_book(db, book)
        session = memory.create_session(
            db,
            grade=selected.grade if selected else grade,
            subject=selected.subject if selected else subject,
            book_id=selected.id if selected else None,
            title=selected.title if selected else None,
        )
        label = selected.title if selected else "بدون كتاب"
        console.print(f"[dim]session={session.id}  book={label}[/dim]")

        while True:
            try:
                text = console.input("[bold cyan]you>[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if not text:
                continue
            if text in {"/exit", "/quit"}:
                break
            try:
                console.print("[bold green]tutor>[/bold green] ", end="")
                found = []
                for event in answer_stream(db, session=session, user_message=text):
                    if event.sources is not None:
                        found = event.sources
                    if event.delta:
                        console.print(
                            event.delta, end="", highlight=False, markup=False, soft_wrap=True
                        )
            except (httpx.HTTPError, SQLAlchemyError, RuntimeError) as exc:
                console.print(f"\n[red]error:[/red] {exc}")
                continue
            console.print()
            if sources and found:
                refs = ", ".join(
                    f"ص{chunk.display_page}" for chunk in found if chunk.display_page
                )
                if refs:
                    console.print(f"[dim]sources: {refs}[/dim]")

        console.print("[dim]bye[/dim]")


if __name__ == "__main__":
    app()