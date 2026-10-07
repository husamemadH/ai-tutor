from pathlib import Path
from runpy import run_path

audit = run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "audit_textbooks.py"))


def test_missing_sign_and_constant_in_projectile_formula():
    finding = audit["compare_formulas"]("f(x)=-0.04x2+0.84x+2", ["0.04x2+0.84x=(x)f"])
    assert finding is not None
    assert finding["signals"]["missing_negative_terms"] == {"-0.04": 1}
    assert finding["signals"]["missing_number_occurrences"] == {"2": 1}


def test_equivalent_digits_powers_and_latex_are_not_flagged():
    source = audit["formulas"]("٢x² + x − ٨ = ٠")[0]
    candidates = audit["formulas"](r"$$2x^2 + x - 8 = 0$$")
    assert audit["compare_formulas"](source, candidates) is None
    assert audit["compare_formulas"]("x2-8x=(x-4)2-16", ["16-(4-x)2=8x-x2"]) is None


def test_equations_do_not_merge_across_lines_or_capture_arabic_words():
    assert audit["formulas"]("x = 2\ny = 3") == ["x=2", "y=3"]
    assert audit["formulas"]("ارتفاع القرص f(x) = -0.04x² + 0.84x + 2 متر") == [
        "f(x)=-0.04x2+0.84x+2"
    ]


def test_superscript_attaches_to_formula_baseline():
    class Page:
        def get_text(self, mode):
            assert mode == "words"
            return [
                (305, 236, 325, 250, "f(x)"),
                (328, 236, 337, 250, "="),
                (340, 236, 377, 250, "-0.04x"),
                (377, 234, 381, 242, "2"),
                (384, 236, 393, 250, "+"),
                (395, 236, 424, 250, "0.84x"),
                (426, 236, 435, 250, "+"),
                (438, 236, 444, 250, "2"),
            ]

    lines = audit["pdf_lines"](Page())
    assert audit["formulas"]("\n".join(lines)) == ["f(x)=-0.04x2+0.84x+2"]
