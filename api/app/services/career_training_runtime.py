"""Durable budget and repair progress for native TRAINING tasks."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.services.career_training_contract import TrainingContract, TrainingContractError
from app.services.career_training_verifier import TrainingPlan, VerificationReport


class TrainingOperation(BaseModel):
    id: str
    kind: Literal["GENERATE", "REPAIR", "LOCAL_REPAIR"]
    status: Literal["RESERVED", "NO_RESULT", "VALIDATED"] = "RESERVED"


class TrainingProgress(BaseModel):
    startedAt: datetime
    stage: Literal["CONTEXT_PREPARING", "CONTRACT_READY", "EXECUTING", "VERIFYING", "REPAIRING",
                   "VERIFIED", "FAILED"] = "CONTRACT_READY"
    modelCalls: int = Field(default=0, ge=0)
    transientRetries: int = Field(default=0, ge=0)
    repairRounds: int = Field(default=0, ge=0)
    verificationFailures: int = Field(default=0, ge=0)
    modelConfigId: str | None = None
    modelRevision: str | None = None
    lastReport: VerificationReport | None = None
    candidate: TrainingPlan | None = None
    previousErrors: list[str] = Field(default_factory=list)
    stalled: bool = False
    operation: TrainingOperation | None = None
    unknownOperations: int = Field(default=0, ge=0)
    failureCode: str | None = None


def retry_block(row: dict, *, now: datetime | None = None) -> TrainingContractError | None:
    raw = (row.get("context_json") or {}).get("trainingContract")
    saved = row.get("training_runtime_json")
    if not raw or not saved or row.get("training_draft_json") or saved.get("stage") == "VERIFIED":
        return None
    contract = TrainingContract.model_validate(raw)
    progress = TrainingProgress.model_validate(saved)
    deadline = progress.startedAt + timedelta(seconds=contract.budget.maxSeconds)
    if (now or datetime.now(timezone.utc)) >= deadline:
        return _budget_error("EXECUTION_TIME_EXHAUSTED")
    code = progress.failureCode
    if code in {"MODEL_CONFIG_CHANGED", "TASK_CONTRACT_UNSATISFIABLE", "CONTRACT_CONFIRMATION_REQUIRED",
                "TASK_CONTRACT_FEASIBILITY_UNDETERMINED", "CONTEXT_BUDGET_EXCEEDED", "CONTRACT_SCOPE_MISMATCH"}:
        return TrainingContractError("请检查模型配置或调整训练要求，再创建新任务。", code)
    if progress.lastReport and not progress.lastReport.passed and progress.repairRounds >= contract.budget.maxRepairRounds:
        return _budget_error("REPAIR_BUDGET_EXHAUSTED")
    if progress.modelCalls >= contract.budget.maxModelCalls:
        return _budget_error("MODEL_BUDGET_EXHAUSTED")
    return None


def _budget_error(code: str) -> TrainingContractError:
    messages = {
        "EXECUTION_TIME_EXHAUSTED": "备考任务已达到执行时限，请创建新任务。",
        "MODEL_BUDGET_EXHAUSTED": "备考任务已达到模型调用上限，请创建新任务。",
        "REPAIR_BUDGET_EXHAUSTED": "备考计划已达到修复次数上限，请创建新任务。",
    }
    return TrainingContractError(messages[code], code)


class TrainingExecution:
    def __init__(
        self, contract: TrainingContract, saved: TrainingProgress | None, save: Callable[[dict], Awaitable[None]],
    ):
        self.contract = contract
        self.state = saved or TrainingProgress(startedAt=datetime.now(timezone.utc))
        self._save = save

    @property
    def seconds_left(self) -> float:
        return (self.execution_deadline - datetime.now(timezone.utc)).total_seconds()

    @property
    def execution_deadline(self) -> datetime:
        return self.state.startedAt + timedelta(seconds=self.contract.budget.maxSeconds)

    async def update(self, **changes) -> None:
        next_state = self.state.model_copy(update=changes)
        await self._save(next_state.model_dump(mode="json"))
        self.state = next_state

    async def reserve(self, *, model: bool, repair: bool) -> str:
        budget = self.contract.budget
        if self.seconds_left <= 0:
            raise _budget_error("EXECUTION_TIME_EXHAUSTED")
        if model and self.state.modelCalls >= budget.maxModelCalls:
            raise _budget_error("MODEL_BUDGET_EXHAUSTED")
        if repair and self.state.repairRounds >= budget.maxRepairRounds:
            raise _budget_error("REPAIR_BUDGET_EXHAUSTED")
        previous = self.state.operation
        operation = TrainingOperation(id=str(uuid4()), kind=("REPAIR" if model else "LOCAL_REPAIR") if repair else "GENERATE")
        await self.update(stage="REPAIRING" if repair else "EXECUTING", modelCalls=self.state.modelCalls + model,
                          operation=operation, unknownOperations=self.state.unknownOperations + bool(
                              previous and previous.status == "RESERVED",
                          ), failureCode=None)
        return operation.id

    async def no_result(self, operation_id: str) -> None:
        operation = self._active_operation(operation_id)
        if operation:
            await self.update(operation=operation.model_copy(update={"status": "NO_RESULT"}))

    def _active_operation(self, operation_id: str) -> TrainingOperation | None:
        operation = self.state.operation
        return operation if operation and operation.id == operation_id and operation.status == "RESERVED" else None

    async def verified(self, operation_id: str, plan: TrainingPlan | None, report: VerificationReport) -> bool:
        operation = self._active_operation(operation_id)
        if not operation:
            return False
        signature = sorted({f"{issue.code}:{issue.field}" for issue in report.errors})
        await self.update(
            stage="VERIFIED" if report.passed else "VERIFYING", candidate=plan, lastReport=report,
            verificationFailures=self.state.verificationFailures + (not report.passed),
            previousErrors=signature, stalled=bool(signature and signature == self.state.previousErrors),
            operation=operation.model_copy(update={"status": "VALIDATED"}),
            repairRounds=self.state.repairRounds + (operation.kind != "GENERATE"),
        )
        return True

    def details(self) -> dict:
        contract = self.contract
        return {
            "contractId": contract.id, "contractVersion": contract.version, "harnessVersion": contract.harnessVersion,
            "verifierVersion": contract.verifierVersion, "repairVersion": contract.repairVersion,
            "policyVersion": contract.learningVersion, "stage": self.state.stage, "modelCalls": self.state.modelCalls,
            "modelAttempts": self.state.modelCalls, "transientRetries": self.state.transientRetries,
            "repairRounds": self.state.repairRounds, "verificationFailures": self.state.verificationFailures,
            "executionDeadline": self.execution_deadline.isoformat(), "unknownOperations": self.state.unknownOperations,
            "operation": self.state.operation.model_dump() if self.state.operation else None,
            "modelConfigId": self.state.modelConfigId, "modelRevision": self.state.modelRevision,
        }
