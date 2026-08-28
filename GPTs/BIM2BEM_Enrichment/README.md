# BIM2BEM Enrichment GPT

This package contains the configuration materials for the custom GPT that
enriches the initial Step 7 IDF with energy-related inputs and checks the final
model for simulation readiness.

## Included Materials

- BIM2BEM_Enrich_Instructions.txt: primary enrichment instructions.
- BIM2BEM_Step_00_ through BIM2BEM_Step_08_: task-specific instructions for
  controller, construction, loads, schedules, HVAC, weather, validation, and
  final readiness checks.
- BIM2BEM_Source_Trace_Guard_V1.md: source-traceability requirements.
- BIM2BEM_IDF_Syntax_Guard_V2.md: IDF syntax and object-integrity checks.
- Library.zip: prototype-model reference library.
- Weather.zip: weather and design-day reference library.
- Schedules.idf: EnergyPlus schedule reference library.

## Custom GPT Setup

Upload the instruction, guard, and reference files in this directory as
knowledge files for the Enrichment GPT. Enable Code Interpreter and Data
Analysis. Enable Web Search only when the workflow needs to consult an
official prototype, code, or reference source.

The enrichment workflow begins with the initial IDF and intermediate evidence
files in ../../BIM2BEM_Input_Output/Output/. It records direct IFC evidence
where available and uses reference fallbacks only when a higher-priority source
is insufficient.

Schedules.idf is a legacy EnergyPlus reference data set derived from the BLAST
schedule library and building-type patterns from ASHRAE 90.1-1989, Section 13.
It is a reference source, not a representation of the actual operation of the
case-study building or a current code requirement.
