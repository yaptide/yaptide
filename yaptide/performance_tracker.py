import time
import random


class _Measurement:

    def __init__(self, name: str):
        self.name = name
        self.max = float('-inf')
        self.min = float('inf')
        self.total = 0.0
        self.count = 0

    @property
    def mean(self) -> float | None:
        if self.count == 0:
            return None
        return self.total / self.count

    def add(self, duration: float) -> None:
        self.count += 1
        self.total += duration
        if duration > self.max:
            self.max = duration
        if duration < self.min:
            self.min = duration
    

_measurements: dict[str, _Measurement] = {}
_start_times: dict[float, float] = {}
_names: dict[float, str] = {}


def start(name: str) -> float:
    if name not in _measurements:
        _measurements[name] = _Measurement(name)

    id = random.random()
    _start_times[id] = time.time()
    _names[id] = name
    return id


def end(id: float) -> None:
    if id not in _start_times:
        raise ValueError(f"Measurement with id {id} not found.")
    
    duration = time.time() - _start_times[id]
    del _start_times[id]

    name = _names[id]
    del _names[id]

    _measurements[name].add(duration)


def _generate_measurement_report(m: _Measurement) -> str:
    unfinished = sum(1 for id in _names if _names[id] == m.name)

    if m.count == 0:
        lines = [f"--- {m.name} ---", 
                 f"  no measurements finished",
                 f"  unfinished: {unfinished}"]
        return '\n'.join(lines)
    
    lines = [f"--- {m.name} ---", 
             f"  count: {m.count}", 
             f"  total: {m.total:.8f}s",
             f"  min: {m.min:.8f}s",
             f"  max: {m.max:.8f}s",
             f"  mean: {m.mean:.8f}s",
             f"  unfinished: {unfinished}"]
    return '\n'.join(lines)


def generate_report() -> str:
    report_lines = ["\n----- Tracker Report -----\n",
                    f"current time: {time.strftime('%H:%M:%S', time.localtime())}\n",
                    *[f"{_generate_measurement_report(m)}\n" for m in _measurements.values()],
                    "\n----- End of Report -----"]

    return "\n".join(report_lines)


def reset() -> None:
    _measurements.clear()
    _start_times.clear()
    _names.clear()
