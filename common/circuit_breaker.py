import time
from enum import Enum


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(self, name, failure_threshold=3, recovery_timeout=10):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.opened_at = None

    def call(self, func, *args, fallback=None, **kwargs):
        if self.state == CircuitState.OPEN:
            if time.time() - self.opened_at >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                return fallback

        try:
            result = func(*args, **kwargs)

            self.failure_count = 0

            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.opened_at = None

            return result

        except Exception:
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.opened_at = time.time()
            else:
                self.failure_count += 1

                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    self.opened_at = time.time()

            return fallback

    def status(self):
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
        }