"""Validación de placeholders en config."""

from __future__ import annotations

import config


def test_placeholder_detection() -> None:
    assert config._is_placeholder("") is True
    assert config._is_placeholder("tu_correo@gmail.com") is True
    assert config._is_placeholder("tu_client_id.apps.googleusercontent.com") is True
    assert config._is_placeholder("tu_refresh_token") is True
    assert config._is_placeholder("andrade.nico@gmail.com") is False
    assert config._is_placeholder("1//0abcREALTOKEN") is False
    assert config._is_placeholder("GOCSPX-real-secret") is False
