"""
Shared token bucket for application-level bandwidth limiting, used when
OS-level traffic shaping (wireless_bottleneck) is unavailable.

All three worker processes share one bucket, so they compete for a fixed
bandwidth budget. Without a cap, file transfer dominates at 100+ Mbps because
loopback presents no real congestion; with a cap the three connections must
share a limited resource, and QUIC's congestion control actually responds to
backpressure. Meaningful contention is a precondition for the Q-learning agents
having anything to optimise.

Process safety
--------------
The bucket is shared across processes, not threads, so its state lives in
`multiprocessing.Value` cells guarded by a `multiprocessing.Lock` rather than
in ordinary attributes; plain attributes would be copied into each child and
the three workers would silently get a full bucket each.

Burst sizing
------------
`_max_tokens` is the larger of 65536 bytes or 5% of one second of capacity.
The floor matters: a bucket smaller than the largest single packet (a 64KB file
chunk or a ~50KB video I-frame) could never accumulate enough tokens for that
packet and `consume_async` would spin forever. The 5% ceiling was chosen after
a 100ms burst window was found to permit roughly 2500ms of bufferbloat.

Connections
-----------
Imports from : standard library only (asyncio, time, multiprocessing)
Imported by  : simulation.process_orchestrator (constructs and shares it),
               simulation.worker_process (consumes before each send)
"""

import asyncio
import time
import multiprocessing


class SharedTokenBucket:
    """
    Process safe token bucket shared across all worker processes
    Workers call consume_async(n_bytes) before sending each packet
    The bucket refills at rate_bps bits/second. When exhausted, workers yield to event loop asyncio.sleep retry every ms
    max burst capped at 100ms of capacity so bucket cannot accumulate large debt during idle periods
    """

    def __init__(self, cap_bps: float):
        """
        cap_bps is total bandwidth cap in bits per second shared across all workers
        """
        self._rate_Bps = cap_bps / 8.0
        #burst cap at least one max chunk worth 65536 bytes covers both file_transfer 64KB and video I frames 50KB) or 5% of per s capacity whatevers bigger
        #prevents consume_async from deadlocking on packets bigger than burst window while still being much tighter than 100ms which caused 2500ms RTT bufferbloat
        self._max_tokens = max(self._rate_Bps * 0.05, 65536)
        self._tokens = multiprocessing.Value('d', self._max_tokens)
        self._last_refill = multiprocessing.Value('d', time.monotonic())
        self._lock = multiprocessing.Lock()

    def _refill(self):
        """Add tokens earned since last call. Must be called under self._lock."""
        now = time.monotonic()
        elapsed = now - self._last_refill.value
        self._last_refill.value = now
        self._tokens.value = min(
            self._max_tokens,
            self._tokens.value + elapsed * self._rate_Bps,
        )

    def try_consume(self, n_bytes: int) -> bool:
        """non blocking attempt returns true if tokens consumed"""
        with self._lock:
            self._refill()
            if self._tokens.value >= n_bytes:
                self._tokens.value -= n_bytes
                return True
            return False

    async def consume_async(self, n_bytes: int) -> None:
        """
        Consume n_bytes yielding to event loop until tokens available and retries every 1ms so event loop stays responsive
        """
        while not self.try_consume(n_bytes):
            await asyncio.sleep(0.001)
