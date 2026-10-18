"""When each user last followed the status of their simulations, for the engine reading HPC progress

Revision ID: 5e7a3c9d2b10
Revises: 2a6c8e0b4d17
Create Date: 2026-10-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '5e7a3c9d2b10'
down_revision = '2a6c8e0b4d17'
branch_labels = None
depends_on = None


def upgrade():
    """Adds UserActivity"""
    op.create_table(
        'UserActivity',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['User.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade():
    """Removes UserActivity"""
    op.drop_table('UserActivity')
