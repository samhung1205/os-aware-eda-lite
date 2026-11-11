"""Application-level frame scheduling for the MobileViT detector (Phase 3 / Batch 1).

Standard library only (no ROS 2, no torch), so every policy, the queue bound,
the frame accounting and the thread-safety rules are unit-tested without ROS.

Architecture (all application policies share it; only the policy differs)::

    DDS subscription (KEEP_LAST qos_depth)          <- DDS queue (middleware)
      -> ingestion callback (executor thread)        records received_at_ns, submit()
      -> FrameScheduler: bounded application queue   <- application queue (this module)
      -> one inference worker thread                 next_frame() -> preprocess/inference

The DDS queue and the application queue are different queues. In the
application modes the ingestion callback only timestamps the message and hands
it to the scheduler, so the DDS queue is drained continuously and the
discard decisions are made (and logged with a reason) by the policy, not by
KEEP_LAST overwrites. ``legacy_qos`` is not implemented here: it is the
unchanged Phase 2 behaviour (inference inside the subscription callback, the
DDS KEEP_LAST queue is the only queue).

Policies (exact semantics, see ``admit`` / ``select``):

``fifo``
    Serve in arrival order. Queue full on arrival: ``fifo_overflow=reject_newest``
    (default, tail drop: the arriving frame is dropped, ``queue_full_reject_newest``)
    or ``evict_oldest`` (head drop: the oldest pending frame is dropped,
    ``queue_full_evict_oldest``).
``latest_frame``
    At most one pending frame. An arriving frame supersedes the pending one
    (``superseded``); the worker always takes the newest frame. ``queue_capacity``
    is ignored (effective capacity 1).
``adaptive`` (deadline-aware)
    Bounded queue; full on arrival -> evict the oldest (``queue_full_evict_oldest``).
    When the worker is free it predicts, for every pending frame,
    ``predicted_latency = (now - published) + S_q`` with ``S_q`` the
    ``adaptive_quantile`` (nearest rank) of the last ``adaptive_window``
    *completed, non-warm-up* service times (preprocess + artificial delay +
    inference). A frame is feasible iff ``predicted_latency <= deadline -
    adaptive_margin_ms``. Utilisation ``rho_hat = lambda_hat * S_mean`` uses the
    arrival rate measured at ingestion over the last ``adaptive_window`` arrivals.

    - no estimate yet (start-up): serve the oldest frame (FIFO), decision ``no_estimate``;
    - some frame feasible: ``rho_hat < adaptive_overload_threshold`` -> the oldest
      feasible frame (EDF; no frame is dropped that could still be served,
      decision ``edf``); otherwise the newest feasible frame (shed load,
      decision ``newest_feasible``). Older frames are dropped
      (``deadline_infeasible`` if predicted to miss, else ``superseded``);
      newer ones stay queued;
    - nothing feasible but a fresh frame could make it (median ingest delay +
      ``S_q`` <= budget): drop them all (``deadline_infeasible``) and wait for the
      next arrival (decision ``wait``);
    - the deadline is unattainable even for a fresh frame: serve the newest
      (best effort, decision ``best_effort``), drop older ones (``superseded``).

    Only information observed before the decision is used (completed service
    times, past arrivals, current queue); parameters are fixed per run.
``deadline_guard`` (Phase 3 / Batch 2 ablation)
    Exactly ``adaptive`` (same queue, same service-time estimator, same feasibility
    check, same ``no_estimate`` / ``wait`` / ``best_effort`` branches) **without the
    utilisation switch**: whenever some frame is feasible it always serves the newest
    feasible frame (decision ``newest_feasible``), whatever ``rho_hat`` is. It is
    "Latest-Frame + deadline feasibility guard". Comparing it with ``adaptive``
    isolates the contribution of the EDF / shed-load switch; comparing it with
    ``latest_frame`` isolates the contribution of the feasibility check.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from math import ceil
from typing import Any, Callable

POLICY_LEGACY = "legacy_qos"
POLICY_FIFO = "fifo"
POLICY_LATEST = "latest_frame"
POLICY_ADAPTIVE = "adaptive"
POLICY_DEADLINE_GUARD = "deadline_guard"
APP_POLICIES = (POLICY_FIFO, POLICY_LATEST, POLICY_ADAPTIVE, POLICY_DEADLINE_GUARD)
# Policies that use the service-time estimator + deadline feasibility check.
DEADLINE_AWARE_POLICIES = (POLICY_ADAPTIVE, POLICY_DEADLINE_GUARD)
ALL_POLICIES = (POLICY_LEGACY, *APP_POLICIES)

FIFO_REJECT_NEWEST = "reject_newest"
FIFO_EVICT_OLDEST = "evict_oldest"
FIFO_OVERFLOW_MODES = (FIFO_REJECT_NEWEST, FIFO_EVICT_OLDEST)

# drop_reason values written to the detector CSV.
DROP_QUEUE_FULL_NEWEST = "queue_full_reject_newest"
DROP_QUEUE_FULL_OLDEST = "queue_full_evict_oldest"
DROP_SUPERSEDED = "superseded"
DROP_DEADLINE_INFEASIBLE = "deadline_infeasible"
DROP_SHUTDOWN = "shutdown_pending"      # still queued when the run stopped
DROP_SHUTDOWN_INFLIGHT = "shutdown_inflight"  # worker did not finish it before shutdown
DROP_CONVERSION = "conversion_error"
POLICY_DROP_REASONS = frozenset({
    DROP_QUEUE_FULL_NEWEST, DROP_QUEUE_FULL_OLDEST, DROP_SUPERSEDED, DROP_DEADLINE_INFEASIBLE,
})
SHUTDOWN_DROP_REASONS = frozenset({DROP_SHUTDOWN, DROP_SHUTDOWN_INFLIGHT})
ALL_DROP_REASONS = POLICY_DROP_REASONS | SHUTDOWN_DROP_REASONS | {DROP_CONVERSION}

# adaptive decision labels
DECISION_FIFO = "fifo"
DECISION_LATEST = "latest"
DECISION_NO_ESTIMATE = "no_estimate"
DECISION_EDF = "edf"
DECISION_NEWEST_FEASIBLE = "newest_feasible"
DECISION_BEST_EFFORT = "best_effort"
DECISION_WAIT = "wait"


@dataclass(frozen=True)
class SchedulerConfig:
    policy: str
    queue_capacity: int = 5
    deadline_ms: float = 100.0
    fifo_overflow: str = FIFO_REJECT_NEWEST
    adaptive_window: int = 32
    adaptive_quantile: float = 0.9
    adaptive_margin_ms: float = 0.0
    adaptive_overload_threshold: float = 1.0

    def __post_init__(self) -> None:
        if self.policy not in APP_POLICIES:
            raise ValueError(
                f"scheduler_policy '{self.policy}' is not an application policy "
                f"(expected one of {', '.join(APP_POLICIES)}; '{POLICY_LEGACY}' needs no scheduler)."
            )
        if int(self.queue_capacity) < 1:
            raise ValueError("queue_capacity must be >= 1.")
        if not self.deadline_ms > 0:
            raise ValueError("deadline_ms must be positive.")
        if self.fifo_overflow not in FIFO_OVERFLOW_MODES:
            raise ValueError(f"fifo_overflow must be one of {', '.join(FIFO_OVERFLOW_MODES)}.")
        if int(self.adaptive_window) < 1:
            raise ValueError("adaptive_window must be >= 1.")
        if not 0.0 < self.adaptive_quantile <= 1.0:
            raise ValueError("adaptive_quantile must be in (0, 1].")
        if self.adaptive_margin_ms < 0:
            raise ValueError("adaptive_margin_ms must be non-negative.")
        if not self.adaptive_overload_threshold > 0:
            raise ValueError("adaptive_overload_threshold must be positive.")

    @property
    def effective_capacity(self) -> int:
        return 1 if self.policy == POLICY_LATEST else int(self.queue_capacity)

    def params(self) -> dict[str, Any]:
        """Parameters that affect this policy (recorded per row and in metadata)."""

        out: dict[str, Any] = {"capacity": self.effective_capacity}
        if self.policy == POLICY_FIFO:
            out["overflow"] = self.fifo_overflow
        elif self.policy in DEADLINE_AWARE_POLICIES:
            out.update({
                "overflow": FIFO_EVICT_OLDEST,
                "window": int(self.adaptive_window),
                "quantile": self.adaptive_quantile,
                "margin_ms": self.adaptive_margin_ms,
                "deadline_ms": self.deadline_ms,
            })
            if self.policy == POLICY_ADAPTIVE:  # the guard has no utilisation switch
                out["overload_threshold"] = self.adaptive_overload_threshold
        return out

    def params_text(self) -> str:
        return format_params(self.params())


def format_params(params: dict[str, Any]) -> str:
    """Deterministic ``k=v;k=v`` text (sorted keys) for CSV columns."""

    return ";".join(f"{key}={params[key]}" for key in sorted(params))


@dataclass
class FrameItem:
    """One received frame on its way through the application queue."""

    frame_id: int | None
    published_at_ns: int
    received_at_ns: int
    payload: Any = None
    received_perf_ns: int | None = None
    enqueued_at_ns: int | None = None
    queue_len_at_enqueue: int | None = None
    dequeued_at_ns: int | None = None
    queue_len_at_dequeue: int | None = None
    dropped_at_ns: int | None = None
    predicted_latency_ms: float | None = None
    decision: str = ""
    est_service_ms: float | None = None
    est_utilization: float | None = None

    def age_ms(self, now_ns: int) -> float:
        return (now_ns - self.published_at_ns) / 1e6


class WindowEstimator:
    """Sliding window over the last ``size`` observations (past information only)."""

    def __init__(self, size: int) -> None:
        self._values: deque[float] = deque(maxlen=int(size))

    def add(self, value: float) -> None:
        self._values.append(float(value))

    def __len__(self) -> int:
        return len(self._values)

    def mean(self) -> float | None:
        return sum(self._values) / len(self._values) if self._values else None

    def quantile(self, q: float) -> float | None:
        """Nearest-rank quantile (same method as the analyzer's percentiles)."""

        if not self._values:
            return None
        ordered = sorted(self._values)
        return ordered[max(0, ceil(q * len(ordered)) - 1)]


class ArrivalRateEstimator:
    """Arrival rate (frames/s) at ingestion over the last ``size`` arrivals."""

    def __init__(self, size: int) -> None:
        self._stamps: deque[int] = deque(maxlen=max(2, int(size)))

    def add(self, stamp_ns: int) -> None:
        self._stamps.append(int(stamp_ns))

    def rate_fps(self) -> float | None:
        if len(self._stamps) < 2:
            return None
        span = (self._stamps[-1] - self._stamps[0]) / 1e9
        return None if span <= 0 else (len(self._stamps) - 1) / span


@dataclass
class Estimates:
    service_q_ms: float | None
    service_mean_ms: float | None
    arrival_fps: float | None
    ingest_delay_ms: float | None

    @property
    def utilization(self) -> float | None:
        if self.service_mean_ms is None or self.arrival_fps is None:
            return None
        return self.arrival_fps * self.service_mean_ms / 1000.0


Drop = tuple[FrameItem, str]


# ------------------------------------------------------------------ pure policy functions

def admit(config: SchedulerConfig, pending: deque[FrameItem], item: FrameItem) -> list[Drop]:
    """Insert ``item`` into ``pending`` (arrival order) and return the frames dropped.

    Never lets ``len(pending)`` exceed ``config.effective_capacity``.
    """

    if config.policy == POLICY_LATEST:
        drops = [(old, DROP_SUPERSEDED) for old in pending]
        pending.clear()
        pending.append(item)
        return drops
    drops: list[Drop] = []
    if len(pending) >= config.effective_capacity:
        if config.policy == POLICY_FIFO and config.fifo_overflow == FIFO_REJECT_NEWEST:
            return [(item, DROP_QUEUE_FULL_NEWEST)]
        while len(pending) >= config.effective_capacity:
            drops.append((pending.popleft(), DROP_QUEUE_FULL_OLDEST))
    pending.append(item)
    return drops


def select(
    config: SchedulerConfig, pending: deque[FrameItem], now_ns: int, est: Estimates
) -> tuple[FrameItem | None, list[Drop], str]:
    """Choose the next frame for the (free) worker; return (frame or None, drops, decision).

    ``pending`` is modified in place: the chosen frame and the dropped frames are removed.
    Returns ``None`` only for the adaptive ``wait`` decision (or an empty queue).
    """

    if not pending:
        return None, [], ""
    if config.policy == POLICY_FIFO:
        return pending.popleft(), [], DECISION_FIFO
    if config.policy == POLICY_LATEST:
        chosen = pending.pop()
        drops = [(old, DROP_SUPERSEDED) for old in pending]
        pending.clear()
        return chosen, drops, DECISION_LATEST
    return _select_adaptive(config, pending, now_ns, est)


def _select_adaptive(
    config: SchedulerConfig, pending: deque[FrameItem], now_ns: int, est: Estimates
) -> tuple[FrameItem | None, list[Drop], str]:
    s_q = est.service_q_ms
    if s_q is None:
        return pending.popleft(), [], DECISION_NO_ESTIMATE
    budget = config.deadline_ms - config.adaptive_margin_ms
    frames = list(pending)
    predicted = [frame.age_ms(now_ns) + s_q for frame in frames]
    for frame, value in zip(frames, predicted):
        frame.predicted_latency_ms = value
    feasible = [i for i, value in enumerate(predicted) if value <= budget]

    if feasible:
        rho = est.utilization
        if config.policy == POLICY_DEADLINE_GUARD:
            overloaded = True  # no utilisation switch: always the newest feasible frame
        else:
            overloaded = rho is not None and rho >= config.adaptive_overload_threshold
        index = feasible[-1] if overloaded else feasible[0]
        decision = DECISION_NEWEST_FEASIBLE if overloaded else DECISION_EDF
    else:
        fresh = (est.ingest_delay_ms or 0.0) + s_q
        if fresh <= budget:
            drops = [(frame, DROP_DEADLINE_INFEASIBLE) for frame in frames]
            pending.clear()
            return None, drops, DECISION_WAIT
        index = len(frames) - 1
        decision = DECISION_BEST_EFFORT

    drops = [
        (frame, DROP_DEADLINE_INFEASIBLE
         if predicted[i] > budget and decision != DECISION_BEST_EFFORT else DROP_SUPERSEDED)
        for i, frame in enumerate(frames[:index])
    ]
    chosen = frames[index]
    pending.clear()
    pending.extend(frames[index + 1:])
    return chosen, drops, decision


# ------------------------------------------------------------------ thread-safe scheduler

class FrameScheduler:
    """Bounded application queue shared by one ingestion thread and one worker thread.

    Accounting invariant (``stats()``): every submitted frame ends in exactly one
    of dequeued / dropped / drained, or is still pending::

        submitted == dequeued + dropped + drained + pending
    """

    def __init__(self, config: SchedulerConfig, clock_ns: Callable[[], int] = time.time_ns) -> None:
        self.config = config
        self._clock = clock_ns
        self._cond = threading.Condition(threading.Lock())
        self._pending: deque[FrameItem] = deque()
        self._closed = False
        self._service = WindowEstimator(config.adaptive_window)
        self._arrivals = ArrivalRateEstimator(config.adaptive_window)
        self._ingest_delay = WindowEstimator(config.adaptive_window)
        self._counts: dict[str, int] = {"submitted": 0, "dequeued": 0, "drained": 0}
        self._drops: dict[str, int] = {}
        self._max_len = 0

    # -- producer side (ingestion callback)
    def submit(self, item: FrameItem) -> list[Drop]:
        with self._cond:
            now = self._clock()
            self._counts["submitted"] += 1
            if self._closed:
                return self._mark([(item, DROP_SHUTDOWN)], now)
            item.enqueued_at_ns = now
            self._arrivals.add(item.received_at_ns)
            self._ingest_delay.add((item.received_at_ns - item.published_at_ns) / 1e6)
            drops = admit(self.config, self._pending, item)
            if not any(dropped is item for dropped, _ in drops):
                item.queue_len_at_enqueue = len(self._pending)
            self._max_len = max(self._max_len, len(self._pending))
            self._mark(drops, now)
            self._cond.notify()
            return drops

    # -- consumer side (inference worker)
    def next_frame(self, timeout: float | None = None) -> tuple[FrameItem | None, list[Drop]]:
        """Block until a frame is chosen, frames were dropped, the scheduler closes or ``timeout``.

        Returns ``(frame, drops)``. ``frame`` is None when only drops happened (call
        again), on timeout, or when closed (check ``closed``).
        """

        with self._cond:
            while not self._closed and not self._pending:
                if not self._cond.wait(timeout):
                    return None, []
            if self._closed:
                return None, []
            now = self._clock()
            est = self.estimates()
            item, drops, decision = select(self.config, self._pending, now, est)
            self._mark(drops, now)
            if item is not None:
                item.dequeued_at_ns = now
                item.queue_len_at_dequeue = len(self._pending)
                item.decision = decision
                item.est_service_ms = est.service_q_ms
                item.est_utilization = est.utilization
                self._counts["dequeued"] += 1
            return item, drops

    def record_service(self, service_ms: float, warmup: bool) -> None:
        """Feed a completed frame's service time (warm-up frames are not used)."""

        if warmup or service_ms is None:
            return
        with self._cond:
            self._service.add(service_ms)

    def close(self) -> list[FrameItem]:
        """Stop accepting frames; return the frames still pending (drained, reason shutdown)."""

        with self._cond:
            self._closed = True
            drained = list(self._pending)
            self._pending.clear()
            now = self._clock()
            for item in drained:
                item.dropped_at_ns = now
            self._counts["drained"] += len(drained)
            self._cond.notify_all()
            return drained

    @property
    def closed(self) -> bool:
        with self._cond:
            return self._closed

    def estimates(self) -> Estimates:
        # Called with the lock held (from next_frame) or for diagnostics.
        return Estimates(
            service_q_ms=self._service.quantile(self.config.adaptive_quantile),
            service_mean_ms=self._service.mean(),
            arrival_fps=self._arrivals.rate_fps(),
            ingest_delay_ms=self._ingest_delay.quantile(0.5),
        )

    def stats(self) -> dict[str, Any]:
        with self._cond:
            dropped = sum(self._drops.values())
            return {
                **self._counts,
                "dropped": dropped,
                "drops_by_reason": dict(sorted(self._drops.items())),
                "pending": len(self._pending),
                "max_queue_len": self._max_len,
                "capacity": self.config.effective_capacity,
            }

    def _mark(self, drops: list[Drop], now: int) -> list[Drop]:
        for item, reason in drops:
            item.dropped_at_ns = now
            self._drops[reason] = self._drops.get(reason, 0) + 1
        return drops
