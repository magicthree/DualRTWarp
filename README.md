# RT Corrector

<img src="./logo.jpg" style="width: 20%">

## Overview
The RT Corrector is designed to fix complex retention time (RT) shift in LC(GC)-MS based 'omics analysis, enabling comparable feature RTs in downstream analysis.
RT Corrector takes individual feature lists (in .csv/.tsv format) as input, trains RT correction models for each sample, and applies models to .csv/.tsv formatted feature lists or directly to .mzML data files.

## Installation
Python >= 3.10 is required

Dependency installation:
```
pip install -r requirements.txt
```

For Windows users, Pre-packaged executables are available  (see release).

## Usage-Command Line mode
```
python mzml_model_trainer.py [parameters]
python mzml_correction.py [parameters]
python apply_model_featurelist.py [parameters]
```

## Usage-GUI mode 
GUI mode
```
python Gui_command.py
```
<img src="./Figs/Gui_view.png" style="width: 40%">

