"""Primaries of partial results are summed over the tasks, beyond the range of an integer

Revision ID: 8d3f1b6a2c4e
Revises: 7c2e9a4d1b3f
Create Date: 2026-10-17 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '8d3f1b6a2c4e'
down_revision = '7c2e9a4d1b3f'
branch_labels = None
depends_on = None

# the trigger of 7c2e9a4d1b3f, as Postgres changes the type of a column only without the triggers reading it
TRIGGER = """
CREATE OR REPLACE TRIGGER simulation_stream_events AFTER UPDATE OF job_state, partial_primaries ON "Simulation"
FOR EACH ROW WHEN (OLD.job_state IS DISTINCT FROM NEW.job_state OR OLD.partial_primaries IS DISTINCT FROM
NEW.partial_primaries) EXECUTE FUNCTION notify_simulation()
"""


def alter_partial_primaries(new_type, old_type) -> None:
    """Changes the type of the column, the trigger reading it put back afterwards"""
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute('DROP TRIGGER IF EXISTS simulation_stream_events ON "Simulation"')
    with op.batch_alter_table('Simulation') as batch_op:
        batch_op.alter_column('partial_primaries', type_=new_type, existing_type=old_type)
    if postgres:
        op.execute(TRIGGER)


def upgrade():
    """Widens the column"""
    alter_partial_primaries(sa.BigInteger(), sa.Integer())


def downgrade():
    """Narrows the column back; partial results beyond an integer lose their primaries"""
    op.execute('UPDATE "Simulation" SET partial_primaries = NULL WHERE partial_primaries > 2147483647')
    alter_partial_primaries(sa.Integer(), sa.BigInteger())
