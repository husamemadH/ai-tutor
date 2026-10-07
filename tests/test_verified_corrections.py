import json
from contextlib import contextmanager
from pathlib import Path
from runpy import run_path

import pytest

script = run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "correct_verified_equations.py")
)
corrected_content = script["corrected_content"]
apply_corrections = script["apply_corrections"]


def test_replaces_verified_equation_without_changing_surrounding_text():
    original = "قبل\n0.04x2 + 0.84x = (x)f\nبعد"
    result = corrected_content(original, "0.04x2 + 0.84x = (x)f", "f(x) = -0.04x^2 + 0.84x + 2")
    assert result == "قبل\nf(x) = -0.04x^2 + 0.84x + 2\nبعد"


def test_already_corrected_equation_is_idempotent():
    assert corrected_content("before new after", "old", "new") == "before new after"


@pytest.mark.parametrize("content", ["unexpected content", "old and old"])
def test_unexpected_or_ambiguous_source_is_rejected(content):
    with pytest.raises(ValueError, match="exactly one occurrence"):
        corrected_content(content, "old", "new")


@pytest.mark.parametrize("failure", ["provider", "invalid_vector"])
def test_embedding_failure_preserves_backup_without_starting_database_write(
    monkeypatch, tmp_path, failure
):
    class FailingEmbedder:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def embed_one(self, text):
            if failure == "provider":
                raise RuntimeError("Provider unavailable")
            return [float("nan")] * 1024

    @contextmanager
    def forbidden_session():
        pytest.fail("Database write started before all embeddings were valid")
        yield

    monkeypatch.setitem(apply_corrections.__globals__, "EmbeddingClient", FailingEmbedder)
    monkeypatch.setitem(apply_corrections.__globals__, "session_scope", forbidden_session)
    pending = [{"content": "original", "new_content": "corrected", "embedding": [0.0]}]
    with pytest.raises((RuntimeError, ValueError)):
        apply_corrections(pending, tmp_path)
    backups = list(tmp_path.glob("chunks-before-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == pending
    assert backups[0].stat().st_mode & 0o777 == 0o600
