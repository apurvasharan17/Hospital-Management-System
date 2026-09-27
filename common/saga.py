from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class SagaStep:
    name: str
    action: Callable[[], Any]
    compensation: Callable[[], Any]


@dataclass
class SagaResult:
    success: bool
    completed_steps: list[str]
    error: str | None = None


class SagaOrchestrator:
    def __init__(self):
        self.steps: list[SagaStep] = []

    def add_step(self, step: SagaStep):
        self.steps.append(step)

    def execute(self) -> SagaResult:
        completed = []

        try:
            for step in self.steps:
                step.action()
                completed.append(step.name)

            return SagaResult(
                success=True,
                completed_steps=completed
            )

        except Exception as e:
            for step in reversed(self.steps):
                if step.name in completed:
                    try:
                        step.compensation()
                    except Exception:
                        pass

            return SagaResult(
                success=False,
                completed_steps=completed,
                error=str(e)
            )