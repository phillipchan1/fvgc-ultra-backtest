#!/usr/bin/env python3
import argparse
import ast
import math
import os
from typing import List, Tuple

import numpy as np
import pandas as pd

# Optional but recommended: install scikit-learn if you want model-based importance
# pip install scikit-learn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder

# ---------------------------
# Helpers
# ---------------------------

def coerce_float_series(s: pd.Series) -> pd.Series:
    """Coerce a series to float, mapping 'inf'/'Infinity' to np.inf."""
    def _to_float(x):
        if isinstance(x, (float, int)):
            return float(x)
        if x is None:
            return np.nan
        xs = str(x).strip().lower()
        if xs in ("inf", "infinity"):
            return np.inf
        try:
            return float(x)
        except Exception:
            return np.nan
    return s.apply(_to_float)

def safe_literal_eval(x):
    """Parse Python-literal-like strings (e.g., "['0930-0945']") into lists; return [] if empty/invalid."""
    if isinstance(x, list):
        return x
    if pd.isna(x):
        return []
    try:
        v = ast.literal_eval(str(x))
        if isinstance(v, list):
            return v
        return [str(v)]
    except Exception:
        # fall back to empty or single-item
        xs = str(x).strip()
        if xs == "" or xs.lower() in ("none", "nan"):
            return []
        return [xs]

def stringify_time_buckets(lst: List[str]) -> str:
    """Make time bucket lists model-friendly as a single categorical string."""
    if not lst:
        return ""
    # normalize like ['0930-0945','1000-1015'] -> '0930-0945|1000-1015'
    return "|".join(sorted([str(i) for i in lst]))

def is_bool_col(s: pd.Series) -> bool:
    return s.dropna().isin([True, False, "True", "False"]).all()

def summarize_numeric_effects(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """
    Spearman correlation for numeric columns vs target.
    """
    out = []
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != target]
    for c in num_cols:
        # Spearman handles monotonic relationships
        s = df[[c, target]].dropna()
        if len(s) < 10:
            continue
        corr = s[c].corr(s[target], method="spearman")
        out.append({"feature": c, "type": "numeric", "metric": "spearman_corr", "value": corr})
    return pd.DataFrame(out).sort_values("value", ascending=False)

def summarize_categorical_effects(df: pd.DataFrame, target: str, cat_cols: List[str]) -> pd.DataFrame:
    """
    For each categorical/boolean col: compute group means/medians and a simple "range of medians"
    as an effect size proxy.
    """
    rows = []
    for c in cat_cols:
        groups = (
            df[[c, target]]
            .dropna(subset=[target])
            .groupby(c)[target]
            .agg(["count", "mean", "median"])
            .reset_index()
        )
        if groups.empty or groups["count"].sum() < 10:
            continue
        # range of medians as a quick-and-dirty sensitivity proxy
        med_range = groups["median"].max() - groups["median"].min()
        rows.append({
            "feature": c,
            "type": "categorical",
            "metric": "median_range",
            "value": med_range,
            "levels": len(groups),
            "largest_group": int(groups["count"].max()),
        })
    return pd.DataFrame(rows).sort_values("value", ascending=False)

def build_model_importance(df: pd.DataFrame, target: str, candidate_features: List[str], random_state: int = 42) -> Tuple[pd.DataFrame, List[str]]:
    """
    RandomForest + OneHot for categoricals + permutation importance.
    Returns (importances_df, feature_names_out)
    """
    X = df[candidate_features].copy()
    y = df[target].astype(float)

    # Identify types
    cat_cols = [c for c in X.columns if X[c].dtype == "object"]
    num_cols = [c for c in X.columns if c not in cat_cols]

    # Preprocess
    pre = ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="median"), num_cols),
            ("cat", OneHotEncoder(handle_unknown="ignore"), cat_cols),
        ],
        remainder="drop",
    )

    X_pre = pre.fit_transform(X)

    # Train/test split
    Xtr, Xte, ytr, yte = train_test_split(X_pre, y, test_size=0.25, random_state=random_state)

    rf = RandomForestRegressor(
        n_estimators=400,
        max_depth=None,
        random_state=random_state,
        n_jobs=-1,
    )
    rf.fit(Xtr, ytr)

    # Permutation importance on test set (more honest)
    pi = permutation_importance(rf, Xte, yte, n_repeats=10, random_state=random_state, n_jobs=-1)
    # Get feature names out of the ColumnTransformer
    feature_names_out = []
    feature_names_out.extend(num_cols)
    # Pull OneHot categories
    ohe: OneHotEncoder = pre.named_transformers_["cat"]
    cat_feature_names = []
    if cat_cols:
        ohe_names = list(ohe.get_feature_names_out(cat_cols))
        cat_feature_names.extend(ohe_names)
    feature_names_out.extend(cat_feature_names)

    imp_df = pd.DataFrame({
        "feature_encoded": feature_names_out,
        "importance_mean": pi.importances_mean,
        "importance_std": pi.importances_std,
    }).sort_values("importance_mean", ascending=False)

    return imp_df, feature_names_out

