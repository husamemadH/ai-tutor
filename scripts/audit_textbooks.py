import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import pymupdf
from sqlalchemy import select, text

from ai_tutor.db import engine
from ai_tutor.models import Book, Chunk

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_COMMANDS = {"pm": "±", "times": "×", "cdot": "×", "div": "÷", "sqrt": "√"}
_VARIABLES = "a-zA-Zسصأبج"
_MATH = rf"0-9{_VARIABLES}.=+\-×÷*/√±()<>,"
_FORMULA = re.compile(rf"(?<![\u0621-\u064a])[{_MATH} \t]+=[{_MATH} \t]+(?![\u0621-\u064a])")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_VARIABLE = re.compile(rf"[{_VARIABLES}]")
_NEGATIVE = re.compile(rf"-(?:\d+(?:\.\d+)?|[{_VARIABLES}])")
_OPERATOR = re.compile(r"[+\-×÷/√±]")


def canonical(value: str, compact: bool = True) -> str:
    value = unicodedata.normalize("NFKC", value).translate(_DIGITS)
    value = re.sub(r"[\u064b-\u065f\u0670\u0640\u200e\u200f]", "", value)
    value = re.sub(r"(?<=\d)[,٫](?=\d)", ".", value)
    value = value.replace("−", "-").replace("–", "-").replace("—", "-")
    value = re.sub(r"\\([a-zA-Z]+)", lambda m: _COMMANDS.get(m[1], ""), value)
    value = value.replace("*", "×")
    value = re.sub(r"[${}\^_]", "", value)
    return re.sub(r"\s", "", value) if compact else value


def formulas(value: str) -> list[str]:
    return list(
        dict.fromkeys(
            canonical(match.group())
            for line in value.splitlines()
            for match in _FORMULA.finditer(canonical(line, compact=False))
        )
    )


def pdf_lines(page) -> list[str]:
    rows = []
    words = sorted(page.get_text("words"), key=lambda word: ((word[1] + word[3]) / 2, word[0]))
    heights = [word[3] - word[1] for word in words if word[4] == "="]
    math_height = median(heights) if heights else 0
    superscripts = []
    for word in words:
        center = (word[1] + word[3]) / 2
        height = word[3] - word[1]
        if math_height and height < math_height * 0.8:
            superscripts.append(word)
            continue
        nearby = [
            row
            for row in rows
            if abs(row["center"] - center) <= max(3, 0.35 * max(row["height"], height))
        ]
        if nearby:
            row = min(nearby, key=lambda row: abs(row["center"] - center))
            count = len(row["words"])
            row["center"] = (row["center"] * count + center) / (count + 1)
            row["height"] = max(row["height"], height)
            row["words"].append(word)
        else:
            rows.append({"center": center, "height": height, "words": [word]})
    for word in superscripts:
        center = (word[1] + word[3]) / 2
        nearby = [
            row
            for row in rows
            if abs(row["center"] - center) <= math_height
            and any(
                max(other[0] - word[2], word[0] - other[2], 0) <= math_height * 0.6
                for other in row["words"]
            )
        ]
        if nearby:
            min(nearby, key=lambda row: abs(row["center"] - center))["words"].append(word)
    result = []
    for row in rows:
        groups = [[]]
        for word in sorted(row["words"], key=lambda word: word[0]):
            if groups[-1] and word[0] - groups[-1][-1][2] > row["height"] * 3:
                groups.append([])
            groups[-1].append(word)
        for group in groups:
            if len(group) > 1 and group[0][4].isdigit() and re.match(r"[a-zA-Z]", group[1][4]):
                gap = group[1][0] - group[0][2]
                if gap > (group[0][3] - group[0][1]) * 0.4:
                    group = group[1:]
            result.append(" ".join(word[4] for word in group))
    return result


def features(value: str) -> Counter:
    result = Counter(f"number:{token}" for token in _NUMBER.findall(value))
    result.update(f"variable:{token}" for token in _VARIABLE.findall(value))
    return result


