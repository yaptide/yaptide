"""Partial results of running simulations, and events for the streams following a simulation

Revision ID: 7c2e9a4d1b3f
Revises: 4b8e2c6d1a7f
Create Date: 2026-10-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7c2e9a4d1b3f'
down_revision = '4b8e2c6d1a7f'
branch_labels = None
depends_on = None

# the same as NOTIFY_SIMULATION_FUNCTION and NOTIFY_SIMULATION_TRIGGER in yaptide/persistence/models.py, at this revision
FUNCTION = """
CREATE OR REPLACE FUNCTION notify_simulation() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('yaptide_simulation', NEW.id::text);
    RETURN NEW;
END
$$ LANGUAGE plpgsql
"""
TRIGGER = """
CREATE OR REPLACE TRIGGER simulation_stream_events AFTER UPDATE OF job_state, partial_primaries ON "Simulation"
FOR EACH ROW WHEN (OLD.job_state IS DISTINCT FROM NEW.job_state OR OLD.partial_primaries IS DISTINCT FROM
NEW.partial_primaries) EXECUTE FUNCTION notify_simulation()
"""


def upgrade():
    """Adds the partial results columns, and on Postgres the trigger sending the events"""
    with op.batch_alter_table('Simulation') as batch_op:
        batch_op.add_column(sa.Column('partial_primaries', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('partial_time', sa.DateTime(timezone=True), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        op.execute(FUNCTION)
        op.execute(TRIGGER)


def downgrade():
    """Drops the trigger, its function and the columns"""
    if op.get_bind().dialect.name == "postgresql":
        op.execute('DROP TRIGGER IF EXISTS simulation_stream_events ON "Simulation"')
        op.execute("DROP FUNCTION IF EXISTS notify_simulation()")
    with op.batch_alter_table('Simulation') as batch_op:
        batch_op.drop_column('partial_time')
        batch_op.drop_column('partial_primaries')
