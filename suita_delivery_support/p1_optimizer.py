"""Shared validation error for P1 optimization; v23.4 uses p1_full_constraints.

The earlier unconstrained single-commodity prototype was removed: it did not
include paper rev21 (25)-(26), (29)-(30) and could give misleading P1 results.
"""
class P1InputError(ValueError):
    pass
