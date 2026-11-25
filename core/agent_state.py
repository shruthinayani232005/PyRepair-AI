"""Tracks the status of each agent stage so the UI can show live progress."""
STAGES = ["Code Analysis", "Execution", "Error Detection",
          "AI Diagnosis", "Repair Generation", "Verification"]


class AgentState:
    def __init__(self, on_change=None):
        self.stages = {s: "Pending" for s in STAGES}
        self.on_change = on_change

    def set(self, stage, status):
        self.stages[stage] = status
        if self.on_change:
            try:
                self.on_change(self)
            except Exception:
                pass  # a UI refresh problem must never stop the agent
