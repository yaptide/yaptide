"""The status of a user's simulations pushed to the UI as server-sent events, whenever one is submitted, its state or
partial results change or its tasks save their progress

Postgres tells when that happens (the trigger in yaptide/persistence/models.py), so nobody polls. A stream holds a
thread for as long as it is open, so streams are served by their own gthread server (yaptide_events in
docker-compose.yml), never by the sync workers answering the other requests.
"""

import json
import queue
import threading
from typing import Iterable, Iterator, Optional

from flask import Response, current_app, stream_with_context
from flask_restful import Resource
from sqlalchemy import or_

from yaptide.persistence.database import db, listen_to
from yaptide.persistence.db_methods import fetch_task_summaries, note_watching
from yaptide.persistence.models import SIMULATION_CHANNEL, SimulationModel, UserModel
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.utils import FINAL_STATES, job_status_content

# a comment sent this often keeps proxies from closing a quiet stream and finds streams the browser closed
KEEPALIVE_SECONDS = 25
# each stream holds a thread of the events server (yaptide_events): one user must not take them all
MAX_STREAMS_PER_USER = 10


class Subscribers:
    """The open streams of this process by user, woken by one connection listening to the database"""

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

    def subscribe(self, user_id: int, database_uri: str) -> queue.SimpleQueue:
        """Queue that gets the id of every simulation of the user that may have changed, None when any may have"""
        wakeup = queue.SimpleQueue()
        with self.lock:
            if self.listener is None:
                self.listener = threading.Thread(
                    target=listen_to,
                    args=(database_uri, SIMULATION_CHANNEL, self.wake_all, self.notified),
                    daemon=True,
                )
                self.listener.start()
            self.wakeups.setdefault(user_id, set()).add(wakeup)
        return wakeup

    def unsubscribe(self, user_id: int, wakeup: queue.SimpleQueue) -> None:
        """Forgets a closed stream"""
        with self.lock:
            self.wakeups[user_id].discard(wakeup)
            if not self.wakeups[user_id]:
                del self.wakeups[user_id]

    def notified(self, payload: str) -> None:
        """Wakes the streams of the simulation's user"""
        event = json.loads(payload)
        with self.lock:
            for wakeup in self.wakeups.get(event["user"], ()):
                wakeup.put(event["simulation"])

    def wake_all(self) -> None:
        """Wakes every stream, after a (re)connection to the database during which changes may have been missed"""
        with self.lock:
            for wakeups in self.wakeups.values():
                for wakeup in wakeups:
                    wakeup.put(None)


subscribers = Subscribers()


def woken(wakeup: queue.SimpleQueue) -> Optional[set[int]]:
    """Waits for a wakeup and takes the ones that came with it: the simulations that changed, None when any may have;
    queue.Empty when none came in time
    """
    items = [wakeup.get(timeout=KEEPALIVE_SECONDS)]
    while True:
        try:
            items.append(wakeup.get_nowait())
        except queue.Empty:
            return None if None in items else set(items)


def statuses(user_id: int, changed: Optional[set[int]], followed: Iterable[int]) -> list[tuple[int, dict]]:
    """Status of the user's simulations that changed or, with None, of the unfinished and the followed ones; one
    query for the simulations and one for their tasks, however many changed
    """
    if changed == set():
        return []
    query = db.session.query(SimulationModel).filter(SimulationModel.user_id == user_id)
    if changed is None:
        query = query.filter(or_(SimulationModel.job_state.notin_(FINAL_STATES), SimulationModel.id.in_(followed)))
    else:
        query = query.filter(SimulationModel.id.in_(changed))
    simulations = query.order_by(SimulationModel.id).all()
    summaries = fetch_task_summaries([simulation.id for simulation in simulations])
    found = [
        (
            simulation.id,
            {"job_id": simulation.job_id, **job_status_content(simulation, False, summaries[simulation.id])},
        )
        for simulation in simulations
    ]
    # the connection goes back to the pool while the stream waits
    db.session.remove()
    return found


def simulations_events(user_id: int) -> Iterator[str]:
    """The status of the user's simulations unfinished when the stream opens or submitted later, now and after
    every change; a final state is sent once and the simulation is not followed any more
    """
    wakeup = subscribers.subscribe(user_id, current_app.config["SQLALCHEMY_DATABASE_URI"])
    try:
        sent: dict[int, dict] = {}
        finished: set[int] = set()
        changed: Optional[set[int]] = None
        while True:
            # also with no news, at every keepalive: the progress of the user's simulations is read often
            note_watching(user_id)
            for simulation_id, content in statuses(user_id, changed, list(sent)):
                if simulation_id in finished or content == sent.get(simulation_id):
                    continue
                yield f"data: {json.dumps(content)}\n\n"
                if content["job_state"] in FINAL_STATES:
                    sent.pop(simulation_id, None)
                    finished.add(simulation_id)
                else:
                    sent[simulation_id] = content
            try:
                changed = woken(wakeup)
            except queue.Empty:
                yield ": keepalive\n\n"
                changed = set()
    finally:
        subscribers.unsubscribe(user_id, wakeup)


class SimulationsEventsResource(Resource):
    """Stream of the status of the user's simulations for the UI"""

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Opens the stream; it lasts until the browser closes it"""
        user_id = user.id
        db.session.remove()
        if not subscribers.admit(user_id):
            return yaptide_response(message="Too many open streams", code=429)
        response = Response(
            stream_with_context(simulations_events(user_id)),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
        # the server closes every response, also one whose stream never started
        response.call_on_close(lambda: subscribers.release(user_id))
        return response
