"""fvgc.context — point-in-time market-state snapshots for confluence research.

Additive layer on top of the frozen FVGC v2.0.5 model. Nothing in here touches
signal generation or trade simulation. Built for the Confluence Framework
program (studies/confluence_framework/) and designed for reuse by the
NQ-VP-Lab session-state tagger.

Causality contract: every feature emitted by this package is computable from
data strictly at or before the trade's entry timestamp. Each feature group in
snapshot.py carries a one-line point-in-time justification.
"""
