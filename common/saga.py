from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class SagaStep:
    name: str
    action: Callable[[], Any]
    compensation: Callable[[], Any] | None = None


@dataclass
class SagaResult:
    ok: bool
    completed_steps: list[str]
    failed_step: str | None = None
    error: str | None = None


class SagaOrchestrator:
    def __init__(self, name="saga"):
        self.name = name
        self.steps: list[SagaStep] = []

    def add_step(self, name, action, compensation=None):
        self.steps.append(
            SagaStep(
                name=name,
                action=action,
                compensation=compensation,
            )
        )

    def execute(self) -> SagaResult:
        completed = []

        for step in self.steps:
            try:
                step.action()
                completed.append(step.name)

            except Exception as exc:
                # Compensate completed steps in reverse order.
                for completed_step in reversed(self.steps):
                    if completed_step.name in completed:
                        if completed_step.compensation is not None:
                            try:
                                completed_step.compensation()
                            except Exception:
                                # Compensation failures should not hide the
                                # original Saga failure.
                                pass

                return SagaResult(
                    ok=False,
                    completed_steps=completed,
                    failed_step=step.name,
                    error=str(exc),
                )

        return SagaResult(
            ok=True,
            completed_steps=completed,
        )