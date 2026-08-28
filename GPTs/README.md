# Custom GPT Workflow Packages

This directory contains the documented configuration materials for the two
custom GPT workflows used by the case study.

| Directory | Role |
| --- | --- |
| BIM2BEM_Geometry | Extracts and processes IFC geometry, assigns boundary conditions, and produces an initial IDF. |
| BIM2BEM_Enrichment | Enriches the initial IDF with traceable energy-related input parameters and validates simulation readiness. |

## Sequential Configuration Design

The case-study workflow uses two sequential custom GPT configurations. The
Geometry GPT produces the initial IDF and the intermediate geometry evidence;
the Enrichment GPT then uses these artifacts to supplement non-geometric
energy inputs and check simulation readiness. The split was a practical
configuration decision because the combined workflow rules exceeded the
instruction-field capacity used for a single configuration in the case study.
It is not a multi-agent architecture: the handoff occurs through explicit
intermediate files and user-supervised stages.

## Reconstructing the Configurations

For each workflow, create a custom GPT and use the applicable instruction file
and companion knowledge files from its directory. Enable Code Interpreter and
Data Analysis. Enable Web Search for the enrichment workflow when official
prototype, code, or reference sources must be consulted.

The included files document the configuration used for the case study. A custom
GPT deployment can change as the underlying ChatGPT product evolves; therefore,
the instruction and knowledge files are retained here as the reproducibility
record.

## Example Prompts and Outputs

`BIM2BEM_Geometry/Result_with_Input_and_Prompt/` contains screenshots for
Steps 1-7, and `BIM2BEM_Enrichment/Result_with_Input_and_Prompt/` contains the
Step 8 screenshot. These images illustrate the reported case-study interaction;
use the accompanying machine-readable scripts and workflow artifacts for
reproduction.
