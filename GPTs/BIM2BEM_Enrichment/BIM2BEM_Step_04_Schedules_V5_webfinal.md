# BIM2BEM Step 04: Schedules V5 - V9.4 Alignment Patch

Objects owned in this step:
- `ScheduleTypeLimits`
- `Schedule:Compact`
- `Schedule:Constant`
- other schedule objects only if needed

This step does not change geometry, envelope constructions, or numeric design magnitudes owned by Step 03.

## Source priority
For every schedule object, use this exact order:
1. direct complete schedule objects/values from IFC/Revit
2. exact applicable schedule object from the selected full DOE/PNNL prototype IDF
3. exact applicable schedule object from the uploaded `Schedules.idf`
4. retain the valid schedule already contained in the Step 7 IDF

Reasoning may be used only to select/map an existing schedule object. Do not generate time values from building type, location, space type, schedule name, COMNET, generic web search, or a new conservative constant schedule.

## Full-prototype schedule completeness rule
The prototype stage means the complete selected DOE prototype, not a compact schedule/envelope extract. Before declaring that the prototype lacks an occupancy, lighting, equipment, infiltration, or thermostat schedule, search the corresponding full prototype IDF.

If the local prototype file is reduced/compact and the required schedule family is absent, it is permitted to use the web only to retrieve the official full DOE/PNNL prototype. This remains source level 2 and is not permission to derive a schedule from a web page.

## Zero schedule rule
A schedule value of `0` is not a `trivial zero` by itself. Zero may legitimately represent an off period, unoccupied period, design-day condition, or other intended schedule state. Evaluate the complete schedule profile and source semantics; do not replace a valid schedule merely because some fields are zero.

The critical-zero validation used for Step 03 design magnitudes must not be mechanically applied to schedule fractions.

## Required schedule families
- occupancy
- lights
- equipment
- infiltration
- heating setpoint
- cooling setpoint
- activity schedule if `People` needs one

Do not leave a schedule name in an object unless the actual schedule object exists in the final IDF.

## Prototype-to-load consistency rule
When Step 03 uses a prototype fallback for a load/infiltration object, prefer the schedule actually referenced by that same or closest applicable full-prototype object, unless a higher-priority direct IFC schedule exists.

## Reporting rule
For each schedule, record:
- source class
- exact source file/object name
- prototype space/use relationship when applicable
- selection reason
- whether any zero values are intentional schedule states
- final schedule object name
- if Step 7 was retained, why full prototype and `Schedules.idf` were insufficient
