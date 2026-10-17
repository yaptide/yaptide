"""One event stream per user: saves of the tasks' progress and new simulations wake it, events name the user

Revision ID: 2a6c8e0b4d17
Revises: 8d3f1b6a2c4e
Create Date: 2026-10-17 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2a6c8e0b4d17'
down_revision = '8d3f1b6a2c4e'
branch_labels = None
depends_on = None

# the same as NOTIFY_SIMULATION_FUNCTION and NOTIFY_SIMULATION_TRIGGER in yaptide/persistence/models.py, at this revision
FUNCTION = """
CREATE OR REPLACE FUNCTION notify_simulation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' OR OLD.job_state IS DISTINCT FROM NEW.job_state
            OR OLD.partial_primaries IS DISTINCT FROM NEW.partial_primaries
            OR OLD.progress_revision IS DISTINCT FROM NEW.progress_revision THEN
        PERFORM pg_notify('yaptide_simulation', json_build_object('simulation', NEW.id, 'user', NEW.user_id)::text);
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql
"""
TRIGGER = """
CREATE OR REPLACE TRIGGER simulation_stream_events
AFTER INSERT OR UPDATE OF job_state, partial_primaries, progress_revision ON "Simulation"
FOR EACH ROW EXECUTE FUNCTION notify_simulation()
"""
# those of 7c2e9a4d1b3f and 8d3f1b6a2c4e
PREVIOUS_FUNCTION = """
CREATE OR REPLACE FUNCTION notify_simulation() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('yaptide_simulation', NEW.id::text);
    RETURN NEW;
END
$$ LANGUAGE plpgsql
"""
PREVIOUS_TRIGGER = """
CREATE OR REPLACE TRIGGER simulation_stream_events AFTER UPDATE OF job_state, partial_primaries ON "Simulation"
FOR EACH ROW WHEN (OLD.job_state IS DISTINCT FROM NEW.job_state OR OLD.partial_primaries IS DISTINCT FROM
NEW.partial_primaries) EXECUTE FUNCTION notify_simulation()
"""


def upgrade():
    """Adds the revision of the tasks' progress, and on Postgres the trigger following it and new simulations"""
    with op.batch_alter_table('Simulation') as batch_op:
        batch_op.add_column(sa.Column('progress_revision', sa.BigInteger(), nullable=False, server_default="0"))
    if op.get_bind().dialect.name == "postgresql":
        op.execute(FUNCTION)
        op.execute(TRIGGER)


def downgrade():
    """Puts the previous trigger back; Postgres drops a column only without the triggers reading it"""
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute('DROP TRIGGER IF EXISTS simulation_stream_events ON "Simulation"')
        op.execute(PREVIOUS_FUNCTION)
    with op.batch_alter_table('Simulation') as batch_op:
        batch_op.drop_column('progress_revision')
    if postgres:
        op.execute(PREVIOUS_TRIGGER)
