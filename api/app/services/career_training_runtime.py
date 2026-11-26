"""Durable budget and repair progress for native TRAINING tasks."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.services.career_training_contract import TrainingContract, TrainingContractError
from app.services.career_training_verifier import TrainingPlan, VerificationReport


class TrainingProgress(BaseModel):
    startedAt: datetime
    stage: Literal["CONTEXT_PREPARING", "CONTRACT_READY", "EXECUTING", "VERIFYING", "REPAIRING",
                   "VERIFIED", "FAILED"] = "CONTRACT_READY"
    modelCalls: int = Field(default=0, ge=0)
    repairRounds: int = Field(default=0, ge=0)
    verificationFailures: int = Field(default=0, ge=0)
    modelConfigId: str | None = None
    modelRevision: str | None = None
    lastReport: VerificationReport | None = None
    candidate: TrainingPlan | None = None
    previousErrors: list[str] = Field(default_factory=list)
    stalled: bool = False


class TrainingExecution:
    def __init__(
        self, contract: TrainingContract, saved: TrainingProgress | None, save: Callable[[dict], Awaitable[None]],
    ):
        self.contract = contract
        self.state = saved or TrainingProgress(startedAt=datetime.now(timezone.utc))
        self._save = save

    @property
    def seconds_left(self) -> float:
        return self.contract.budget.maxSeconds - (datetime.now(timezone.utc) - self.state.startedAt).total_seconds()

    async def update(self, **changes) -> None:
        next_state = self.state.model_copy(update=changes)
        await self._save(next_state.model_dump(mode="json"))
        self.state = next_state

    async def reserve(self, *, model: bool, repair: bool) -> None:
        budget = self.contract.budget
        if self.seconds_left <= 0:
            raise TrainingContractError("备考任务已达到执行时限，请创建新任务。", "EXECUTION_TIME_EXHAUSTED")
        if model and self.state.modelCalls >= budget.maxModelCalls:
            raise TrainingContractError("备考任务已达到模型调用上限，请创建新任务。", "MODEL_BUDGET_EXHAUSTED")
        if repair and self.state.repairRounds >= budget.maxRepairRounds:
            raise TrainingContractError("备考计划在修复次数上限内未通过验证。", "REPAIR_BUDGET_EXHAUSTED")
        await self.update(stage="REPAIRING" if repair else "EXECUTING", modelCalls=self.state.modelCalls + model,
                          repairRounds=self.state.repairRounds + repair)

    async def verified(self, plan: TrainingPlan | None, report: VerificationReport) -> None:
        signature = sorted({f"{issue.code}:{issue.field}" for issue in report.errors})
        await self.update(
            stage="VERIFIED" if report.passed else "VERIFYING", candidate=plan, lastReport=report,
            verificationFailures=self.state.verificationFailures + (not report.passed),
            previousErrors=signature, stalled=bool(signature and signature == self.state.previousErrors),
        )

    def details(self) -> dict:
        contract = self.contract
        return {
            "contractId": contract.id, "contractVersion": contract.version, "harnessVersion": contract.harnessVersion,
            "verifierVersion": contract.verifierVersion, "repairVersion": contract.repairVersion,
            "policyVersion": contract.learningVersion, "stage": self.state.stage, "modelCalls": self.state.modelCalls,
            "repairRounds": self.state.repairRounds, "verificationFailures": self.state.verificationFailures,
            "modelConfigId": self.state.modelConfigId, "modelRevision": self.state.modelRevision,
        }
