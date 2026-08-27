# BIM2BEM Step 03: Internal Loads Numeric V3.2 - V9.4 Alignment Patch

Objects owned in this step:
- `People`
- `Lights`
- `ElectricEquipment`
- `ZoneInfiltration:DesignFlowRate`

This step owns numeric internal-load and infiltration design inputs only. Schedules are selected/written in Step 04.

## Core source order
For every target value, after the source-validity gate, use:
1. direct, semantically valid IFC/Revit + traceable Step 6 evidence
2. selected full DOE/PNNL prototype object
3. applicable EnergyPlus DataSets library object
4. when permitted, a directly applicable COMNET published guideline or applicable code/standard that explicitly provides a usable value
5. retain the existing valid Step 7 value only when the preceding sources are insufficient

Do not generate a numeric load or infiltration value through conservative reasoning.

## Mandatory IFC-first search
Before using any prototype or fallback, search IFC/Revit-exported semantic data for:
- space type / use
- occupiable and conditioned status
- area per person / people density / explicit number of people
- lighting design load density or explicit design load
- equipment/power design density or explicit design load
- explicit envelope infiltration rate/method
- outdoor-air/ventilation properties as a separate semantic family
- heating/cooling and humidity setpoint clues for Step 05 handoff

Use Step 6 to map Step 7 zones/surfaces back to the correct IFC spaces/STEP IDs. Step 6 is not an independent numeric authority unless the value is traceable to IFC or a documented deterministic calculation.

## Direct-value acceptance rule
If IFC contains a clear, project-specific, semantically correct value, use it directly and do not replace it with a prototype value.

Examples of direct IFC values that normally take priority when correctly mapped:
- `Area per Person = <non-zero project value>`
- `Specified Lighting Load per area = <non-zero W/m2>`
- `Specified Power Load per area = <non-zero W/m2>`
- explicit infiltration `Flow/Area`, `Flow/ExteriorArea`, `ACH`, or design flow when the property is explicitly envelope infiltration

Do not prefer generic `Actual ... = 0` export fields over separate non-zero `Specified ...` design fields when the model context identifies the latter as the intended design input.

## Zero/default-like value rule for design magnitudes
Zero is not automatically invalid, but a zero critical design magnitude must not terminate the hierarchy without explicit contextual support.

For `People`, `Lights`, `ElectricEquipment`, and infiltration:
- if zero is explicitly intentional for an unused, unoccupied, unlit, equipment-free, unconditioned, or otherwise applicable space, zero may be accepted
- if zero is a generic/default/uninitialized export, conflicts with non-zero design properties, or lacks semantic evidence, classify it as insufficient and continue to the selected full DOE prototype
- record the raw zero candidate and the rejection/acceptance reason

Do not apply the `trivial zero` rule to schedule values; schedules belong to Step 04 and may legitimately contain 0 during off periods.

## Infiltration semantic hard rule
Do not equate outdoor-air/ventilation values with envelope infiltration.

Properties such as:
- `Outdoor Air Method`
- `Outdoor Air per Area`
- `Outdoor Air per Person`
- `Outdoor Airflow`
- ACH contained in a property set whose semantic role is outdoor-air/ventilation
must not be mapped to `ZoneInfiltration:DesignFlowRate` unless the IFC context explicitly identifies them as envelope infiltration.

If IFC contains `Air Changes per Hour = 0` in a generic energy-analysis or outdoor-air context without explicit infiltration intent, treat it as an ambiguous/default-like candidate, not as proof of zero infiltration.

## Full DOE prototype rule
Only if accepted IFC evidence is missing or insufficient:
1. select the full DOE/PNNL prototype using building type or documented proxy, climate zone/location, and standard/version
2. search the actual full prototype for `People`, `Lights`, `ElectricEquipment`, and `ZoneInfiltration:DesignFlowRate`
3. choose the closest applicable prototype space/use object
4. use the exact sourced parameter/method, subject to the scaling rule below

A compact/reduced prototype extract that omits internal loads or infiltration does not count as the DOE prototype being checked. If the local file is partial, retrieve/search the corresponding official full DOE/PNNL prototype before using a lower-priority source.

## Prototype method and scaling rule
Preserve the source object's calculation method whenever it is directly transferable to the target geometry.

Preferred transferable intensive methods include:
- `People/Area` or `Area/Person`
- `Watts/Area` or `Watts/Person`
- infiltration `Flow/Area`, `Flow/ExteriorWallArea` / `Flow/ExteriorArea`, or `AirChanges/Hour`

Do not blindly copy a prototype zone-specific extensive total such as a fixed `Number of People`, `LightingLevel`, `EquipmentLevel`, or fixed infiltration `DesignFlowRate` into a differently sized target zone.

If only an extensive prototype total is available and a deterministic conversion to an intensive reference is necessary, it may be performed only from concrete values in the same full prototype (for example prototype total divided by prototype floor area or exterior area). Record:
- source prototype object
- source prototype geometry/area object or value
- formula
- derived intensive value
- target application method

If the required normalization cannot be supported by concrete source data, continue the hierarchy rather than inventing a scale factor.

## Method-slot rules
Use the method actually selected from the accepted source and populate only the corresponding EnergyPlus field.

### People
- `People` -> Number of People
- `People/Area` -> People per Floor Area
- `Area/Person` -> Floor Area per Person

### Lights
- `LightingLevel` -> Lighting Level
- `Watts/Area` -> Watts per Zone Floor Area
- `Watts/Person` -> Watts per Person

### ElectricEquipment
- `EquipmentLevel` -> Design Level
- `Watts/Area` -> Watts per Zone Floor Area
- `Watts/Person` -> Watts per Person

### ZoneInfiltration:DesignFlowRate
- `Flow/Zone` -> Design Flow Rate
- `Flow/Area` -> Flow per Zone Floor Area
- `Flow/ExteriorArea` or `Flow/ExteriorWallArea` -> Flow per Exterior Surface Area
- `AirChanges/Hour` -> Air Changes per Hour

Do not populate mutually exclusive fields simultaneously.

## HVAC handoff rule
Pass forward any explicit setpoint evidence found in IFC/Step 6, including source property names, values, semantic confidence, and whether the value was accepted or rejected.

## COMNET/code rule
Only if IFC, the selected full DOE prototype, and an applicable EnergyPlus library do not provide a usable value, use a directly applicable COMNET publication, code, or standard only when it explicitly provides the required parameter. Record exact publication/version/table/section/URL. Do not use generic web pages or inferred assumptions.

## Unit-conversion rule
Convert direct source units only as needed for EnergyPlus and record the conversion. Examples:
- `L/s-m2` -> `m3/s-m2` by multiplying by `0.001`
- preserve `m2/person` as `Area/Person`
- preserve `W/m2` as `Watts/Area`

## Reporting rule
For each zone or grouped space type, record:
- IFC/Step 6 evidence searched
- accepted direct values
- rejected candidates and reasons
- explicit zero-value review result
- semantic distinction between infiltration and outdoor air when relevant
- unit conversions
- exact full DOE prototype file/object/method/value if fallback was used
- whether prototype scaling/normalization was required and the exact formula/source geometry
- exact EnergyPlus library, COMNET, or code source if used
- whether Step 7 was retained and why
- final source class and object names written
- assumptions/warnings
