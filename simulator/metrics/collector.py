from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from simulator.control import Strategy
from simulator.core.request import Request


@dataclass
class EpochRecord:
    time: float
    severities: dict[int, float]
    strategies: dict[int, Strategy]
    weights: dict[int, float]
    system_p99: float
    slo_dist: float
    spare_capacity: float


class MetricsCollector:
    def __init__(self) -> None:
        self.requests: list[Request] = []
        self.request_metadata: list[dict[str, str]] = []
        self.epochs: list[EpochRecord] = []

    def record_request(self, request: Request, strategy: str = "") -> None:
        """Record a completed request. Does NOT filter cancelled requests."""
        self.requests.append(request)
        self.request_metadata.append({"strategy": strategy})

    def record_epoch(
        self,
        time: float,
        severities: dict[int, float],
        strategies: dict[int, Strategy],
        weights: dict[int, float],
        system_p99: float,
        slo_dist: float,
        spare_capacity: float,
    ) -> None:
        self.epochs.append(EpochRecord(
            time=time,
            severities=dict(severities),
            strategies={k: v for k, v in strategies.items()},
            weights=dict(weights),
            system_p99=system_p99,
            slo_dist=slo_dist,
            spare_capacity=spare_capacity,
        ))

    def requests_dataframe(self, warmup: float = 0.0) -> pd.DataFrame:
        rows = []
        for i, r in enumerate(self.requests):
            if r.arrival_time < warmup:
                continue
            meta = self.request_metadata[i] if i < len(self.request_metadata) else {}
            rows.append({
                "id": r.id,
                "arrival": r.arrival_time,
                "start": r.start_time,
                "end": r.end_time,
                "latency": r.end_time - r.arrival_time if r.end_time > 0 else 0.0,
                "service_time": r.end_time - r.start_time if r.end_time > 0 else 0.0,
                "worker_id": r.worker_id,
                "strategy": meta.get("strategy", ""),
                "is_hedge": r.is_hedge,
                "cancelled": r.cancelled,
            })
        return pd.DataFrame(rows)

    def epochs_dataframe(self) -> pd.DataFrame:
        rows = []
        for e in self.epochs:
            row: dict = {
                "time": e.time,
                "system_p99": e.system_p99,
                "slo_dist": e.slo_dist,
                "spare_capacity": e.spare_capacity,
            }
            for wid in sorted(e.severities.keys()):
                row[f"severity_{wid}"] = e.severities[wid]
                row[f"strategy_{wid}"] = e.strategies.get(wid, Strategy.NORMAL).name
                row[f"weight_{wid}"] = e.weights.get(wid, 1.0)
            rows.append(row)
        return pd.DataFrame(rows)

    def to_dataframes(self, warmup: float = 0.0) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Convert to pandas DataFrames (requests, epochs)."""
        return self.requests_dataframe(warmup), self.epochs_dataframe()

    def save(self, prefix: str, warmup: float = 0.0) -> None:
        """Save to CSV files."""
        df_req, df_ep = self.to_dataframes(warmup)
        df_req.to_csv(f"{prefix}_requests.csv", index=False)
        df_ep.to_csv(f"{prefix}_epochs.csv", index=False)
