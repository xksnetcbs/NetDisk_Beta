"""invite codes activation

Revision ID: 7f3c1a2b9c10
Revises: d6d36b7fb482
Create Date: 2026-05-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "7f3c1a2b9c10"
down_revision = "d6d36b7fb482"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "invite_codes" not in tables:
        op.create_table(
            "invite_codes",
            sa.Column("id", sa.BigInteger(), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("note", sa.String(length=255), nullable=True),
            sa.Column("created_by", sa.BigInteger(), nullable=True),
            sa.Column("used_count", sa.BigInteger(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("invite_codes", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_invite_codes_code"), ["code"], unique=True)
            batch_op.create_index(batch_op.f("ix_invite_codes_created_by"), ["created_by"], unique=False)
    else:
        invite_columns = {c["name"] for c in inspector.get_columns("invite_codes")}
        with op.batch_alter_table("invite_codes", schema=None) as batch_op:
            if "code" not in invite_columns:
                batch_op.add_column(sa.Column("code", sa.String(length=64), nullable=False))
            if "enabled" not in invite_columns:
                batch_op.add_column(sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
            if "note" not in invite_columns:
                batch_op.add_column(sa.Column("note", sa.String(length=255), nullable=True))
            if "created_by" not in invite_columns:
                batch_op.add_column(sa.Column("created_by", sa.BigInteger(), nullable=True))
            if "used_count" not in invite_columns:
                batch_op.add_column(sa.Column("used_count", sa.BigInteger(), nullable=False, server_default="0"))
            if "created_at" not in invite_columns:
                batch_op.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
            if "updated_at" not in invite_columns:
                batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

    user_columns = {c["name"] for c in inspector.get_columns("users")}
    with op.batch_alter_table("users", schema=None) as batch_op:
        if "invite_code" not in user_columns:
            batch_op.add_column(sa.Column("invite_code", sa.String(length=64), nullable=True))
            batch_op.create_index(batch_op.f("ix_users_invite_code"), ["invite_code"], unique=False)
        if "is_activated" not in user_columns:
            batch_op.add_column(sa.Column("is_activated", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "users" in inspector.get_table_names():
        user_columns = {c["name"] for c in inspector.get_columns("users")}
        with op.batch_alter_table("users", schema=None) as batch_op:
            if "is_activated" in user_columns:
                batch_op.drop_column("is_activated")
            if "invite_code" in user_columns:
                batch_op.drop_index(batch_op.f("ix_users_invite_code"))
                batch_op.drop_column("invite_code")

    if "invite_codes" in inspector.get_table_names():
        op.drop_table("invite_codes")
