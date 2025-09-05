import sys
import re
import traceback
from typing import Optional
import pandas as pd
import numpy as np

# ========= Configuration =========
INPUT_CSV  = "attendance_reports_attendance.csv"   
OUTPUT_CSV = "attendance_summary_by_student.csv"

# ========= Utilities =========
def norm_header(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip()).lower()

def is_mostly_dates(series: pd.Series, thresh: float = 0.65) -> bool:
    s = series.dropna().astype(str).str.strip()
    if s.empty:
        return False
    # quick format check like 9/2/2025 or 2025-09-02
    date_like_hits = s.str.match(r"^\d{1,4}[-/]\d{1,2}[-/]\d{1,4}$", na=False)
    if date_like_hits.mean() >= thresh:
        return True
    parsed = pd.to_datetime(s, errors="coerce", infer_datetime_format=True)
    return parsed.notna().mean() >= thresh

def looks_like_attendance(series: pd.Series, thresh: float = 0.7) -> bool:
    """True if the column largely consists of present/absent/late (after normalization)."""
    s = normalize_attendance(series)
    return s.isin({"present", "absent", "late"}).mean() >= thresh

def is_mostly_numeric(series: pd.Series, thresh: float = 0.7) -> bool:
    s = series.dropna().astype(str).str.strip()
    if s.empty:
        return False
    numeric_hits = s.str.match(r"^[0-9]+$", na=False)
    return numeric_hits.mean() >= thresh

def has_letters(series: pd.Series, thresh: float = 0.5) -> bool:
    """True if at least `thresh` fraction of non-null values contain letters."""
    s = series.dropna().astype(str).str.strip()
    if s.empty:
        return False
    return s.str.contains(r"[A-Za-z]", na=False).mean() >= thresh

def normalize_attendance(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.lower()
    s = s.str.replace(r"[.,;:!?]+$", "", regex=True)
    label_map = {
        "present": "present", "p": "present", "here": "present",
        "absent": "absent", "a": "absent",
        "unexcused absence": "absent", "excused absence": "absent",
        "late": "late", "l": "late", "tardy": "late",
        "late arrival": "late", "late check-in": "late",
    }
    return s.map(lambda x: label_map.get(x, x)).str.strip()

def find_attendance_column(df: pd.DataFrame) -> str:
    known = {"present", "absent", "late"}
    best_col, best_score = None, -1.0
    for col in df.columns:
        score = normalize_attendance(df[col]).isin(known).mean()
        if score > best_score:
            best_col, best_score = col, score
    if best_col is None or best_score < 0.4:
        raise KeyError(
            "Could not confidently identify the Attendance column. "
            "Please specify it explicitly or ensure values resemble present/absent/late."
        )
    return best_col

def choose_student_name_column(df: pd.DataFrame, attendance_col: str) -> str:
    """
    Prefer a valid 'Student Name' column; else fall back to 'Student ID' if it looks like names;
    else pick the most name-like column (letters present, not dates, not attendance).
    """
    norm_map = {norm_header(c): c for c in df.columns}

    # 1) Prefer an actual Student Name header if it isn't dates or attendance
    for alias in ("student name", "student", "name"):
        if alias in norm_map:
            cand = norm_map[alias]
            if not is_mostly_dates(df[cand]) and not looks_like_attendance(df[cand]):
                return cand

    # 2) Fall back to Student ID if it appears to actually contain names (letters/mixed)
    if "student id" in norm_map:
        sid = norm_map["student id"]
        # Use it if it has letters (many systems put names in the wrong column)
        if has_letters(df[sid], thresh=0.3) and not looks_like_attendance(df[sid]) and not is_mostly_dates(df[sid]):
            return sid

    # 3) Heuristic: pick the most name-like among remaining columns
    best_col, best_score = None, -1.0
    for col in df.columns:
        if col == attendance_col:
            continue
        if is_mostly_dates(df[col]) or looks_like_attendance(df[col]):
            continue
        # Score: letters preferred; avoid mostly numeric; moderate uniqueness
        s = df[col].dropna().astype(str).str.strip()
        if s.empty:
            continue
        letters = s.str.contains(r"[A-Za-z]", na=False).mean()
        non_numeric = 1.0 - float(is_mostly_numeric(df[col]))
        nunique = s.nunique()
        n = max(len(s), 1)
        # prefer ~25% unique ratio (names repeat across sessions); clamp to [0,1]
        card = 1.0 - abs((nunique / n) - 0.25)
        card = max(0.0, min(1.0, card))
        score = 0.5 * letters + 0.3 * non_numeric + 0.2 * card
        if score > best_score:
            best_col, best_score = col, score

    if not best_col:
        raise KeyError("Could not determine a student-name column.")
    return best_col

# ========= Main =========
def main():
    df = pd.read_csv(INPUT_CSV)
    # normalize headers (preserve readable case otherwise)
    df.columns = [re.sub(r"\s+", " ", c.strip()) for c in df.columns]

    # 1) Find and normalize attendance
    attendance_col = find_attendance_column(df)
    df["attendance_norm"] = normalize_attendance(df[attendance_col])

    # 2) Choose a reliable student-name column
    student_col = choose_student_name_column(df, attendance_col)

    # Diagnostics
    print(f"[attendance_aggregate] Student column chosen: '{student_col}'")
    print(f"[attendance_aggregate] Attendance column chosen: '{attendance_col}'")
    # Uncomment to inspect uniques:
    # print("Unique student_col samples:", df[student_col].dropna().astype(str).str[:40].head(10).tolist())
    # print("Unique attendance_norm:", df["attendance_norm"].unique().tolist())

    # 3) Build one row per student (NO date involved)
    summary = pd.crosstab(index=df[student_col], columns=df["attendance_norm"])

    # 4) Ensure canonical columns exist
    for col in ["present", "absent", "late"]:
        if col not in summary.columns:
            summary[col] = 0

    # 5) Output formatting
    summary = summary[["present", "absent", "late"]].astype(int).reset_index()
    summary = summary.rename(columns={student_col: "Student Name"})
    summary["total_marked"] = summary[["present", "absent", "late"]].sum(axis=1)
    summary["attended"] = summary["present"] + summary["late"]
    summary["absent_equiv"] = summary["absent"] + 0.5 * summary["late"]
    summary = summary.sort_values("Student Name").reset_index(drop=True)

    # 6) Save + preview
    summary.to_csv(OUTPUT_CSV, index=False)
    print(f"[attendance_aggregate] Saved per-student summary to: {OUTPUT_CSV}")
    print(summary.head(12).to_string(index=False))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[attendance_aggregate] {e}")
        traceback.print_exc()
        sys.exit(1)
