"""empty message

Revision ID: 41149fa64bd2
Revises: 4027fc5cbcb1
Create Date: 2024-12-07 20:23:21.686840

"""
import gzip
import json
import logging

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '41149fa64bd2'
down_revision = '4027fc5cbcb1'
branch_labels = None
depends_on = None

# the tables as they are at this revision - a migration must not use the application's models, which follow the
# latest revision (and e.g. load tables a database at this revision does not have yet)
simulations = sa.table(
    "Simulation", sa.column("id"), sa.column("sim_type"), sa.column("input_type")
)
inputs = sa.table("Input", sa.column("simulation_id"), sa.column("compressed_data"))
estimators = sa.table("Estimator", sa.column("id"), sa.column("simulation_id"), sa.column("name"), sa.column("file_name"))


def unpack(data):
    """The gzipped JSON the models store"""
    return json.loads(gzip.decompress(data).decode("utf-8")) if data else None


def upgrade():
    """Keeps the result file name of each estimator and gives it a readable name"""
    with op.batch_alter_table('Estimator', schema=None) as batch_op:
        batch_op.add_column(sa.Column('file_name', sa.String(), nullable=False, server_default=""))

    bind = op.get_bind()
    for simulation in bind.execute(sa.select(simulations)).all():
        rows = bind.execute(
            sa.select(estimators.c.id, estimators.c.name)
            .where(estimators.c.simulation_id == simulation.id)
            .order_by(estimators.c.id)
        ).all()
        outputs = None
        if simulation.sim_type == "fluka" and simulation.input_type == "EDITOR":
            input_row = bind.execute(
                sa.select(inputs.c.compressed_data).where(inputs.c.simulation_id == simulation.id)
            ).first()
            try:
                outputs = unpack(input_row.compressed_data)["input_json"]["scoringManager"]["outputs"]
            except (AttributeError, KeyError, TypeError, ValueError):
                logging.warning("Simulation %d has no editor outputs, estimator names stay", simulation.id)
        for i, row in enumerate(rows):
            if outputs is not None and i < len(outputs):
                name = outputs[i]["name"]
            else:
                name = row.name.rstrip("_")
            bind.execute(estimators.update().where(estimators.c.id == row.id).values(name=name, file_name=row.name))


def downgrade():
    """Puts the file names back as estimator names"""
    op.execute("""
        UPDATE "Estimator"
        SET name = file_name
    """)
    with op.batch_alter_table('Estimator', schema=None) as batch_op:
        batch_op.drop_column('file_name')

    # ### end Alembic commands ###


