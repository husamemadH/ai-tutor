from ai_tutor.tts import normalize_math, sanitize, split_for_tts


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
