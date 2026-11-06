package com.searchagent.career.material;

import java.util.List;
import java.util.UUID;

import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.*;

import com.searchagent.career.web.CareerResponse;
import com.searchagent.career.web.CareerUser;

@RestController
@RequestMapping("/api/career")
class CareerMaterialsController {
    private final CareerMaterials materials;

    CareerMaterialsController(CareerMaterials materials) {
        this.materials = materials;
    }

    @GetMapping("/resumes")
    CareerResponse<List<CareerMaterials.Resume>> resumes(@CareerUser String user) {
        return CareerResponse.ok(materials.resumes(user));
    }

    @PostMapping("/resumes")
    CareerResponse<CareerMaterials.Resume> resume(@CareerUser String user, @Valid @RequestBody CareerMaterials.ResumeInput input) {
        return CareerResponse.ok(materials.generate(user, input));
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
