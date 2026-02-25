"""Tests for symbol validation and CSV injection prevention."""

import pytest

from src.utils.csv_safety import parse_number, sanitize_csv_field, validate_symbol


class TestValidateSymbol:
    def test_valid_uppercase(self):
        assert validate_symbol("HPG") == "HPG"

    def test_lowercase_normalized(self):
        assert validate_symbol("hpg") == "HPG"

    def test_mixed_case(self):
        assert validate_symbol("Hpg") == "HPG"

    def test_with_numbers(self):
        assert validate_symbol("TCB") == "TCB"
        assert validate_symbol("VN30") == "VN30"

    def test_with_spaces_stripped(self):
        assert validate_symbol("  HPG  ") == "HPG"

    def test_empty_string(self):
        with pytest.raises(ValueError):
            validate_symbol("")

    def test_too_long(self):
        with pytest.raises(ValueError):
            validate_symbol("A" * 11)

    def test_special_chars(self):
        with pytest.raises(ValueError):
            validate_symbol("HP@G")
        with pytest.raises(ValueError):
            validate_symbol("HP G")
        with pytest.raises(ValueError):
            validate_symbol("HP-G")
        with pytest.raises(ValueError):
            validate_symbol("HP.G")

    def test_formula_injection_attempt(self):
        with pytest.raises(ValueError):
            validate_symbol("=CMD")
        with pytest.raises(ValueError):
            validate_symbol("+HPG")


class TestSanitizeCsvField:
    def test_normal_string(self):
        assert sanitize_csv_field("hello") == "hello"

    def test_strip_equals(self):
        assert sanitize_csv_field("=cmd('calc')") == "cmd('calc')"

    def test_strip_plus(self):
        assert sanitize_csv_field("+cmd") == "cmd"

    def test_strip_minus(self):
        assert sanitize_csv_field("-cmd") == "cmd"

    def test_strip_at(self):
        assert sanitize_csv_field("@SUM(A1)") == "SUM(A1)"

    def test_strip_tab(self):
        assert sanitize_csv_field("\tcmd") == "cmd"

    def test_strip_cr(self):
        assert sanitize_csv_field("\rcmd") == "cmd"

    def test_strip_multiple_leading(self):
        assert sanitize_csv_field("=+@cmd") == "cmd"

    def test_number_as_string(self):
        assert sanitize_csv_field("12345") == "12345"

    def test_empty_string(self):
        assert sanitize_csv_field("") == ""


class TestParseNumber:
    def test_integer(self):
        assert parse_number("25000") == 25000.0

    def test_float(self):
        assert parse_number("25000.50") == 25000.50

    def test_with_spaces(self):
        assert parse_number("  25000  ") == 25000.0

    def test_negative(self):
        assert parse_number("-100") == -100.0

    def test_invalid_string(self):
        with pytest.raises(ValueError):
            parse_number("abc")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse_number("")

    def test_nan(self):
        with pytest.raises(ValueError):
            parse_number("nan")
