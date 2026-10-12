"""Stable, private WeChat attachment project and message-to-file mapping.

Revision ID: d913e0c624ba
Revises: b731c0d516fa
Create Date: 2026-10-12
"""

from alembic import op
import sqlalchemy as sa


revision = "d913e0c624ba"
down_revision = "b731c0d516fa"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wechat_file_sync_states",
        sa.Column("instance_id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "wechat_file_imports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("source_uid", sa.String(64), nullable=False),
        sa.Column("message_uid", sa.Text(), nullable=False),
        sa.Column("chat_username", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("source_rel_path", sa.Text(), nullable=True),
        sa.Column("source_signature", sa.String(191), nullable=True),
        sa.Column("source_md5", sa.String(32), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("file_node_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("instance_id", "source_uid", name="uq_wechat_file_source"),
    )
    op.create_index("ix_wechat_file_imports_instance_id", "wechat_file_imports", ["instance_id"])
    op.create_index("ix_wechat_file_imports_file_node_id", "wechat_file_imports", ["file_node_id"])


def downgrade():
    op.drop_table("wechat_file_imports")
    op.drop_table("wechat_file_sync_states")
