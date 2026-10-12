"""Durable NetDisk message publication outbox.

Revision ID: c48a716b902e
Revises: 9b21f7a0b3d1
Create Date: 2026-10-11
"""

from alembic import op
import sqlalchemy as sa


revision = "c48a716b902e"
down_revision = "9b21f7a0b3d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "message_bridge_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("event_uid", sa.String(191), nullable=False),
        sa.Column("event_kind", sa.String(32), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(64), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_uid", name="uq_message_bridge_event_uid"),
    )
    op.create_index("ix_message_bridge_outbox_source_id", "message_bridge_outbox", ["source_id"])
    op.create_index("ix_message_bridge_outbox_delivered_at", "message_bridge_outbox", ["delivered_at"])


def downgrade():
    op.drop_table("message_bridge_outbox")
