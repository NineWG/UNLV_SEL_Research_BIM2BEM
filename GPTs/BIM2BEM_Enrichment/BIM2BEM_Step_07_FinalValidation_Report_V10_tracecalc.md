# BIM2BEM Step 07: Final Validation and Report V10 - V9.5 Minimum-Enrichment / Output-Dedup Patch

This is the final enrichment gate before the simulation-readiness check.

Use:
- `BIM2BEM_IDF_Syntax_Guard_V2.md`
- `BIM2BEM_Source_Trace_Guard_V1.md`

## Static IDF validation checklist
- IDF opens without parse-like structural error
- all generated objects exist in the file
- field counts are valid
- no extra trailing fields exist in generated load objects
- People/Lights/ElectricEquipment/infiltration use the field matching the selected calculation method
- only 2 `SizingPeriod:DesignDay` objects remain unless explicitly requested otherwise
- thermostat names referenced by ideal-load zones exist
- all referenced schedules/constructions/materials exist
- no placeholder schedule names remain
- duplicate-name registry returns zero duplicate object names within each object type
- window/door construction compatibility is valid
- required output requests exist exactly once for each required normalized request tuple
- no exact duplicate `Output:Variable` request tuples remain
- if `Construction:FfactorGroundFloor` exists, ground-temperature requirements are truthfully evaluated

## Critical energy-parameter credibility validation
A model can be syntactically valid and still be energetically meaningless. Therefore scan the final IDF and enrichment report for critical energy inputs, including as applicable:
- opaque construction/thermal parameters
- fenestration U-factor/SHGC/visible transmittance
- People design magnitude
- Lights design magnitude
- ElectricEquipment design magnitude
- envelope infiltration design magnitude and calculation method
- outdoor-air design inputs when modeled
- occupancy/load/infiltration schedules
- heating/cooling setpoints
- ground-temperature data when required

For each critical design magnitude:
1. identify the final value and source
2. verify source semantics and target applicability
3. if the final value is zero/blank/default-like where a nonzero design magnitude would normally be expected, require explicit source evidence that the result is intentional
4. if explicit evidence is absent, validation fails and the source hierarchy must continue

Do not flag every numeric zero. Exempt valid schedule off-period values, valid EnergyPlus coefficients, and explicitly supported inactive/unoccupied/unconditioned cases.

## IFC priority preservation check
If the IFC contains a clear, project-specific, semantically valid direct value, confirm that the final IDF preserves it within normal unit conversion/rounding. If a prototype/library value replaced such a direct IFC value without a documented mapping error, validation fails.

## Rejected-candidate check
For any rejected IFC/Step 6 candidate, especially zero/default-like candidates, verify that the report includes:
- source property/STEP ID
- raw value/unit
- semantic role
- rejection reason
- next source level searched

## Full-prototype completeness check
Whenever IFC/Step 6 was insufficient and a DOE prototype fallback was needed, confirm:
- building type or documented proxy
- climate zone/location
- standard/version
- exact prototype filename
- target object family searched in the complete prototype
- exact prototype object selected, or a truthful statement that the complete prototype lacked a usable object

If the local prototype was compact/reduced and the required object family was absent, the report must show that the corresponding official full DOE/PNNL prototype was retrieved/searched before EnergyPlus library, COMNET/code, or Step 7 fallback. If not, validation fails.

Absence from a partial prototype extract is never sufficient evidence that the full DOE prototype lacks the parameter.

## Prototype method/scaling validation
If a prototype fallback was applied:
- verify the calculation method/slot matches the source or documented target conversion
- verify zone-specific extensive prototype totals were not blindly copied to differently sized target geometry
- if deterministic normalization/scaling was used, verify the report includes the source prototype total, source geometry/area, formula, derived intensive value, and target application method

## Schedule validation
Schedules must follow:
IFC/Revit -> selected full DOE prototype -> `Schedules.idf` -> retain Step 7.

Do not reject a schedule merely because it contains zero during off periods. Validate the full time profile and actual source object.

COMNET/generic web values are not schedule sources. Official web retrieval of the full DOE prototype is allowed only as part of the prototype stage.

## Required output requests
The final IDF must contain the following requests unless explicitly suppressed, but **each required request must appear only once**.

Before adding anything, scan every existing `Output:Variable` object in the full IDF. Normalize each request as:
`(Key Value, Variable Name, Reporting Frequency)` with case-insensitive, whitespace-normalized comparison.

Rules:
1. If the required normalized tuple already exists anywhere in the IDF, do not append another copy.
2. If the same normalized tuple appears more than once, keep the first valid occurrence and delete later exact duplicates.
3. Requests that differ by key value or reporting frequency are not exact duplicates; preserve them unless another owner rule explicitly removes them.
4. Keep no more than one identical `Output:VariableDictionary, IDF;` object.
5. Perform the de-duplication pass after all objects/design days have been inserted, so no tail-appended duplicate remains.

Required normalized requests:

```idf
Output:Variable,
  *,
  Site Outdoor Air Drybulb Temperature,
  Hourly;

Output:Variable,
  *,
  Zone Mean Air Temperature,
  Hourly;

Output:Variable,
  *,
  Zone Ideal Loads Zone Total Heating Rate,
  Hourly;

Output:Variable,
  *,
  Zone Ideal Loads Zone Total Cooling Rate,
  Hourly;

Output:VariableDictionary,
  IDF;
```

If a variable is unavailable because the final HVAC system does not expose it, record that rather than silently omitting the request.

The validation report must include:
- `required_output_request_count_expected`
- `required_output_request_count_present`
- `duplicate_output_request_count_before_cleanup`
- `duplicate_output_request_count_after_cleanup` (must be 0)

## Fenestration compatibility validation
Scan actual final IDF construction layers:
- a door must not reference a construction containing `WindowMaterial:*`
- a window must reference a window-compatible construction
- any violation is blocking

## Mandatory traceability checks
The report must include exact source traces for:
- opaque constructions
- windows/doors
- internal loads
- infiltration
- schedules
- HVAC setpoints
- weather/design days/simulation control
- site ground temperature when evaluated

Exact traceability includes source file, object type/name, IFC STEP/property/value, prototype identity and completeness status, COMNET/code references when used, and deterministic calculation inputs when used.

## Source-order truthfulness check
For non-schedule energy inputs, the report must reflect:
1. semantically valid IFC/Revit + traceable Step 6 evidence
2. selected full DOE prototype
3. EnergyPlus DataSets library
4. permitted COMNET guideline
5. applicable code/standard
6. valid Step 7 fallback
7. optional pass/omission

The report fails if it lists `conservative reasoning`, `reasoned generation`, a generic web result, or a newly invented constant schedule as a final source.

## Output rule
Return:
- `enriched_output.idf`
- `enrichment_report.json`
- `selected_weather.epw`
- `selected_weather.ddy` if available

The report must additionally include:
- `energy_parameter_validation_status`: pass/fail
- `suspicious_zero_count`
- `unresolved_critical_parameter_count`
- `prototype_completeness_check_status`
- `rejected_candidate_count`
- `critical_parameter_blockers`
