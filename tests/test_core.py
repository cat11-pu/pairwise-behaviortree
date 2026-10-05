"""Behaviour tests for btree.core."""

import unittest

from btree.core import (
    Action,
    BehaviorTree,
    Blackboard,
    Cooldown,
    Inverter,
    RepeatUntilFail,
    Selector,
    Sequence,
    Status,
    Succeeder,
)


class Probe:
    """Callable leaf body that records every call and replays a status script.

    The last entry of the script is repeated once the script is exhausted.
    """

    def __init__(self, name, statuses, log):
        self.name = name
        self.statuses = list(statuses)
        self.log = log
        self.calls = 0

    def __call__(self, blackboard):
        self.calls += 1
        self.log.append(self.name)
        return self.statuses[min(self.calls - 1, len(self.statuses) - 1)]


def leaf(name, statuses, log):
    """Build a leaf node that writes its name into log on every tick."""
    return Action(Probe(name, statuses, log))


class SequenceTests(unittest.TestCase):
    def test_sequence_starts_over_after_failure(self):
        log = []
        tree = BehaviorTree(
            Sequence(
                [
                    leaf("a", [Status.SUCCESS], log),
                    leaf("b", [Status.FAILURE, Status.SUCCESS], log),
                ]
            )
        )

        self.assertIs(tree.tick(), Status.FAILURE)
        self.assertIs(tree.tick(), Status.SUCCESS)
        self.assertEqual(log, ["a", "b", "a", "b"])

        with self.assertRaises(ValueError):
            Sequence([])


class SelectorTests(unittest.TestCase):
    def test_selector_retries_the_running_child(self):
        log = []
        tree = BehaviorTree(
            Selector(
                [
                    leaf("slow", [Status.RUNNING, Status.RUNNING, Status.SUCCESS], log),
                    leaf("backup", [Status.SUCCESS], log),
                ]
            )
        )

        self.assertIs(tree.tick(), Status.RUNNING)
        self.assertIs(tree.tick(), Status.RUNNING)
        self.assertIs(tree.tick(), Status.SUCCESS)
        self.assertEqual(log, ["slow", "slow", "slow"])

    def test_selector_recovers_after_a_child_failure(self):
        log = []
        branch = Sequence(
            [
                leaf("good", [Status.SUCCESS], log),
                leaf("flaky", [Status.RUNNING, Status.FAILURE, Status.SUCCESS], log),
            ]
        )
        tree = BehaviorTree(Selector([branch, leaf("backup", [Status.SUCCESS], log)]))

        self.assertIs(tree.tick(), Status.RUNNING)
        self.assertEqual(log, ["good", "flaky"])

        self.assertIs(tree.tick(), Status.SUCCESS)
        self.assertEqual(log, ["good", "flaky", "flaky", "backup"])

        self.assertIs(tree.tick(), Status.SUCCESS)
        self.assertEqual(log, ["good", "flaky", "flaky", "backup", "good", "flaky"])


class DecoratorTests(unittest.TestCase):
    def test_decorators_map_and_forward_statuses(self):
        log = []
        probe = Probe(
            "probe", [Status.FAILURE, Status.SUCCESS, Status.RUNNING, Status.SUCCESS], log
        )
        inverter_tree = BehaviorTree(Inverter(Action(probe)))

        self.assertIs(inverter_tree.tick(), Status.SUCCESS)
        self.assertIs(inverter_tree.tick(), Status.FAILURE)
        self.assertIs(inverter_tree.tick(), Status.RUNNING)
        self.assertIs(inverter_tree.tick(), Status.FAILURE)
        self.assertEqual(log, ["probe", "probe", "probe", "probe"])

        other_log = []
        succeeder_tree = BehaviorTree(
            Succeeder(
                Action(Probe("child", [Status.FAILURE, Status.SUCCESS, Status.RUNNING], other_log))
            )
        )
        self.assertIs(succeeder_tree.tick(), Status.SUCCESS)
        self.assertIs(succeeder_tree.tick(), Status.SUCCESS)
        self.assertIs(succeeder_tree.tick(), Status.RUNNING)
        self.assertEqual(other_log, ["child", "child", "child"])

        bad_tree = BehaviorTree(Action(lambda blackboard: "nope"))
        with self.assertRaises(TypeError):
            bad_tree.tick()


