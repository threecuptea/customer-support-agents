import threading
from models.model import RefundRequest 

# In Python, a standard dictionary (dict) is not fully thread-safe. While individual atomic operations 
# (like retrieving d[key] or setting d[key] = value) are safe from memory corruption due to Python's internal design,
# Implement a simple in-memory dict for DEMO_MODE = True

refund_requests_processing_dict: dict[int, RefundRequest] = {}

class ThreadSafeCounter:
    def __init__(self, initial_value=0):
        self._value = initial_value
        self._lock = threading.Lock()

    def increment(self, amount=1):
        """Safely increment the counter by a given amount and return the new value."""
        with self._lock:
            self._value += amount
            return self._value
