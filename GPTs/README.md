# Custom GPT Workflow Packages

This directory contains the documented configuration materials for the two
custom GPT workflows used by the case study.

| Directory | Role |
| --- | --- |
| BIM2BEM_Geometry | Extracts and processes IFC geometry, assigns boundary conditions, and produces an initial IDF. |
| BIM2BEM_Enrichment | Enriches the initial IDF with traceable energy-related input parameters and validates simulation readiness. |

## Reconstructing the Configurations

For each workflow, create a custom GPT and use the applicable instruction file
and companion knowledge files from its directory. Enable Code Interpreter and
Data Analysis. Enable Web Search for the enrichment workflow when official
prototype, code, or reference sources must be consulted.

The included files document the configuration used for the case study. A custom
GPT deployment can change as the underlying ChatGPT product evolves; therefore,
the instruction and knowledge files are retained here as the reproducibility
record.