def similarity(left: Counter, right: Counter) -> float:
    total = left.total() + right.total()
    return 2 * (left & right).total() / total if total else 0


def compare_formulas(source: str, candidates: list[str]) -> dict | None:
    source_features = features(source)
    if source_features.total() < 3 or not candidates:
        return None
    source_ops = Counter(_OPERATOR.findall(source))

    def score(candidate: str) -> float:
        token_score = similarity(source_features, features(candidate))
        candidate_ops = Counter(_OPERATOR.findall(candidate))
        operator_score = similarity(source_ops, candidate_ops) if source_ops or candidate_ops else 1
        return 0.85 * token_score + 0.15 * operator_score

    candidate = max(candidates, key=score)
    confidence = score(candidate)
    if confidence < 0.8:
        return None
    missing_numbers = Counter(_NUMBER.findall(source)) - Counter(_NUMBER.findall(candidate))
    missing_variables = Counter(_VARIABLE.findall(source)) - Counter(_VARIABLE.findall(candidate))
    missing_negatives = Counter(_NEGATIVE.findall(source)) - Counter(_NEGATIVE.findall(candidate))
    missing_ops = source_ops - Counter(_OPERATOR.findall(candidate))
    if not any((missing_numbers, missing_variables, missing_ops)):
        return None
    reasons = {}
    for label, differences in (
        ("missing_number_occurrences", missing_numbers),
        ("missing_variables", missing_variables),
        ("missing_negative_terms", missing_negatives),
        ("missing_operators", missing_ops),
    ):
        if differences:
            reasons[label] = dict(differences)
    return {
        "pdf_formula": source,
        "stored_formula": candidate,
        "match_similarity": round(confidence, 3),
        "signals": reasons,
        "priority": 3 * missing_negatives.total() + 2 * missing_numbers.total(),
    }


