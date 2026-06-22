# FILM ROOM — opening-window FVG short (benchmark play)

All 83 benchmark trades over 8 years (at ~10 signals/yr, a "trailing 60
days" film room would hold ~3 charts — so this is the full set), plus the 20 most
recent opening-window signals that did NOT qualify. Charts: 30s candles 9:15–10:30
ET, named levels, FVG zone shaded, entry/stop/target and outcome path marked. Side
panel lists the Part 3 factors (W1 direction, ON tercile, OR5 state at entry,
stop-vs-W1-extreme) so the film room doubles as visual context for the hypothesis
results — note W1 is usually NOT yet formed at these entries; it is context, not
entry-time information.

Regenerate any time with: `python3.13 studies/replay_simulator/run.py --film-room`

## Section 1 — Winners (58): what textbook looks like

- `charts/trade_01_2018-03-27_win.png` — 2018-03-27, short @ 6799.5, stop 20pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_02_2018-03-27_win.png` — 2018-03-27, short @ 6799.75, stop 20pt, WIN (+1.0R). W1 down, ON normal, OR5 broke_low, stop inside W1 extreme
- `charts/trade_03_2019-04-26_win.png` — 2019-04-26, short @ 7807.25, stop 15pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_07_2020-07-23_win.png` — 2020-07-23, short @ 10820.75, stop 20pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_08_2020-08-27_win.png` — 2020-08-27, short @ 11960.75, stop 50pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_09_2020-09-28_win.png` — 2020-09-28, short @ 11303.25, stop 40pt, WIN (+1.0R). W1 down, ON normal, OR5 broke_low, stop beyond W1 extreme
- `charts/trade_10_2020-10-13_win.png` — 2020-10-13, short @ 12107.75, stop 40pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_12_2021-01-04_win.png` — 2021-01-04, short @ 12911.0, stop 20pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_17_2021-03-05_win.png` — 2021-03-05, short @ 12547.5, stop 35pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_18_2021-03-10_win.png` — 2021-03-10, short @ 12935.25, stop 30pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_19_2021-09-17_win.png` — 2021-09-17, short @ 15445.0, stop 40pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_22_2021-10-15_win.png` — 2021-10-15, short @ 15069.5, stop 20pt, WIN (+1.0R). W1 down, ON compressed, OR5 inside, stop inside W1 extreme
- `charts/trade_23_2021-11-24_win.png` — 2021-11-24, short @ 16160.75, stop 35pt, WIN (+1.0R). W1 down, ON expanded, OR5 inside, stop inside W1 extreme
- `charts/trade_24_2021-12-01_win.png` — 2021-12-01, short @ 16301.5, stop 30pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_26_2021-12-08_win.png` — 2021-12-08, short @ 16298.5, stop 30pt, WIN (+1.0R). W1 down, ON normal, OR5 inside, stop inside W1 extreme
- `charts/trade_28_2022-01-04_win.png` — 2022-01-04, short @ 16486.0, stop 20pt, WIN (+1.0R). W1 down, ON compressed, OR5 forming, stop inside W1 extreme
- `charts/trade_29_2022-01-04_win.png` — 2022-01-04, short @ 16485.0, stop 20pt, WIN (+1.0R). W1 down, ON compressed, OR5 inside, stop inside W1 extreme
- `charts/trade_30_2022-02-16_win.png` — 2022-02-16, short @ 14484.5, stop 20pt, WIN (+1.0R). W1 down, ON compressed, OR5 inside, stop inside W1 extreme
- `charts/trade_33_2023-03-28_win.png` — 2023-03-28, short @ 12758.75, stop 15pt, WIN (+1.0R). W1 down, ON compressed, OR5 forming, stop inside W1 extreme
- `charts/trade_35_2023-06-16_win.png` — 2023-06-16, short @ 15432.5, stop 25pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_39_2023-09-22_win.png` — 2023-09-22, short @ 14919.25, stop 15pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_40_2023-10-31_win.png` — 2023-10-31, short @ 14393.75, stop 25pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_41_2023-12-01_win.png` — 2023-12-01, short @ 15916.5, stop 15pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_44_2024-03-05_win.png` — 2024-03-05, short @ 18101.0, stop 30pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_45_2024-04-15_win.png` — 2024-04-15, short @ 18297.5, stop 35pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_46_2024-04-15_win.png` — 2024-04-15, short @ 18278.0, stop 55pt, WIN (+1.0R). W1 down, ON expanded, OR5 broke_low, stop inside W1 extreme
- `charts/trade_48_2024-07-26_win.png` — 2024-07-26, short @ 19112.5, stop 45pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_49_2024-08-23_win.png` — 2024-08-23, short @ 19731.5, stop 15pt, WIN (+1.0R). W1 down, ON compressed, OR5 inside, stop inside W1 extreme
- `charts/trade_50_2024-09-16_win.png` — 2024-09-16, short @ 19634.75, stop 35pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_51_2024-10-17_win.png` — 2024-10-17, short @ 20531.5, stop 40pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_52_2024-10-24_win.png` — 2024-10-24, short @ 20335.75, stop 30pt, WIN (+1.0R). W1 down, ON normal, OR5 inside, stop inside W1 extreme
- `charts/trade_53_2024-10-28_win.png` — 2024-10-28, short @ 20578.75, stop 45pt, WIN (+1.0R). W1 down, ON normal, OR5 inside, stop inside W1 extreme
- `charts/trade_54_2024-11-27_win.png` — 2024-11-27, short @ 20864.25, stop 45pt, WIN (+1.0R). W1 down, ON compressed, OR5 inside, stop inside W1 extreme
- `charts/trade_55_2024-11-27_win.png` — 2024-11-27, short @ 20879.5, stop 30pt, WIN (+1.0R). W1 down, ON compressed, OR5 broke_low, stop inside W1 extreme
- `charts/trade_57_2025-01-16_win.png` — 2025-01-16, short @ 21450.5, stop 40pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_58_2025-02-21_win.png` — 2025-02-21, short @ 22146.25, stop 35pt, WIN (+1.0R). W1 down, ON normal, OR5 inside, stop inside W1 extreme
- `charts/trade_60_2025-03-18_win.png` — 2025-03-18, short @ 19861.25, stop 35pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_61_2025-05-16_win.png` — 2025-05-16, short @ 21418.0, stop 45pt, WIN (+1.0R). W1 down, ON compressed, OR5 inside, stop inside W1 extreme
- `charts/trade_62_2025-05-30_win.png` — 2025-05-30, short @ 21340.0, stop 40pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_63_2025-07-31_win.png` — 2025-07-31, short @ 23688.5, stop 30pt, WIN (+1.0R). W1 down, ON expanded, OR5 broke_low, stop inside W1 extreme
- `charts/trade_64_2025-07-31_win.png` — 2025-07-31, short @ 23677.75, stop 40pt, WIN (+1.0R). W1 down, ON expanded, OR5 broke_low, stop inside W1 extreme
- `charts/trade_66_2025-08-15_win.png` — 2025-08-15, short @ 23856.5, stop 50pt, WIN (+1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_67_2025-08-15_win.png` — 2025-08-15, short @ 23869.25, stop 40pt, WIN (+1.0R). W1 down, ON normal, OR5 inside, stop inside W1 extreme
- `charts/trade_68_2025-08-20_win.png` — 2025-08-20, short @ 23363.0, stop 45pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_69_2025-08-20_win.png` — 2025-08-20, short @ 23371.0, stop 35pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_70_2025-09-10_win.png` — 2025-09-10, short @ 23953.5, stop 45pt, WIN (+1.0R). W1 down, ON normal, OR5 inside, stop inside W1 extreme
- `charts/trade_71_2025-09-10_win.png` — 2025-09-10, short @ 23959.25, stop 35pt, WIN (+1.0R). W1 down, ON normal, OR5 broke_low, stop inside W1 extreme
- `charts/trade_72_2025-09-30_win.png` — 2025-09-30, short @ 24799.75, stop 15pt, WIN (+1.0R). W1 down, ON compressed, OR5 broke_low, stop inside W1 extreme
- `charts/trade_73_2025-10-02_win.png` — 2025-10-02, short @ 25137.25, stop 25pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_74_2025-10-06_win.png` — 2025-10-06, short @ 25177.25, stop 35pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_75_2025-10-15_win.png` — 2025-10-15, short @ 24967.75, stop 35pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_76_2025-10-15_win.png` — 2025-10-15, short @ 24958.75, stop 40pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_77_2025-10-30_win.png` — 2025-10-30, short @ 26068.25, stop 50pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_78_2025-11-07_win.png` — 2025-11-07, short @ 25051.5, stop 55pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_80_2026-01-22_win.png` — 2026-01-22, short @ 25676.75, stop 45pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_81_2026-02-26_win.png` — 2026-02-26, short @ 25304.25, stop 35pt, WIN (+1.0R). W1 down, ON compressed, OR5 forming, stop inside W1 extreme
- `charts/trade_82_2026-04-16_win.png` — 2026-04-16, short @ 26376.25, stop 50pt, WIN (+1.0R). W1 down, ON compressed, OR5 broke_low, stop inside W1 extreme
- `charts/trade_83_2026-05-15_win.png` — 2026-05-15, short @ 29246.75, stop 30pt, WIN (+1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme

## Section 2 — Losers (25): what a CORRECT trade that loses looks like

These are not mistakes. Every chart below is a rule-perfect entry that hit its stop.
At 56–83% WR depending on regime, 1-in-6 to 1-in-2 of correct trades lose; treating
them as system failure is how validated plays get abandoned mid-drawdown.

- `charts/trade_04_2020-04-29_loss.png` — 2020-04-29, short @ 8839.0, stop 15pt, LOSS (-1.0R). W1 up, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_05_2020-06-17_loss.png` — 2020-06-17, short @ 9983.75, stop 15pt, LOSS (-1.0R). W1 up, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_06_2020-06-19_loss.png` — 2020-06-19, short @ 10082.75, stop 15pt, LOSS (-1.0R). W1 down, ON normal, OR5 inside, stop inside W1 extreme
- `charts/trade_11_2020-12-22_loss.png` — 2020-12-22, short @ 12696.5, stop 20pt, LOSS (-1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_13_2021-01-27_loss.png` — 2021-01-27, short @ 13335.75, stop 35pt, LOSS (-1.0R). W1 down, ON expanded, OR5 broke_low, stop inside W1 extreme
- `charts/trade_14_2021-01-27_loss.png` — 2021-01-27, short @ 13331.0, stop 40pt, LOSS (-1.0R). W1 down, ON expanded, OR5 broke_low, stop inside W1 extreme
- `charts/trade_15_2021-02-03_loss.png` — 2021-02-03, short @ 13477.25, stop 55pt, LOSS (-1.0R). W1 down, ON normal, OR5 inside, stop inside W1 extreme
- `charts/trade_16_2021-02-03_loss.png` — 2021-02-03, short @ 13507.0, stop 25pt, LOSS (-1.0R). W1 down, ON normal, OR5 broke_low, stop inside W1 extreme
- `charts/trade_20_2021-09-21_loss.png` — 2021-09-21, short @ 15053.25, stop 30pt, LOSS (-1.0R). W1 down, ON expanded, OR5 inside, stop inside W1 extreme
- `charts/trade_21_2021-10-15_loss.png` — 2021-10-15, short @ 15051.25, stop 25pt, LOSS (-1.0R). W1 down, ON compressed, OR5 forming, stop inside W1 extreme
- `charts/trade_25_2021-12-01_loss.png` — 2021-12-01, short @ 16306.25, stop 25pt, LOSS (-1.0R). W1 down, ON expanded, OR5 broke_low, stop inside W1 extreme
- `charts/trade_27_2021-12-08_loss.png` — 2021-12-08, short @ 16299.75, stop 25pt, LOSS (-1.0R). W1 down, ON normal, OR5 broke_low, stop inside W1 extreme
- `charts/trade_31_2022-09-16_loss.png` — 2022-09-16, short @ 11814.75, stop 30pt, LOSS (-1.0R). W1 down, ON normal, OR5 inside, stop inside W1 extreme
- `charts/trade_32_2023-01-04_loss.png` — 2023-01-04, short @ 11006.5, stop 20pt, LOSS (-1.0R). W1 down, ON compressed, OR5 inside, stop inside W1 extreme
- `charts/trade_34_2023-05-04_loss.png` — 2023-05-04, short @ 13047.5, stop 30pt, LOSS (-1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_36_2023-08-11_loss.png` — 2023-08-11, short @ 15068.0, stop 20pt, LOSS (-1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme
- `charts/trade_37_2023-08-22_loss.png` — 2023-08-22, short @ 15065.0, stop 20pt, LOSS (-1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_38_2023-08-28_loss.png` — 2023-08-28, short @ 15065.5, stop 30pt, LOSS (-1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_42_2024-03-04_loss.png` — 2024-03-04, short @ 18289.25, stop 35pt, LOSS (-1.0R). W1 down, ON compressed, OR5 forming, stop inside W1 extreme
- `charts/trade_43_2024-03-04_loss.png` — 2024-03-04, short @ 18312.0, stop 15pt, LOSS (-1.0R). W1 down, ON compressed, OR5 inside, stop inside W1 extreme
- `charts/trade_47_2024-06-07_loss.png` — 2024-06-07, short @ 19013.75, stop 25pt, LOSS (-1.0R). W1 down, ON expanded, OR5 inside, stop inside W1 extreme
- `charts/trade_56_2024-12-12_loss.png` — 2024-12-12, short @ 21671.25, stop 20pt, LOSS (-1.0R). W1 down, ON normal, OR5 forming, stop inside W1 extreme
- `charts/trade_59_2025-03-06_loss.png` — 2025-03-06, short @ 20255.0, stop 50pt, LOSS (-1.0R). W1 down, ON expanded, OR5 inside, stop inside W1 extreme
- `charts/trade_65_2025-08-05_loss.png` — 2025-08-05, short @ 23309.75, stop 35pt, LOSS (-1.0R). W1 up, ON compressed, OR5 forming, stop inside W1 extreme
- `charts/trade_79_2025-12-11_loss.png` — 2025-12-11, short @ 25583.25, stop 25pt, LOSS (-1.0R). W1 down, ON expanded, OR5 forming, stop inside W1 extreme

## Section 3 — Almost-but-not-quite (20 most recent non-qualifying opening-window signals)

What fires the pattern-recognition but fails the cohort definition. Knowing these
cold is what keeps the live count at ~10/yr instead of 50/yr.

- `charts/nottraded_01_2026-01-02.png` — 2026-01-02, long, variant=bos, outcome=loss — fails cohort because: long (benchmark is shorts only)
- `charts/nottraded_02_2026-01-09.png` — 2026-01-09, short, variant=protected_swing, outcome=loss — fails cohort because: protected_swing variant
- `charts/nottraded_03_2026-01-15.png` — 2026-01-15, short, variant=protected_swing, outcome=win — fails cohort because: protected_swing variant
- `charts/nottraded_04_2026-01-22.png` — 2026-01-22, short, variant=protected_swing, outcome=win — fails cohort because: protected_swing variant
- `charts/nottraded_05_2026-01-22.png` — 2026-01-22, short, variant=no_fvg, outcome=skip — fails cohort because: not tradeable (skip)
- `charts/nottraded_06_2026-02-02.png` — 2026-02-02, long, variant=bos, outcome=skip — fails cohort because: long (benchmark is shorts only)
- `charts/nottraded_07_2026-02-02.png` — 2026-02-02, long, variant=protected_swing, outcome=win — fails cohort because: long (benchmark is shorts only)
- `charts/nottraded_08_2026-02-05.png` — 2026-02-05, short, variant=bos, outcome=skip — fails cohort because: not tradeable (skip)
- `charts/nottraded_09_2026-03-04.png` — 2026-03-04, long, variant=protected_swing, outcome=win — fails cohort because: long (benchmark is shorts only)
- `charts/nottraded_10_2026-03-04.png` — 2026-03-04, long, variant=protected_swing, outcome=win — fails cohort because: long (benchmark is shorts only)
- `charts/nottraded_11_2026-03-10.png` — 2026-03-10, long, variant=no_fvg, outcome=skip — fails cohort because: long (benchmark is shorts only)
- `charts/nottraded_12_2026-03-11.png` — 2026-03-11, long, variant=bos, outcome=loss — fails cohort because: long (benchmark is shorts only)
- `charts/nottraded_13_2026-03-19.png` — 2026-03-19, short, variant=no_fvg, outcome=skip — fails cohort because: not tradeable (skip)
- `charts/nottraded_14_2026-03-20.png` — 2026-03-20, short, variant=protected_swing, outcome=win — fails cohort because: protected_swing variant
- `charts/nottraded_15_2026-04-02.png` — 2026-04-02, long, variant=no_fvg, outcome=loss — fails cohort because: long (benchmark is shorts only)
- `charts/nottraded_16_2026-04-16.png` — 2026-04-16, short, variant=ifvg, outcome=skip — fails cohort because: not tradeable (skip)
- `charts/nottraded_17_2026-04-23.png` — 2026-04-23, short, variant=protected_swing, outcome=loss — fails cohort because: protected_swing variant
- `charts/nottraded_18_2026-04-29.png` — 2026-04-29, short, variant=protected_swing, outcome=loss — fails cohort because: protected_swing variant
- `charts/nottraded_19_2026-05-11.png` — 2026-05-11, long, variant=ifvg, outcome=loss — fails cohort because: long (benchmark is shorts only)
- `charts/nottraded_20_2026-05-15.png` — 2026-05-15, short, variant=no_fvg, outcome=skip — fails cohort because: not tradeable (skip)

## Section 4 — Self-quiz (10 charts, side panels stripped, truncated at entry)

Charts show everything known AT entry (bars to entry, levels, FVG, entry/stop/target)
and nothing after. Call each one, then check below.

- Q1: `charts/quiz/q01.png` — 2020-07-23, chart truncated at entry; call WIN or LOSS before checking.
- Q2: `charts/quiz/q02.png` — 2020-08-27, chart truncated at entry; call WIN or LOSS before checking.
- Q3: `charts/quiz/q03.png` — 2021-03-05, chart truncated at entry; call WIN or LOSS before checking.
- Q4: `charts/quiz/q04.png` — 2023-05-04, chart truncated at entry; call WIN or LOSS before checking.
- Q5: `charts/quiz/q05.png` — 2024-09-16, chart truncated at entry; call WIN or LOSS before checking.
- Q6: `charts/quiz/q06.png` — 2025-01-16, chart truncated at entry; call WIN or LOSS before checking.
- Q7: `charts/quiz/q07.png` — 2025-03-06, chart truncated at entry; call WIN or LOSS before checking.
- Q8: `charts/quiz/q08.png` — 2025-08-20, chart truncated at entry; call WIN or LOSS before checking.
- Q9: `charts/quiz/q09.png` — 2025-11-07, chart truncated at entry; call WIN or LOSS before checking.
- Q10: `charts/quiz/q10.png` — 2026-01-22, chart truncated at entry; call WIN or LOSS before checking.

### Answers

- Q1: **WIN** (+1.0R)
- Q2: **WIN** (+1.0R)
- Q3: **WIN** (+1.0R)
- Q4: **LOSS** (-1.0R)
- Q5: **WIN** (+1.0R)
- Q6: **WIN** (+1.0R)
- Q7: **LOSS** (-1.0R)
- Q8: **WIN** (+1.0R)
- Q9: **WIN** (+1.0R)
- Q10: **WIN** (+1.0R)

---
Charts skipped for missing bars: (none)
