# Workflow Outputs

These files are the intermediate and final artifacts from the case-study
LLM-assisted BIM2BEM workflow.

| Workflow stage | File |
| --- | --- |
| Step 1: IFC entity extraction and units | seeds.json, ifc_units.json |
| Step 2: IFC entity tracing | step2_traced.json |
| Step 3: Geometry filtering and attributes | step3_geometry.json |
| Step 4: IDF-ready geometry | step4_idf_geometry.json |
| Step 5: Boundary-condition assignment | step5_obc.json |
| Step 6: EnergyPlus-ready geometry | step6_ep_ready.json |
| Step 7: Initial IDF generation | step7_output.idf |
| Step 8: Energy-parameter enrichment | enriched_output.idf |

The JSON files are intermediate evidence files rather than standalone
EnergyPlus input models. The final workflow IDF is enriched_output.idf.
