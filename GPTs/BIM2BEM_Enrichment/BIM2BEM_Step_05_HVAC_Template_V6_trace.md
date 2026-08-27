# BIM2BEM Step 05: HVAC Template V6 Trace - V9.4 Alignment Patch

Objects owned in this step:
- `HVACTemplate:Thermostat`
- `HVACTemplate:Zone:IdealLoadsAirSystem` only for `Template Thermostat Name`

## Core rule
Do not retain the input-IDF thermostat by default. Before keeping any existing thermostat values, perform a mandatory IFC + Step 6 + prior-step search for setpoint evidence.

## Source-validity gate
A direct IFC/Revit setpoint is accepted only when its semantic role is clearly heating/cooling control for the target zone/space type and the value is credible.

A zero, blank, default-like, or implausible setpoint must not terminate the hierarchy unless the IFC context explicitly supports that value for a specialized operating condition. Record rejected candidates and reasons.

A clear project-specific IFC setpoint has priority and must not be overwritten by prototype/library values.

## Source priority
1. direct, semantically valid IFC/Revit setpoint values
2. same-space-type IFC reuse within the same building when the relationship is explicit
3. selected full DOE/PNNL prototype thermostat/setpoint schedule object
4. applicable EnergyPlus library schedule object if needed
5. retain the existing valid Step 7 thermostat/setpoint schedule only if the preceding sources are insufficient

Do not generate setpoints or setpoint schedules through conservative reasoning, generic web search, or a new constant schedule.

## Full-prototype completeness rule
Search the complete selected DOE prototype for thermostat and heating/cooling schedule objects before declaring the prototype insufficient. If the local file is a compact/reduced extract, retrieve/search the official full DOE/PNNL prototype first. Official prototype retrieval is part of the prototype stage, not a generic web setpoint source.

## Mandatory setpoint search
For each zone or grouped space type, search:
- `Heating Set Point`
- `Cooling Set Point`
- `Heating Setpoint`
- `Cooling Setpoint`
- thermostat-related Revit export variants
- HVAC semantic properties on `IfcSpace`
- HVAC semantic properties on space/zone types
- setpoint clues handed off from Step 03
- same-space-type reuse across other spaces in the same IFC

## Schedule consistency rule
If prototype setpoints are used, use the actual referenced full-prototype schedule object. Step 04 remains the owner of schedule object creation/closure.

## Existing shell reuse rule
If the Step 7 thermostat shell is retained but values/schedules are replaced, distinguish:
- `shell_source_file = step7_output.idf`
- `shell_source_object = <existing thermostat name>`
- `value_source_class = direct IFC / DOE prototype / EnergyPlus library / retained Step 7 representative`

Do not collapse shell reuse and value source into one statement.

## Reporting rule
For each thermostat group, record:
- exact source file
- exact IFC properties/values and acceptance/rejection status
- exact full DOE prototype file/object/schedule if used
- exact EnergyPlus library file/object if used
- exact Step 7 shell if reused
- final heating/cooling setpoints and schedule names
- zero/default-like value review status
