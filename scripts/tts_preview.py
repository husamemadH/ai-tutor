from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console

from ai_tutor.config import get_settings
from ai_tutor.tts import TtsError, synthesize

app = typer.Typer(help="Render a sentence with every Arabic neural voice for comparison.")
console = Console()

_DEFAULT_TEXT = (
    "وعليكم السلام ورحمة الله وبركاته، أهلاً وسهلاً بك. "
    "أنا جاهز لمساعدتك في مادة العلوم. أخبرني: "
    "ما الدرس أو السؤال الذي تريد أن نشرحه اليوم؟"
)


def _list_voices(locale_prefix: str) -> list[dict]:
    settings = get_settings()
    url = (
        f"https://{settings.azure_speech_region}.tts.speech.microsoft.com"
        "/cognitiveservices/voices/list"
    )
    response = httpx.get(
        url,
        headers={"Ocp-Apim-Subscription-Key": settings.azure_speech_key},
        timeout=settings.request_timeout,
    )
    response.raise_for_status()
    voices = response.json()
    return [v for v in voices if v["Locale"].lower().startswith(locale_prefix)]


def _render(voice: dict, text: str, out_dir: Path) -> str | None:
    short = voice["ShortName"]
    try:
        audio = synthesize(text, voice=short)
    except (TtsError, httpx.HTTPError) as exc:
        console.print(f"[red]skip[/red] {short}: {exc}")
        return None
    (out_dir / f"{short}.mp3").write_bytes(audio)
    return short


@app.command()
def main(
    text: Annotated[str, typer.Option(help="Sentence to synthesize")] = _DEFAULT_TEXT,
    locale: Annotated[str, typer.Option(help="Locale prefix, e.g. ar")] = "ar",
    out: Annotated[Path, typer.Option(help="Output directory")] = Path("dist/tts_samples"),
    workers: Annotated[int, typer.Option(help="Parallel requests")] = 6,
) -> None:
    """Synthesize `text` with all Arabic voices and build an HTML comparison page."""
    out.mkdir(parents=True, exist_ok=True)
    voices = _list_voices(locale.lower())
    if not voices:
        console.print(f"[yellow]No voices found for locale '{locale}'.[/yellow]")
        raise typer.Exit(1)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda v: _render(v, text, out), voices))
    rendered = {short for short in results if short}

    rows = []
    for voice in sorted(voices, key=lambda v: (v["Locale"], v["Gender"], v["ShortName"])):
        if voice["ShortName"] not in rendered:
            continue
        rows.append(
            f"<div class=card><div class=meta><b>{voice['DisplayName']}</b>"
            f"<span>{voice['Locale']} · {voice['Gender']}</span>"
            f"<code>{voice['ShortName']}</code></div>"
            f"<audio controls preload=none src='{voice['ShortName']}.mp3'></audio></div>"
        )

    html = (
        "<!DOCTYPE html><html lang=ar dir=rtl><head><meta charset=utf-8>"
        "<title>Azure Arabic voices</title><style>"
        "body{font-family:system-ui,sans-serif;background:#0f1420;color:#e8edf5;margin:0;padding:2rem}"
        "h1{font-size:1.2rem}.card{background:#1a2130;border:1px solid #2c3548;border-radius:.75rem;"
        "padding:.8rem 1rem;margin:.6rem 0;display:flex;align-items:center;gap:1rem;flex-wrap:wrap}"
        ".meta{display:flex;flex-direction:column;min-width:16rem}"
        ".meta span,.meta code{color:#8b97ab;font-size:.8rem}audio{flex:1;min-width:16rem}"
        "</style></head><body><h1>الأصوات العربية في Azure</h1>"
        f"<p dir=rtl>{text}</p>{''.join(rows)}</body></html>"
    )
    (out / "index.html").write_text(html, encoding="utf-8")

    console.print(f"[green]Rendered {len(rendered)}/{len(voices)} voices[/green] -> {out}")
    console.print(f"Open: file://{(out / 'index.html').resolve()}")


if __name__ == "__main__":
    app()
