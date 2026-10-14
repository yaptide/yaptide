"""empty message

Revision ID: 5003b9acb1f4
Revises: 41149fa64bd2
Create Date: 2024-12-10 22:51:14.262553

"""
import gzip
import json
import logging

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '5003b9acb1f4'
down_revision = '41149fa64bd2'
branch_labels = None
depends_on = None

# the table as it is at this revision - not the application's model, which follows the latest revision
pages = sa.table(
    "Page", sa.column("id"), sa.column("compressed_data"), sa.column("page_name"), sa.column("page_dimension")
)


def upgrade():
    """Copies the name and dimension of each page out of its data"""
    with op.batch_alter_table('Page', schema=None) as batch_op:
        batch_op.add_column(sa.Column('page_name', sa.String(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column('page_dimension', sa.Integer(), nullable=False, server_default="0"))

    bind = op.get_bind()
    for page in bind.execute(sa.select(pages.c.id, pages.c.compressed_data)).all():
        if not page.compressed_data:
            logging.warning('Missing page data for page ID = %s', page.id)
            continue
        data = json.loads(gzip.decompress(page.compressed_data).decode("utf-8"))
        bind.execute(
            pages.update()
            .where(pages.c.id == page.id)
            .values(page_dimension=int(data["dimensions"]), page_name=str(data["metadata"]["name"]))
        )


def downgrade():
    """Drops the copied page name and dimension"""
    with op.batch_alter_table('Page', schema=None) as batch_op:
        batch_op.drop_column('page_dimension')
        batch_op.drop_column('page_name')

    # ### end Alembic commands ###
