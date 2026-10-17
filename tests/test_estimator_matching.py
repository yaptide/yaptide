"""Results of editor simulations are bound to the editor outputs by the result file each output writes, in any order"""

import copy
import json
import logging
import random
from pathlib import Path

import pytest

from yaptide.application import create_app
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import BatchSimulationModel, ClusterModel, EstimatorModel, InputModel, KeycloakUserModel
from yaptide.routes.common_sim_routes import store_partial_results, store_results
from yaptide.routes.utils.tokens import encode_auth_token, encode_simulation_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType
from yaptide.utils.sim_utils import merge_simulation_outputs

RES = Path(__file__).parent / "res"
EDITOR_JSON = json.loads((RES / "json_payload_editor.json").read_text())["input_json"]
# convertmc on the cluster names them with a trailing underscore: yz_profile_, entrance_, z_profile_, peak_
RESULTS = json.loads((RES / "json_with_results.json").read_text())["estimators"]


@pytest.fixture
def client():
    """Test client of a logged in user"""
    app = create_app()
    with app.app_context():
        db.create_all()
        user = KeycloakUserModel(username="plgtest")
        db.session.add_all([user, ClusterModel(cluster_name="ares")])
        db.session.commit()
        client = app.test_client()
        client.set_cookie("access_token", encode_auth_token(user.id)[0], domain="127.0.0.1")
        yield client
        db.session.remove()
        db.drop_all()


def editor_simulation(input_json: dict, sim_type: SimulationType = SimulationType.SHIELDHIT) -> BatchSimulationModel:
    """A running simulation of the editor input"""
    simulation = BatchSimulationModel(
        job_id="editorjob",
        user_id=db.session.query(KeycloakUserModel.id).scalar(),
        cluster_id=db.session.query(ClusterModel.id).scalar(),
        title="editor",
        input_type=InputType.EDITOR.value,
        sim_type=sim_type.value,
        job_state=EntityState.RUNNING.value,
    )
    db.session.add(simulation)
    db.session.commit()
    input_model = InputModel(simulation_id=simulation.id)
    input_model.data = {"input_json": input_json}
    db.session.add(input_model)
    db.session.commit()
    return simulation


def results(*names: str) -> list[dict]:
    """Estimators of the given result files, each telling its file in the metadata"""
    estimators = []
    for name in names:
        estimator = copy.deepcopy(RESULTS[0])
        estimator["name"] = name
        estimator["metadata"] = {"file": name}
        estimators.append(estimator)
    return estimators


def outputs(*names: str, detector: str = "mesh") -> list[dict]:
    """Editor outputs of the given names, scored with the detector"""
    return [{"name": name, "uuid": f"uuid-{name}", "detectorUuid": detector, "quantities": []} for name in names]


def read_results(client) -> list[dict]:
    """The estimators as the UI reads them"""
    return client.get("/results", query_string={"job_id": "editorjob"}).get_json()["estimators"]


def bindings(client) -> list[tuple]:
    """Name, result file (from the metadata) and output uuid of each estimator the UI gets"""
    return [(e["name"], e["metadata"].get("file"), e.get("output_uuid")) for e in read_results(client)]


def test_results_in_any_order_are_bound_to_the_outputs_writing_them(client):
    """The cluster's results (trailing underscores), shuffled: each output gets its own file's results"""
    simulation = editor_simulation(EDITOR_JSON)
    shuffled = copy.deepcopy(RESULTS)
    random.Random(53).shuffle(shuffled)
    for estimator in shuffled:
        estimator["metadata"]["file"] = estimator["name"]
    payload = {"simulation_id": simulation.id, "update_key": encode_simulation_auth_token(simulation.id)}

    assert client.post("/results", json={**payload, "estimators": shuffled}).status_code == 202

    expected = [(o["name"], o["name"] + "_", o["uuid"]) for o in EDITOR_JSON["scoringManager"]["outputs"]]
    assert bindings(client) == expected


