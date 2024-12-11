import argparse
import json
import logging
import signal
import ssl
from pathlib import Path
from urllib import request


def send_simulation_results(output_Path: Path, simulation_id: int, update_key: str, backend_url: str):
    """Sends simulation results to backend"""
    if not backend_url:
        logging.error("Backend url not specified")
        return

    estimators = []
    for filename in sorted(output_Path.iterdir()):
        if filename.suffix != ".json":
            continue
        with open(filename, "r") as json_file:
            est_dict = json.load(json_file)
            est_dict["name"] = filename.stem
            estimators.append(est_dict)

    dict_to_send = {
        "simulation_id": simulation_id,
        "update_key": update_key,
        "estimators": estimators,
    }
    results_url = f"{backend_url}/results"
    context = ssl.SSLContext()

    req = request.Request(results_url,
                          json.dumps(dict_to_send).encode(), {'Content-Type': 'application/json'},
                          method='POST')

    try:
        with request.urlopen(req, context=context) as res:  # skipcq: BAN-B310
            if res.getcode() != 202:
                logging.warning("Sending update to %s failed", results_url)
    except Exception as e:  # skipcq: PYL-W0703
        logging.error("Sending update to %s failed: %s", results_url, str(e))


def send_simulation_state_update(simulation_id: int, update_key: str, backend_url: str, simulation_state: str):
    """Sends simulation state to backend"""
    dict_to_send = {"sim_id": simulation_id, "job_state": simulation_state, "update_key": update_key}
    jobs_url = f"{backend_url}/jobs"
    context = ssl.SSLContext()

    req = request.Request(jobs_url,
                          json.dumps(dict_to_send).encode(), {'Content-Type': 'application/json'},
                          method='POST')
    try:
        with request.urlopen(req, context=context) as res:  # skipcq: BAN-B310
            if res.getcode() != 202:
                logging.warning("Sending update to %s failed", jobs_url)
    except Exception as e:  # skipcq: PYL-W0703
        logging.error("Sending update to %s failed: %s", jobs_url, str(e))


if __name__ == "__main__":
    # This script allows sending simulation data (either results or state updates) to a backend server.
    # The user must specify the simulation ID, update_key, and backend URL, and either:
    #    - directory containing JSON result files (`--results_dir`) to send simulation results.
    #    - simulation state (`--state`) to send a state update.
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler()])
    parser = argparse.ArgumentParser()
    parser.add_argument("--sim_id", type=int, required=True)
    parser.add_argument("--update_key", type=str, required=True)
    parser.add_argument("--backend_url", type=str, required=True)
    parser.add_argument("--output_dir", type=str, required=False)
    parser.add_argument("--simulation_state", type=str, required=False)
    args = parser.parse_args()

    logging.info("sim_id %s", args.sim_id)
    logging.info("update_key %s", args.update_key)
    logging.info("backend_url %s", args.backend_url)

    if args.output_dir:
        logging.info("Sending simulation results for directory: %s", args.output_dir)
        send_simulation_results(output_Path=Path(args.output_dir),
                                simulation_id=args.sim_id,
                                update_key=args.update_key,
                                backend_url=args.backend_url)
    elif args.simulation_state:
        logging.info("No output_dir provided, sending simulation state update %s", args.simulation_state)
        send_simulation_state_update(simulation_id=args.sim_id,
                                     update_key=args.update_key,
                                     backend_url=args.backend_url,
                                     simulation_state=args.simulation_state)
    else:
        logging.error("Either --results_dir or --simulation_state must be provided.")
