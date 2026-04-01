"""Tests for src.wa_agent.server."""

import pytest
from src.wa_agent.server import main, HealthHandler


def test_server_module_has_main():
    assert callable(main)


def test_health_handler_has_do_get():
    assert hasattr(HealthHandler, "do_GET")


def test_health_handler_has_send_json():
    assert hasattr(HealthHandler, "_send_json")
