"""StageResult 조립 도우미. 이름표·문구는 StageDef(pipeline/stages.json)에서 가져온다.

규칙(CLAUDE.md): 화면에 보이는 모든 유도 값(kind="derived")에는 Derivation이 있어야 하고,
비트에서 바로 읽은 값(kind="decoded")에는 어느 비트에서 나왔는지(source)가 있어야 한다.
build()가 이를 검사해 어기면 예외를 던진다.
"""

from __future__ import annotations

from typing import Any

from .contracts_gen import (
    Derivation,
    DerivationInput,
    Diagnostic,
    DiagnosticAction,
    Plot,
    Result,
    StageResult,
    Tree,
    Value,
)
from .pipeline import StageDef

Scalar = float | int | str | bool | None


class ContractError(ValueError):
    pass


def fmt(x: float, digits: int = 6) -> str:
    """계산 과정에 적는 숫자. 불필요한 0을 떼고 유효숫자를 제한한다."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return str(x)
    if isinstance(x, int) or float(x).is_integer() and abs(x) < 1e15:
        return f"{int(x):d}"
    return f"{x:.{digits}g}"


def inp(symbol: str, value: Scalar, source: str, unit: str = "") -> DerivationInput:
    return DerivationInput(symbol=symbol, value=value, source=source, unit=unit or None)


class ResultBuilder:
    def __init__(self, stage: StageDef):
        self.stage = stage
        self.values: list[Value] = []
        self.derivations: list[Derivation] = []
        self.plots: list[Plot] = []
        self.diagnostics: list[Diagnostic] = []
        self.trees: list[Tree] = []
        self.next_inputs: dict[str, Any] = {}

    # --- 값 ---
    def _value(self, key: str, value: Any, kind: str, **extra: Any) -> None:
        meta = self.stage.data["values"][key]
        self.values.append(Value(
            key=key, label=meta["label"], value=value, unit=extra.pop("unit", None) or meta.get("unit", ""),
            kind=kind, term=meta.get("term"), group=meta.get("group"),  # type: ignore[arg-type]
            note=extra.pop("note", None) or meta.get("note"), **extra,
        ))

    def decoded(self, key: str, value: Any, source: str, *, raw: Scalar = None, primary: bool = False,
                unit: str | None = None) -> None:
        self._value(key, value, "decoded", source=source, raw=raw, primary=primary or None, unit=unit)

    def measured(self, key: str, value: Any, *, primary: bool = False, note: str | None = None) -> None:
        self._value(key, value, "measured", primary=primary or None, note=note)

    def derived(self, key: str, value: Any, derivation_id: str, *, raw: Scalar = None, primary: bool = False,
                unit: str | None = None) -> None:
        self._value(key, value, "derived", derivation_id=derivation_id, raw=raw, primary=primary or None, unit=unit)

    # --- 계산 과정 ---
    def derive(self, key: str, formula_tex: str, inputs: list[DerivationInput], steps: list[str],
               value: Scalar, unit: str, spec_ref: str, *, suffix: str = "") -> str:
        did = f"{self.stage.id}.{key}{suffix}"
        self.derivations.append(Derivation(
            id=did, title=self.stage.data["derivations"][key]["title"], formula_tex=formula_tex,
            inputs=inputs, steps=steps, result=Result(value=value, unit=unit), spec_ref=spec_ref,
        ))
        return did

    # --- 그림, 진단 ---
    def plot(self, plot: Plot) -> None:
        self.plots.append(plot)

    def plot_text(self, plot_id: str, field: str) -> str:
        return self.stage.data["plots"][plot_id][field]

    def diag(self, code: str, *, default_level: str = "error", detail: str | None = None) -> None:
        """실패/주의 코드 하나를 원인 후보 목록(가능성 순)으로 펼친다. 후보마다 버튼(action)이 하나씩 붙는다."""
        catalog = self.stage.data["diagnostics"]
        causes = catalog.get(code) or self.stage.data["_common_diagnostics"].get(code)
        if causes is None:  # 엔진이 모르는 코드를 돌려준 경우
            causes, detail = self.stage.data["_common_diagnostics"]["INTERNAL"], f"{code} {detail or ''}".strip()
        for i, cause in enumerate(causes):
            action = cause.get("action")
            self.diagnostics.append(Diagnostic(
                level=cause.get("level", default_level), code=code if i == 0 else f"{code}.{i + 1}",
                message_easy=cause["message"], fix=cause["fix"], detail=detail if i == 0 else None,
                action=DiagnosticAction(**action) if action else None,
            ))

    def tree(self, tree_id: str, title: str, data: Any) -> None:
        self.trees.append(Tree(id=tree_id, title=title, data=data))

    # --- 마무리 ---
    def build(self, status: str, **summary_vars: Any) -> StageResult:
        ids = {d.id for d in self.derivations}
        for v in self.values:
            if v.kind == "derived" and v.derivation_id not in ids:
                raise ContractError(f"{self.stage.id}.{v.key}: 유도 값인데 계산 과정(Derivation)이 없습니다")
            if v.kind == "decoded" and not v.source:
                raise ContractError(f"{self.stage.id}.{v.key}: 복호 값인데 출처(source)가 없습니다")
        prefix = "fail" if status == "fail" else "ok"
        return StageResult(
            stage=self.stage.id, status=status,  # type: ignore[arg-type]
            summary_easy=self.stage.text("summary", f"{prefix}_easy", **summary_vars),
            summary_expert=self.stage.text("summary", f"{prefix}_expert", **summary_vars),
            values=self.values, derivations=self.derivations, plots=self.plots,
            diagnostics=self.diagnostics, next_inputs=self.next_inputs,
            spec_refs=self.stage.data["spec_refs"], trees=self.trees or None,
        )
