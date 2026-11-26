"""Versioned question bank and objective submissions."""

import re
from datetime import timezone

from sqlalchemy import bindparam, text

from app.core.exceptions import BizError
from app.services.career_question_catalog import order_questions, required_skills
from app.services.career_training_contract import topic_skills
from app.services.career_queue import conflict
from app.services.career_records import CareerRecords

QUESTION_COLUMNS = """
    q.id, q.version, q.role, q.topic, q.prompt, q.option_a, q.option_b, q.option_c, q.option_d,
    q.source_name AS sourceName, q.source_url AS sourceUrl, q.sourced_on AS sourcedOn
"""
LATEST = """
    NOT EXISTS (SELECT 1 FROM career_question_version newer WHERE newer.id = q.id AND newer.version > q.version)
"""
ATTEMPT_SELECT = """
    SELECT a.request_id AS requestId, a.question_id AS questionId, a.question_version AS questionVersion,
        a.grading_version AS gradingVersion, q.prompt, a.answer, a.correct, q.correct_answer AS correctAnswer,
        ELT(FIELD(a.answer, 'A', 'B', 'C', 'D'), q.option_a, q.option_b, q.option_c, q.option_d) AS answerText,
        ELT(FIELD(q.correct_answer, 'A', 'B', 'C', 'D'),
            q.option_a, q.option_b, q.option_c, q.option_d) AS correctAnswerText,
        q.explanation, a.submitted_at AS submittedAt, a.job_id AS jobId
    FROM career_practice_attempt a
    JOIN career_question_version q ON q.id = a.question_id AND q.version = a.question_version
    WHERE a.user_id = :user
"""


def _question(row) -> dict:
    question = dict(row)
    question["options"] = [question.pop(f"option_{letter}") for letter in "abcd"]
    return question


def _attempt(row) -> dict:
    return dict(row, correct=bool(row["correct"]),
                submittedAt=row["submittedAt"].replace(tzinfo=timezone.utc))


