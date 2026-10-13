"""SLURM status checks shared by all server processes, instead of Redis

Revision ID: b77c3e1f9a20
Revises: 5003b9acb1f4
Create Date: 2026-10-13 13:40:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b77c3e1f9a20'
down_revision = '5003b9acb1f4'
branch_labels = None
depends_on = None


def upgrade():
    """Creates the SlurmStatusCheck table"""
    op.create_table(
        'SlurmStatusCheck',
        sa.Column('simulation_id', sa.Integer(), nullable=False),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['simulation_id'], ['BatchSimulation.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('simulation_id'),
    )


def downgrade():
    """Drops the SlurmStatusCheck table"""
    op.drop_table('SlurmStatusCheck')
