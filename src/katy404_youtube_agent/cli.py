"""Compatibility entry point for the old ``kt404-youtube`` command."""

from yt_uploader.cli import CliApp, OAuthService, main

__all__ = ["CliApp", "OAuthService", "main"]
