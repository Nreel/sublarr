"""Sublarr CLI — root group and global options."""

import os

import click

from cli.client import SublarrClient


def _default_url() -> str:
    """API base URL derived from SUBLARR_PORT (default 5765, the BootSettings default)."""
    return f"http://localhost:{os.environ.get('SUBLARR_PORT', '5765')}"


@click.group()
@click.option(
    "--url",
    envvar="SUBLARR_URL",
    default=_default_url,
    show_default=True,
    help="Sublarr API base URL.",
)
@click.option(
    "--api-key",
    envvar="SUBLARR_API_KEY",
    default="",
    help="API key (or set SUBLARR_API_KEY env var).",
)
@click.pass_context
def cli(ctx: click.Context, url: str, api_key: str) -> None:
    """Sublarr subtitle manager — command-line interface."""
    ctx.ensure_object(dict)
    ctx.obj["client"] = SublarrClient(url, api_key)


from cli.commands.search import search
from cli.commands.status import status
from cli.commands.sync import sync
from cli.commands.translate import translate

cli.add_command(search)
cli.add_command(translate)
cli.add_command(sync)
cli.add_command(status)
