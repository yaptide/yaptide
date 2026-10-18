"""What the admins of a cluster said when its login node closed the connection, for the users waiting for it

Revision ID: d2a8f6c4e1b9
Revises: b7d4e9f1a2c3
Create Date: 2026-10-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd2a8f6c4e1b9'
down_revision = 'b7d4e9f1a2c3'
branch_labels = None
depends_on = None


def upgrade():
    """Adds Cluster.notice"""
    with op.batch_alter_table('Cluster', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notice', sa.Text(), nullable=True))


def downgrade():
    """Drops Cluster.notice: the next login the cluster refuses stores it again"""
    with op.batch_alter_table('Cluster', schema=None) as batch_op:
        batch_op.drop_column('notice')