def test_merged_results_of_the_tasks_are_bound_to_the_outputs(client):
    """The merge on the server names the estimators without the trailing underscore"""
    editor_simulation(EDITOR_JSON)
    merged = merge_simulation_outputs([RES / "bdo" / "task_1", RES / "bdo" / "task_2"])

    store_results(db.session.query(BatchSimulationModel).one(), merged)

    estimators = read_results(client)
    names = [o["name"] for o in EDITOR_JSON["scoringManager"]["outputs"]]
    assert [e["name"] for e in estimators] == names
    assert [e["metadata"]["file_corename"] for e in estimators] == names
    assert [e["output_uuid"] for e in estimators] == [o["uuid"] for o in EDITOR_JSON["scoringManager"]["outputs"]]


def test_fluka_results_are_bound_by_the_output_unit(client):
    """FLUKA files are named by the output unit, from 21 for each output the converter scores: not alphabetically,
    and an output without a supported detector writes no file
    """
    input_json = {
        "detectorManager": {
            "detectors": [
                {"uuid": "mesh", "geometryData": {"geometryType": "Mesh"}},
                {"uuid": "zone", "geometryData": {"geometryType": "Zone"}},
            ]
        },
        "scoringManager": {
            "outputs": outputs("Zdose") + outputs("Unscored", detector="zone") + outputs("Adose", "Mdose")
        },
    }
    editor_simulation(input_json, SimulationType.FLUKA)

    store_results(db.session.query(BatchSimulationModel).one(), results("23", "21", "22"))

    assert bindings(client) == [
        ("Zdose", "21", "uuid-Zdose"),
        ("Adose", "22", "uuid-Adose"),
        ("Mdose", "23", "uuid-Mdose"),
    ]


def test_final_results_replace_partial_ones_of_the_same_output(client):
    """Partial results merged on the server ("dose"), final ones from the cluster ("dose_"): one estimator each"""
    editor_simulation({"scoringManager": {"outputs": outputs("dose", "dose2")}})
    simulation = db.session.query(BatchSimulationModel).one()

    assert store_partial_results(simulation, results("dose", "dose2"), 300)
    store_results(simulation, results("dose2_", "dose_"))

    assert bindings(client) == [("dose", "dose_", "uuid-dose"), ("dose2", "dose2_", "uuid-dose2")]
    assert {e.file_name for e in db.session.query(EstimatorModel)} == {"dose_", "dose2_"}


def test_results_uploaded_to_storage_are_bound_to_the_outputs(client, monkeypatch):
    """The cluster uploads the pages and tells which it uploaded (POST /results/done), listed in any order"""
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setattr(result_storage, "stored_matches", lambda key, size, md5: True)
    monkeypatch.setattr(result_storage, "page_url", lambda key: key)
    simulation = editor_simulation({"scoringManager": {"outputs": outputs("dose", "dose2")}})
    pages = [{"page_number": 0, "name": "", "dimensions": 1, "size": 1, "md5": "1B2M2Y8AsgTpgAmY7PhCfg=="}]
    estimators = [{"name": name, "metadata": {"file": name}, "pages": pages} for name in ("dose_", "dose2_")]
    payload = {"simulation_id": simulation.id, "update_key": encode_simulation_auth_token(simulation.id)}

    assert client.post("/results/done", json={**payload, "estimators": estimators}).status_code == 202

    assert bindings(client) == [("dose", "dose_", "uuid-dose"), ("dose2", "dose2_", "uuid-dose2")]


def test_results_no_output_writes_keep_their_file_name(client, caplog):
    """Not bound to any output, and said so"""
    editor_simulation({"scoringManager": {"outputs": outputs("dose")}})

    with caplog.at_level(logging.ERROR):
        store_results(db.session.query(BatchSimulationModel).one(), results("extra_", "dose_"))

    assert bindings(client) == [("dose", "dose_", "uuid-dose"), ("extra_", "extra_", None)]
    assert "extra_" in caplog.text


def test_results_stored_before_are_bound_by_their_file(client):
    """Estimators stored by the earlier versions get the output of their file too"""
    simulation = editor_simulation({"scoringManager": {"outputs": outputs("dose", "dose2")}})
    for name, file_name in (("dose", "dose2_"), ("dose2", "dose_")):
        # bound by the sorted names, a different order of the files gave an output the results of another
        estimator = EstimatorModel(name=name, file_name=file_name, simulation_id=simulation.id)
        estimator.data = {"file": file_name}
        db.session.add(estimator)
    db.session.commit()

    assert bindings(client) == [("dose", "dose2_", "uuid-dose2"), ("dose2", "dose_", "uuid-dose")]
