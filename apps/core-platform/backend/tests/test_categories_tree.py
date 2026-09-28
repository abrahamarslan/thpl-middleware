"""Hermetic unit tests for the pure nested-set routines (no DB)."""

from dataclasses import dataclass

import pytest

from app.modules.categories.tree import (
    TreeError,
    ancestors_of,
    recompute_bounds,
    subtree_of,
)


@dataclass
class Node:
    id: int
    parent_id: int | None = None
    slug: str | None = None
    position: int = 0
    depth: int = 0
    lft: int = 0
    rgt: int = 0
    path: str | None = None
    is_root: bool = False


def _forest():
    # root -> [a -> a1, a2], b
    return [
        Node(1, None, "root", 0),
        Node(2, 1, "a", 0),
        Node(3, 2, "a1", 0),
        Node(4, 1, "a2", 1),
        Node(5, None, "b", 1),
    ]


def test_recompute_bounds_assigns_nested_set():
    nodes = _forest()
    ordered = recompute_bounds(nodes)
    by_id = {n.id: n for n in nodes}

    assert [n.id for n in ordered] == [1, 2, 3, 4, 5]
    assert by_id[1].lft == 1 and by_id[1].rgt == 8
    assert by_id[2].lft == 2 and by_id[2].rgt == 5
    assert by_id[3].lft == 3 and by_id[3].rgt == 4
    assert by_id[4].lft == 6 and by_id[4].rgt == 7
    assert by_id[5].lft == 9 and by_id[5].rgt == 10


def test_recompute_bounds_depth_path_and_root_flag():
    nodes = _forest()
    recompute_bounds(nodes)
    by_id = {n.id: n for n in nodes}

    assert by_id[1].depth == 0 and by_id[1].path == "/root/"
    assert by_id[2].depth == 1 and by_id[2].path == "/root/a/"
    assert by_id[3].depth == 2 and by_id[3].path == "/root/a/a1/"
    assert by_id[1].is_root and by_id[5].is_root
    assert not by_id[2].is_root


def test_children_ordered_by_position():
    nodes = _forest()
    recompute_bounds(nodes)
    by_id = {n.id: n for n in nodes}
    # a2 (position 1) comes after a1's subtree but the bracket layout follows position
    assert by_id[4].lft == 6


def test_cycle_raises():
    nodes = [
        Node(1, 2, "one", 0),
        Node(2, 1, "two", 0),
    ]
    with pytest.raises(TreeError):
        recompute_bounds(nodes)


def test_duplicate_ids_raise():
    with pytest.raises(TreeError):
        recompute_bounds([Node(1, None, "a"), Node(1, None, "b")])


def test_ancestors_and_subtree():
    nodes = _forest()
    recompute_bounds(nodes)
    by_id = {n.id: n for n in nodes}

    assert [a.id for a in ancestors_of(nodes, by_id[3])] == [1, 2]
    assert [n.id for n in subtree_of(nodes, by_id[2])] == [2, 3]
    assert [n.id for n in subtree_of(nodes, by_id[5])] == [5]
    assert [n.id for n in subtree_of(nodes, by_id[2], include_self=False)] == [3]
