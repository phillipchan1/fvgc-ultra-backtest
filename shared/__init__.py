"""Primitives shared between fvgc/ and ifvg_reversal/.

Keep this package free of model-specific filters, constants, or state. Pure
functions and minimal dataclasses only. Both models import from here and
attach their own state on top.
"""
