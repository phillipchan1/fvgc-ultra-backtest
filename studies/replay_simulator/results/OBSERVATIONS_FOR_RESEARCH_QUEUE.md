# Observations for the research queue — Track C

Per REPLAY_RULES.md §7 and program constraint #3: everything in this file is an
**untested hypothesis or unmodeled mechanic** noticed during the replay/film-room
work. Nothing here was acted on, nothing modifies the frozen rules, and nothing
carries statistical weight. Each item needs its own pre-registered study (or
forward data) before it can touch a playbook.

## From the replay / portfolio statistics (Part 1)

1. **Signal frequency may itself be the observable regime variable.** Signal
   frequency and WR moved together across eras: IS era 0.56 signals/month at 56.1%
   WR (n=41) vs recent era 1.58/month at 83.3% (n=42). Untested hypothesis: a
   trailing signal-density measure (e.g. benchmark signals in the last 60 sessions)
   predicts the WR regime, which would let sizing respond to regime without
   predicting price. Confound to control: this is 2 eras, i.e. effectively n=2
   regime observations — needs the rolling-window stability study already queued in
   Track A's FORWARD_TEST_PROTOCOL.md §A.
2. **Same-session double signals cluster losses.** The worst losing streak (4
   losses) came from two double-signal sessions (2021-01-27: two entries 30 seconds
   apart, both losses; 2021-02-03: two more). Tiebreak T-2 takes both, and the
   replay respects that. Untested question: per-session risk cap (one benchmark
   trade per day) — what does it do to the 8-yr distribution? (It changes the rules,
   so it is a new study, not an adjustment.)
3. **The 2018–2020 drought is a cohort-definition stress test.** From 2018-03-27 to
   2020-04-29 the play fired once. Any forward-test protocol that interprets "no
   signals for a year" as system failure will false-alarm; the historical base
   includes year-long droughts as normal behavior.

## From the account-survival Monte Carlo (Part 2)

4. **Locked-floor death zone.** Once the TPT PRO floor locks at $50,000, any
   balance in [$50,000, $50,000 + 1 stop's dollar risk] can be terminated by a
   single trade's intraday adverse excursion — including a trade that ultimately
   WINS (intraday trailing counts unrealized dips). Unmodeled mitigation: reduced
   size while balance is within one stop of the locked floor. This is a sizing-rule
   change → needs its own study before use.
5. **Half-sizing reallocates failure, it does not remove it.** $350 risk drops
   12-month termination to ~0–7% across regimes but also caps P(buffer in 12mo) at
   ~3–52%. A dynamic schedule (start at 0.5×, increase only after the floor locks)
   is the obvious untested compromise.

## From the pre-registered family (Part 3)

6. **T2 (stop beyond W1 extreme) is the one to re-watch.** It passed IS decisively
   (59.3% WR vs 49.3% base, n=199, q=0.017) and then failed the one-shot OOS look
   with the effect mildly reversed (49.2% vs 51.8% base, n=118). Under this
   program's rules it is dead. If 12+ months of forward data ever re-opens it, the
   question must be re-registered fresh — the OOS look here is spent.

## From the film room (Part 4)

7. **The not-quite set is dominated by protected_swing shorts and longs.** Of the
   20 most recent non-qualifying opening-window signals, the most common
   near-misses are PS-variant shorts (which the validated cohort excludes) and
   longs (where large-FVG longs are a validated ANTI-signal). Eye-training risk:
   the visual pattern is nearly identical at 9:31; only the variant tag and
   direction separate a validated trade from an excluded one. No new hypothesis —
   just the reason the film room exists.
