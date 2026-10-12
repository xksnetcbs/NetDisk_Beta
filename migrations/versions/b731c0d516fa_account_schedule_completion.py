"""Persist account schedule completion and idempotent personal creation.

Revision ID: b731c0d516fa
Revises: f102dc8a716b
"""
from alembic import op
import sqlalchemy as sa

revision = "b731c0d516fa"
down_revision = "f102dc8a716b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("calendar_events", sa.Column("client_request_id", sa.String(80), nullable=True))
    op.add_column("calendar_events", sa.Column("request_digest", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_calendar_request", "calendar_events", ["created_by", "client_request_id"])
    op.create_table("schedule_overrides",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("schedule_uid", sa.String(512), nullable=False),
        sa.Column("forced_completed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "schedule_uid", name="uq_schedule_override_user_uid"))
    op.create_index("ix_schedule_overrides_user_id", "schedule_overrides", ["user_id"])


def downgrade():
    op.drop_table("schedule_overrides")
    op.drop_constraint("uq_calendar_request", "calendar_events", type_="unique")
    op.drop_column("calendar_events", "request_digest")
    op.drop_column("calendar_events", "client_request_id")
