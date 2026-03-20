import threading

class FirstEntry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claimed = False

    def claim(self) -> bool:
        # Double-checked locking fast-path
        if self._claimed:
            return False
        
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True