"""empty message

Revision ID: 41149fa64bd2
Revises: 4027fc5cbcb1
Create Date: 2024-12-07 20:23:21.686840

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from yaptide.persistence.models import EstimatorModel, SimulationModel
from yaptide.utils.enums import InputType, SimulationType
import logging

# revision identifiers, used by Alembic.
revision = '41149fa64bd2'
down_revision = '4027fc5cbcb1'
branch_labels = None
depends_on = None

def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('Estimator', schema=None) as batch_op:
        batch_op.add_column(sa.Column('file_name', sa.String(), nullable=False, server_default=""))

    bind = op.get_bind()
    session = sessionmaker(bind=bind)()
    
    simulations = session.query(SimulationModel).all()

    for simulation in simulations:
        # Query all estimators for this simulation
        estimators = session.query(EstimatorModel).filter(EstimatorModel.simulation_id == simulation.id).all()

        try:
            for i, estimator in enumerate(estimators):
                file_name = estimator.name
                if simulation.sim_type == SimulationType.FLUKA.value and simulation.input_type == InputType.EDITOR.value:
                    if simulation.inputs:
                      estimator_name = simulation.inputs[0].data["input_json"]["scoringManager"]["outputs"][i]["name"]
                    else:
                      logging.warning('Missing input info in editor data for estimator %s', estimator.name)
                      logging.warning('Falling back to file_name as estimator name')
                      estimator_name = file_name.rstrip('_')
                        
                else:
                    estimator_name = file_name[:-1] if file_name[-1] == "_" else file_name

                # Update the estimator's name and file_name
                estimator.name = estimator_name
                estimator.file_name = file_name
        except Exception as e:
            logging.error(f"Failed to migrate name and file_name for estimator with ID {estimator.id}: {e}")  

        if simulation.input_type == InputType.EDITOR.value:
            try:
                outputs = simulation.inputs[0].data["input_json"]["scoringManager"]["outputs"]
                output_names = [output["name"] for output in outputs]
                
                # Reorder estimators to match the output names
                estimators.sort(key=lambda estimator: output_names.index(estimator.name))
            except Exception as e:
                logging.warning(f"Failed to reorder estimator with ID {estimator.id}: {e}")    
    session.commit()
    session.close()


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.execute("""
        UPDATE "Estimator"
        SET name = file_name
    """)
    with op.batch_alter_table('Estimator', schema=None) as batch_op:
        batch_op.drop_column('file_name')

    # ### end Alembic commands ###


