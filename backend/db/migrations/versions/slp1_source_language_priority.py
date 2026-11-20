"""Language profiles: source_language → ordered source_languages_json.

Translation direction became a per-profile policy: the profile holds a
priority list of source languages (first = strongest preference) instead of
one source code + display name. The display name was always derivable via
language_name(code), so it is dropped along with the single column.

Both old columns are nullable-history: databases created from the current
model after the change already have source_languages_json and no old
columns, and app.py's pre-Alembic patch adds the new column on stamped-at-head
databases. Every step reflects first and skips what is already done.

Revision ID: slp1_source_language_priority
Revises: gtl1_glossary_target_language
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "slp1_source_language_priority"
down_revision = "gtl1_glossary_target_language"
branch_labels = None
depends_on = None

_TABLE = "language_profiles"


def _columns() -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    cols = _columns()
    if "source_languages_json" not in cols:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(
                sa.Column(
                    "source_languages_json", sa.Text(), nullable=False, server_default='["en"]'
                )
            )
        if "source_language" in _columns():
            bind = op.get_bind()
            for row in bind.execute(sa.text(f"SELECT id, source_language FROM {_TABLE}")):
                code = (row[1] or "").strip()
                bind.execute(
                    sa.text(f"UPDATE {_TABLE} SET source_languages_json = :langs WHERE id = :id"),
                    {"langs": json.dumps([code] if code else ["en"]), "id": row[0]},
                )
    # Drop the superseded columns once the priority list exists.
    cols = _columns()
    if "source_language" in cols or "source_language_name" in cols:
        with op.batch_alter_table(_TABLE) as batch:
            if "source_language" in cols:
                batch.drop_column("source_language")
            if "source_language_name" in cols:
                batch.drop_column("source_language_name")


def downgrade() -> None:
    cols = _columns()
    if "source_language" not in cols or "source_language_name" not in cols:
        with op.batch_alter_table(_TABLE) as batch:
            if "source_language" not in cols:
                batch.add_column(
                    sa.Column("source_language", sa.Text(), nullable=False, server_default="en")
                )
            if "source_language_name" not in cols:
                batch.add_column(
                    sa.Column("source_language_name", sa.Text(), nullable=False, server_default="English")
                )
        if "source_languages_json" in _columns():
            from config_language_data import language_name

            bind = op.get_bind()
            for row in bind.execute(sa.text(f"SELECT id, source_languages_json FROM {_TABLE}")):
                try:
                    langs = json.loads(row[1] or "[]")
                except (TypeError, ValueError):
                    langs = []
                first = langs[0] if langs else "en"
                bind.execute(
                    sa.text(
                        f"UPDATE {_TABLE} SET source_language = :code, "
                        f"source_language_name = :name WHERE id = :id"
                    ),
                    {"code": first, "name": language_name(first), "id": row[0]},
                )
    cols = _columns()
    if "source_languages_json" in cols:
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column("source_languages_json")
