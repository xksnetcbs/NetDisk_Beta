"""Indexed durable reply request keys for current reads and safe retries.

Revision ID: e21f39c81d62
Revises: d913e0c624ba
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

revision = "e21f39c81d62"
down_revision = "d913e0c624ba"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("message_bridge_outbox", sa.Column("reply_request_key", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_outbox_reply_request_key", "message_bridge_outbox", ["reply_request_key"])


def downgrade():
    op.drop_constraint("uq_outbox_reply_request_key", "message_bridge_outbox", type_="unique")
    op.drop_column("message_bridge_outbox", "reply_request_key")