class CareerPractice:
    def __init__(self, records: CareerRecords):
        self.records = records
        self.db = records.db
        self.user = records.user

    async def notes(self) -> list[dict]:
        result = await self.db.execute(text("""
            SELECT id, role, company, title, summary, source_name AS sourceName, source_url AS sourceUrl,
                published_on AS publishedOn, sourced_on AS sourcedOn
            FROM career_interview_note ORDER BY published_on DESC, id
        """))
        return [dict(row) for row in result.mappings()]

    async def questions(self, role: str | None = None) -> list[dict]:
        result = await self.db.execute(text(f"""
            SELECT {QUESTION_COLUMNS} FROM career_question_version q
            WHERE {LATEST} AND (:role IS NULL OR q.role = :role) ORDER BY q.role, q.topic, q.id
        """), {"role": role})
        return [_question(row) for row in result.mappings()]

    async def question(self, question: str, version: int | None) -> dict:
        row = (await self.db.execute(text(f"""
            SELECT {QUESTION_COLUMNS} FROM career_question_version q
            WHERE q.id = :id AND ((:version IS NULL AND {LATEST}) OR q.version = :version)
        """), {"id": question, "version": version})).mappings().one_or_none()
        if row is None:
            raise BizError("题目不存在", code=404, status_code=404)
        return _question(row)

    async def evidence_question(self, question: str, version: int) -> dict:
        row = (await self.db.execute(text("""
            SELECT id, version, grading_version AS gradingVersion, role, prompt,
                ELT(FIELD(correct_answer, 'A', 'B', 'C', 'D'),
                    option_a, option_b, option_c, option_d) AS referenceAnswer,
                explanation, source_url AS sourceUrl
            FROM career_question_version WHERE id = :id AND version = :version
        """), {"id": question, "version": version})).mappings().one_or_none()
        if row is None:
            raise BizError("题目版本不存在", code=404, status_code=404)
        return dict(row)

    async def matching_questions(
        self, job: dict, role: str | None = None, *, extra_skills: set[str] | None = None,
        pinned_ids: set[str] | None = None,
    ) -> list[dict]:
        candidates = await self.questions(role)
        if role is not None:
            return order_questions(candidates, job)
        needed = required_skills(job) | (extra_skills or set())
        content = " ".join(str(job.get(key) or "") for key in ("title", "jd", "skills")).lower()
        matches = []
        for candidate in candidates:
            topic = candidate["topic"].lower()
            terms = re.split(r"[\s、/]+", topic)
            if candidate["id"] in (pinned_ids or ()) or topic in content \
                    or any(len(term) > 1 and term in content for term in terms) or topic_skills(topic, needed):
                matches.append(candidate)
        return order_questions(matches, job)

    async def submit(self, submission: dict) -> dict:
        values = {"user": self.user, **submission}
        previous = await self.attempt_for_request(submission["requestId"])
        if previous is None and submission["jobId"] is not None:
            await self.records.jobs().get(submission["jobId"], lock=True)
        grading = (await self.db.execute(text("""
            SELECT grading_version, correct_answer FROM career_question_version
            WHERE id = :questionId AND version = :questionVersion
        """), values)).one_or_none()
        if grading is None:
            raise BizError("题目版本不存在", code=404, status_code=404)
        await self.db.execute(text("""
            INSERT INTO career_practice_attempt
                (user_id, request_id, question_id, question_version, grading_version, answer, correct, job_id)
            VALUES (:user, :requestId, :questionId, :questionVersion, :grading, :answer, :correct, :jobId)
            ON DUPLICATE KEY UPDATE sequence_id = sequence_id
        """), dict(values, grading=grading.grading_version, correct=grading.correct_answer == submission["answer"]))
        saved = await self.attempt_for_request(submission["requestId"])
        if saved is None or any(saved[key] != submission[key] for key in ("questionId", "questionVersion", "answer", "jobId")):
            raise conflict("提交编号已用于另一条作答")
        return saved

    async def attempt_for_request(self, request_id: str) -> dict | None:
        row = (await self.db.execute(text(
            ATTEMPT_SELECT + " AND a.request_id = :request_id"
        ), {"user": self.user, "request_id": request_id})).mappings().one_or_none()
        return _attempt(row) if row is not None else None

    async def attempts(self, job: str | None, page: int) -> dict:
        rows = await self.db.execute(text(ATTEMPT_SELECT + """
            AND (:job IS NULL OR a.job_id = :job) ORDER BY a.sequence_id DESC LIMIT 21 OFFSET :offset
        """), {"user": self.user, "job": job, "offset": (page - 1) * 20})
        items = [_attempt(row) for row in rows.mappings()]
        return {"items": items[:20], "hasMore": len(items) > 20}

    async def wrong_questions(self, job: str | None) -> list[dict]:
        rows = await self.db.execute(text("""
            WITH latest AS (
                SELECT question_id, question_version, correct, sequence_id,
                    ROW_NUMBER() OVER (PARTITION BY question_id ORDER BY sequence_id DESC) AS position_in_question,
                    SUM(CASE WHEN correct = FALSE THEN 1 ELSE 0 END) OVER (PARTITION BY question_id) AS wrong_count
                FROM career_practice_attempt
                WHERE user_id = :user AND (:job IS NULL OR job_id = :job)
            )
            SELECT q.id AS questionId, q.prompt, q.topic, latest.wrong_count AS wrongCount, latest.correct AS reviewed
            FROM latest
            JOIN career_question_version q ON q.id = latest.question_id AND q.version = latest.question_version
            WHERE latest.position_in_question = 1 AND latest.wrong_count > 0
            ORDER BY latest.correct, latest.sequence_id DESC
        """), {"user": self.user, "job": job})
        return [dict(row, reviewed=bool(row["reviewed"]), wrongCount=int(row["wrongCount"])) for row in rows.mappings()]

    async def training_attempts(self, job: str) -> list[dict]:
        rows = await self.db.execute(text("""
            SELECT recent.attemptId, recent.questionId, recent.questionVersion, recent.correct, recent.submittedAt, q.topic,
                (SELECT MAX(v.version) FROM career_question_version v WHERE v.id = recent.questionId) AS currentVersion
            FROM (
                SELECT a.request_id AS attemptId, a.question_id AS questionId,
                    a.question_version AS questionVersion, a.correct, a.sequence_id, a.submitted_at AS submittedAt
                FROM career_practice_attempt a
                WHERE a.user_id = :user AND a.job_id = :job
                    AND a.submitted_at >= CURRENT_TIMESTAMP - INTERVAL 30 DAY
                ORDER BY a.sequence_id DESC LIMIT 60
            ) recent JOIN career_question_version q
                ON q.id = recent.questionId AND q.version = recent.questionVersion
            ORDER BY recent.sequence_id DESC
        """), {"user": self.user, "job": job})
        return [dict(row, correct=bool(row["correct"])) for row in rows.mappings()]

    async def plan_attempts(self, refs: list[tuple], job: str, include_unscoped: bool, *, feedback: bool) -> list[dict]:
        if not refs:
            return []
        prefix = ATTEMPT_SELECT if feedback else """
            SELECT DISTINCT a.question_id AS id, a.question_version AS version
            FROM career_practice_attempt a WHERE a.user_id = :user
        """
        suffix = " ORDER BY a.sequence_id DESC LIMIT 20" if feedback else ""
        query = text(prefix + """
            AND (a.job_id = :job OR (:unscoped = TRUE AND a.job_id IS NULL))
            AND (a.question_id, a.question_version) IN :refs
        """ + suffix).bindparams(bindparam("refs", expanding=True))
        rows = await self.db.execute(query, {"user": self.user, "job": job, "unscoped": include_unscoped, "refs": refs})
        return [(_attempt(row) if feedback else dict(row)) for row in rows.mappings()]
