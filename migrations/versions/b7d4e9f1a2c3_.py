"""When a cluster whose SLURM does not answer is tried again, for the status of the simulations waiting for it

Revision ID: b7d4e9f1a2c3
Revises: 2a6c8e0b4d17
Create Date: 2026-10-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b7d4e9f1a2c3'
down_revision = '2a6c8e0b4d17'
branch_labels = None
depends_on = None


def upgrade():
    """Adds Cluster.busy_until"""
    with op.batch_alter_table('Cluster', schema=None) as batch_op:
        batch_op.add_column(sa.Column('busy_until', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    """Drops Cluster.busy_until: the engine sets it again while a cluster does not answer"""
    with op.batch_alter_table('Cluster', schema=None) as batch_op:
        batch_op.drop_column('busy_until')
