"""Assign NetDisk calendar events to users for their Terminal schedule.

Revision ID: ae812dc409fa
Revises: c48a716b902e
"""
from alembic import op
import sqlalchemy as sa

revision = "ae812dc409fa"
down_revision = "c48a716b902e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("calendar_events", sa.Column("assignee_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_calendar_events_assignee_id", "calendar_events", ["assignee_id"])


def downgrade():
    op.drop_index("ix_calendar_events_assignee_id", table_name="calendar_events")
    op.drop_column("calendar_events", "assignee_id")