class CooldownTests(unittest.TestCase):
    def test_cooldown_counts_ticks(self):
        log = []
        tree = BehaviorTree(Cooldown(leaf("work", [Status.SUCCESS], log), ticks=10))

        self.assertIs(tree.tick(), Status.SUCCESS)
        for _ in range(10):
            self.assertIs(tree.tick(), Status.FAILURE)
        self.assertIs(tree.tick(), Status.SUCCESS)

        self.assertEqual(log, ["work", "work"])
        self.assertEqual(tree.tick_count, 12)


class RepeatUntilFailTests(unittest.TestCase):
    def test_repeat_until_fail_keeps_the_running_child(self):
        log = []
        child = Sequence(
            [
                leaf("first", [Status.SUCCESS], log),
                leaf("second", [Status.RUNNING, Status.SUCCESS, Status.FAILURE], log),
            ]
        )
        tree = BehaviorTree(RepeatUntilFail(child))

        self.assertIs(tree.tick(), Status.RUNNING)
        self.assertIs(tree.tick(), Status.RUNNING)
        self.assertIs(tree.tick(), Status.SUCCESS)
        self.assertEqual(log, ["first", "second", "second", "first", "second"])


class BudgetTests(unittest.TestCase):
    def test_exhausted_budget_stops_the_tick(self):
        log = []
        tree = BehaviorTree(
            Sequence(
                [
                    leaf("a", [Status.SUCCESS], log),
                    leaf("b", [Status.FAILURE, Status.SUCCESS], log),
                ]
            ),
            tick_budget=1,
        )

        self.assertIs(tree.tick(), Status.RUNNING)
        self.assertEqual(log, ["a"])

        self.assertIs(tree.tick(), Status.FAILURE)
        self.assertEqual(log, ["a", "b"])

        self.assertIs(tree.tick(), Status.RUNNING)
        self.assertEqual(log, ["a", "b", "a"])


class BlackboardTests(unittest.TestCase):
    def test_scopes_do_not_share_data(self):
        blackboard = Blackboard()
        blackboard.set("hp", 10)

        left = blackboard.child("left")
        right = blackboard.child("right")
        self.assertIsNot(left, right)

        left.set("hp", 3)
        left.set("plan", "attack")

        self.assertEqual(blackboard.get("hp"), 10)
        self.assertEqual(left.get("hp"), 3)
        self.assertEqual(right.get("hp"), 10)
        self.assertIsNone(right.get("plan"))
        self.assertEqual(right.get("plan", "idle"), "idle")
        self.assertFalse(right.has("plan"))

        blackboard.set_global("round", 2)
        self.assertEqual(left.get("round"), 2)
        self.assertEqual(right.get("round"), 2)

        tree = BehaviorTree(Succeeder(Action(lambda blackboard: Status.SUCCESS)))
        first = tree.scope("patrol")
        second = tree.scope("guard")
        self.assertIsNot(first, second)
        first.set("target", 1)
        self.assertIsNone(second.get("target"))


class ResetTests(unittest.TestCase):
    def test_reset_clears_nested_state_and_blackboard(self):
        log = []
        branch = Sequence(
            [
                leaf("a", [Status.SUCCESS], log),
                leaf("b", [Status.RUNNING, Status.SUCCESS], log),
            ]
        )
        tree = BehaviorTree(Sequence([branch]))
        tree.blackboard.set("phase", 1)

        self.assertIs(tree.tick(), Status.RUNNING)
        self.assertEqual(log, ["a", "b"])

        tree.reset()

        self.assertIsNone(tree.blackboard.get("phase"))
        self.assertIs(tree.tick(), Status.SUCCESS)
        self.assertEqual(log, ["a", "b", "a", "b"])


if __name__ == "__main__":
    unittest.main()
