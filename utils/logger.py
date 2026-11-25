"""Timestamped agent log (shown as a timeline in the UI)."""
from datetime import datetime


class AgentLogger:
    def __init__(self):
        self.entries = []

    def add(self, message, level="info"):
        self.entries.append({"time": datetime.now().strftime("%H:%M:%S"),
                             "level": level, "message": message})
