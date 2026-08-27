# BIM2BEM Step 00: Controller V9.4 Alignment Patch

This controller defines the mandatory source order, value-validity gate, and full-prototype completeness rule for every downstream step.

## Required run inputs
- target building type
- target location / climate zone
- selected building standard/version when prototype selection requires it
- original IFC
- Step 6 JSON
- Step 7 IDF
- `Library.zip` containing full DOE/PNNL prototype IDFs when available
- EnergyPlus DataSets references such as `Schedules.idf`
- weather library

## Source-validity gate before source priority
Do not equate `field exists` with `field is usable`.
For every candidate energy parameter, classify it before acceptance:
- `accepted_direct_value`
- `accepted_partial_selection_evidence`
- `rejected_wrong_semantic_role`
- `rejected_default_or_placeholder_like`
- `rejected_unsupported_zero`
- `rejected_not_applicable_to_target`
- `missing`

A direct IFC/Revit value is accepted only when:
1. its semantic meaning matches the target EnergyPlus parameter
2. it applies to the target space/type/system/construction
3. the value is credible and intentionally specified or otherwise supported by the IFC context

### Zero-value rule
Zero is not automatically invalid. However, a zero critical design magnitude must not stop the hierarchy unless the source context explicitly supports zero as intentional.

Examples of values that require scrutiny before accepting zero:
- occupancy design density / area per person
- lighting design power
- electric equipment design power
- envelope infiltration design magnitude
- outdoor-air design magnitude
- window U-factor / SHGC / visible transmittance where zero would be unusual for the target window type
- heating/cooling setpoints
- thermal-property values where zero would be nonphysical or default-like

Do not apply this rule mechanically to:
- schedule off-period values
- valid EnergyPlus coefficients that may intentionally be 0
- intentionally inactive/unconditioned/unused zones when the source explicitly supports that condition
- fields where zero is physically and semantically valid

A clear, project-specific, semantically correct IFC value has priority even when the selected prototype differs. Accepted IFC values must be locked against later overwrite.

## Step 6 provenance rule
Step 6 is not an independent authority merely because it contains a number. Treat Step 6 as direct IFC evidence only when the report can trace it to:
- an IFC STEP ID/property/property set, or
- a documented deterministic calculation from IFC geometry/evidence.

## Full DOE prototype rule
The selected DOE prototype must be chosen using:
- building type or documented closest proxy
- climate zone/location
- standard/version

Record the exact prototype filename before enrichment.

`Library.zip` is expected to contain full DOE/PNNL prototype IDFs. A prototype is not considered fully checked for a target parameter until the target object family is searched in the complete model.

If a local file is marked compact/reduced/representative/extracted or explicitly omits the required object family, do not interpret absence as evidence that the DOE prototype lacks that parameter. Identify the original prototype and retrieve/search the corresponding official full DOE/PNNL prototype before moving to lower-priority sources. Preferred official source:
`https://www.energycodes.gov/development/commercial/prototype_models`

Official full-prototype retrieval is part of the DOE prototype stage. It does not authorize generic web-derived energy values.

## Universal source priority
For every enrichment target, after applying the validity gate, use this order:
1. direct, semantically valid IFC/Revit + traceable Step 6 evidence
2. selected full DOE/PNNL prototype object
3. applicable EnergyPlus DataSets library object
4. when the owning step permits a guideline lookup, a directly applicable COMNET published technical guideline
5. a jurisdictionally applicable building code or standard for code-governed parameters
6. retain the existing valid Step 7 object only if the preceding sources are insufficient
7. pass only if the object is optional and omission is safer than invention

For schedules, use:
IFC/Revit -> selected full DOE prototype -> `Schedules.idf` -> retain Step 7.
COMNET and generic web sources are excluded from the schedule-value path. Retrieving the official full DOE prototype is allowed because it remains source level 2.

## Cross-step lock rule
Once a value is accepted as valid direct IFC/Revit evidence, later steps may not replace it with a prototype, library, COMNET, code, or Step 7 value unless a validation error proves the IFC mapping itself was wrong. Any such reversal must be explicit in the report.

## Universal reporting rule
Every step must leave an auditable trail:
- target parameter/object family
- candidate sources searched
- accepted and rejected candidate values
- reason for each rejection, especially zero/default-like or wrong-semantic candidates
- exact IFC STEP IDs/property sets/property names/values when relevant
- exact prototype building type/proxy, climate zone, standard/version, file name, object type, and object name
- whether the local prototype was full or partial
- official prototype URL if a full model had to be retrieved
- exact EnergyPlus library object when used
- exact COMNET publication/version/direct URL/table/section when used
- exact code/standard identifier/URL when used
- exact deterministic calculation method and source inputs when permitted
- exact reason for Step 7 retention or optional omission


## V9.5 minimum-scope and output-request rule
This workflow is intentionally a minimum LLM-assisted enrichment workflow. Do not require exhaustive mapping of every IFC energy property to every possible EnergyPlus object/version. The mandatory enrichment scope is limited to the object families owned by Steps 01-06 and the existing minimal HVAC shell.

For final output requests:
1. scan the full current IDF before adding any required `Output:Variable`
2. normalize `(Key Value, Variable Name, Reporting Frequency)`
3. add only missing tuples
4. remove later exact duplicates while preserving the first valid occurrence
5. do not treat requests with different frequencies or keys as duplicates
6. ensure `Output:VariableDictionary` is not duplicated

Step 07 and Step 08 must verify this rule before the files are returned.
