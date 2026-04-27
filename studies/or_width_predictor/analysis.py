"""Univariate quintile analysis for OR-width predictors.

For each candidate feature x and target y = or_45min_range:
  1. Spearman rank correlation (monotone strength)
  2. Bucket x into quintiles (or use raw categories for binary/categorical)
  3. Per-bucket: n, mean(y), median(y), P(y in global Q5 wide), P(y in global Q1 tight)
  4. Spread metric: (top_bucket_mean_y - bot_bucket_mean_y) / std(y)
  5. Monotonicity score: fraction of adjacent bucket pairs where mean(y) moves in
     the dominant direction (1.0 = perfectly monotonic, 0.5 = noise)
"""

from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def _quintile_buckets(s: pd.Series, n_buckets: int = 5) -> Optional[pd.Series]:
    """Cut into rank-based quantile bins. Returns None if not enough variance."""
    s = s.copy()
    if s.nunique(dropna=True) < n_buckets:
        return None
    try:
        return pd.qcut(s, q=n_buckets, labels=[f'Q{i+1}' for i in range(n_buckets)],
                       duplicates='drop')
    except ValueError:
        return None


def _category_buckets(s: pd.Series) -> pd.Series:
    """Treat as categorical (for binary flags / strings)."""
    return s.astype(str)


def analyse_feature(
    df: pd.DataFrame,
    feature: str,
    target: str = 'or_45min_range',
    treat_as: str = 'auto',
) -> tuple[dict, pd.DataFrame]:
    """Run the per-feature stat pack.

    Returns (summary_row, per_bucket_table).
    """
    sub = df[[feature, target]].dropna()
    n = len(sub)
    if n < 50:
        return ({'feature': feature, 'n': n, 'note': 'insufficient_n'}, pd.DataFrame())

    # Decide bucketing
    is_numeric = pd.api.types.is_numeric_dtype(sub[feature])
    is_binary_int = is_numeric and set(sub[feature].dropna().unique()).issubset({0, 1})
    if treat_as == 'auto':
        treat_as = 'category' if (not is_numeric or is_binary_int) else 'quintile'

    if treat_as == 'quintile':
        buckets = _quintile_buckets(sub[feature])
        if buckets is None:
            return ({'feature': feature, 'n': n, 'note': 'cannot_bucket'}, pd.DataFrame())
        sub = sub.assign(bucket=buckets)
    else:
        sub = sub.assign(bucket=_category_buckets(sub[feature]))

    # Global Q5/Q1 cutoffs on target
    y = sub[target]
    q1_cut = y.quantile(0.20)
    q5_cut = y.quantile(0.80)
    sub['_is_top'] = (y >= q5_cut).astype(int)
    sub['_is_bot'] = (y <= q1_cut).astype(int)

    table = (
        sub.groupby('bucket', observed=True)
        .agg(
            n=(target, 'size'),
            mean_or=(target, 'mean'),
            median_or=(target, 'median'),
            p_top_quintile=('_is_top', 'mean'),
            p_bot_quintile=('_is_bot', 'mean'),
        )
        .reset_index()
    )
    table['feature'] = feature

    # Spearman (numeric only)
    if is_numeric and not is_binary_int:
        rho, p = spearmanr(sub[feature], sub[target])
    else:
        rho, p = np.nan, np.nan

    # Spread = (max bucket mean - min bucket mean) / std(target)
    spread = (table['mean_or'].max() - table['mean_or'].min()) / y.std()

    # Monotonicity: fraction of adjacent bucket pairs moving in dominant direction
    # (only meaningful for ordered quintile bucketing)
    if treat_as == 'quintile':
        ordered = table.sort_values('bucket')
        diffs = ordered['mean_or'].diff().dropna()
        if len(diffs) > 0:
            up = (diffs > 0).sum()
            down = (diffs < 0).sum()
            mono = max(up, down) / len(diffs)
        else:
            mono = np.nan
    else:
        mono = np.nan

    summary = {
        'feature': feature,
        'n': n,
        'treatment': treat_as,
        'spearman_rho': rho,
        'spearman_p': p,
        'spread_z': spread,
        'monotonicity': mono,
        'top_bucket_mean_or': table['mean_or'].max(),
        'bot_bucket_mean_or': table['mean_or'].min(),
        'best_bucket_p_top': table['p_top_quintile'].max(),
        'worst_bucket_p_top': table['p_top_quintile'].min(),
    }
    return summary, table


def rank_features(
    df: pd.DataFrame,
    features: list[str],
    target: str = 'or_45min_range',
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries = []
    detail_frames = []
    for feat in features:
        if feat not in df.columns:
            summaries.append({'feature': feat, 'note': 'missing_column'})
            continue
        s, t = analyse_feature(df, feat, target=target)
        summaries.append(s)
        if not t.empty:
            detail_frames.append(t)

    summary_df = pd.DataFrame(summaries)
    # Score = combination of |rho| and spread, ignoring tiny samples
    if 'spearman_rho' in summary_df.columns:
        summary_df['abs_rho'] = summary_df['spearman_rho'].abs()
        summary_df['score'] = summary_df['abs_rho'].fillna(0) * 0.5 + \
            summary_df['spread_z'].fillna(0) * 0.5
        summary_df = summary_df.sort_values('score', ascending=False, na_position='last')
    detail_df = pd.concat(detail_frames, ignore_index=True) if detail_frames else pd.DataFrame()
    return summary_df, detail_df
