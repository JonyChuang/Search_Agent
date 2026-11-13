package com.searchagent.career.job;

import static org.springframework.http.HttpStatus.CONFLICT;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;

@Service
public class JobMemory {
    private final JobService jobs;
    private final JdbcClient db;

    JobMemory(JobService jobs, JdbcClient db) {
        this.jobs = jobs;
        this.db = db;
    }

    public Entry read(String user, String job) {
        jobs.find(user, job);
        return db.sql("SELECT revision, notes FROM career_job_memory WHERE user_id = ? AND job_id = ?")
                .params(user, job).query((rs, index) -> new Entry(rs.getInt("revision"), rs.getString("notes")))
                .optional().orElse(new Entry(0, null));
    }

    @Transactional
    public Entry save(String user, String job, Input input) {
        jobs.find(user, job);
        String notes = input.notes() == null || input.notes().isBlank() ? null : input.notes().strip();
        db.sql("""
                INSERT INTO career_job_memory (user_id, job_id, revision)
                VALUES (?, ?, 0) ON DUPLICATE KEY UPDATE revision = revision
                """).params(user, job).update();
        int changed = db.sql("""
                UPDATE career_job_memory SET notes = :notes, revision = revision + 1, updated_at = CURRENT_TIMESTAMP(6)
                WHERE user_id = :user AND job_id = :job AND revision = :revision
                """).param("notes", notes).param("user", user).param("job", job).param("revision", input.revision()).update();
        if (changed == 0) throw new ResponseStatusException(CONFLICT, "备考偏好已更新，请重新读取后再保存");
        return new Entry(input.revision() + 1, notes);
    }

    public record Entry(int revision, String notes) {}
    record Input(@NotNull @PositiveOrZero Integer revision, @Size(max = 3000) String notes) {}
}

@RestController
@RequestMapping("/api/career/jobs/{id}/memory")
class JobMemoryController {
    private final JobMemory memory;

    JobMemoryController(JobMemory memory) { this.memory = memory; }

    @GetMapping
    CareerResponse<JobMemory.Entry> read(@CareerUser String user, @PathVariable String id) {
        return CareerResponse.ok(memory.read(user, id));
    }

    @PutMapping
    CareerResponse<JobMemory.Entry> save(@CareerUser String user, @PathVariable String id,
            @Valid @RequestBody JobMemory.Input input) {
        return CareerResponse.ok(memory.save(user, id, input));
    }
}
