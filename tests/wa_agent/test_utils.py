"""Tests for src.wa_agent.utils."""

import pytest
from src.wa_agent.utils import (
    parse_bool,
    parse_int,
    parse_float,
    clean_text,
    normalize_key,
)


def test_parse_bool():
    assert parse_bool("1") is True
    assert parse_bool("true") is True
    assert parse_bool("yes") is True
    assert parse_bool("on") is True
    assert parse_bool("0") is False
    assert parse_bool("false") is False
    assert parse_bool("no") is False
    assert parse_bool("off") is False
    assert parse_bool("") is False


def test_parse_int():
    assert parse_int("42") == 42
    assert parse_int("abc") == 0
    assert parse_int("42", default=10) == 42
    assert parse_int("abc", default=10) == 10
    assert parse_int("42", minimum=50) == 50
    assert parse_int("42", maximum=10) == 10


def test_parse_float():
    assert parse_float("3.14") == 3.14
    assert parse_float("abc") == 0.0
    assert parse_float("3.14", default=1.0) == 3.14


def test_clean_text():
    assert clean_text("  hello  world  ") == "hello world"
    assert clean_text(None) == ""
    assert clean_text("") == ""


def test_normalize_key():
    assert normalize_key("Hello World") == "helloworld"
    assert normalize_key("你好") == "你好"
    assert normalize_key("") == ""
