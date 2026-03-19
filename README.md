# DualRTWarp

<img src="./logo.svg" style="width: 40%">

## Overview
DualRTWarp is a Python tool designed to correct complex retention time (RT) shifts in LC-/GC-MS-based ’omics analyses, enabling consistent and comparable feature RTs for downstream data processing and interpretation.

DualRTWarp contains **three modules**:

1. **Model training**  
- Train RT correction models (warping curves) for each sample using feature/peak lists.

2. **Correct feature lists**
- Trained models are applied to feature lists in **.csv** / **.tsv** format.

3. **Correct mzML files**  
- Trained models are directly applied to raw LC-/GC-MS data stored in the standardized **.mzML** format.

Direct RT correction at the raw data level provides high flexibility and allows integration with diverse analytical platforms and downstream software tools.

DualRTWarp is distributed with a Windows **.exe** graphical user interface (GUI), the same functionality is also available in command-line mode.

For XCMS users (in R), we additionally provide scripts to export feature lists and to directly apply trained RT correction models to **XCMSnExp** object.
   
---

## Installation
Python >= 3.10 is required

Dependency installation:
```
pip install -r requirements.txt
```

For Windows users, a .exe GUI is available in the release and can be used without installation.

---
## Usage: Command Line mode

## Module 1: DualRTWarp Model Training:
```
python mzml_model_trainer.py [parameters]
```
### Inputs files
- **.csv/.tsv** formatted feature/peak lists files (See example. To be noticed, individual feature lists for each sample are required, instead of aligned feature lists)
- For most analytical platforms, feature/peak lists can be directly exported using embedded tools
- For XCMS >= 4.8 (R) users, **RT_Corrector_XCMS.R**  script is recommended for feature/peak list exportation

example:
```
...load XCMS/other packages...
source("RT_Corrector_XCMS.R")

xdata <- readMSData(...)
xdata <- findChromPeaks(...)

export_feature_lists(
  xdata,
  outdir = "Path for export",
  suffix = ".csv"
)
...downstream analysis...
```

### Outputs
- Correction curves figures
- RT shift matrix plots
- Intermediate files
- Trained model file: **rt_correction_models.pkl**

### Parameters
**Basic settings**
| Parameter | Type | Description |
|---------|------|-------------|
| --input_dir | str (path) | Directory containing feature lists |
| --output_dir | str (path) | Output directory |
| --datatype | str | Format of your feature lists, "csv","tsv", or "msdial" (default: tsv) |
| --redo | bool | If True, always re-run the feature list collection (default: false) |
| --rm_iso | bool | If True, filter isotopic feature in feature list (default: true) |
| --min_peak | float | Minimum features intensity/area to be involved (default: 5000) |
| --rt_max | float | Maximum retention time (min) of the dataset (default: 45) |

**Feature list load setting (for csv / tsv)**
| Parameter | Type | Description |
|---------|------|-------------|
| --id_col | int | ID column number in feature lists (start from 0) |
| --rt_col | int | RT column number in feature lists |
| --mz_col | int | m/z column number in feature lists |
| --intensity_col | int | Intensity/area column number in feature lists |
| --file_suffix | str | Suffix of feature list files |
| --rt_unit | str | "min" or "sec" (default: min) |

**DBSCAN parameters setting**
| Parameter | Type | Description |
|---------|------|-------------|
| --dbscan_rt | float | DBSCAN RT tolerance for 1st round correction (min) (default: 0.4) |
| --dbscan_rt2 | float | DBSCAN RT tolerance for 2nd round correction (min) (default: 0.2) |
| --dbscan_mz | float | DBSCAN absolute m/z threshold (default: 0.02)|
| --dbscan_mz_ppm | float | DBSCAN m/z ppm threshold (default: 15) |

**Feature filter setting**
| Parameter | Type | Description |
|---------|------|-------------|
| --linear_fit | bool | Enables linear regression of feature RT as a function of sample order. Features with a linear coefficient r lower than the given threshold will be filtered. Recommended for one batch dataset, where it shows continuous RT shift along the sequence (default: False) |
| --linear_r | float | r threshold for linear fit. From 0-1 (default: 0.6) |
| --max_rt_diff | float | Maximum RT shifts (min) expected, compared to medium value (default: 0.5) |
| --min_sample | int | Minimum number of samples in which a feature should be present (default: 10) |
| --min_sample2 | int | Minimum number of samples in which a feature should be present. For edge RT regions with fewer features (default: 5) |
| --min_feature_group | int | Minimum features per sample (default: 5) |
| --rt_bins | int | Number of rt bins used for grouping features (default: 500) |

