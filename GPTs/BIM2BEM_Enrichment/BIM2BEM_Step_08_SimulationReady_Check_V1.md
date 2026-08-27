# BIM2BEM Step 08: Simulation-Ready Check V1 - V9.5 Minimum-Enrichment / Output-Dedup Patch

This is the final acceptance gate.

## Goal
Distinguish three questions:
1. Can the IDF parse/run without unresolved structural/runtime blockers?
2. Are the energy parameters credibly enriched and source-valid?
3. Is the overall model ready to be returned as simulation-ready?

A model may pass runtime syntax checks while still failing energy-parameter readiness because of unresolved zero/default-like design inputs or an unsearched full prototype.

## Required statuses
The report must include:
- `runtime_simulation_ready_status`: pass/fail
- `energy_parameter_readiness_status`: pass/fail
- `simulation_ready_status`: pass only when both statuses above pass

## Runtime acceptance order
1. static scan of full final IDF
2. duplicate-name scan
3. reference-integrity scan
4. template/field-count scan for modified object families
5. if an EnergyPlus `.err` file is available, use it as authoritative runtime evidence

## Static runtime scan
Check:
- duplicate object names
- missing construction/material/schedule/thermostat references
- field-count/semicolon/empty-name errors
- required output requests, with no exact duplicate `Output:Variable` tuples
- fenestration construction compatibility

## Energy-parameter readiness scan
Import the Step 07 credibility result and independently verify that no unresolved blocker remains for critical energy parameters.

Blocking energy-parameter conditions include:
- final critical design magnitude is zero/blank/default-like without explicit evidence that it is intentional
- an accepted direct IFC value was overwritten by a lower-priority source
- outdoor-air/ventilation data was incorrectly mapped as envelope infiltration
- a required full DOE prototype object family was never checked because only a compact/reduced extract was searched
- prototype zone-specific extensive totals were copied to differently sized target geometry without a documented supported normalization
- a schedule was invented rather than taken from IFC/full prototype/`Schedules.idf`/Step 7
- source trace is insufficient to reproduce the selected value

Do not treat valid schedule off-period zeros or valid coefficient zeros as blockers merely because they are zero.

## EnergyPlus `.err` rule
If an `.err` file is provided:
- extract every `Severe` and `Fatal`
- classify root cause
- correct model files/instructions accordingly
- runtime status cannot pass while unresolved severe/fatal errors remain

A clean `.err` file does not override an energy-parameter-readiness failure.

## Output-request duplicate rule
Before overall acceptance, build a registry of every `Output:Variable` using normalized `(Key Value, Variable Name, Reporting Frequency)`.
- exact duplicate tuples must be cleaned up before return
- preserve the first valid occurrence and remove later exact duplicates
- different reporting frequencies or key values are not exact duplicates
- duplicate `Output:VariableDictionary` requests must also be reduced to one identical request

An unresolved exact duplicate output request is a final acceptance blocker even if EnergyPlus would otherwise parse the file.
The report must record duplicate counts before and after cleanup; the after-cleanup count must be zero.

## Duplicate-name fatal rule
Any unresolved duplicate object name is a runtime blocker. Reuse the existing object intentionally or rename the generated object and update all references.

## Overall pass rule
Set `simulation_ready_status = pass` only when:
- `runtime_simulation_ready_status = pass`
- `energy_parameter_readiness_status = pass`
- no unresolved critical source/parameter blockers remain
- all generated references resolve
- report truthfully records the validation state

## Required report fields
- `simulation_ready_status`
- `runtime_simulation_ready_status`
- `energy_parameter_readiness_status`
- `static_check_status`
- `err_file_checked`
- `severe_error_count_if_err_available`
- `fatal_error_count_if_err_available`
- `suspicious_zero_count`
- `unresolved_critical_parameter_count`
- `prototype_completeness_check_status`
- `simulation_ready_blockers`
- `energy_parameter_blockers`
- `fixes_applied_or_required`
- `duplicate_output_request_count_before_cleanup`
- `duplicate_output_request_count_after_cleanup`
