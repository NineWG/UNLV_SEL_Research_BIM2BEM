# BIM2BEM Step 02: FenestrationSurface V4 Trace

Objects owned in this step:
- `FenestrationSurface:Detailed`
- `WindowMaterial:SimpleGlazingSystem`
- window `Construction`
- door `Construction`
- door materials only if needed

Targets:
- windows
- doors

## Universal source priority for fenestration
1. direct IFC + Step 6 evidence
2. same-type IFC reuse
3. same-building representative reuse
4. selected full DOE prototype object using similar building type/proxy, climate zone/location, and standard/version
5. applicable EnergyPlus DataSets library object
6. when permitted, a directly applicable COMNET published technical guideline for a documented modeling assumption
7. a jurisdictionally applicable building-code or standard requirement for a code-governed fenestration property
8. retained valid Step 7 construction

Reasoning may be used only to select an existing source object. Do not create a glazing, door construction, U-factor, SHGC, or visible transmittance value through conservative reasoning.

## Source-validity gate for fenestration
Direct IFC remains highest priority only when the property is semantically correct and credible for the target window/door. A zero/blank/default-like U-factor, SHGC, or visible transmittance must not automatically terminate the hierarchy. Accept zero only when the IFC type/material/analytic-construction context explicitly supports that zero for the target fenestration. Otherwise record the candidate as rejected/insufficient and continue to the full DOE prototype.

A clear, project-specific IFC U-factor/SHGC/VT or door thermal property must be used and locked against later overwrite.

## Full-prototype completeness rule
Search the complete selected DOE prototype for glazing, fenestration construction, and door objects. If the local prototype is a compact/reduced extract and the target object family is absent, retrieve/search the corresponding official full DOE/PNNL prototype before moving to EnergyPlus DataSets, COMNET/code, or Step 7.

## Critical window rule
If direct IFC window thermal properties exist on the window instance, window type, or type-linked property sets, those direct values must be used.
Do not overwrite direct IFC window values with prototype/library glazing.

## Mandatory IFC window search
For each Step 7 window:
1. match Step 7 window to Step 6 by name
2. read Step 6 `ifc_stepid`
3. inspect IFC window instance
4. inspect IFC window type
5. inspect instance property sets
6. inspect type property sets
7. inspect material associations
8. inspect analytic construction / thermal properties
9. try same-type IFC reuse
10. only then consider the selected DOE prototype
11. only then consider an applicable EnergyPlus DataSets library object
12. only then consider a directly applicable COMNET guideline when it explicitly provides the needed modeling assumption
13. only then consider a code or standard reference when it directly governs the property

## Accepted direct window property names
Search at minimum for these property names and variants:
- `Heat Transfer Coefficient (U)`
- `Heat Transfer Coefficient`
- `U-Value`
- `Thermal Transmittance`
- `Solar Heat Gain Coefficient`
- `SHGC`
- `Visual Light Transmittance`
- `Visible Light Transmittance`
- `Visual Light Transmission`
- `Analytic Construction`

## Direct window mapping rule
Map direct IFC values to:
- `WindowMaterial:SimpleGlazingSystem.U-Factor`
- `WindowMaterial:SimpleGlazingSystem.Solar Heat Gain Coefficient`
- `WindowMaterial:SimpleGlazingSystem.Visible Transmittance`

## Window tolerance rule
If direct IFC window values are found, the final written values must match those IFC-derived values except for insignificant formatting or rounding.
Do not substitute library values that materially differ from IFC.

## Door rule
For doors, use IFC thermal intent evidence first:
- U-value
- R-value
- analytic construction text
- panel material
- frame material
- thickness
- type name

If direct full layer data is not possible:
- report source as `partial IFC thermal intent`
- use those clues to select an equivalent DOE prototype or EnergyPlus library door construction
- use a directly applicable COMNET guideline only when it directly documents the required modeling assumption
- use a code or standard only when it provides a directly usable door requirement


## Door/window construction compatibility hard rule
Never assign a `WindowMaterial:*` based construction to a `FenestrationSurface:Detailed` object where `Surface Type = Door`.

For every door:
1. the referenced `Construction` must be opaque or door-specific
2. the referenced `Construction` must not contain any `WindowMaterial:*` layer
3. if direct IFC door thermal/layer data is unavailable, use partial IFC door intent to select a representative opaque DOE prototype or EnergyPlus library door construction
4. if no credible prototype or library door construction is available, use a directly applicable COMNET guideline or code/standard only when it directly provides the required property; otherwise retain a valid opaque Step 7 door construction
5. if no valid opaque door construction exists, do not invent a new conservative door construction; report the missing source and return the Step 7 fallback or a blocking validation issue

Before returning the Step 02 result, validate every door construction reference against the actual construction layers in the final IDF text. A door using a window/glazing construction is a blocking error.

## Mandatory report detail
For each window or grouped window type, the report must include:
- `source_file = <actual original IFC filename>`
- Step 6 file name and `ifc_stepid`
- IFC type name if available
- property set names if available
- exact property names used
- exact values used and units
- whether values came from instance, type, or same-type reuse
- generated glazing material name
- generated construction name

For each door or grouped door type, include the same trace detail as applicable.
For any COMNET-derived assumption, include the exact publication title, version, direct URL, and applicable section/table.

## Do not
- do not report only “prototype/library with IFC linkage preserved” when direct IFC values exist
- do not change window geometry or host wall names
- do not use prototype glazing values that materially differ from direct IFC values when direct IFC values are available
- do not use generic web results, the COMNET home page, or conservative reasoning to create fenestration properties
