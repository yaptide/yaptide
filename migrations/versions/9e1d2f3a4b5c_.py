"""Postgres tells the engine about direct simulations to start or stop

Revision ID: 9e1d2f3a4b5c
Revises: c75a1d0e4f21
Create Date: 2026-10-14 22:30:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '9e1d2f3a4b5c'
down_revision = 'c75a1d0e4f21'
branch_labels = None
depends_on = None

# the same as NOTIFY_ENGINE_FUNCTION and NOTIFY_ENGINE_TRIGGER in yaptide/persistence/models.py, at this revision
FUNCTION = """
CREATE OR REPLACE FUNCTION notify_engine() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.platform = 'DIRECT' THEN
            PERFORM pg_notify('yaptide_engine', json_build_object('simulation', OLD.id, 'event', 'DELETED')::text);
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.platform = 'DIRECT' AND NEW.job_state IN ('PENDING', 'CANCELED') THEN
        PERFORM pg_notify('yaptide_engine', json_build_object('simulation', NEW.id, 'event', NEW.job_state)::text);
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql
"""
TRIGGER = """
CREATE OR REPLACE TRIGGER simulation_engine_events AFTER INSERT OR UPDATE OF job_state OR DELETE ON "Simulation"
FOR EACH ROW EXECUTE FUNCTION notify_engine()
"""


def upgrade():
    """Creates the function and the trigger sending the events (Postgres only, SQLite has no notifications)"""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(FUNCTION)
        op.execute(TRIGGER)


def downgrade():
    """Drops the trigger and the function"""
    if op.get_bind().dialect.name == "postgresql":
        op.execute('DROP TRIGGER IF EXISTS simulation_engine_events ON "Simulation"')
        op.execute("DROP FUNCTION IF EXISTS notify_engine()")
