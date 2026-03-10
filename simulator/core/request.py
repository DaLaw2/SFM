from dataclasses import dataclass, field


@dataclass
class Request:
    id: int
    arrival_time: float
    start_time: float = 0.0
    end_time: float = 0.0
    worker_id: int = -1
    is_hedge: bool = False
    is_probe: bool = False
    cancelled: bool = False

    @property
    def latency(self) -> float:
        return self.end_time - self.arrival_time

    @property
    def service_time(self) -> float:
        return self.end_time - self.start_time
