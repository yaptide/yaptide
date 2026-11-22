import json

import pytest
from flask import Flask


def log_in(client: Flask, username: str, password: str) -> None:
    """Register and log in a local user."""
    credentials = json.dumps(dict(username=username, password=password))
    client.put("/auth/register", data=credentials, content_type="application/json")
    client.post("/auth/login", data=credentials, content_type="application/json")


@pytest.mark.parametrize(
    "sim_type, input_files, missing",
    [
        ("fluka", {"beam.dat": "NSTAT 10 0", "fl_sim (1).inp": "START 10.0"}, "fl_sim.inp"),
        ("shieldhit", {"fl_sim.inp": "START 10.0", "geo.dat": "geo"}, "beam.dat"),
    ],
)
def test_run_from_files_without_primaries_file(
    client: Flask, db_good_username: str, db_good_password: str, sim_type: str, input_files: dict, missing: str
):
    """A run from input files without the file with primaries is rejected before a simulation is created."""
    log_in(client, db_good_username, db_good_password)
    payload = {"sim_type": sim_type, "input_type": "files", "ntasks": 2, "input_files": input_files}

    resp = client.post("/jobs/direct", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 400
    assert json.loads(resp.data.decode())["message"] == f"Missing {missing} in input files"

    resp = client.get("/user/simulations", query_string={"page_size": 10, "page_idx": 1, "order_by": "start_time"})
    assert json.loads(resp.data.decode())["simulations_count"] == 0
