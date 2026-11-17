package com.searchagent.career.material;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.UUID;

import jakarta.validation.Valid;
import org.springframework.http.CacheControl;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartHttpServletRequest;

import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;

@RestController
@RequestMapping("/api/career")
class CareerMaterialsController {
    private final CareerMaterials materials;
    private final ResumeProfiles profiles;

    CareerMaterialsController(CareerMaterials materials, ResumeProfiles profiles) {
        this.materials = materials;
        this.profiles = profiles;
    }

    @GetMapping("/resumes")
    CareerResponse<List<CareerMaterials.Resume>> resumes(@CareerUser String user) {
        return CareerResponse.ok(materials.resumes(user));
    }

    @PostMapping("/resumes")
    CareerResponse<CareerMaterials.Resume> resume(@CareerUser String user, @Valid @RequestBody CareerMaterials.ResumeInput input) {
        return CareerResponse.ok(materials.generate(user, input));
    }

    @GetMapping("/resume-profile")
    CareerResponse<ResumeProfiles.Profile> resumeProfile(@CareerUser String user) {
        return CareerResponse.ok(profiles.get(user));
    }

    @PutMapping("/resume-profile")
    CareerResponse<ResumeProfiles.Profile> saveResumeProfile(@CareerUser String user,
            @Valid @RequestBody ResumeProfiles.Input input) {
        return CareerResponse.ok(profiles.save(user, input));
    }

    @PostMapping("/resumes/composed")
    CareerResponse<CareerMaterials.Resume> compose(@CareerUser String user,
            @Valid @RequestBody CareerMaterials.CompositionInput input) {
        return CareerResponse.ok(materials.compose(user, input));
    }

    @GetMapping("/resumes/{id}/composition")
    CareerResponse<JsonNode> composition(@CareerUser String user, @PathVariable UUID id) {
        return CareerResponse.ok(materials.composition(user, id));
    }

    @GetMapping("/applications")
    CareerResponse<List<CareerMaterials.Application>> applications(@CareerUser String user) {
        return CareerResponse.ok(materials.applications(user));
    }

    @PostMapping("/applications")
    CareerResponse<CareerMaterials.Application> create(@CareerUser String user,
            @Valid @RequestBody CareerMaterials.ApplicationInput input) {
        return CareerResponse.ok(materials.create(user, input));
    }

    @GetMapping("/jobs/{jobId}/application-workspace")
    CareerResponse<CareerMaterials.WorkspaceState> workspace(@CareerUser String user, @PathVariable UUID jobId) {
        return CareerResponse.ok(materials.workspace(user, jobId));
    }

    @PutMapping(value = "/jobs/{jobId}/application-workspace", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    CareerResponse<CareerMaterials.WorkspaceState> saveWorkspace(@CareerUser String user, @PathVariable UUID jobId,
            @Valid @RequestPart("draft") CareerMaterials.WorkspaceInput input, MultipartHttpServletRequest request) {
        var files = new HashMap<>(request.getMultiFileMap());
        files.remove("draft");
        return CareerResponse.ok(materials.saveWorkspace(user, jobId, input, files));
    }

    @GetMapping("/applications/{id}/files/{fileId}")
    ResponseEntity<byte[]> applicationFile(@CareerUser String user, @PathVariable UUID id, @PathVariable UUID fileId) {
        var file = materials.applicationFile(user, id, fileId);
        String disposition = ContentDisposition.attachment().filename(file.name(), StandardCharsets.UTF_8).build().toString();
        return ResponseEntity.ok().contentType(MediaType.APPLICATION_OCTET_STREAM).cacheControl(CacheControl.noStore())
                .header(HttpHeaders.CONTENT_DISPOSITION, disposition).header("X-Content-Type-Options", "nosniff")
                .body(file.content());
    }

    @PutMapping("/applications/{id}")
    CareerResponse<CareerMaterials.Application> update(@CareerUser String user, @PathVariable UUID id,
            @Valid @RequestBody CareerMaterials.DraftInput input) {
        return CareerResponse.ok(materials.update(user, id, input));
    }

    @PostMapping("/applications/{id}/stage")
    CareerResponse<CareerMaterials.Application> stage(@CareerUser String user, @PathVariable UUID id,
            @Valid @RequestBody CareerMaterials.StageInput input) {
        return CareerResponse.ok(materials.stage(user, id, input));
    }

    @GetMapping("/applications/{id}/events")
    CareerResponse<List<CareerMaterials.Event>> events(@CareerUser String user, @PathVariable UUID id) {
        return CareerResponse.ok(materials.events(user, id));
    }
}
