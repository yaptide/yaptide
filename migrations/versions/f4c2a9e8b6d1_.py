"""Who looks at a running simulation's partial results, and the maps asked for

Revision ID: f4c2a9e8b6d1
Revises: e3b9c1d7f5a2
Create Date: 2026-11-05 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f4c2a9e8b6d1"
down_revision = "e3b9c1d7f5a2"
branch_labels = None
depends_on = None


def upgrade():
    """Adds PartialViewer and PartialPage"""
    op.create_table(
        "PartialViewer",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("simulation_id", sa.Integer(), nullable=False),
        sa.Column("viewer", sa.String(length=64), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["simulation_id"], ["Simulation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("simulation_id", "viewer"),
    )
    op.create_table(
        "PartialPage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("simulation_id", sa.Integer(), nullable=False),
        sa.Column("estimator", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("page_name", sa.String(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("primaries", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["simulation_id"], ["Simulation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("simulation_id", "estimator", "page_number"),
    )


def downgrade():
    """Drops PartialViewer and PartialPage"""
    op.drop_table("PartialPage")
    op.drop_table("PartialViewer")