def audit_book(book: dict, chunks: list[dict]) -> dict:
    record = {
        "book_id": str(book["id"]),
        "title": book["title"],
        "grade": book["grade"],
        "pdf": book["file_path"],
        "pages": 0,
        "pages_with_text_layer": 0,
        "pages_with_stored_text": 0,
        "pages_with_pdf_formulas": 0,
        "unmatched_pdf_formulas": 0,
        "findings": [],
    }
    pdf_path = Path(book["file_path"])
    if not pdf_path.is_file():
        return {**record, "status": "missing_pdf"}
    stored = defaultdict(list)
    printed = defaultdict(set)
    for chunk in chunks:
        start = chunk["page_start"]
        end = chunk["page_end"] or start
        if start is None:
            continue
        for page in range(start, end + 1):
            stored[page].append(chunk["content"])
            if chunk["printed_page"] is not None:
                printed[page].add(chunk["printed_page"])
    try:
        with pymupdf.open(pdf_path) as pdf:
            record["pages"] = len(pdf)
            for number, page in enumerate(pdf, 1):
                blocks = page.get_text("blocks")
                contents = [block[4] for block in blocks if block[6] == 0]
                if len("".join(contents).strip()) < 40:
                    continue
                record["pages_with_text_layer"] += 1
                if not stored[number]:
                    continue
                record["pages_with_stored_text"] += 1
                source_formulas = list(
                    dict.fromkeys(
                        equation for line in pdf_lines(page) for equation in formulas(line)
                    )
                )
                source_formulas = [
                    equation
                    for equation in source_formulas
                    if equation.count("(") == equation.count(")")
                ]
                if source_formulas:
                    record["pages_with_pdf_formulas"] += 1
                candidates = list(
                    dict.fromkeys(
                        equation for chunk in stored[number] for equation in formulas(chunk)
                    )
                )
                for equation in source_formulas:
                    finding = compare_formulas(equation, candidates)
                    if finding:
                        record["findings"].append(
                            {
                                "pdf_page": number,
                                "printed_pages": sorted(printed[number]),
                                **finding,
                            }
                        )
                    elif (
                        not candidates
                        or max(
                            similarity(features(equation), features(candidate))
                            for candidate in candidates
                        )
                        < 0.8
                    ):
                        record["unmatched_pdf_formulas"] += 1
        record["status"] = "audited" if record["pages_with_text_layer"] else "no_usable_text_layer"
    except (RuntimeError, ValueError) as exc:
        record["status"] = "pdf_unreadable"
        record["error_type"] = type(exc).__name__
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only, local math textbook audit; no OCR/API."
    )
    parser.add_argument(
        "--book-title", help="Audit one stored book title; default is all math books."
    )
    parser.add_argument("--output", type=Path, default=Path("dist/textbook-audit"))
    args = parser.parse_args()
    query = select(Book.id, Book.title, Book.grade, Book.file_path)
    if args.book_title:
        query = query.where(Book.title == args.book_title)
    else:
        query = query.where(Book.subject.in_(["math", "رياضيات", "الرياضيات"]))
    with engine.begin() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        books = [
            dict(row) for row in conn.execute(query.order_by(Book.grade, Book.title)).mappings()
        ]
        if not books:
            raise SystemExit("No matching books found.")
        chunk_query = select(
            Chunk.book_id,
            Chunk.page_start,
            Chunk.page_end,
            Chunk.printed_page,
            Chunk.content,
        ).where(Chunk.book_id.in_([book["id"] for book in books]))
        chunks = defaultdict(list)
        for row in conn.execute(chunk_query).mappings():
            chunks[row["book_id"]].append(dict(row))
    records = []
    for book in books:
        result = audit_book(book, chunks[book["id"]])
        records.append(result)
        print(f"{book['title']}: {result['status']}, {len(result['findings'])} review candidates")
    summary = {
        "books": len(records),
        "books_audited": sum(book["status"] == "audited" for book in records),
        "pdf_pages": sum(book["pages"] for book in records),
        "pages_with_text_layer": sum(book["pages_with_text_layer"] for book in records),
        "pages_flagged": sum(len({f["pdf_page"] for f in book["findings"]}) for book in records),
        "review_candidates": sum(len(book["findings"]) for book in records),
        "provider_api_calls": 0,
        "database_changes": 0,
    }
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "limitations": [
            "Candidates require PDF visual review; they are not confirmed OCR errors.",
            "PDF text order, superscripts, fraction layout, and chunk boundaries cause false positives.",
            "Only sufficiently similar equality expressions are compared; absence of flags proves nothing.",
            "Missing PDFs and pages without usable text layers cannot be checked this way.",
        ],
        "summary": summary,
        "books": records,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    lines = [
        "# Local textbook audit",
        "",
        "Read-only: no paid APIs and no database edits.",
        "",
        "Flags are review candidates, not confirmed errors. PDF text extraction can also be wrong.",
        "",
        "| Book | Status | PDF pages | Review pages |",
        "|---|---|---:|---:|",
    ]
    for book in records:
        pages = len({finding["pdf_page"] for finding in book["findings"]})
        lines.append(f"| {book['title']} | {book['status']} | {book['pages']} | {pages} |")
    review = sorted(
        [(book, finding) for book in records for finding in book["findings"]],
        key=lambda pair: (pair[1]["priority"], pair[1]["match_similarity"]),
        reverse=True,
    )[:20]
    lines.extend(["", "## First candidates to review", ""])
    for book, finding in review:
        lines.extend(
            [
                f"### {book['title']}, PDF page {finding['pdf_page']}",
                "",
                f"PDF text: `{finding['pdf_formula']}`",
                "",
                f"Stored text: `{finding['stored_formula']}`",
                "",
                f"Signals: `{json.dumps(finding['signals'], ensure_ascii=False)}`",
                "",
            ]
        )
    lines.extend(["## Limits", "", *[f"- {limit}" for limit in report["limitations"]], ""])
    (args.output / "SUMMARY.md").write_text("\n".join(lines))
    print(json.dumps(summary))
    print(f"Report: {args.output / 'SUMMARY.md'}")


if __name__ == "__main__":
    main()
