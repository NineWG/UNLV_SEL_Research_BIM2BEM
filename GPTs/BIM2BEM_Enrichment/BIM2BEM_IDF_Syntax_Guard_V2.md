# BIM2BEM IDF Syntax Guard V2

Use this file with every step whenever creating or modifying IDF text.

## Goal
Prevent EnergyPlus parse, reference, and duplicate-name failures.

## Core writing rule
Do not write a new object tail from memory if a valid object of the same type already exists in:
- the prototype/library IDF
- the Step 7 input IDF
- a validated earlier object in the current output

Instead:
1. find a valid object of the same type
2. clone its exact field order
3. keep non-variable fields unchanged unless the owner step owns them
4. replace only the intended variable fields
5. keep the final field count valid

## Basic IDF syntax rule
Every object must follow this pattern:
- object type line ends with a comma
- each intermediate field ends with a comma
- only the true final field ends with a semicolon
- comments must not break field order
- do not leave stray commas or stray semicolons

## Object-count and field-count rule
Before returning the IDF, verify for every generated or modified object:
- the object type is valid
- the field count matches the chosen schema/prototype pattern
- no extra trailing value was appended
- no required field was accidentally dropped

## Reference-integrity rule
Before returning the IDF, verify:
- every `Construction Name` points to an existing `Construction`
- every construction layer points to an existing material object
- every schedule reference points to an existing schedule object
- every thermostat reference points to an existing thermostat object
- every named object reference is spelled exactly the same as the created object

## Duplicate-name registry rule
Build a registry across the full output IDF for:
- object type
- object name

Then verify:
- no duplicate object name exists within the same object type
- comparisons must be case-insensitive and whitespace-normalized
- imported prototype object names must not collide with existing Step 7 names
- if a name collision occurs, either:
  - reuse the existing valid object intentionally, or
  - rename the new object with a BIM2BEM-specific stable name

Do not rely on the report alone; scan the actual final IDF text.

## Prototype-name collision rule
Never copy a prototype object name unchanged into the final IDF if an object of the same type and name already exists in the Step 7 IDF unless intentional reuse is desired and verified.

Prefer BIM2BEM-prefixed names for newly generated objects, for example:
- `BIM2BEM_WALL_<...>`
- `BIM2BEM_ROOF_<...>`
- `BIM2BEM_WIN_<...>`
- `BIM2BEM_SCH_<...>`
- `BIM2BEM_TSTAT_<...>`


## Output-request uniqueness rule
`Output:Variable` objects do not have ordinary object names, so the duplicate-name registry alone is insufficient. Build a separate output-request registry.

For each `Output:Variable`, normalize and compare:
- Key Value
- Variable Name
- Reporting Frequency

If all three fields match an earlier request, the later object is an exact duplicate and must be removed. Keep the first valid occurrence. Do not remove requests that intentionally differ in key or frequency.

Also avoid duplicate identical `Output:VariableDictionary` requests.
When adding standard BIM2BEM output requests, always search first and add only missing requests. After writing the full IDF, run the registry again and confirm zero exact duplicates remain.

## Common failure patterns to prevent

### People
Populate only the field matching the selected calculation method:
- `People` -> populate `Number of People` only
- `People/Area` -> populate `People per Floor Area` only
- `Area/Person` -> populate `Floor Area per Person` only

### Lights
Populate only the field matching the selected calculation method:
- `LightingLevel` -> populate `Lighting Level` only
- `Watts/Area` -> populate `Watts per Zone Floor Area` only
- `Watts/Person` -> populate `Watts per Person` only

### ElectricEquipment
Populate only the field matching the selected calculation method:
- `EquipmentLevel` -> populate `Design Level` only
- `Watts/Area` -> populate `Watts per Zone Floor Area` only
- `Watts/Person` -> populate `Watts per Person` only
- do not append an extra trailing value like `1.0`

### Infiltration
Populate only the field matching the selected calculation method:
- `Flow/Zone` -> `Design Flow Rate`
- `Flow/Area` -> `Flow per Zone Floor Area`
- `Flow/ExteriorArea` or `Flow/ExteriorWallArea` -> `Flow per Exterior Surface Area`
- `AirChanges/Hour` -> `Air Changes per Hour`

Leave the mutually exclusive design fields blank when they do not correspond to the selected method. Do not force every prototype infiltration object into `Flow/Area`; preserve the valid source method when it is transferable to the target geometry.

### DesignDay
- do not paste the whole DDY block
- keep only the intended design-day objects
- validate the field count against the target IDF format
- delete old design days before adding the new pair

## Safe object-generation rule
When creating a new object:
1. determine the owner step
2. identify a valid template object
3. copy the template structure
4. replace only the owned fields
5. validate field count
6. validate references
7. validate duplicate-name registry
8. then write to the IDF

## Reporting rule
If an object could not be written with confidence because the schema/template was unclear:
- do not guess aggressively
- report the issue
- fall back to a safer representative object only if justified by the workflow
