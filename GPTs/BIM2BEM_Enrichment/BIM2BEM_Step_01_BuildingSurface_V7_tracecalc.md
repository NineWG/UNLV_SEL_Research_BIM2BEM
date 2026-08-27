# BIM2BEM Step 01: BuildingSurface V7

Objects owned in this step:
- `BuildingSurface:Detailed`
- opaque `Construction`
- opaque `Material`
- opaque `Material:NoMass`
- `Construction:FfactorGroundFloor`
- `Site:GroundTemperature:FCfactorMethod` when appropriate for the chosen ground-floor modeling path

Targets:
- walls
- floors
- ceilings
- roofs

## Core goal
Use IFC + Step 6 evidence first.
If IFC is not enough to fully write the final EnergyPlus envelope object, use the IFC evidence to select the closest DOE prototype construction, then an applicable EnergyPlus DataSets library construction.
If those sources are insufficient, use an applicable building-code or standard requirement only for a code-governed envelope parameter.
If all of those sources fail, retain a valid Step 7 object or pass only if the target object is optional.

## Source-validity gate for envelope values
Before accepting an IFC thermal/material value, verify that it is semantically the intended envelope property and credible for the target surface. A zero/blank/default-like U-value, R-value, conductivity, thickness, or other thermal indicator must not be treated as a valid direct value merely because it exists. Zero may be accepted only when the property and construction context explicitly make zero physically and semantically appropriate. Partial IFC clues remain valuable for prototype selection even when a numeric candidate is rejected.

Accepted direct IFC values are locked against prototype/library overwrite.

## Full-prototype completeness rule
The selected DOE prototype must be the complete prototype model for the chosen building type/proxy, climate zone, and standard/version. Search the actual full prototype construction/material objects before declaring the prototype insufficient. If the local prototype file is a reduced/compact extract that omits the required construction/material family, retrieve/search the corresponding official full DOE/PNNL prototype before moving to EnergyPlus DataSets, COMNET/code, or Step 7.

## Mandatory source chain
For each opaque building-surface target, use this order:
1. IFC + Step 6 direct and partial evidence
2. selected full DOE prototype object using similar building type/proxy, climate zone/location, and standard/version
3. applicable EnergyPlus DataSets library object
4. applicable building-code or standard requirement for code-governed envelope properties
5. retained valid Step 7 representative only if the preceding levels failed or remained non-credible
6. pass only if the object is optional for the chosen modeling path and omission is safer than invention

Reasoning may be used only to select a concrete source construction. It must not invent an unsupported material layer, U-value, or construction.

## Envelope reasoning rule
IFC data is often not enough by itself to fill every EnergyPlus layer field.
That does not mean “no data.”

Use IFC + Step 6 for:
- host STEP ID
- thickness
- boundary condition
- construction hint
- material/type clues
- adjacency / exposure role

Then use those clues to find the closest representative or equivalent envelope construction.

## Mandatory IFC + Step 6 search sequence
For every opaque target surface:
1. locate the Step 6 surface by Step 7 surface name
2. read `ConstructionHint`
3. read `OutsideBoundaryCondition`
4. read host STEP ID if available
5. inspect related IFC wall/slab instance
6. inspect related IFC type
7. inspect material associations
8. inspect property sets
9. record thickness and material/type clues
10. classify the evidence as:
   - direct IFC thermal/layer data
   - partial IFC thermal intent
   - host-linked semantic evidence only

Do not report `no data` unless all of the above fail.

## Prototype and EnergyPlus library rule
If direct IFC does not fully define the final opaque construction:
- search the selected full DOE prototype first, then the uploaded EnergyPlus library set, for the closest same or similar:
  - building type
  - location/climate
  - boundary condition
  - surface class
  - thickness band
  - material/assembly clues

If a prototype or EnergyPlus library object is used, the report must include:
- `source_file`
- `source_object_type`
- `source_object_name`
- why this prototype was chosen from the IFC evidence

## COMNET, code, or deterministic-calculation rule
If IFC + Step 6 + DOE prototype + EnergyPlus library still do not provide a credible envelope object:
- use a directly applicable COMNET published technical guideline only when it explicitly provides the needed modeling assumption; record the exact publication, version, and table/section
- use a jurisdictionally applicable building code or standard when a code-governed envelope requirement is needed; COMNET guidance does not replace an adopted local code
- use a deterministic calculation only to transform a documented source value into an EnergyPlus-ready value

### Code or standard reference may be used for:
- code-based wall/roof/floor insulation requirements
- climate-zone assembly guidance
- standard nonresidential assembly assumptions

### COMNET guidance may be used for:
- directly documented building-energy-modeling assumptions that apply to the target envelope parameter
- quality-assurance or modeling-guideline interpretation when it does not conflict with direct IFC data, the selected prototype, an EnergyPlus library object, or an adopted local code

### Deterministic calculation may be used for:
- converting a credible source thermal indicator into an EnergyPlus-ready equivalent input
- deriving F-factor or related representative inputs when the method and source files are clear

Do not use generic web results, the COMNET home page, or conservative reasoning to invent an envelope value.

If a code/standard or deterministic calculation is used, the report must include:
- exact URL or code/standard identifier when applicable
- exact COMNET publication title, version, and section/table when COMNET guidance is used
- calculation method name
- input files or source values used in the calculation
- assumptions and limitations

## Ground-temperature rule for F-factor floors
If a `Construction:FfactorGroundFloor` is selected or retained, evaluate `Site:GroundTemperature:FCfactorMethod` using this exact order:
1. IFC / Step 6 if available
2. selected similar-location DOE prototype or EnergyPlus library IDF
3. calculation from credible weather/stat-style inputs if available
4. retained Step 7 object if one exists and is consistent
5. pass only if the object is optional or omission is safer than invention

### Important clarification
- Do not jump to a calculation if the selected prototype or EnergyPlus library already contains a usable `Site:GroundTemperature:FCfactorMethod`.
- Do not claim a library fallback if the object actually came from the selected prototype.
- If the object is derived by calculation, report the exact method and inputs.
- If the object is omitted, explain why omission is valid for the chosen modeling path.

## Retain/pass-last rule
Retaining a Step 7 representative is allowed only when:
1. IFC/Step 6 was searched and was insufficient
2. DOE prototype and applicable EnergyPlus library objects were searched and were insufficient
3. a directly applicable COMNET guideline or code/standard was checked when meaningful and did not provide a credible better match, or was not applicable to this target
4. the Step 7 object is still the safest valid representative

Passing without creating an object is allowed only when:
1. the object is optional for the chosen modeling path, or
2. no credible source exists and omission is safer than writing an unsupported guess

## Reporting rule
For each grouped surface assignment, record:
- Step 7 surface names or grouped set
- surface class
- host STEP ID if available
- source IFC object and property names
- thickness and boundary condition used
- source class:
  - direct IFC
  - partial IFC / Step 6
  - DOE prototype
  - EnergyPlus library
  - COMNET published guideline
  - code or standard
  - deterministic calculation
  - retained input-IDF representative
  - pass / optional omission
- exact source file
- exact source object type
- exact source object name
- exact source property names and values
- exact COMNET publication, version, direct URL, and section/table when COMNET guidance was used
- exact code/standard URL if a code-governed value was used
- exact calculation method and inputs if calculation was used
- whether Step 7 was retained
- whether the object was passed/omitted
- generated material and construction names
- assumptions and warnings
