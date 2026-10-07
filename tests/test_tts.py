import pytest

from ai_tutor.tts import TtsError, normalize_math, sanitize, split_for_tts


def test_subtraction_between_operands():
    assert "ناقص" in normalize_math("٣ س – ٥ = ١")
    assert "سالب" not in normalize_math("٣ س – ٥ = ١")


def test_negative_numbers():
    assert normalize_math("= -٣").endswith("سالب ٣")
    assert "سالب ٢" in normalize_math("(-٢، -٨)")


def test_operators_to_words():
    out = normalize_math("٥ × ٢ ÷ ٤ + ١ = ٣")
    assert "في" in out and "على" in out and "زائد" in out and "يساوي" in out


def test_pi_decimal_and_approx():
    out = normalize_math("π ≈ ٣,١٤")
    assert "بَايْ" in out and "تقريبا" in out and "فاصلة" in out


def test_abbreviations():
    out = normalize_math("نق = ١٤ سم")
    assert "نصف القطر" in out and "سنتيمتر" in out
    assert "نصف القطر مربع" in normalize_math("م = π نق2")


def test_exponents_and_root():
    assert "نصف القطر مربع" in normalize_math("٤ π نق2")
    assert "سنتيمتر مكعب" in normalize_math("١٤ سم3")
    assert "جذر ١٩٦" in normalize_math("نق = ١٩٦√")


def test_single_letters_named():
    out = normalize_math("بين أن م د ينصف س ص.")
    assert "ميم دال" in out and "سين صاد" in out


def test_vocalized_words_preserved_for_speech():
    text = "أَهْلًا بِكَ. نَعَمْ، أَنَا مُعَلِّمُكَ."
    assert sanitize(text) == text


def test_vocalized_standalone_variables_still_named():
    assert normalize_math("سَ + صَ = ٥") == "سين زائد صاد يساوي ٥"


def test_western_digits_converted():
    assert "٤" in normalize_math("4 π")


def test_split_short_text_single_chunk():
    assert split_for_tts("جملة قصيرة.", 2000) == ["جملة قصيرة."]


def test_split_respects_limit_and_preserves_text():
    text = "هذا شرح طويل للمعادلة س يساوي ص زائد ثلاثة. " * 40
    chunks = split_for_tts(text, 90)
    assert len(chunks) > 1
    assert all(len(chunk) <= 90 for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_split_hard_wraps_oversized_token():
    chunks = split_for_tts("ا" * 250, 100)
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert "".join(chunks) == "ا" * 250


def test_emoticons_and_emoji_stripped():
    assert ":(" not in sanitize("شكراً :(")
    assert "sad" not in sanitize("شكراً :(")
    assert "🙂" not in sanitize("أهلاً 🙂")


def test_page_citation_stripped_for_speech():
    assert "154" not in sanitize("الجواب كذا (صفحة 154)")
    assert "154" not in sanitize("الجواب كذا [صفحة 154]")


def test_markdown_bullets_and_bold_are_not_math_operators():
    assert sanitize("## المعاملات\n- **الأول**\n- الثاني\n---") == "المعاملات\nالأول\nالثاني"


def test_coefficients_keep_negative_sign_without_speaking_bullet():
    assert sanitize("- $a = 2$\n- $c = -8$") == ("إيه يساوي ٢\nسي يساوي سالب ٨")


def test_quadratic_formula_spoken_with_fraction_and_root():
    assert sanitize(r"$$x = \frac{-b \pm \sqrt{\Delta}}{2a}$$") == (
        "إكس يساوي الكسر سالب بي زائد أو ناقص الجذر التربيعي لـ دلتا نهاية الجذر "
        "على ٢ في إيه نهاية الكسر"
    )


def test_equation_keeps_powers_multiplication_and_subtraction():
    assert sanitize(r"$2x^2 + x - 8 = 0$") == ("٢ في إكس تربيع زائد إكس ناقص ٨ يساوي ٠")
    assert "٤ في إيه في سي" in sanitize(r"$b^2 - 4ac$")


def test_roots_indices_and_decimal_approximations():
    assert sanitize(r"$$x_1 = \frac{-1 + 8.06}{4} \approx 1.8$$") == (
        "إكس رقم ١ يساوي الكسر سالب ١ زائد ٨ فاصلة صفر ستة على ٤ نهاية الكسر "
        "يساوي تقريبا ١ فاصلة ثمانية"
    )


def test_nested_fraction_scope_and_alternate_delimiters():
    assert sanitize(r"\[\frac{1}{\frac{2}{3}}\]") == (
        "الكسر ١ على الكسر ٢ على ٣ نهاية الكسر نهاية الكسر"
    )
    assert sanitize(r"\(x^{3}\)") == "إكس تكعيب"


def test_arithmetic_multiplication_preserved_without_latex():
    assert sanitize("2 * 3 = 6") == "٢ في ٣ يساوي ٦"
    assert sanitize("**الجذران**") == "الجذران"


def test_unsupported_latex_does_not_silently_change_equation():
    with pytest.raises(TtsError, match="Unsupported math notation"):
        sanitize(r"$\unsupported{x}$")
