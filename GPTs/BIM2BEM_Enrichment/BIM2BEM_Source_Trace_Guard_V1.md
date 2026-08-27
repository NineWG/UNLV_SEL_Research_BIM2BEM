# BIM2BEM Source Trace Guard V1 - V9.4 Alignment Patch

Use this file with every step and with final reporting.

## Goal
Make the enrichment report auditable not only for the final value, but also for rejected high-priority candidates. Every modeled value must be traceable to a concrete source and every rejected direct candidate must have a documented reason.

## Accepted source categories
- IFC / traceable Step 6 evidence
- selected full DOE/PNNL prototype file
- EnergyPlus DataSets library file
- directly applicable COMNET published technical guideline when permitted
- applicable building code or standard
- weather/DDY/stat-style file
- retained input-IDF representative
- deterministic calculation from documented source data when the owning step permits it

## Required trace fields
For each final parameter/object family, record as many as apply:
- `target_object_family`
- `target_object_name_or_group`
- `target_parameter`
- `source_class`
- `source_file`
- `source_object_type`
- `source_object_name`
- `source_step_id`
- `source_property_set`
- `source_property_name`
- `source_value`
- `source_units`
- `selection_reason`
- `semantic_role`
- `candidate_status`
- `candidate_rejection_reason`
- `zero_value_review_status`
- `prototype_building_type_or_proxy`
- `prototype_climate_zone`
- `prototype_standard_version`
- `prototype_file_name`
- `prototype_completeness_status` = `full_local`, `partial_local_then_full_retrieved`, or `full_official_retrieved`
- `prototype_source_url` if retrieved
- `web_source_title`
- `web_source_domain`
- `web_source_date` if available
- `web_source_url`
- `comnet_document_version` when COMNET is used
- `comnet_section_or_table` when COMNET is used

## Rejected-candidate trace rule
Do not hide a high-priority candidate simply because it was not used.
When IFC/Step 6 contains a candidate that is rejected, record:
- exact source file
- STEP ID/property set/property name
- raw value and units
- semantic role found
- rejection class
- rejection reason

Examples of valid rejection reasons:
- `ventilation/outdoor-air ACH, not envelope infiltration`
- `generic zero with no evidence that zero is an intentional design magnitude`
- `actual-load field is zero while a separate specified design-density field is non-zero`
- `value applies to a different space type or construction type`
- `partial prototype extract intentionally omits required object family`

Do not use vague rejection language such as `seems wrong` or `probably default` without citing the contextual evidence that made the value insufficient.

## IFC/Step 6 trace rule
If IFC is used directly or partially, include:
- original IFC file name
- IFC STEP ID/type when available
- property set/property name
- exact value and unit
- whether the value is accepted direct input or only partial selection evidence

If Step 6 is used as direct IFC evidence, link it back to the IFC STEP ID/property or document the deterministic geometry calculation. A Step 6 number without provenance must not be labeled `direct IFC`.

## Prototype completeness and trace rule
If a DOE prototype is used or searched, include:
- building type or documented proxy
- climate zone/location
- standard/version
- exact prototype filename
- exact object family searched
- exact source object used
- why the object applies to the target

A reduced/compact/extracted prototype is not sufficient evidence that the full DOE prototype lacks an object family. If the local file is partial, record that status and retrieve/search the corresponding official full DOE/PNNL prototype before declaring the prototype insufficient.

Preferred official prototype source:
`https://www.energycodes.gov/development/commercial/prototype_models`

## Schedule trace rule
Schedules may come only from:
- direct IFC/Revit complete schedule data
- selected full DOE prototype
- `Schedules.idf`
- retained valid Step 7 schedule

The report must include the exact schedule object and source file. A zero within a schedule is not a rejected `trivial zero` merely because it is zero; evaluate the schedule as a time profile. Do not generate schedule time values from reasoning, COMNET, generic web search, or a new constant schedule.

## COMNET trace rule
When permitted, use only a directly applicable COMNET publication that explicitly provides the needed assumption. Record title, version/date, exact section/table, direct URL, exact value/assumption, and applicability. The COMNET home page or a search-result snippet is not a numeric source.

## Weather/DDY trace rule
Record exact EPW/DDY filenames, exact design-day object names, and exact ground-temperature source/calculation when evaluated.

## Truthfulness rule
Do not use vague final source labels such as:
- `prototype/library representative`
- `uploaded weather match`
- `COMNET guidance`
- `IFC value`
without the exact underlying file/object/property/value.

Do not use `conservative reasoning`, `reasoned generation`, or `generic web result` as a final energy-input source class.
