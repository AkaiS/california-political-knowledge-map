"""Headline Metrics: one fixed, versioned run-level result per task (ADR 0026).

A task declares its result as a ``HeadlineDefinition`` built from a closed set
of measures over single cases.  When the run completes, the definition's
report evaluator computes every row over the run population and freezes them
into the Evaluation Report as one ``Headline metrics`` table.  Readers recover
that table only through ``Headline.from_analyses``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, model_validator
from pydantic_evals.evaluators import ReportEvaluator, ReportEvaluatorContext
from pydantic_evals.reporting import EvaluationReport, ReportCase, ReportCaseFailure
from pydantic_evals.reporting.analyses import TableResult

from .scoring import Counts, detection_counts

__all__ = [
    "Aggregation",
    "Counts",
    "Headline",
    "HeadlineDefinition",
    "HeadlineFormatError",
    "HeadlineRow",
    "Measure",
    "Rate",
    "Role",
    "SetAgreement",
    "Unavailable",
    "detection_counts",
    "is_failed_outcome",
]

TITLE = "Headline metrics"
EXECUTION_FAILURE_RATE = "execution_failure_rate"
COLUMNS = (
    "metric",
    "role",
    "value",
    "numerator",
    "denominator",
    "aggregation",
    "scored_cases",
    "selected_cases",
    "unavailable_reason",
)
ZERO_DENOMINATOR = "no case contributed to the denominator"


class Role(StrEnum):
    PRIMARY = "primary"
    HEADLINE = "headline"
    DIAGNOSTIC = "diagnostic"


class Aggregation(StrEnum):
    POOLED = "pooled"
    PER_CASE_MEAN = "per_case_mean"
    RATE = "rate"
    QUANTILE = "quantile"


_ROLE_ORDER = {Role.PRIMARY: 0, Role.HEADLINE: 1, Role.DIAGNOSTIC: 2}


class HeadlineFormatError(ValueError):
    """A report's headline table does not follow the table contract."""


class HeadlineRow(BaseModel, frozen=True):
    """One Headline Metric, with the evidence its value rests on."""

    metric: str
    role: Role
    aggregation: Aggregation
    value: float | None
    numerator: float | None
    denominator: float | None
    scored_cases: int
    selected_cases: int
    unavailable_reason: str | None

    @model_validator(mode="after")
    def _absence_is_explained(self) -> HeadlineRow:
        if (self.value is None) != (self.unavailable_reason is not None):
            raise ValueError(
                f"{self.metric}: a value is null exactly when a reason is given"
            )
        if (
            self.aggregation is Aggregation.POOLED
            and self.value is not None
            and (self.numerator is None or self.denominator is None)
        ):
            raise ValueError(
                f"{self.metric}: a pooled value needs its numerator and denominator"
            )
        return self


class Headline(BaseModel, frozen=True):
    """A run's Headline Metrics: the primary row, then headline, then diagnostic."""

    rows: tuple[HeadlineRow, ...]

    @model_validator(mode="after")
    def _follows_the_contract(self) -> Headline:
        keys = Counter((row.metric, row.aggregation) for row in self.rows)
        repeated = sorted(
            f"{metric} ({aggregation})"
            for (metric, aggregation), n in keys.items()
            if n > 1
        )
        if repeated:
            raise ValueError("a headline repeats a metric: " + ", ".join(repeated))
        if [row.role for row in self.rows].count(Role.PRIMARY) != 1:
            raise ValueError("a headline has exactly one primary row")
        orders = [_ROLE_ORDER[row.role] for row in self.rows]
        if orders != sorted(orders):
            raise ValueError(
                "a headline lists its primary row, then headline rows, then "
                "diagnostic rows"
            )
        if not any(row.metric == EXECUTION_FAILURE_RATE for row in self.rows):
            raise ValueError(f"a headline includes {EXECUTION_FAILURE_RATE}")
        return self

    @property
    def primary(self) -> HeadlineRow:
        return self.rows[0]

    def row(self, metric: str, aggregation: Aggregation) -> HeadlineRow | None:
        return next(
            (
                row
                for row in self.rows
                if row.metric == metric and row.aggregation == aggregation
            ),
            None,
        )

    def by_role(self, role: Role) -> tuple[HeadlineRow, ...]:
        return tuple(row for row in self.rows if row.role == role)

    def to_table(self) -> TableResult:
        return TableResult(
            title=TITLE,
            columns=list(COLUMNS),
            rows=[
                [row.model_dump(mode="json")[column] for column in COLUMNS]
                for row in self.rows
            ],
        )

    @classmethod
    def from_analyses(cls, analyses: Iterable[Any]) -> Headline | None:
        """Read the headline table from a report's analyses, in memory or saved.

        Returns ``None`` when the report has no headline table.
        """

        tables = [
            analysis
            for analysis in (
                item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for item in analyses
            )
            if isinstance(analysis, Mapping)
            and analysis.get("type") == "table"
            and analysis.get("title") == TITLE
        ]
        if not tables:
            return None
        if len(tables) > 1:
            raise HeadlineFormatError("a report holds more than one headline table")
        (table,) = tables
        if tuple(table.get("columns") or ()) != COLUMNS:
            raise HeadlineFormatError(
                f"headline table columns {table.get('columns')!r} differ from "
                f"{list(COLUMNS)!r}"
            )
        return cls(
            rows=tuple(
                HeadlineRow.model_validate(dict(zip(COLUMNS, row, strict=True)))
                for row in table.get("rows") or ()
            )
        )


