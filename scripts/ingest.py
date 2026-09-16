from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ai_tutor.db import session_scope
from ai_tutor.ingest.pipeline import ingest_book

app = typer.Typer(help="Ingest a textbook PDF into the tutor knowledge base.")
console = Console()


@app.command()
def main(
    pdf: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    grade: Annotated[str, typer.Option(help="Grade metadata, e.g. 4")],
    subject: Annotated[str, typer.Option(help="Subject metadata, e.g. science")],
    title: Annotated[str, typer.Option(help="Book title (defaults to filename)")] = "",
    ocr: Annotated[bool, typer.Option(help="Transcribe pages with vision OCR")] = True,
) -> None:
    """OCR (default) or parse -> chunk -> embed -> store a PDF."""
    with session_scope() as db:
        book, count = ingest_book(
            db,
            pdf_path=pdf,
            grade=grade,
            subject=subject,
            title=title or pdf.stem,
            ocr=ocr,
        )
    mode = "OCR" if ocr else "text-layer"
    console.print(f"[green]Ingested[/green] '{book.title}' ({book.id}) via {mode}")
    console.print(f"chunks: {count}  grade: {book.grade}  subject: {book.subject}")


if __name__ == "__main__":
    app()