# ---------------------------
# Main analysis
# ---------------------------

def main():
    parser = argparse.ArgumentParser(description="Analyze sweep_results and rank best setups by profit factor.")
    parser.add_argument("--file", required=True, help="Path to sweep_results.csv")
    parser.add_argument("--min-trades", type=int, default=5, help="Minimum trades to include (default: 5)")
    parser.add_argument("--top-n", type=int, default=200, help="How many top setups to export (default: 200)")
    parser.add_argument("--outdir", default="analysis_out", help="Output directory (default: analysis_out)")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    # Load
    df = pd.read_csv(
        args.file,
        dtype=str,  # read as strings first (we will coerce)
        keep_default_na=False
    )

    # Known columns from your sample (we'll coerce types below)
    # Parse list-like columns
    list_cols = ["allowed_time_buckets"]
    for c in list_cols:
        if c in df.columns:
            df[c] = df[c].apply(safe_literal_eval).apply(stringify_time_buckets)

    # Coerce numeric columns where appropriate
    numeric_like = [
        "run_id","points_tp","points_sl","ifvg_overlap_min_ratio","ifvg_lookback_bars",
        "min_gap_taps","max_gap_taps","min_bars_to_prev_break","max_bars_to_prev_break",
        "gap_size_min_pts","gap_size_max_pts","trades","win_rate","gross_profit","gross_loss",
        "commissions","net","profit_factor","avg_trade","ending_balance"
    ]
    for c in numeric_like:
        if c in df.columns:
            df[c] = coerce_float_series(df[c])

    # Coerce booleans if given as strings
    for c in df.columns:
        if is_bool_col(df[c]):
            df[c] = df[c].astype(str).str.lower().map({"true": True, "false": False})

    # Clean/derive
    # Keep rows with finite PF and sufficient trades
    df["is_pf_finite"] = np.isfinite(df["profit_factor"])
    base = df[df["is_pf_finite"] & (df["trades"] >= args.min_trades)].copy()

    # Add some handy metrics
    base["net_per_trade"] = base["net"] / base["trades"]
    base["profit_per_trade_abs"] = (base["gross_profit"] - base["gross_loss"] - base["commissions"]) / base["trades"]

    # Rank top setups (exclude infinite PF already)
    # Tie-breakers: more trades, higher net, higher win_rate, higher avg_trade
    top = (
        base.sort_values(
            by=["profit_factor","trades","net","win_rate","avg_trade"],
            ascending=[False, False, False, False, False]
        )
        .head(args.top_n)
        .reset_index(drop=True)
    )

    # Save top setups
    top.to_csv(os.path.join(args.outdir, "top_setups.csv"), index=False)

    # --- Variable Influence ---

    target = "profit_factor"

    # Numeric effects (spearman)
    num_effects = summarize_numeric_effects(base, target)

    # Categorical/boolean columns (object dtype or bool)
    cat_cols = [c for c in base.columns
                if (base[c].dtype == "object" or base[c].dtype == "bool")
                and c not in ("run_id", target)]
    cat_effects = summarize_categorical_effects(base, target, cat_cols)

    variable_effects = pd.concat([num_effects, cat_effects], ignore_index=True)
    variable_effects.to_csv(os.path.join(args.outdir, "variable_effects.csv"), index=False)

    # Model-based importance (handles nonlinearities & interactions)
    # Pick candidate features = all except identifiers and post-trade result columns
    exclude = {
        "run_id", target, "gross_profit", "gross_loss", "commissions", "net",
        "avg_trade", "ending_balance", "is_pf_finite", "net_per_trade", "profit_per_trade_abs"
    }
    candidate_features = [c for c in base.columns if c not in exclude]

    # Guard against empty/degenerate cases
    model_importance_df = pd.DataFrame(columns=["feature_encoded","importance_mean","importance_std"])
    try:
        model_importance_df, feat_names = build_model_importance(base, target, candidate_features)
    except Exception as e:
        # If scikit-learn not installed or data degenerate, skip cleanly
        model_importance_df = pd.DataFrame(
            [{"feature_encoded": "N/A (model failed)", "importance_mean": 0.0, "importance_std": 0.0}]
        )

    model_importance_df.to_csv(os.path.join(args.outdir, "model_importance.csv"), index=False)

    # Quick per-feature level table for top categorical signals (to inspect actionable values)
    # Take the top few categorical features by median_range and dump their level stats
    per_feature_summaries = []
    for feat in cat_effects.head(8)["feature"].tolist():
        g = (
            base[[feat, target, "trades", "net", "win_rate"]]
            .groupby(feat)
            .agg(
                n=("trades","count"),
                trades_sum=("trades","sum"),
                pf_median=(target,"median"),
                pf_mean=(target,"mean"),
                net_sum=("net","sum"),
                win_rate_mean=("win_rate","mean"),
            )
            .sort_values("pf_median", ascending=False)
            .reset_index()
        )
        g.insert(0, "feature", feat)
        per_feature_summaries.append(g)
    if per_feature_summaries:
        per_feature = pd.concat(per_feature_summaries, ignore_index=True)
        per_feature.to_csv(os.path.join(args.outdir, "categorical_level_summaries.csv"), index=False)

    # Write a small Markdown report
    report_lines = []
    report_lines.append("# Sweep Analysis Report\n")
    report_lines.append(f"- Source file: `{args.file}`")
    report_lines.append(f"- Min trades: `{args.min_trades}`")
    report_lines.append(f"- Rows (finite PF & >= min trades): **{len(base):,}**\n")

    if not top.empty:
        best_row = top.iloc[0].to_dict()
        report_lines.append("## Best Finite Profit Factor Setup")
        report_lines.append(f"- Profit Factor: **{best_row['profit_factor']:.4f}**")
        report_lines.append(f"- Trades: **{int(best_row['trades'])}**")
        report_lines.append(f"- Win Rate: **{best_row['win_rate']:.3f}**")
        report_lines.append(f"- Net: **{best_row['net']:.2f}**\n")
        # Show a subset of key decision variables for quick glance
        keys_to_show = [
            "points_tp","points_sl","require_pullback_from_outside","require_directional_close",
            "require_prev_close_break","ifvg_internal_criterion","ifvg_overlap_min_ratio",
            "ifvg_allow_opposite_internal","ifvg_same_bar","ifvg_lookback_bars","ifvg_break_metric",
            "ifvg_allow_equal","bos_require_close_through","bos_allow_equal","skip_conflicting_fvgs",
            "ifvg_ignore_internal_conflict","entry_touch_type","allowed_time_buckets",
            "penetrated_midline","min_gap_taps","max_gap_taps","min_bars_to_prev_break",
            "max_bars_to_prev_break","gap_size_min_pts","gap_size_max_pts"
        ]
        keys_to_show = [k for k in keys_to_show if k in best_row]
        report_lines.append("**Key Params:**")
        for k in keys_to_show:
            report_lines.append(f"- {k}: `{best_row[k]}`")
        report_lines.append("")

    if not variable_effects.empty:
        top_fx = variable_effects.sort_values("value", ascending=False).head(12)
        report_lines.append("## Variables with Highest Apparent Influence")
        for _, r in top_fx.iterrows():
            report_lines.append(f"- {r['feature']} ({r['type']} – {r['metric']}): **{r['value']:.4f}**")
        report_lines.append("")

    if not model_importance_df.empty:
        report_lines.append("## Model (RF) Permutation Importance — Top Encoded Features")
        for _, r in model_importance_df.head(15).iterrows():
            report_lines.append(f"- {r['feature_encoded']}: **{r['importance_mean']:.6f}** (± {r['importance_std']:.6f})")
        report_lines.append("")

    with open(os.path.join(args.outdir, "report.md"), "w") as f:
        f.write("\n".join(report_lines))

    print(f"✅ Done. Outputs written to `{args.outdir}`:")
    print(" - top_setups.csv")
    print(" - variable_effects.csv (numeric correlations + categorical effect sizes)")
    print(" - categorical_level_summaries.csv (top categorical features by level)")
    print(" - model_importance.csv (RandomForest + permutation importance)")
    print(" - report.md (human-readable summary)")
    print("\nTip: Open report.md first, then inspect CSVs for detail. 🙌")

if __name__ == "__main__":
    main()
