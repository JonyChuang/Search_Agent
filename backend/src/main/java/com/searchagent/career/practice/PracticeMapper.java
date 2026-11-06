package com.searchagent.career.practice;

import java.util.List;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
interface PracticeMapper {
    String QUESTION_COLUMNS = """
            q.id, q.version, q.role, q.topic, q.prompt, q.option_a, q.option_b, q.option_c, q.option_d,
            q.source_name, q.source_url, q.sourced_on
            """;
    String LATEST_VERSION = """
            NOT EXISTS (SELECT 1 FROM career_question_version newer WHERE newer.id = q.id AND newer.version > q.version)
            """;
    String ATTEMPT_SELECT = """
            SELECT a.request_id, a.question_id, a.question_version, a.grading_version,
                   q.prompt, a.answer, a.correct, q.correct_answer,
                   ELT(FIELD(a.answer, 'A', 'B', 'C', 'D'), q.option_a, q.option_b, q.option_c, q.option_d) AS answer_text,
                   ELT(FIELD(q.correct_answer, 'A', 'B', 'C', 'D'), q.option_a, q.option_b, q.option_c, q.option_d) AS correct_answer_text,
                   q.explanation, a.submitted_at
            FROM career_practice_attempt a
            JOIN career_question_version q ON q.id = a.question_id AND q.version = a.question_version
            WHERE a.user_id = #{userId}
            """;

    @Select("""
            SELECT id, role, company, title, summary, source_name, source_url, published_on, sourced_on
            FROM career_interview_note
            ORDER BY published_on DESC, id
            """)
    List<PracticeService.InterviewNote> notes();

    @Select("SELECT " + QUESTION_COLUMNS + " FROM career_question_version q WHERE " + LATEST_VERSION + """
            AND (#{role} IS NULL OR q.role = #{role})
            ORDER BY q.role, q.topic, q.id
            """)
    List<PracticeService.QuestionRow> questions(String role);

    @Select("SELECT " + QUESTION_COLUMNS + " FROM career_question_version q WHERE q.id = #{id} AND "
            + "((#{version} IS NULL AND " + LATEST_VERSION + ") OR q.version = #{version})")
    PracticeService.QuestionRow question(@Param("id") String id, @Param("version") Integer version);

    @Select("""
            SELECT grading_version, correct_answer
            FROM career_question_version
            WHERE id = #{id} AND version = #{version}
            """)
    PracticeService.GradingRule gradingRule(@Param("id") String id, @Param("version") int version);

    @Insert("""
            INSERT INTO career_practice_attempt
                (user_id, request_id, question_id, question_version, grading_version, answer, correct)
            VALUES (#{userId}, #{requestId}, #{submission.questionId}, #{submission.questionVersion},
                    #{gradingVersion}, #{submission.answer}, #{correct})
            ON DUPLICATE KEY UPDATE sequence_id = sequence_id
            """)
    void saveAttempt(@Param("userId") String userId, @Param("requestId") String requestId,
            @Param("submission") PracticeService.Submission submission,
            @Param("gradingVersion") int gradingVersion, @Param("correct") boolean correct);

    @Select(ATTEMPT_SELECT + " AND a.request_id = #{requestId}")
    PracticeService.Attempt attempt(@Param("userId") String userId, @Param("requestId") String requestId);

    @Select("""
            SELECT id, version, grading_version, role, prompt,
                   ELT(FIELD(correct_answer, 'A', 'B', 'C', 'D'), option_a, option_b, option_c, option_d)
                       AS reference_answer,
                   explanation, source_url
            FROM career_question_version WHERE id = #{id} AND version = #{version}
            """)
    PracticeService.InterviewQuestion interviewQuestion(@Param("id") String id, @Param("version") int version);

    @Select("<script>" + ATTEMPT_SELECT + """
            AND (a.question_id, a.question_version) IN
            <foreach item="ref" collection="refs" open="(" separator="," close=")">
                (#{ref.id}, #{ref.version})
            </foreach>
            ORDER BY a.sequence_id DESC LIMIT 20
            </script>
            """)
    List<PracticeService.Attempt> feedback(@Param("userId") String userId, @Param("refs") List<PracticeService.QuestionVersion> refs);

    @Select(ATTEMPT_SELECT + " ORDER BY a.sequence_id DESC LIMIT #{limit} OFFSET #{offset}")
    List<PracticeService.Attempt> attempts(
            @Param("userId") String userId, @Param("limit") int limit, @Param("offset") long offset);

    @Select("""
            WITH latest AS (
                SELECT question_id, question_version, correct, sequence_id,
                       ROW_NUMBER() OVER (PARTITION BY question_id ORDER BY sequence_id DESC) AS position_in_question,
                       SUM(CASE WHEN correct = FALSE THEN 1 ELSE 0 END) OVER (PARTITION BY question_id) AS wrong_count
                FROM career_practice_attempt
                WHERE user_id = #{userId}
            )
            SELECT q.id AS question_id, q.prompt, q.topic, latest.wrong_count, latest.correct AS reviewed
            FROM latest
            JOIN career_question_version q ON q.id = latest.question_id AND q.version = latest.question_version
            WHERE latest.position_in_question = 1 AND latest.wrong_count > 0
            ORDER BY latest.correct, latest.sequence_id DESC
            """)
    List<PracticeService.WrongQuestion> wrongQuestions(String userId);
}
