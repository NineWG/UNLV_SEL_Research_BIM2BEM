# BIM2BEM Step 06: Weather, DesignDay, SimulationControl, GroundTemperature V7

Objects owned in this step:
- weather file selection
- `SizingPeriod:DesignDay`
- `SimulationControl`
- `RunPeriod` daylight-saving flag
- `Site:GroundTemperature:FCfactorMethod` when appropriate for the final chosen ground-floor modeling path

## Full-prototype and location rule
When a prototype is used for `SimulationControl` or ground-temperature reference, search the complete selected DOE prototype. If the local prototype is partial, retrieve/search the official full DOE/PNNL prototype before declaring the prototype insufficient.

The target building location and uploaded weather library control site/weather/design-day selection. Do not copy a prototype city's `Site:Location` or design days when they do not match the target location merely because the prototype building type matches.

Zero values in weather/design-day objects are not automatically invalid; evaluate them according to the field semantics (for example wind direction or a dry-bulb range may legitimately be 0). The critical-zero rule is about unsupported design magnitudes, not every numeric zero.

## Source priority
1. uploaded weather library
2. prototype-linked weather and ground-temperature data if clearly appropriate
3. deterministic calculation from credible weather/stat-style inputs only when needed for a ground-temperature object
4. retained Step 7 representative only if all above fail
5. pass only if the object is optional and omission is acceptable

Do not use generic web results or reasoning to create weather, design-day, simulation-control, or ground-temperature values.

## Weather/design-day rules
- exact uploaded location match first
- only this step may modify design days
- remove all existing design days
- keep only one winter and one summer design day by default
- do not paste the full DDY block
- align `SimulationControl` to the chosen prototype logic
- set `RunPeriod -> Use Weather File Daylight Saving Period = No` unless explicitly requested otherwise
- do not create `RunPeriodControl:DaylightSavingTime`

## Ground-temperature rule
If the final model uses any `Construction:FfactorGroundFloor`:
- evaluate whether `Site:GroundTemperature:FCfactorMethod` is required
- if required, search in this order:
  1. IFC / Step 6
  2. selected DOE prototype or EnergyPlus library object
  3. calculation from available weather/stat-style inputs
  4. retained Step 7 object if valid
  5. pass only if optional or safer to omit

### Calculation examples
A calculation path is allowed when a prototype or weather/stat context clearly supports it, such as:
- monthly ground temperatures derived from a stat-based F-factor method
- prototype-linked ground-temperature generation using credible weather/stat inputs

If calculation is used, the report must include:
- method name
- input file names
- input source values
- generated monthly ground temperatures

## Reporting rule
Record:
- selected location
- selected EPW full file name
- selected DDY full file name
- chosen design-day object names
- whether the weather match was exact or fallback
- exact weather source file names
- simulation control source file/object
- whether `Site:GroundTemperature:FCfactorMethod` was required
- whether it was written
- if written, its exact source file/object
- whether it came from prototype, EnergyPlus library, deterministic calculation, retained Step 7, or pass
- exact calculation method and input file names if calculation was used
