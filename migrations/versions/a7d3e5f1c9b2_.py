"""A task the user asked to finish early

Revision ID: a7d3e5f1c9b2
Revises: f4c2a9e8b6d1
Create Date: 2026-11-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7d3e5f1c9b2"
down_revision = "f4c2a9e8b6d1"
branch_labels = None
depends_on = None


def upgrade():
    """Adds Task.finish_requested"""
    with op.batch_alter_table("Task") as batch_op:
        batch_op.add_column(sa.Column("finish_requested", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    """Drops Task.finish_requested"""
    with op.batch_alter_table("Task") as batch_op:
        batch_op.drop_column("finish_requested")
