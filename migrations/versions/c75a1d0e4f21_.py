"""Result pages kept in object storage

Revision ID: c75a1d0e4f21
Revises: 5003b9acb1f4
Create Date: 2026-10-14 19:40:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c75a1d0e4f21'
down_revision = '5003b9acb1f4'
branch_labels = None
depends_on = None


def upgrade():
    """Creates the PageObject table"""
    op.create_table(
        'PageObject',
        sa.Column('page_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('format', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['page_id'], ['Page.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('page_id'),
    )


def downgrade():
    """Drops the PageObject table"""
    op.drop_table('PageObject')
