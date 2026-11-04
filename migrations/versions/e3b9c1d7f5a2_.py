"""Pages of partial results replaced by the final ones, removed 15 minutes after the simulation ended

Revision ID: e3b9c1d7f5a2
Revises: d2a8f6c4e1b9
Create Date: 2026-11-04 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e3b9c1d7f5a2"
down_revision = "d2a8f6c4e1b9"
branch_labels = None
depends_on = None


def upgrade():
    """Adds ExpiringObject"""
    op.create_table(
        "ExpiringObject",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("simulation_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("delete_after", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["simulation_id"], ["Simulation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ExpiringObject", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ExpiringObject_delete_after"), ["delete_after"], unique=False)


def downgrade():
    """Drops ExpiringObject: the pages it listed stay in storage until their simulation is deleted"""
    with op.batch_alter_table("ExpiringObject", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ExpiringObject_delete_after"))
    op.drop_table("ExpiringObject")