def is_failed_outcome(
    case: ReportCase | ReportCaseFailure | Mapping[str, Any],
) -> bool:
    """A framework failure, or a completed case whose output records a failure.

    Shared by a run's exit status, its ``execution_failure_rate`` and the
    summary of a saved report, in memory or as a saved completed case, so none
    of them can disagree on which cases failed.
    """

    if isinstance(case, ReportCaseFailure):
        return True
    output = case.get("output") if isinstance(case, Mapping) else case.output
    return any(
        (
            output.get(name)
            if isinstance(output, Mapping)
            else getattr(output, name, None)
        )
        is not None
        for name in ("failure", "failure_type")
    )


@dataclass(frozen=True)
class _Population:
    """Every case the run reached an outcome for, split by that outcome.

    Built only from the report's completed and failed cases, never from
    experiment metadata, so every route into a run counts it the same way.
    """

    succeeded: tuple[ReportCase, ...]
    failed: tuple[ReportCase | ReportCaseFailure, ...]

    @classmethod
    def of(cls, report: EvaluationReport) -> _Population:
        outcomes = [*report.cases, *report.failures]
        return cls(
            succeeded=tuple(
                case for case in report.cases if not is_failed_outcome(case)
            ),
            failed=tuple(case for case in outcomes if is_failed_outcome(case)),
        )

    @property
    def everyone(self) -> tuple[ReportCase | ReportCaseFailure, ...]:
        return (*self.succeeded, *self.failed)


def _ratio(
    metric: str,
    role: Role,
    aggregation: Aggregation,
    numerator: float,
    denominator: float,
    *,
    scored_cases: int,
    population: _Population,
) -> HeadlineRow:
    return HeadlineRow(
        metric=metric,
        role=role,
        aggregation=aggregation,
        value=numerator / denominator if denominator else None,
        numerator=numerator,
        denominator=denominator,
        scored_cases=scored_cases,
        selected_cases=len(population.everyone),
        unavailable_reason=None if denominator else ZERO_DENOMINATOR,
    )


class Measure(BaseModel, frozen=True):
    """One member of the closed measure set a ``HeadlineDefinition`` is built from."""

    def _declared(self) -> tuple[tuple[str, Role], ...]:
        """The metric and role of each row this measure produces."""
        raise NotImplementedError

    def _rows(self, population: _Population) -> tuple[HeadlineRow, ...]:
        raise NotImplementedError


class SetAgreement(Measure, frozen=True):
    """Pooled precision, recall and F1 over each succeeded case's ``Counts``.

    A case that agrees on nothing contributes zero to every count.
    """

    prefix: str
    counts: Callable[[ReportCase], Counts]
    roles: Mapping[Literal["precision", "recall", "f1"], Role]

    @model_validator(mode="after")
    def _names_every_row(self) -> SetAgreement:
        if set(self.roles) != {"precision", "recall", "f1"}:
            raise ValueError("set agreement assigns a role to precision, recall and f1")
        return self

    def _declared(self) -> tuple[tuple[str, Role], ...]:
        return tuple(
            (f"{self.prefix}_{name}", self.roles[name])
            for name in ("precision", "recall", "f1")
        )

    def _rows(self, population: _Population) -> tuple[HeadlineRow, ...]:
        cases = [self.counts(case) for case in population.succeeded]
        precision_numerator = sum(c.precision_numerator for c in cases)
        precision_denominator = sum(c.precision_denominator for c in cases)
        recall_numerator = sum(c.recall_numerator for c in cases)
        recall_denominator = sum(c.recall_denominator for c in cases)
        # F1 as one fraction: 2PR / (P + R) with P and R written over their
        # own counts, which is 2·matched / (found + expected) when precision
        # and recall share a numerator.
        if precision_numerator == recall_numerator:
            f1_numerator = 2 * precision_numerator
            f1_denominator = precision_denominator + recall_denominator
        else:
            f1_numerator = 2 * precision_numerator * recall_numerator
            f1_denominator = (
                precision_numerator * recall_denominator
                + recall_numerator * precision_denominator
            )
        fractions = {
            "precision": (precision_numerator, precision_denominator),
            "recall": (recall_numerator, recall_denominator),
            "f1": (f1_numerator, f1_denominator),
        }
        return tuple(
            _ratio(
                metric,
                role,
                Aggregation.POOLED,
                *fractions[metric.removeprefix(f"{self.prefix}_")],
                scored_cases=len(population.succeeded),
                population=population,
            )
            for metric, role in self._declared()
        )


