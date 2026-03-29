"""
Shared token bucket for application level bandwidth limiting used when OS level traffic shaping (wireless_bottleneck) unavailable
All 3 worker processes share same token bucket so they compete for fixed bandwidth budget for meaningful Q-learning optimization
without bandwidth cap file_transfer dominates at 100+ Mbps because theres no real congestion on loopback interface
With cap all 3 connections must share a limited resource and quics congestion control actually responds to backpressure
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
