# Manual Reference EnergyPlus Model

This directory contains the independently created EnergyPlus reference model
used for comparison with the LLM-generated IDF.

| File | Description |
| --- | --- |
| ManualGen_EP.idf | Manually created EnergyPlus 9.6 reference input data file. |
| ManualGen_EP.csv | EnergyPlus output data used for result inspection and plotting. |
| ManualGen_EPTable.html | EnergyPlus tabular-output report. |
| ManualGen_EP.err | EnergyPlus runtime and diagnostic log. |

Run the IDF with the weather files in ../../Weather_Data/ when reproducing the
case-study simulation.
