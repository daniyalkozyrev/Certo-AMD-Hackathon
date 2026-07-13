"""Evaluation orchestration — the core end-to-end use-case.

For one evaluation: load the agent + benchmark, and for every task run the
agent, grade it, and persist a TaskResult (+ a per-step trajectory for agentic
agents), then aggregate the TrustScore.

Two agent execution paths:

* one-shot (`llm_endpoint`): prompt -> one code block -> sandbox -> grade.
* agentic (`agentic` / `multi_agent`): the agent works inside a LIVE sandbox
  over many steps; the judge grades EVERY step and then the whole run.

Grading is correctness-aware: a `code` task with `test_code` is judged by
actually running that test in the sandbox (so "didn't crash" is no longer an
automatic 5/5); a `code` task without a test, and every `judge` task, are
graded by the LLM judge ensemble.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.agent import AgentType
from app.models.benchmark import GradingType, Task
from app.models.evaluation import AgentStep, Evaluation, EvaluationStatus, TaskResult
from app.models.trace import TraceSource
from app.repositories.agent import AgentRepository
from app.repositories.benchmark import BenchmarkRepository
from app.repositories.evaluation import EvaluationRepository
from app.services.agent_runner.agentic import AgenticRunner, StepRecord
from app.services.agent_runner.runner import AgentOutput, AgentRunner
from app.services.compliance.catalog import summarize_compliance
from app.services.judge.base import JudgeRequest
from app.services.judge.ensemble import EnsembleJudge
from app.services.judge.prompts import (
    FINAL_RUBRIC,
    MAS_FINAL_RUBRIC,
    OUTCOME_RUBRIC,
    STEP_RUBRIC,
    build_outcome_instruction,
    build_span_instruction,
    build_step_instruction,
    format_span_response,
    format_step_response,
    format_trajectory,
)
from app.services.sandbox.e2b_sandbox import SandboxRunner
from app.services.scoring.answer_match import answer_match, extract_final_answer
from app.services.scoring.swebench_harness import extract_patch, grade_patches_async
from app.services.scoring.trust_score import (
    TaskScore,
    compute_trust_score,
    norm_score,
    process_score,
    trust_quality,
)
from app.services.trace_recorder import record_trace

logger = get_logger(__name__)

_AGENTIC_TYPES = {AgentType.AGENTIC, AgentType.MULTI_AGENT}


def _unpack(grade) -> tuple[int, str, list[dict] | None, str | None]:
    """Flatten an EnsembleResult into the fields a TaskResult/AgentStep stores."""
    votes = [
        {"judge": v.judge, "score": v.score, "feedback": v.feedback} for v in grade.votes
    ]
    return grade.score, grade.feedback, (votes or None), grade.disagreement


def _as_text(value: object) -> str | None:
    """Coerce a span field (str / dict / list / None) to storable text."""
    if value in (None, "", {}, []):
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


class EvaluationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.evaluations = EvaluationRepository(session)
        self.agents = AgentRepository(session)
        self.benchmarks = BenchmarkRepository(session)
        self.sandbox = SandboxRunner()
        self.judge = EnsembleJudge()

    async def run(self, evaluation_id: uuid.UUID) -> None:
        evaluation = await self.evaluations.get(evaluation_id)
        if evaluation is None:
            raise NotFoundError("Evaluation not found")

        evaluation.status = EvaluationStatus.RUNNING
        await self.session.flush()

        try:
            await self._execute(evaluation)
            evaluation.status = EvaluationStatus.COMPLETED
        except Exception as exc:
            logger.exception("evaluation.failed", evaluation_id=str(evaluation_id))
            evaluation.status = EvaluationStatus.FAILED
            evaluation.error = str(exc)
        await self.session.commit()

    async def _execute(self, evaluation: Evaluation) -> None:
        agent = await self.agents.get(evaluation.agent_id)
        if agent is None:
            raise NotFoundError("Agent not found")
        benchmark = await self.benchmarks.get_with_tasks(evaluation.benchmark_id)
        if benchmark is None:
            raise NotFoundError("Benchmark not found")

        task_scores: list[TaskScore] = []
        probe_results: list[tuple[list[str], bool]] = []  # (control refs, passed)
        for task in benchmark.tasks:
            # Isolate per-task failures: a transient agent/network/harness error on
            # ONE task must not sink the whole evaluation. Record it as a failed task
            # (clearly flagged as an execution error) and carry on.
            try:
                if agent.agent_type in _AGENTIC_TYPES:
                    result, score = await self._run_agentic_task(
                        evaluation.id, task, agent.config, multi=agent.agent_type == AgentType.MULTI_AGENT
                    )
                else:
                    result, score = await self._run_oneshot_task(
                        evaluation.id, task, AgentRunner(agent.config)
                    )
            except Exception as exc:
                logger.exception("evaluation.task_failed", task_id=str(task.id))
                score = TaskScore(judge_score=1, max_score=task.max_score, passed=False)
                result = TaskResult(
                    evaluation_id=evaluation.id,
                    task_id=task.id,
                    agent_output=None,
                    judge_score=1,
                    judge_feedback=f"task execution error (not scored on merit): {exc}",
                    normalized_score=score.normalized,
                    reward=score.reward,
                )
            self.session.add(result)
            task_scores.append(score)
            # Compliance probes: map this task's outcome onto framework controls.
            controls = (task.meta or {}).get("controls")
            if controls:
                probe_results.append((controls, bool(score.reward)))
            # Unify: also record this run as a Trace so it appears in /traces.
            await self._record_task_trace(evaluation, agent, task, result, score)

        aggregate = compute_trust_score(task_scores)
        evaluation.trust_score = aggregate.trust_score
        evaluation.pass_rate = aggregate.pass_rate
        evaluation.summary = {**aggregate.summary, "agent_type": agent.agent_type.value}
        # Per-framework rollup (OWASP / NIST / EU AI Act / ISO 42001) — only when
        # the benchmark actually contained control-tagged probes.
        compliance = summarize_compliance(probe_results)
        if compliance:
            evaluation.summary["compliance"] = compliance
        await self.session.flush()

    async def _record_task_trace(
        self, evaluation: Evaluation, agent, task: Task, result: TaskResult, score: TaskScore
    ) -> None:
        """Mirror an executed task as a unified Trace so it shows up in /traces."""
        spans: list[dict] = []
        if result.steps:  # agentic / multi-agent trajectory
            for st in result.steps:
                obs = (st.observation_stdout or "").strip()
                spans.append({
                    "kind": "tool" if st.action_code else "agent",
                    "name": st.role,
                    "input": st.thought or st.action_code,
                    "output": obs or None,
                    "error": st.observation_stderr if st.exit_code not in (None, 0) else None,
                    "judge_score": st.judge_score,
                    "judge_feedback": st.judge_feedback,
                    "judge_votes": st.judge_votes,
                })
        else:  # one-shot answer
            spans.append({
                "kind": "agent",
                "name": "answer",
                "input": task.prompt,
                "output": result.final_answer or result.agent_output,
                "judge_score": result.judge_score,
                "judge_feedback": result.judge_feedback,
                "judge_votes": result.judge_votes,
            })
        await record_trace(
            self.session,
            owner_id=evaluation.owner_id,
            agent_id=evaluation.agent_id,
            source=TraceSource.AGENTIC,
            name=f"{agent.name} · {task.prompt[:50]}",
            task=task.prompt,
            final_output=result.final_answer or result.agent_output,
            trust_score=round(score.normalized * 100, 2),
            summary={
                "final_score": result.judge_score,
                "reward": result.reward,
                "n_spans": len(spans),
                "is_multi_agent": agent.agent_type == AgentType.MULTI_AGENT,
                "evaluation_id": str(evaluation.id),
                "agent_type": agent.agent_type.value,
            },
            spans=spans,
        )

    # ── correctness check: actually run the task's test_code ─────────────
    async def _check_test_code(
        self, *, agent_stdout: str, agent_code: str | None, test_code: str, session=None
    ) -> tuple[bool, str]:
        """Run test_code in the sandbox. It may assert against `agent_stdout`
        (and `agent_code`); for agentic runs the agent's own variables are also
        in scope (same persistent session). Returns (passed, detail)."""
        harness = (
            f"agent_stdout = {json.dumps(agent_stdout)}\n"
            f"agent_code = {json.dumps(agent_code or '')}\n"
            f"{test_code}"
        )
        res = await (session.run(harness) if session is not None else self.sandbox.run_python(harness))
        passed = res.exit_code == 0
        detail = "test_code passed" if passed else f"test_code failed: {res.stderr.strip()[:500]}"
        return passed, detail

    # ── merit-based second opinion (only on the FAIL path) ───────────────
    async def _grade_on_merit(
        self, task: Task, response_text: str, objective_note: str, reference: str | None = None
    ) -> tuple[int, str, list[dict] | None, str | None]:
        """The LLM judge reads the agent's full answer/trajectory and awards partial
        credit after a deterministic check failed to confirm an exact match. Costs
        judge tokens only here — passing tasks never reach this."""
        grade = await self.judge.grade(
            JudgeRequest(
                instruction=build_outcome_instruction(task.prompt, objective_note),
                response=response_text,
                rubric=OUTCOME_RUBRIC,
                reference_answer=reference if reference is not None else task.reference_answer,
            )
        )
        return _unpack(grade)

    # ── one-shot agent (llm_endpoint) ────────────────────────────────────
    async def _run_oneshot_task(
        self, evaluation_id: uuid.UUID, task: Task, runner: AgentRunner
    ) -> tuple[TaskResult, TaskScore]:
        agent_output = await runner.solve(task.prompt)

        # Only execute in the sandbox if the agent actually returned a code block
        # to run. Answer agents (e.g. Hermes) reply in prose — nothing to execute.
        # SWE-bench output is a patch, never a runnable program.
        if agent_output.has_code and task.grading_type != GradingType.SWEBENCH:
            sandbox = await self.sandbox.run_python(agent_output.code)
            response_text = sandbox.stdout.strip() or agent_output.raw
            sb_stdout, sb_stderr, sb_exit = sandbox.stdout, sandbox.stderr, sandbox.exit_code
            verify_stdout = sandbox.stdout  # tests assert against program output
        else:
            response_text = agent_output.raw
            sb_stdout = sb_stderr = sb_exit = None
            verify_stdout = agent_output.raw  # tests assert against the answer text

        # Outcome axis: was the task actually solved?
        judge_score, feedback, votes, disagreement, passed = await self._grade_outcome(
            task, agent_output, response_text, verify_stdout
        )

        # Trajectory axis: when the agent exposed its own execution trace
        # (e.g. via the adapter's <certo:trace> block), the judge grades EVERY
        # step, and the task score blends step quality with the outcome.
        steps, step_scores = await self._grade_spans(task, agent_output.spans)
        # TrustScore (two-axis): correctness gates the trajectory. Here `judge_score`
        # IS the outcome/correctness grade (5 on match-pass, merit partial-credit on
        # fail), so c derives from it; there's no separate holistic → process = steps.
        correctness = 1.0 if passed is True else norm_score(judge_score, task.max_score)
        quality = trust_quality(correctness, process_score(step_scores, max_score=task.max_score))
        mean_step = round(sum(step_scores) / len(step_scores), 3) if step_scores else None

        score = TaskScore(
            judge_score=judge_score, max_score=task.max_score, passed=passed, quality=quality
        )
        result = TaskResult(
            evaluation_id=evaluation_id,
            task_id=task.id,
            agent_output=agent_output.raw,
            sandbox_stdout=sb_stdout,
            sandbox_stderr=sb_stderr,
            sandbox_exit_code=sb_exit,
            judge_score=judge_score,
            judge_feedback=feedback,
            judge_votes=votes,
            disagreement=disagreement,
            normalized_score=score.normalized,
            reward=score.reward,
            final_answer=response_text,
            step_count=len(steps) or None,
            mean_step_score=mean_step,
            steps=steps,
        )
        return result, score

    # ── outcome grading (dispatch per task type) ──────────────────────────
    async def _grade_outcome(
        self, task: Task, agent_output: AgentOutput, response_text: str, verify_stdout: str
    ) -> tuple[int, str, list[dict] | None, str | None, bool | None]:
        """Grade WHAT the agent produced. Deterministic checks (test_code, answer
        match, SWE-bench harness) are a free PASS fast-path; on FAIL the LLM judge
        re-grades on merit with partial credit, so a substantively-correct answer
        in the "wrong" format is never auto-failed.

        Returns (judge_score, feedback, votes, disagreement, passed)."""
        if task.grading_type == GradingType.CODE and task.test_code and settings.allow_code_execution:
            ok, detail = await self._check_test_code(
                agent_stdout=verify_stdout, agent_code=agent_output.code, test_code=task.test_code
            )
            return (5 if ok else 1), detail, None, None, ok

        if task.grading_type == GradingType.MATCH:
            return await self._grade_match(task, response_text)

        if task.grading_type == GradingType.SWEBENCH and settings.swebench_enabled:
            return await self._grade_swebench(task, response_text)

        # JUDGE task, or CODE task without a test -> the judge decides correctness.
        grade = await self.judge.grade(
            JudgeRequest(
                instruction=task.prompt,
                response=response_text,
                rubric=task.rubric or FINAL_RUBRIC,
                reference_answer=task.reference_answer,
            )
        )
        judge_score, feedback, votes, disagreement = _unpack(grade)
        return judge_score, feedback, votes, disagreement, None

    async def _grade_match(
        self, task: Task, response_text: str
    ) -> tuple[int, str, list[dict] | None, str | None, bool | None]:
        """GAIA-style answer matching with a merit-based judge fallback."""
        final = extract_final_answer(response_text)
        if answer_match(final, task.reference_answer):
            return 5, f"answer matched reference (extracted {final!r})", None, None, True
        note = (
            f"A deterministic matcher extracted {final!r}, which did NOT exactly "
            f"match the reference {task.reference_answer!r}."
        )
        judge_score, feedback, votes, disagreement = await self._grade_on_merit(
            task, response_text, note
        )
        passed = judge_score >= settings.reward_pass_threshold
        return judge_score, f"[no exact match — graded on merit] {feedback}", votes, disagreement, passed

    async def _grade_swebench(
        self, task: Task, response_text: str
    ) -> tuple[int, str, list[dict] | None, str | None, bool | None]:
        """Official SWE-bench harness (Docker) with a merit-based judge fallback:
        a genuine test failure weighs heavily, but an infra failure (Docker down)
        must not zero out a possibly-correct patch."""
        instance_id = (task.meta or {}).get("instance_id")
        gold = (task.meta or {}).get("gold_patch")
        patch = extract_patch(response_text)
        if not patch:
            return 1, "agent produced no patch (empty diff)", None, None, False

        if instance_id:
            graded = await grade_patches_async({instance_id: patch})
            verdict = graded[instance_id]
            if verdict.resolved:
                return 5, f"[{instance_id}] {verdict.detail}", None, None, True
            note = f"The official SWE-bench harness for {instance_id} reported: {verdict.detail}"
            prefix = f"[{instance_id} — graded on merit] "
        else:
            note = "No SWE-bench instance id, so the official test harness could not run."
            prefix = "[graded on merit] "

        judge_score, feedback, votes, disagreement = await self._grade_on_merit(
            task, response_text, note, reference=gold
        )
        passed = judge_score >= settings.reward_pass_threshold
        return judge_score, prefix + feedback, votes, disagreement, passed

    # ── trajectory grading: the judge reads EVERY step ────────────────────
    async def _grade_spans(
        self, task: Task, spans: list[dict]
    ) -> tuple[list[AgentStep], list[int]]:
        """Judge each span of an agent-supplied trajectory (tool call: input,
        output, the thought before it). Capped by judge_span_limit to bound cost."""
        if not spans or not settings.judge_grade_steps:
            return [], []
        step_models: list[AgentStep] = []
        step_scores: list[int] = []
        for idx, span in enumerate(spans[: settings.judge_span_limit], start=1):
            kind = str(span.get("kind") or "tool")
            name = span.get("name")
            grade = await self.judge.grade(
                JudgeRequest(
                    instruction=build_span_instruction(task.prompt, idx, kind, name),
                    response=format_span_response(
                        kind=kind,
                        name=name,
                        input=span.get("input"),
                        output=span.get("output"),
                        error=span.get("error"),
                    ),
                    rubric=STEP_RUBRIC,
                )
            )
            s_score, s_fb, s_votes, _ = _unpack(grade)
            step_scores.append(s_score)
            step_models.append(
                AgentStep(
                    step_index=idx,
                    role=f"{kind}:{name}" if name else kind,
                    thought=_as_text(span.get("thought")),
                    action_code=_as_text(span.get("input")),
                    observation_stdout=_as_text(span.get("output")),
                    observation_stderr=_as_text(span.get("error")),
                    judge_score=s_score,
                    judge_feedback=s_fb,
                    judge_votes=s_votes,
                )
            )
        return step_models, step_scores

    # ── agentic / multi-agent ────────────────────────────────────────────
    async def _run_agentic_task(
        self, evaluation_id: uuid.UUID, task: Task, config: dict, *, multi: bool
    ) -> tuple[TaskResult, TaskScore]:
        runner = AgenticRunner(config, multi_agent=multi)
        step_models: list[AgentStep] = []
        step_scores: list[int] = []

        async with self.sandbox.open_session() as session:
            outcome = await runner.run(task.prompt, session)

            # 1. Grade EVERY step of the trajectory.
            for idx, st in enumerate(outcome.steps, start=1):
                grade = await self.judge.grade(
                    JudgeRequest(
                        instruction=build_step_instruction(task.prompt, idx, st.role, outcome.plan),
                        response=format_step_response(
                            thought=st.thought, code=st.code,
                            stdout=st.stdout, stderr=st.stderr, exit_code=st.exit_code,
                        ),
                        rubric=STEP_RUBRIC,
                    )
                )
                s_score, s_fb, s_votes, _ = _unpack(grade)
                step_scores.append(s_score)
                step_models.append(_to_step_model(st, idx, s_score, s_fb, s_votes))

            # 2. Holistic grade of the whole run.
            traj = [_step_dict(st, i) for i, st in enumerate(outcome.steps, start=1)]
            final_grade = await self.judge.grade(
                JudgeRequest(
                    instruction=task.prompt,
                    response=format_trajectory(traj, outcome.final_answer),
                    # Multi-agent systems get the MAS criteria; single agents the
                    # single-agent criteria. A task's own rubric still wins.
                    rubric=task.rubric or (MAS_FINAL_RUBRIC if multi else FINAL_RUBRIC),
                    reference_answer=task.reference_answer,
                )
            )
            final_score, final_fb, final_votes, disagreement = _unpack(final_grade)

            # 3. Deterministic correctness gate for CODE tasks (same live session).
            passed: bool | None
            if task.grading_type == GradingType.CODE and task.test_code and settings.allow_code_execution:
                ok, detail = await self._check_test_code(
                    agent_stdout=outcome.final_answer, agent_code=None,
                    test_code=task.test_code, session=session,
                )
                passed = ok
                final_fb = f"{detail}\n\n{final_fb}"
            elif task.grading_type == GradingType.MATCH:
                final = extract_final_answer(outcome.final_answer)
                passed = answer_match(final, task.reference_answer)
                detail = (
                    f"answer matched reference (extracted {final!r})" if passed
                    else f"answer {final!r} did not match reference: {task.reference_answer!r}"
                )
                final_fb = f"{detail}\n\n{final_fb}"
            else:
                passed = None

        # 4. TrustScore (two-axis): correctness gates trajectory. Here `final_score`
        #    is the HOLISTIC trajectory grade and `passed` is the objective check.
        correctness = (
            1.0 if passed is True
            else 0.0 if passed is False
            else norm_score(final_score, task.max_score)
        )
        quality = trust_quality(
            correctness, process_score(step_scores, final_score, max_score=task.max_score)
        )
        mean_step = round(sum(step_scores) / len(step_scores), 3) if step_scores else None

        score = TaskScore(
            judge_score=final_score, max_score=task.max_score, passed=passed, quality=quality
        )
        last = outcome.steps[-1] if outcome.steps else None
        result = TaskResult(
            evaluation_id=evaluation_id,
            task_id=task.id,
            agent_output=outcome.final_answer,
            sandbox_stdout=(last.stdout if last else None),
            sandbox_stderr=(last.stderr if last else None),
            sandbox_exit_code=(last.exit_code if last else None),
            judge_score=final_score,
            judge_feedback=final_fb,
            judge_votes=final_votes,
            disagreement=disagreement,
            normalized_score=score.normalized,
            reward=score.reward,
            final_answer=outcome.final_answer,
            step_count=len(outcome.steps),
            mean_step_score=mean_step,
            steps=step_models,
        )
        return result, score


def _step_dict(st: StepRecord, idx: int) -> dict:
    return {
        "step_index": idx,
        "role": st.role,
        "thought": st.thought,
        "action_code": st.code,
        "observation_stdout": st.stdout,
        "observation_stderr": st.stderr,
    }


def _to_step_model(
    st: StepRecord, idx: int, score: int, feedback: str, votes: list[dict] | None
) -> AgentStep:
    return AgentStep(
        step_index=idx,
        role=st.role,
        thought=st.thought,
        action_code=st.code,
        observation_stdout=st.stdout,
        observation_stderr=st.stderr,
        exit_code=st.exit_code,
        judge_score=score,
        judge_feedback=feedback,
        judge_votes=votes,
    )
