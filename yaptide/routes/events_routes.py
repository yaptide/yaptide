"""The status of a simulation pushed to the UI as server-sent events, whenever its state or partial results change

Postgres tells when that happens (the trigger in yaptide/persistence/models.py), so nobody polls. A stream holds a
thread for as long as it is open, so streams are served by their own gthread server (yaptide_events in
docker-compose.yml), never by the sync workers answering the other requests.
"""

import json
import queue
import threading
from typing import Iterator

from flask import Response, current_app, request, stream_with_context
from flask_restful import Resource
from marshmallow import Schema, fields

from yaptide.persistence.database import db, listen_to
from yaptide.persistence.db_methods import fetch_simulation_id_by_job_id
from yaptide.persistence.models import SIMULATION_CHANNEL, SimulationModel, UserModel
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.utils import FINAL_STATES, check_if_job_is_owned_and_exist, job_status_content

# a comment sent this often keeps proxies from closing a quiet stream and finds streams the browser closed
KEEPALIVE_SECONDS = 25
# each stream holds a thread of the events server (yaptide_events): one user must not take them all
MAX_STREAMS_PER_USER = 10


class Subscribers:
    """The open streams of this process by simulation, woken by one connection listening to the database"""

    def __init__(self):
        """No streams, nothing listening until the first stream opens"""
        self.lock = threading.Lock()
        self.wakeups: dict[int, set[queue.SimpleQueue]] = {}
        self.listener = None
        self.streams_of_user: dict[int, int] = {}

    def admit(self, user_id: int) -> bool:
        """Counts a new stream of the user, unless the user has too many open"""
        with self.lock:
            if self.streams_of_user.get(user_id, 0) >= MAX_STREAMS_PER_USER:
                return False
            self.streams_of_user[user_id] = self.streams_of_user.get(user_id, 0) + 1
            return True

    def release(self, user_id: int) -> None:
        """Forgets a closed stream of the user"""
        with self.lock:
            self.streams_of_user[user_id] -= 1
            if not self.streams_of_user[user_id]:
                del self.streams_of_user[user_id]

    def subscribe(self, simulation_id: int, database_uri: str) -> queue.SimpleQueue:
        """Queue that gets an item whenever the simulation may have changed"""
        wakeup = queue.SimpleQueue()
        with self.lock:
            if self.listener is None:
                self.listener = threading.Thread(
                    target=listen_to,
                    args=(database_uri, SIMULATION_CHANNEL, self.wake_all, lambda payload: self.wake(int(payload))),
                    daemon=True,
                )
                self.listener.start()
            self.wakeups.setdefault(simulation_id, set()).add(wakeup)
        return wakeup

    def unsubscribe(self, simulation_id: int, wakeup: queue.SimpleQueue) -> None:
        """Forgets a closed stream"""
        with self.lock:
            self.wakeups[simulation_id].discard(wakeup)
            if not self.wakeups[simulation_id]:
                del self.wakeups[simulation_id]

    def wake(self, simulation_id: int) -> None:
        """Wakes the streams of a simulation"""
        with self.lock:
            for wakeup in self.wakeups.get(simulation_id, ()):
                wakeup.put(None)

    def wake_all(self) -> None:
        """Wakes every stream, after a (re)connection to the database during which changes may have been missed"""
        with self.lock:
            for wakeups in self.wakeups.values():
                for wakeup in wakeups:
                    wakeup.put(None)


subscribers = Subscribers()


def simulation_events(simulation_id: int) -> Iterator[str]:
    """The simulation's status now and after every change, until it reaches a final state"""
    wakeup = subscribers.subscribe(simulation_id, current_app.config["SQLALCHEMY_DATABASE_URI"])
    try:
        sent = None
        while True:
            simulation = db.session.get(SimulationModel, simulation_id)
            content = simulation and job_status_content(simulation, with_tasks=False)
            # the connection goes back to the pool while the stream waits
            db.session.remove()
            if content is None:
                return
            if content != sent:
                yield f"data: {json.dumps(content)}\n\n"
                sent = content
            if content["job_state"] in FINAL_STATES:
                return
            try:
                wakeup.get(timeout=KEEPALIVE_SECONDS)
            except queue.Empty:
                yield ": keepalive\n\n"
    finally:
        subscribers.unsubscribe(simulation_id, wakeup)


class SimulationEventsResource(Resource):
    """Stream of a simulation's status for the UI"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String(required=True)

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Opens the stream; it ends when the simulation does, the browser closes it before then"""
        schema = SimulationEventsResource.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        job_id = schema.load(request.args)["job_id"]
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)
        simulation_id = fetch_simulation_id_by_job_id(job_id=job_id)
        user_id = user.id
        db.session.remove()
        if not subscribers.admit(user_id):
            return yaptide_response(message="Too many open streams", code=429)
        response = Response(
            stream_with_context(simulation_events(simulation_id)),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
        # the server closes every response, also one whose stream never started
        response.call_on_close(lambda: subscribers.release(user_id))
        return response