**LOESS fit setting**
| Parameter | Type | Description |
|---------|------|-------------|
| --it | int | Number of lowess iterations (default: 3) |
| --loess_frac | float | Lowess smoothing fraction, 0–1 (default: 0.1) |

**Interpolation setting**
| Parameter | Type | Description |
|---------|------|-------------|
| --interpolate_f | float | Interpolation strictness, 0–1 (default: 0.6) |

**Save and load preset configuration**
| Parameter | Type | Description |
|---------|------|-------------|
| --create_preset | str | Create preset (name) and exit |
| --config | str | Load preset (name) |

## Module 2: Correct Feature Lists
```
python apply_model_featurelist.py [parameters]
```

### Basic settings
| Parameter | Type | Description |
|--------|------|------------|
| --featurelist_dir | str (path) | Directory containing feature list files |
| --model_path | str (path) | Path to trained RT model (.pkl) |
| --output_dir | str (path) | Output directory |

### Feature list settings

| Parameter | Type | Description |
|--------|------|------------|
| --rt_columns | str | RT column name(s); comma-separated if multiple |
| --input_suffix | str | Suffix of feature list files |
| --model_suffix | str | Suffix used in model training files |
| --rt_unit | str | RT unit in input files "min" or "sec" (default: min)|

### Processing options

| Parameter | Type | Description |
|--------|------|------------|
| --ow_rt | bool | Overwrite original RT values if true (default: true) |
| --n_workers | int | Number of CPU processors (default: cpu_count-1) |
| --round_digits | int | Number of decimal digits to keep in RT (default: 4) |

## Module 3: Apply RT Model to mzML Files

```
python mzml_correction.py [parameters]
```
### Basic settings

| Parameter | Type | Description |
|--------|------|------------|
| --mzml_dir | str (path) | Directory containing mzML files |
| --out_dir | str (path) | Output directory |
| --model_path | str (path) | Path to trained RT model (.pkl) |
| --model_suffix | str | Suffix used in model training files |
| --n_workers | int | Number of CPU processors (default: cpu_count-1) |

## Module 4: Area Bias Correction

```
python area_bias_correction.py [parameters]
```
### Basic settings

| Parameter | Type | Description |
|------------|------|------------|
| --input | str (path) | Folder (feature lists) or file path (aligned feature list) |
| --output_dir | str (path) | Output directory for corrected results |
| --model_path | str (path) | Path to trained RT correction model (.pkl) |
| --rt_max | float | Maximum retention time of the dataset (min) |
| --input_suffix | str | Suffix of feature list files |
| --model_suffix | str | Suffix used in model training files |
| --rt_unit | str | RT unit in input files "min" or "sec" (default: min) |
| --n_workers | int | Number of CPU processors (default: cpu_count-1) |

### Modes

| Parameter | Type | Description |
|------------|------|------------|
| --aligned_mode | bool (`true` / `false`) | "true": input is one aligned feature list file; "false": inputs are individual feature lists |
| --rt_center_only | bool (`true` / `false`) | "true": correct bias using RT center (recommended); "false": correct bias using RT left and right edges |
| --keep_ori | bool (`true` / `false`) | `true`: keep original RT and area information |

### RT & Area Columns

| Parameter | Type | Description |
|------------|------|------------|
| --area_col | str | Name of the area column |
| --rt_center_col | str | Name of RT center column (used when "rt_center_only=true") |
| --rt_left_col | str | Name of RT left boundary column (used when "rt_center_only=false") |
| --rt_right_col | str | Name of RT right boundary column (used when "rt_center_only=false") |

---

## Usage: GUI mode 
Open GUI
```
python Gui_command.py
```
<img src="./Figs/Gui_view.png" style="width: 40%">

The parameter setting can refer to command line mode

---

## Usage: RT_Corrector_XCMS.R
This script is for applying the DualRTWarp model in XCMS object (XCMS >= 4.8) in R

Peak picking should be done before usage 

example:
```
...load XCMS/other packages...
source("DualRTWarp_XCMS.R")

xdata <- readMSData(...)
xdata <- findChromPeaks(...)

xdata_corr <- apply_DualRTWarp_XCMS(
  xdata = xdata,
  model_pkl = "path to .pkl model",
  input_suffix = ".mzML",
  model_suffix = ".txt",
)
...downstream analysis...
```

# Cite DualRTWarp
Waiting for submission......

# References
Smith, C. A., et al. (2006). "XCMS:  Processing Mass Spectrometry Data for Metabolite Profiling Using Nonlinear Peak Alignment, Matching, and Identification." Analytical Chemistry 78(3): 779–787.
