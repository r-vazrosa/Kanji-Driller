# logic.py
import pandas as pd
import random
import os
import sys
import json
from typing import Dict, Any

def resource_path(relative_path: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative_path)

data: Dict[str, Any]
kanji_json_path = resource_path("kanji.json")
try:
    with open(kanji_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if not isinstance(data, dict):
            data = {}
except Exception:
    data = {}

empty_df = pd.DataFrame()

if data:
    try:
        df = pd.DataFrame.from_dict(data, orient="index").reset_index().rename(columns={"index": "kanji"})
    except Exception:
        df = empty_df
else:
    df = empty_df

def filterDataFrame(system, levels, drill):

    if df is None or df.shape[0] == 0:
        return empty_df

    try:
        if system == "JLPT":
            if drill == "Meaning":
                return df[
                    (df.get("jlpt_new").isin(levels)) &
                    (df.get("meanings").notna())
                ]

            elif drill == "Reading":
                return df[
                    (df.get("jlpt_new").isin(levels)) &
                    (df.get("readings_on").notna()) &
                    (df.get("readings_kun").notna())
                ]

        elif system == "WaniKani":
            if drill == "Meaning":
                return df[
                    (df.get("wk_level").isin(levels)) &
                    (df.get("wk_meanings").notna())
                ]

            elif drill == "Reading":
                return df[
                    (df.get("wk_level").isin(levels)) &
                    (df.get("wk_readings_on").notna()) &
                    (df.get("wk_readings_kun").notna())
                ]
    except Exception:
        return empty_df

    return empty_df


def getMaxCount(system, levels, drill):
    filtered = filterDataFrame(system, levels, drill)
    try:
        return int(filtered.shape[0])
    except Exception:
        return 0


def getRandomSample(df_f, count):
    if df_f is None or df_f.shape[0] == 0:
        return df_f.iloc[0:0] if hasattr(df_f, "iloc") else empty_df

    n = int(count)
    if n <= 0:
        return df_f.iloc[0:0]

    n = min(n, len(df_f))
    return df_f.sample(n=n, random_state=None).reset_index(drop=True)


def getRow(df_s, index):
    if df_s is None or df_s.shape[0] == 0:
        raise IndexError("DataFrame is empty")
    if not (0 <= index < len(df_s)):
        raise IndexError(f"index {index} out of range (0..{len(df_s)-1})")
    return df_s.iloc[index]


def getRandomRows(df_s, row, count):
    if df_s is None or df_s.shape[0] == 0:
        raise ValueError("DataFrame is empty")

    if not (0 <= row < len(df_s)):
        raise IndexError(f"row {row} out of range (0..{len(df_s)-1})")

    available_indices = list(df_s.index)
    try:
        available_indices.remove(df_s.index[row])
    except ValueError:
        pass

    if count > len(available_indices):
        raise ValueError(
            f"Requested {count} rows, but only {len(available_indices)} available"
        )

    chosen_indices = random.sample(available_indices, count)
    return df_s.loc[chosen_indices]
