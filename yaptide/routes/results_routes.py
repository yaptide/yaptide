from flask import request
from flask_restful import Resource

from yaptide.persistence.database import db
from yaptide.persistence.models import SimulationModel, EstimatorModel, PageModel

from yaptide.routes.utils.response_templates import yaptide_response


class Results(Resource):
    """Class responsible for managing results"""

    @staticmethod
    def post():
        """
        Method for saving results
        Used by the jobs at the end of simulation
        Structure required by this method to work properly:
        {
            "simulation_id": <int>,
            "update_key": <string>,
            "estimators": <dict>
        }
        """
        payload_dict: dict = request.get_json(force=True)
        if {"simulation_id", "update_key", "update_dict"} != set(payload_dict.keys()):
            return yaptide_response(message="Incomplete JSON data", code=400)

        sim_id = payload_dict["simulation_id"]
        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(id=sim_id).first()

        if not simulation:
            return yaptide_response(message="Task does not exist", code=400)

        if not simulation.check_update_key(payload_dict["update_key"]):
            return yaptide_response(message="Invalid update key", code=400)
        
        for estimator_dict in payload_dict["estimators"]:
            # We forsee the possibility of the estimator being created earlier as element of partial results
            estimator: EstimatorModel = db.session.query(EstimatorModel).filter_by(
                simulation_id=sim_id, name=estimator_dict["name"]).first()
            
            if not estimator:
                estimator = EstimatorModel(name=estimator_dict["name"], simulation_id=simulation.id)
                estimator.data = estimator_dict["metadata"]
                db.session.add(estimator)
                db.session.commit()
        
        return yaptide_response(message="Results saved", code=202)