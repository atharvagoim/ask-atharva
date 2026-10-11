"""Spreadsheet analysis with pandas. Numbers come from the data, never from the AI."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from app.services import files  # noqa: E402

ANALYSES = ("summary", "missing_values", "top_values", "pivot", "chart", "correlation")
MAX_TEXT = 3500


class SheetError(ValueError):
    pass


def load(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            try:
                df = pd.read_csv(path)
            except UnicodeDecodeError:
                df = pd.read_csv(path, encoding="latin-1")
        elif suffix in (".xlsx", ".xlsm"):
            df = pd.read_excel(path)
        else:
            raise SheetError("Only .xlsx and .csv files can be analysed.")
    except SheetError:
        raise
    except Exception as e:  # noqa: BLE001
        raise SheetError(f"I couldn't read {path.name}: {e}") from e
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    if df.empty:
        raise SheetError(f"{path.name} has no data in it.")
    return df


def _columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    numeric = list(df.select_dtypes(include="number").columns)
    categorical = [c for c in df.columns if c not in numeric and df[c].nunique(dropna=True) <= max(50, len(df) // 2)]
    return numeric, categorical


def _pick(columns: list[str], wanted: str | None, fallback_index: int = 0) -> str | None:
    if not columns:
        return None
    if wanted:
        w = wanted.strip().lower()
        for c in columns:
            if c.lower() == w:
                return c
        for c in columns:
            if w in c.lower():
                return c
    return columns[min(fallback_index, len(columns) - 1)]


def _text(obj) -> str:
    out = obj.to_string() if hasattr(obj, "to_string") else str(obj)
    return out if len(out) <= MAX_TEXT else out[:MAX_TEXT] + "\n… (trimmed)"


def analyse(file_name: str, analysis: str = "summary", group_by: str | None = None, value: str | None = None) -> dict:
    path = files.find_upload(file_name)
    if path.suffix.lower() not in files.SPREADSHEETS:
        raise SheetError(f"{path.name} isn't a spreadsheet.")
    df = load(path)
    analysis = analysis if analysis in ANALYSES else "summary"
    numeric, categorical = _columns(df)
    group_col = _pick(categorical, group_by)
    value_col = _pick(numeric, value)

    header = f"{path.name}: {len(df):,} rows, {len(df.columns)} columns ({', '.join(df.columns[:20])}{'…' if len(df.columns) > 20 else ''})"
    made: list[str] = []

    if analysis == "missing_values":
        missing = df.isna().sum()
        missing = missing[missing > 0].sort_values(ascending=False)
        body = "No missing values — every cell is filled in." if missing.empty else "Missing values per column:\n" + _text(missing)
    elif analysis == "correlation":
        if len(numeric) < 2:
            body = "Correlation needs at least two numeric columns."
        else:
            body = "Correlation between numeric columns (1 = move together, -1 = opposite):\n" + _text(df[numeric].corr().round(2))
    elif analysis == "top_values":
        col = group_col or _pick([c for c in df.columns if c not in numeric], group_by)
        if col is None:
            body = "There are no text columns to count."
        else:
            body = f"Most common values in “{col}”:\n" + _text(df[col].value_counts().head(10))
    elif analysis in ("pivot", "chart"):
        if not group_col or not value_col:
            body = "This needs one text column to group by and one number column to add up."
        else:
            grouped = df.groupby(group_col, dropna=False)[value_col].sum().sort_values(ascending=False)
            body = f"Total “{value_col}” by “{group_col}”:\n" + _text(grouped.round(2))
            if analysis == "chart":
                made.append(_bar_chart(grouped.head(15), group_col, value_col, path.stem))
    else:
        parts = []
        if numeric:
            parts.append("Numbers:\n" + _text(df[numeric].describe().T[["mean", "min", "max"]].round(2)))
        if categorical:
            parts.append("Text columns (distinct values): " + ", ".join(f"{c} ({df[c].nunique()})" for c in categorical[:10]))
        missing_total = int(df.isna().sum().sum())
        parts.append(f"Missing cells: {missing_total:,}")
        body = "\n\n".join(parts)

    made.append(_report(df, path.stem, group_col, value_col))
    return {"text": f"{header}\n\n{body}", "files": made}


def _bar_chart(series: pd.Series, group_col: str, value_col: str, stem: str) -> str:
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=144)
    ax.bar([str(i) for i in series.index], series.values, color="#3F6B5C")
    ax.set_title(f"{value_col} by {group_col}", fontsize=14, loc="left", color="#1E2A23")
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(colors="#3d4a43")
    ax.grid(axis="y", alpha=0.25)
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    out = files.output_path(f"{stem} chart {files.timestamp()}.png")
    fig.savefig(out)
    plt.close(fig)
    return out.name


def _report(df: pd.DataFrame, stem: str, group_col: str | None, value_col: str | None) -> str:
    out = files.output_path(f"{stem} analysis {files.timestamp()}.xlsx")
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Data", index=False)
        df.describe(include="all").T.to_excel(writer, sheet_name="Summary")
        if group_col and value_col:
            df.groupby(group_col, dropna=False)[value_col].agg(["sum", "mean", "count"]).to_excel(writer, sheet_name="Pivot")
    return out.name
