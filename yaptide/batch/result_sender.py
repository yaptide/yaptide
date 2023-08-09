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
    for filename in output_Path.iterdir():
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
                          json.dumps(dict_to_send).encode(),
                          {'Content-Type': 'application/json'},
                          method='POST')

    try:
        with request.urlopen(req, context=context) as res:  # skipcq: BAN-B310
            if res.getcode() != 202:
                logging.warning("Sending update to %s failed", results_url)
    except Exception as e:  # skipcq: PYL-W0703
        print(e)


if __name__ == "__main__":
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler()
        ]
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_dir", type=str)
    parser.add_argument("--sim_id", type=int)
    parser.add_argument("--update_key", type=str)
    parser.add_argument("--backend_url", type=str)
    args = parser.parse_args()
    logging.info("output_dir %s", args.output_dir)
    logging.info("sim_id %s", args.sim_id)
    logging.info("update_key %s", args.update_key)
    logging.info("backend_url %s", args.backend_url)

    send_simulation_results(
        output_Path=Path(args.output_dir),
        simulation_id=args.sim_id,
        update_key=args.update_key,
        backend_url=args.backend_url
    )
