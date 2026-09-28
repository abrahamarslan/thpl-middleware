"""Nested-set maintenance for categories — the routine now lives in ``app.common.tree``.

Kept as a re-export so ``categories`` (and its tests) import from one stable path
while the other hierarchies (departments, team types, teams) share the same
tested implementation.
"""

from app.common.tree import TreeError, TreeNode, ancestors_of, recompute_bounds, subtree_of

__all__ = ["TreeError", "TreeNode", "ancestors_of", "recompute_bounds", "subtree_of"]
