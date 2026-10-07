"""Behaviour-tree runtime built on the Python standard library only.

The module offers a small set of leaves, composites and decorators plus a
hierarchical blackboard and a per-tick execution budget.
"""

from __future__ import annotations

from enum import Enum


class Status(Enum):
    """Outcome of a single node tick."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RUNNING = "RUNNING"


class Blackboard:
    """Hierarchical key/value store.

    A scope reads the keys of its ancestors. Writes stay in the scope that
    performs them, unless set_global is used.
    """

    def __init__(self, parent=None, name=None):
        self.parent = parent
        self.name = name
        self._data = {}

    def child(self, name=None):
        """Return a nested scope."""
        return Blackboard(parent=self, name=name)

    def set(self, key, value):
        """Store a key in this scope."""
        self._data[key] = value

    def set_global(self, key, value):
        """Store a key in the outermost scope."""
        scope = self
        while scope.parent is not None:
            scope = scope.parent
        scope._data[key] = value

    def get(self, key, default=None):
        """Read a key from this scope or from the closest ancestor holding it."""
        scope = self
        while scope is not None:
            if key in scope._data:
                return scope._data[key]
            scope = scope.parent
        return default

    def has(self, key):
        """Tell whether this scope or one of its ancestors holds the key."""
        scope = self
        while scope is not None:
            if key in scope._data:
                return True
            scope = scope.parent
        return False

    def clear(self):
        """Drop every key held by this scope."""
        self._data.clear()


class TickContext:
    """State carried through a single tick of a tree."""

    def __init__(self, blackboard, budget=None):
        self.blackboard = blackboard
        self.budget = budget
        self.used = 0
        self.exhausted = False

    def consume(self):
        """Reserve one leaf execution for this tick."""
        if self.budget is None:
            self.used += 1
            return True
        if self.used >= self.budget:
            self.exhausted = True
            return False
        self.used += 1
        return True


class Node:
    """Base class of every node in a tree."""

    def __init__(self, name=None):
        self.name = name or type(self).__name__

    def tick(self, ctx):
        raise NotImplementedError

    def reset(self):
        """Drop the state this node keeps between ticks."""


class Action(Node):
    """Leaf node backed by a callable.

    The callable receives the tick blackboard and returns a Status, or a bool
    that is mapped to SUCCESS/FAILURE.
    """

    def __init__(self, fn, name=None):
        super().__init__(name)
        if not callable(fn):
            raise TypeError("action needs a callable")
        self.fn = fn

    def tick(self, ctx):
        if not ctx.consume():
            return Status.RUNNING
        result = self.fn(ctx.blackboard)
        if isinstance(result, Status):
            return result
        if isinstance(result, bool):
            return Status.SUCCESS if result else Status.FAILURE
        raise TypeError(
            "action callable must return a Status or a bool, got %s" % type(result).__name__
        )


class Composite(Node):
    """Base class of the nodes that own an ordered list of children."""

    def __init__(self, children, name=None):
        super().__init__(name)
        self.children = list(children)
        if not self.children:
            raise ValueError("a composite needs at least one child")
        self._index = 0

    def reset(self):
        self._index = 0
        for child in self.children:
            child.reset()


class Sequence(Composite):
    """Ticks its children in order until one of them does not succeed."""

    def tick(self, ctx):
        while self._index < len(self.children):
            status = self.children[self._index].tick(ctx)
            if status is Status.SUCCESS:
                self._index += 1
            elif status is Status.RUNNING:
                return Status.RUNNING
            else:
                self._index = 0
                return Status.FAILURE
        self._index = 0
        return Status.SUCCESS


class Selector(Composite):
    """Ticks its children in order until one of them succeeds."""

    def tick(self, ctx):
        while self._index < len(self.children):
            status = self.children[self._index].tick(ctx)
            if status is Status.SUCCESS:
                self._index = 0
                return Status.SUCCESS
            if status is Status.RUNNING:
                return Status.RUNNING
            self._index += 1
        self._index = 0
        return Status.FAILURE


class Decorator(Node):
    """Base class of the nodes that wrap exactly one child."""

    def __init__(self, child, name=None):
        super().__init__(name)
        self.child = child

    def reset(self):
        self.child.reset()


class Inverter(Decorator):
    """Flips the outcome of its child."""

    def tick(self, ctx):
        status = self.child.tick(ctx)
        if status is Status.RUNNING:
            return Status.RUNNING
        if status is Status.SUCCESS:
            return Status.FAILURE
        return Status.SUCCESS


class Succeeder(Decorator):
    """Runs its child and reports success whenever the child is not running."""

    def tick(self, ctx):
        status = self.child.tick(ctx)
        if status is Status.RUNNING:
            return Status.RUNNING
        return Status.SUCCESS


class RepeatUntilFail(Decorator):
    """Ticks its child over and over until the child fails."""

    def tick(self, ctx):
        status = self.child.tick(ctx)
        if status is Status.FAILURE:
            self.child.reset()
            return Status.SUCCESS
        if status is Status.SUCCESS:
            self.child.reset()
        return Status.RUNNING


class Cooldown(Decorator):
    """Runs its child at most once every few ticks."""

    def __init__(self, child, ticks=1, name=None):
        super().__init__(child, name)
        if ticks < 0:
            raise ValueError("ticks must not be negative")
        self.ticks = ticks
        self._remaining = 0

    def tick(self, ctx):
        if self._remaining > 0:
            self._remaining -= 1
            return Status.FAILURE
        status = self.child.tick(ctx)
        if status is not Status.RUNNING:
            self._remaining = self.ticks
        return status

    def reset(self):
        self._remaining = 0
        super().reset()


class BehaviorTree:
    """A root node together with the blackboard its nodes share."""

    def __init__(self, root, blackboard=None, tick_budget=None):
        self.root = root
        self.blackboard = blackboard if blackboard is not None else Blackboard(name="root")
        self.tick_budget = tick_budget
        self.tick_count = 0
        self.last_status = None

    def scope(self, name=None):
        """Return a fresh child scope of the tree blackboard."""
        return self.blackboard.child(name)

    def tick(self):
        """Tick the root once and return its status."""
        ctx = TickContext(self.blackboard, budget=self.tick_budget)
        status = self.root.tick(ctx)
        self.tick_count += 1
        self.last_status = status
        return status

    def reset(self):
        """Clear the blackboard and the state kept by every node."""
        self.blackboard.clear()
        self.root.reset()
        self.last_status = None
