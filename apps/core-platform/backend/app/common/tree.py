"""Nested-set / path / depth maintenance — pure functions, no I/O.

Shared by every hierarchy that keeps ``_lft`` / ``_rgt`` / ``depth`` / ``path``:
categories, and the teams module's departments, team types and teams. One
routine owns a tree's bounds. ``recompute_bounds`` is the ONLY writer of
``_lft`` / ``_rgt`` / ``depth`` / ``path`` / ``is_root``: a full recompute under
a per-tree advisory lock in the owning ``service.py`` is provably correct where
incremental bound shifts are not, and these trees are small.
``can_have_children`` (categories) is deliberately NOT recomputed — it is a
service-set flag the database guard reads.

The functions operate on anything with the attributes below (ORM rows or a
test dataclass), which is what makes them hermetically unit-testable.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol


class TreeNode(Protocol):
    id: int
    parent_id: int | None
    slug: str | None
    position: int | None
    depth: int
    lft: int
    rgt: int
    path: str | None
    is_root: bool


class TreeError(ValueError):
    """The node set is not a forest (duplicate ids or a cycle)."""


def _children_map(rows: Sequence[TreeNode]) -> dict[int | None, list[TreeNode]]:
    by_id = {row.id for row in rows}
    children: dict[int | None, list[TreeNode]] = defaultdict(list)
    for row in rows:
        # A parent that is absent (soft-deleted) degrades the node to a root
        # rather than silently dropping it from the tree.
        parent = row.parent_id if row.parent_id in by_id else None
        children[parent].append(row)
    for kids in children.values():
        kids.sort(key=lambda row: (row.position or 0, row.id))
    return children


def recompute_bounds(nodes: Sequence[TreeNode]) -> list[TreeNode]:
    """Assign bounds/depth/path in place; return the nodes in pre-order.

    Raises ``TreeError`` on duplicate ids or a cycle. The caller holds the
    per-taxonomy advisory lock, so no two recomputes race. A node whose parent
    is absent from ``nodes`` (soft-deleted) is laid out as a root but keeps its
    ``parent_id`` and gets ``is_root = False``.
    """
    rows = list(nodes)
    ids = {row.id for row in rows}
    if len(ids) != len(rows):
        raise TreeError("duplicate node ids in one tree")

    children = _children_map(rows)
    ordered: list[TreeNode] = []
    visited: set[int] = set()
    counter = 0

    # Explicit stack (state 0 = enter, 1 = exit) so a deep tree cannot blow the
    # Python recursion limit.
    stack: list[tuple[TreeNode, int, str, int]] = [
        (root, 0, "/", 0) for root in reversed(children.get(None, []))
    ]
    while stack:
        node, depth, parent_path, state = stack.pop()
        if state == 1:
            counter += 1
            node.rgt = counter
            continue
        if node.id in visited:
            raise TreeError(f"cycle detected at node {node.id}")
        visited.add(node.id)
        counter += 1
        node.lft = counter
        node.depth = depth
        key = node.slug or str(node.id)
        node.path = f"{parent_path}{key}/"
        # ``is_root`` is a fact about ``parent_id``, not about the live set: a
        # node whose parent was soft-deleted (a Zoho tombstone, say) is laid
        # out as a root above, but still HAS a parent_id, and
        # ck_categories_root_no_parent forbids the two together.
        node.is_root = node.parent_id is None
        ordered.append(node)
        stack.append((node, depth, parent_path, 1))
        for kid in reversed(children.get(node.id, [])):
            stack.append((kid, depth + 1, node.path, 0))

    if len(visited) != len(rows):
        raise TreeError("the node set contains a cycle")
    return ordered


def ancestors_of(nodes: Sequence[TreeNode], node: TreeNode) -> list[TreeNode]:
    """Root → parent, excluding ``node`` itself."""
    by_id = {row.id: row for row in nodes}
    chain: list[TreeNode] = []
    seen = {node.id}
    parent_id = node.parent_id
    while parent_id is not None and parent_id in by_id and parent_id not in seen:
        parent = by_id[parent_id]
        chain.append(parent)
        seen.add(parent.id)
        parent_id = parent.parent_id
    chain.reverse()
    return chain


def subtree_of(nodes: Sequence[TreeNode], node: TreeNode, *, include_self: bool = True) -> list[TreeNode]:
    """``node`` and its descendants, pre-order."""
    children = _children_map(nodes)
    out: list[TreeNode] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current is not node or include_self:
            out.append(current)
        stack.extend(reversed(children.get(current.id, [])))
    return out


__all__ = ["TreeError", "TreeNode", "ancestors_of", "recompute_bounds", "subtree_of"]
