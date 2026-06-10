"""Part 1 — unconditional base-rate catalog (the gems layer).

Every stat: n, 95% Wilson CI, null-model comparison (500 within-session
shuffles, part1_null.py), stationarity verdict (8 calendar years), and
WHEN/HOW-FAR distributions where applicable.

Outputs:
  results/part1_base_rates.csv     probability stats
  results/part1_distributions.csv  quantile tables (time-to-event, ranges)
Appends every probability row to results/test_ledger.csv.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from atlas_stats import (wilson, ledger_append, stationarity, null_verdict,
                         classify)

CACHE = HERE / "results/cache"
RESULTS = HERE / "results"

st = pd.read_parquet(CACHE / "session_table.parquet").reset_index(drop=True)
nz = np.load(CACHE / "null_summary.npz")
assert (st["date"].values.astype(np.int64) == nz["dates"]).all(), "order mismatch"
S = len(st)
R = int(nz["n_resamples"][0])
U, D = nz["U"], nz["D"]
years = st["year"]

rows = []
dist_rows = []


def band_from_acc(num_key, den_key=None):
    num = nz[f"acc_{num_key}"]
    den = nz[f"acc_{den_key}"] if den_key else np.full(R, S)
    p = num / np.where(den > 0, den, np.nan)
    return float(np.nanmean(p)), (float(np.nanpercentile(p, 2.5)),
                                  float(np.nanpercentile(p, 97.5)))


def band_from_indicator(ind):
    """ind: (n_subset, R) boolean → pooled per-resample mean band."""
    p = ind.mean(axis=0)
    return float(p.mean()), (float(np.percentile(p, 2.5)),
                             float(np.percentile(p, 97.5)))


def add(stat_id, section, label, success, valid, *, null=None, as_of="10:15",
        notes="", t_event=None):
    v = valid.fillna(False).astype(bool) if valid is not None else pd.Series(True, index=st.index)
    s = success.fillna(False).astype(bool) & v
    n, k = int(v.sum()), int(s.sum())
    p = k / n if n else np.nan
    lo, hi = wilson(k, n)
    if null is not None:
        nm, nb = null
        nv = null_verdict(p, nm, nb)
    else:
        nm, nb, nv = np.nan, (np.nan, np.nan), "NO_NULL"
    stv = stationarity(s, v, years)
    grade = classify(p, n, (lo, hi), nv, stv["verdict"])
    t_med = np.nan
    if t_event is not None:
        tt = t_event[s]
        t_med = float(np.median((tt - 34200) / 60.0)) if len(tt) else np.nan
    yearly_str = " ".join(f"{y}:{v[0]*100:.0f}%({v[1]})" if not np.isnan(v[0])
                          else f"{y}:-" for y, v in stv["yearly"].items())
    rows.append(dict(
        stat_id=stat_id, section=section, label=label, as_of=as_of,
        n=n, k=k, p_hat=round(p, 4) if n else np.nan,
        ci_lo=round(lo, 4), ci_hi=round(hi, 4),
        null_mean=round(nm, 4) if not np.isnan(nm) else np.nan,
        null_lo=round(nb[0], 4) if not np.isnan(nb[0]) else np.nan,
        null_hi=round(nb[1], 4) if not np.isnan(nb[1]) else np.nan,
        null_verdict=nv, stationarity=stv["verdict"],
        het_p=round(stv["het_p"], 4) if not np.isnan(stv["het_p"]) else np.nan,
        years_in_ci=f"{stv['in_ci']}/{stv['voted']}",
        p_recent3=round(stv["p_recent"], 4) if not np.isnan(stv["p_recent"]) else np.nan,
        grade=grade, t_median_min=round(t_med, 1) if not np.isnan(t_med) else np.nan,
        yearly=yearly_str, notes=notes))
    ledger_append(dict(test_id=stat_id, part=1, statistic=label,
                       conditioner="none", cell="all", as_of=as_of, n=n,
                       p_hat=round(p, 4), ci_lo=round(lo, 4), ci_hi=round(hi, 4),
                       marginal_p="", delta_pp="", p_value="", q_value="",
                       verdict=f"{nv}|{stv['verdict']}|{grade}", notes=notes))
    return p, n


T = pd.Series(True, index=st.index)

# ============================ A. Opening range ============================
for tag, nm in (("or5", "OR5 (9:30-9:35)"), ("or15", "OR15 (9:30-9:45)")):
    null_any = band_from_acc(f"{tag}_any")
    add(f"A_{tag}_any", "A_OR", f"{nm}: >=1 side taken by 10:15",
        st[f"{tag}_any_break"], T, null=null_any,
        t_event=st[f"{tag}_t_first"],
        notes="Phil's remembered 94% claim target" if tag == "or15" else "")
    null_both = band_from_acc(f"{tag}_both")
    add(f"A_{tag}_both", "A_OR", f"{nm}: BOTH sides taken by 10:15",
        st[f"{tag}_both_break"], T, null=null_both)

add("A_or15_any_touch", "A_OR",
    "OR15: >=1 side taken by 10:15 (>= touch-counts sensitivity)",
    st["or15_any_break_touch"], T,
    notes="sensitivity: touch-equal counts as taken (strict-break is canonical)")

add("A_or15_first_high", "A_OR", "OR15: first side taken = HIGH (given break)",
    st["or15_first_side"] == "high", st["or15_any_break"],
    null=band_from_acc("or15_first_high", "or15_break"))

add("A_or15_w2w3", "A_OR",
    "OR15: side taken within the 9:45/10:00 15m candles (Ryley framing)",
    st["or15_break_in_w2w3"], T,
    notes="identical to A_or15_any by construction (OR15 breaks cannot occur before 9:45)")
add("A_or5_w2w3", "A_OR",
    "OR5: first break falls within the 9:45/10:00 15m candles",
    st["or5_break_in_w2w3"], T,
    notes="OR5 can also break 9:35-9:45; this isolates Ryley's window")
for tag in ("or5", "or15"):
    add(f"A_{tag}_by1000", "A_OR", f"{tag.upper()}: >=1 side taken by 10:00",
        st[f"{tag}_break_by_1000"], T)

brk = st["or15_any_break"]
add("A_or15_retmid", "A_OR",
    "OR15: return to OR midpoint before 10:15 after first break",
    st["or15_ret_mid"] == True, brk,
    null=band_from_acc("or15_ret_mid", "or15_break"))
for X in (10, 20, 30, 50):
    add(f"A_or15_ext{X}", "A_OR",
        f"OR15: extension >= {X} pts beyond first-broken side (given break)",
        st[f"or15_ext_ge{X}"] == True, brk,
        null=band_from_acc(f"or15_ext{X}", "or15_break"))
add("A_or15_ext025atr", "A_OR",
    "OR15: extension >= 0.25 ATR beyond first-broken side (given break)",
    st["or15_ext_atr"] >= 0.25, brk,
    null=band_from_acc("or15_ext025atr", "or15_break"))

# time-to-first-break distributions
for tag in ("or5", "or15"):
    tt = (st.loc[st[f"{tag}_any_break"], f"{tag}_t_first"] - 34200) / 60.0
    qs = tt.quantile([.1, .25, .5, .75, .9]).round(1)
    dist_rows.append(dict(dist_id=f"D_{tag}_t_first",
                          label=f"{tag.upper()} minutes 9:30->first break",
                          n=len(tt),
                          q10=qs.iloc[0], q25=qs.iloc[1], q50=qs.iloc[2],
                          q75=qs.iloc[3], q90=qs.iloc[4],
                          null_q50=(round(float(np.nanmedian((nz['t_first15'] - 34200) / 60.0)), 1)
                                    if tag == "or15" else np.nan)))

# ====================== B. Named-level magnet stats ======================
BUCKETS = ["d00_10", "d10_25", "d25_50", "d50_100", "d100p"]
LEVELS = ["prev_day_high", "prev_day_low", "prev_close", "overnight_high",
          "overnight_low", "asia_high", "asia_low", "london_high",
          "london_low", "6am_high", "6am_low"]
O = st["open_930"].values

for lvl in LEVELS:
    price = st[f"lv_{lvl}_price"]
    untaken = st[f"lv_{lvl}_untaken"] == True
    touched = st[f"lv_{lvl}_touch_t"].notna()
    valid_all = untaken & price.notna()
    dist_pts = (price - st["open_930"]).abs().values
    above = (price.values >= O)
    for bucket in ["ALL"] + BUCKETS:
        v = valid_all if bucket == "ALL" else (valid_all & (st[f"lv_{lvl}_bucket"] == bucket))
        if v.sum() < 30:
            continue
        idx = np.flatnonzero(v.values)
        ind = np.where(above[idx, None], U[idx] >= dist_pts[idx, None],
                       D[idx] >= dist_pts[idx, None])
        nm, nb = band_from_indicator(ind)
        add(f"B_{lvl}_{bucket}", "B_magnet",
            f"{lvl} touched by 10:15 | untaken at 9:30, dist {bucket}",
            touched, v, null=(nm, nb), t_event=st[f"lv_{lvl}_touch_t"],
            notes=f"median dist {np.median(dist_pts[idx]):.0f} pts")

# PD extreme / ON extreme combined (T6/T7) — unconditional on untaken-ness
for key, hn, ln in (("pd_extreme", "prev_day_high", "prev_day_low"),
                    ("on_extreme", "overnight_high", "overnight_low")):
    th = st[f"lv_{hn}_touch_t"]; tl = st[f"lv_{ln}_touch_t"]
    v = st[f"lv_{hn}_price"].notna() & st[f"lv_{ln}_price"].notna()
    success = (th.notna() | tl.notna()) & v
    idx = np.flatnonzero(v.values)
    dh = (st[f"lv_{hn}_price"] - st["open_930"]).abs().values
    dl = (st[f"lv_{ln}_price"] - st["open_930"]).abs().values
    ah = (st[f"lv_{hn}_price"].values >= O); al = (st[f"lv_{ln}_price"].values >= O)
    ih = np.where(ah[idx, None], U[idx] >= dh[idx, None], D[idx] >= dh[idx, None])
    il = np.where(al[idx, None], U[idx] >= dl[idx, None], D[idx] >= dl[idx, None])
    nm, nb = band_from_indicator(ih | il)
    add(f"B_{key}_either", "B_magnet",
        f"{key}: high or low touched by 10:15 (any pre-RTH status)",
        success, v, null=(nm, nb))

# PD extreme by gap bucket (pre-registered in the brief's Part 1 list)
v_all = st["lv_prev_day_high_price"].notna() & st["lv_prev_day_low_price"].notna()
succ_pd = (st["lv_prev_day_high_touch_t"].notna()
           | st["lv_prev_day_low_touch_t"].notna())
for gb in ("flat", "small", "medium", "large"):
    add(f"B_pd_extreme_gap_{gb}", "B_magnet",
        f"pd_extreme touched by 10:15 | gap bucket {gb}",
        succ_pd, v_all & (st["gap_bucket"] == gb), as_of="9:30 conditioner")

# Ryley 6am claims — all variants
p6h, p6l = st["lv_6am_high_price"], st["lv_6am_low_price"]
v6 = p6h.notna() & p6l.notna()
pre_h = st["six_repo_h_preswept"] == True
pre_l = st["six_repo_l_preswept"] == True
rth_h = st["lv_6am_high_touch_t"]
rth_l = st["lv_6am_low_touch_t"]
add("B_ryley6_repo_incl_pre", "B_ryley6",
    "6am(repo 04-08h) H or L taken by 10:15 incl. pre-RTH 8:00-9:30 sweeps",
    (pre_h | rth_h.notna() | pre_l | rth_l.notna()), v6,
    notes="Ryley 97% claim, generous variant")
add("B_ryley6_repo_incl_pre_1000", "B_ryley6",
    "6am(repo) H or L taken by 10:00 incl. pre-RTH sweeps",
    (pre_h | (rth_h < 36000) | pre_l | (rth_l < 36000)), v6)
u6 = (st["lv_6am_high_untaken"] == True) | (st["lv_6am_low_untaken"] == True)
succ_u6 = (((st["lv_6am_high_untaken"] == True) & rth_h.notna())
           | ((st["lv_6am_low_untaken"] == True) & rth_l.notna()))
add("B_ryley6_repo_rth", "B_ryley6",
    "6am(repo): an untaken-at-9:30 side touched by 10:15 | >=1 side untaken",
    succ_u6, v6 & u6)
v62 = st["six2_high"].notna()
add("B_ryley6_lit", "B_ryley6",
    "6am-literal (06:00-9:30 H/L): H or L touched by 10:15",
    st["six2_h_touch_t"].notna() | st["six2_l_touch_t"].notna(), v62,
    notes="Ryley 97% claim, literal variant")
add("B_ryley6_lit_1000", "B_ryley6",
    "6am-literal: H or L touched by 10:00",
    (st["six2_h_touch_t"] < 36000) | (st["six2_l_touch_t"] < 36000), v62)

# nearest untaken draw (T8)
v8 = st["nearest_untaken_name"] != "none"
nm8 = np.nan
idx = np.flatnonzero(v8.values)
dist8 = (st["nearest_untaken_dist_atr"] * st["atr"]).values
above8 = np.array([st[f"lv_{n}_price"].iloc[i] >= O[i] if n != "none" else False
                   for i, n in zip(st.index, st["nearest_untaken_name"])])
ind8 = np.where(above8[idx, None], U[idx] >= dist8[idx, None],
                D[idx] >= dist8[idx, None])
nmean8, nband8 = band_from_indicator(ind8)
add("B_nearest_untaken", "B_magnet",
    "nearest untaken named draw touched by 10:15",
    st["nearest_untaken_touched"] == True, v8, null=(nmean8, nband8))

# ===================== C. Path shape & sequencing =====================
fs = st["first_sweep_name"].value_counts()
for name, cnt in fs.items():
    add(f"C_first_sweep_{name}", "C_firstsweep",
        f"first level swept in session = {name}",
        st["first_sweep_name"] == name, T,
        t_event=st["first_sweep_t"] if name != "none" else None,
        notes="categorical distribution share")

for hn, ln in [("prev_day_high", "prev_day_low"),
               ("overnight_high", "overnight_low"),
               ("asia_high", "asia_low"), ("london_high", "london_low"),
               ("6am_high", "6am_low")]:
    tag = hn.replace("_high", "").replace("prev_day", "pd")
    first = st[f"pp_{tag}_first"]
    opp = st[f"pp_{tag}_opposite"]
    for side in ("high", "low"):
        add(f"C_pp_{tag}_{side}", "C_pingpong",
            f"{tag}: opposite side also swept by 10:15 | {side} swept first (both untaken)",
            opp == True, first == side)

p, n = add("C_w1_match", "C_path",
           "W1 direction matches 9:30->10:15 net direction",
           st["w1_matches_net"] == True, st["w1_matches_net"].notna(),
           null=band_from_acc("w1_match", "w1_valid"))
add("C_w1_extreme_holds", "C_path",
    "W1 high or low remains the 10:15 extreme",
    st["w1_extreme_holds"], T,
    null=band_from_acc("w1_extreme_holds"))

bba = st["below_before_above"]
v_both = (st["nearest_above_name"] != "none") & (st["nearest_below_name"] != "none")
add("C_bba_all", "C_path",
    "nearest BELOW draw before nearest ABOVE draw (neither-touched counts as No)",
    bba == True, v_both)
add("C_bba_either", "C_path",
    "nearest BELOW before ABOVE | at least one side touched",
    bba == True, v_both & bba.notna(),
    null=band_from_acc("bba_below_first", "bba_valid"))

# ======================= D. Distribution tables =======================
for col, lab in (("net_range_atr", "9:30-10:15 range / ATR"),
                 ("mfe_atr", "MFE from open / ATR"),
                 ("mae_atr", "MAE from open / ATR"),
                 ("net_move_atr", "net move (close-open) / ATR")):
    qs = st[col].quantile([.1, .25, .5, .75, .9]).round(3)
    dist_rows.append(dict(dist_id=f"D_{col}", label=lab, n=S,
                          q10=qs.iloc[0], q25=qs.iloc[1], q50=qs.iloc[2],
                          q75=qs.iloc[3], q90=qs.iloc[4], null_q50=np.nan))
# null range check (vol preserved, path destroyed): mean (U+D)/ATR
null_range = float(((U + D) / st["atr"].values[:, None]).mean())
act_range = float(st["net_range_atr"].mean())
dist_rows.append(dict(dist_id="D_range_null", label="mean range/ATR actual vs null",
                      n=S, q10=np.nan, q25=np.nan, q50=act_range,
                      q75=np.nan, q90=np.nan, null_q50=round(null_range, 3)))

out = pd.DataFrame(rows)
out.to_csv(RESULTS / "part1_base_rates.csv", index=False)
pd.DataFrame(dist_rows).to_csv(RESULTS / "part1_distributions.csv", index=False)
print(f"wrote {len(out)} stats")
print("\n=== headline ===")
cols = ["stat_id", "n", "p_hat", "ci_lo", "ci_hi", "null_mean",
        "null_verdict", "stationarity", "grade"]
hl = out[out["stat_id"].isin([
    "A_or15_any", "A_or5_any", "A_or15_both", "A_or15_first_high",
    "A_or15_retmid", "A_or15_ext025atr", "B_pd_extreme_either",
    "B_on_extreme_either", "B_ryley6_repo_incl_pre", "B_ryley6_lit",
    "B_nearest_untaken", "C_w1_match", "C_w1_extreme_holds", "C_bba_either"])]
print(hl[cols].to_string(index=False))
print("\n=== grades ===")
print(out["grade"].value_counts())