class Rate(Measure, frozen=True):
    """The share of cases for which ``test`` holds.

    Build it with ``Rate.quality``, over succeeded cases only, or with
    ``Rate.operational``, over the whole run population.
    """

    metric: str
    test: Callable[[Any], bool]
    role: Role
    over: Literal["succeeded", "population"]

    @classmethod
    def quality(
        cls, metric: str, test: Callable[[ReportCase], bool], role: Role
    ) -> Rate:
        return cls(metric=metric, test=test, role=role, over="succeeded")

    @classmethod
    def operational(
        cls,
        metric: str,
        test: Callable[[ReportCase | ReportCaseFailure], bool],
        role: Role,
    ) -> Rate:
        return cls(metric=metric, test=test, role=role, over="population")

    def _declared(self) -> tuple[tuple[str, Role], ...]:
        return ((self.metric, self.role),)

    def _rows(self, population: _Population) -> tuple[HeadlineRow, ...]:
        cases = (
            population.succeeded if self.over == "succeeded" else population.everyone
        )
        return (
            _ratio(
                self.metric,
                self.role,
                Aggregation.RATE,
                sum(1 for case in cases if self.test(case)),
                len(cases),
                scored_cases=len(cases),
                population=population,
            ),
        )


class Unavailable(Measure, frozen=True):
    """A Headline Metric that keeps its row although it cannot be computed."""

    metric: str
    aggregation: Aggregation
    role: Role
    reason: str

    def _declared(self) -> tuple[tuple[str, Role], ...]:
        return ((self.metric, self.role),)

    def _rows(self, population: _Population) -> tuple[HeadlineRow, ...]:
        return (
            HeadlineRow(
                metric=self.metric,
                role=self.role,
                aggregation=self.aggregation,
                value=None,
                numerator=None,
                denominator=None,
                scored_cases=0,
                selected_cases=len(population.everyone),
                unavailable_reason=self.reason,
            ),
        )


class HeadlineDefinition(BaseModel, frozen=True):
    """A task's Headline Metrics under one immutable headline version.

    Measures produce rows in declared order; the first measure produces the
    one primary row.  ``execution_failure_rate`` is added to every definition.
    """

    version: str
    measures: tuple[Measure, ...]

    @model_validator(mode="after")
    def _declares_one_primary_first(self) -> HeadlineDefinition:
        if not self.version.strip():
            raise ValueError("a headline definition needs a version")
        if not self.measures:
            raise ValueError(f"{self.version} declares no measures")
        declared = [
            (index, metric, role)
            for index, measure in enumerate(self.measures)
            for metric, role in measure._declared()
        ]
        primaries = [index for index, _, role in declared if role is Role.PRIMARY]
        if primaries != [0]:
            raise ValueError(
                f"{self.version} needs exactly one primary row, from its first measure"
            )
        if any(metric == EXECUTION_FAILURE_RATE for _, metric, _ in declared):
            raise ValueError(
                f"{self.version} must not declare {EXECUTION_FAILURE_RATE}; "
                "every headline adds it"
            )
        return self

    def evaluator(self) -> ReportEvaluator:
        return HeadlineMetrics(version=self.version, definition=self)

    def _headline(self, report: EvaluationReport) -> Headline:
        population = _Population.of(report)
        rows = [row for measure in self.measures for row in measure._rows(population)]
        rows.append(
            _ratio(
                EXECUTION_FAILURE_RATE,
                Role.HEADLINE,
                Aggregation.RATE,
                len(population.failed),
                len(population.everyone),
                scored_cases=len(population.everyone),
                population=population,
            )
        )
        return Headline(rows=tuple(sorted(rows, key=lambda row: _ROLE_ORDER[row.role])))


@dataclass(repr=False)
class HeadlineMetrics(ReportEvaluator):
    """Freeze a definition's Headline Metrics into the report when the run completes.

    A plain dataclass because pydantic-evals rejects a frozen subclass.  Only
    the version is serialized, so a recorded failure of this evaluator reads
    the same on every run.
    """

    version: str
    definition: HeadlineDefinition = field(compare=False)

    def build_serialization_arguments(self) -> dict[str, Any]:
        return {"version": self.version}

    def evaluate(self, ctx: ReportEvaluatorContext) -> TableResult:
        return self.definition._headline(ctx.report).to_table()
