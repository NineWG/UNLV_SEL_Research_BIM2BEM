# BIM2BEM Geometry GPT

This package contains the configuration materials for the custom GPT that
processes IFC geometry and generates the initial EnergyPlus IDF.

## Included Materials

- BIM2BEM_Geo_Instructions.txt: primary workflow instructions.
- basic_setup.txt: initial IDF template and setup content.
- IFCextraction.py: Step 1 IFC entity extraction.
- IFCtracing.py: Step 2 IFC relationship tracing.
- IFCgeometry_filter.py: Step 3 geometry filtering and attributes.
- IFCtoIDFGeometry.py: Step 4 IDF-ready surface generation.
- IFC_obc.py: Step 5 boundary-condition assignment and surface matching.
- convert_to_ep_ready.py: Step 6 EnergyPlus vertex-order conversion.
- bim_geo_to_idf.py: Step 7 initial IDF generation.

## Custom GPT Setup

Upload this directory's instruction and helper files as knowledge files for the
Geometry GPT. Enable Code Interpreter and Data Analysis so the workflow can
run the supplied Python scripts and create the JSON and IDF artifacts described
in ../../BIM2BEM_Input_Output/Output/.

The helper scripts use Python standard-library modules. The workflow expects an
IFC input file such as
../../BIM2BEM_Input_Output/Input/4StoryFactoryBuilding.ifc.
