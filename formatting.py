import os
import pandas as pd
import numpy as np
from matplotlib import pyplot as plt


def extract_intensity(val):
    if isinstance(val, str):
        parts = val.split('_')
        try:
            return float(parts[3])
        except (IndexError, ValueError):
            return np.nan
    return np.nan

def extract_rt(val):
    if pd.isna(val):
        return None

    s = str(val).strip()
    if s == "":
        return None

    parts = s.split(';')
    rt_list = []
    for part in parts:
        part = part.strip()
        if part == "":
            continue
        tokens = part.split('_')
        # Index 1 is rt
        if len(tokens) >= 2:
            rt_val = float(tokens[1])
            rt_list.append(f"{rt_val:.4f}")

    if not rt_list:
        return None

    return ';'.join(rt_list)

def apply_extract_rt(aligned_matrix: pd.DataFrame, sp_list: list) -> pd.DataFrame:
    """
    Apply extract_rt to each cell in the specified columns of the DataFrame.
    """
    matrix_rt = aligned_matrix.copy()
    for col in sp_list:
        matrix_rt[col] = matrix_rt[col].apply(extract_rt)
    return matrix_rt


