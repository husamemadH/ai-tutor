from ai_tutor.ingest.ocr import parse_ocr_output


def test_parse_western_page_number():
    printed, text = parse_ocr_output("PAGE: 122\n\nالدرس الأول\nنص")
    assert printed == 122
    assert text == "الدرس الأول\nنص"


def test_parse_arabic_digit_page_number():
    printed, text = parse_ocr_output("PAGE:١٢٢\nنص")
    assert printed == 122
    assert text == "نص"


def test_parse_none_page_number():
    printed, text = parse_ocr_output("PAGE:none\nنص فقط")
    assert printed is None
    assert text == "نص فقط"


def test_parse_missing_page_line():
    printed, text = parse_ocr_output("نص بدون رقم صفحة")
    assert printed is None
    assert text == "نص بدون رقم صفحة"