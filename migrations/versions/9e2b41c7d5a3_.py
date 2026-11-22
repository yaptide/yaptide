"""Result pages kept in object storage

Revision ID: 9e2b41c7d5a3
Revises: 5003b9acb1f4
Create Date: 2026-11-22 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9e2b41c7d5a3'
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
    """Drops the PageObject table - only without pages kept in object storage, it is their only record
    (db_manage move-pages-to-postgres brings them back first)
    """
    stored = op.get_bind().execute(sa.text('SELECT count(*) FROM "PageObject"')).scalar()
    if stored:
        raise RuntimeError(
            f"{stored} result pages are kept in object storage; move them back into the database first "
            "(db_manage move-pages-to-postgres), dropping the table would lose them"
        )
    op.drop_table('PageObject')
