"""invite codes max uses

Revision ID: 9b21f7a0b3d1
Revises: d6d36b7fb482
Create Date: 2026-05-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9b21f7a0b3d1"
down_revision = "d6d36b7fb482"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("invite_codes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("max_uses", sa.BigInteger(), nullable=True))


def downgrade():
    with op.batch_alter_table("invite_codes", schema=None) as batch_op:
        batch_op.drop_column("max_uses")
