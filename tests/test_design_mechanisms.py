"""Small deterministic teaching models, NOT upstream Agent runtime tests.

These models test stated counterexamples under explicit simplifying assumptions.
They do not use a model API, execute shell tools, or implement an OS sandbox.
"""
from __future__ import annotations
import heapq
import unittest
from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduleResult:
    completed: tuple[int, ...]
    committed: tuple[int, ...]
    max_running: int
    max_pending_results: int
    finish_time: int


def schedule(durations: list[int], width: int, outstanding_limit: int | None = None) -> ScheduleResult:
    """Model body execution with ordered commits; no hooks, I/O, or cancellation.

    pending_results counts completed-but-uncommitted results, not total memory.
    This is independently authored and is not a translation of DSH source.
    """
    if width < 1 or any(d < 1 for d in durations):
        raise ValueError('positive width and durations required')
    if outstanding_limit is not None and outstanding_limit < 1:
        raise ValueError('positive outstanding limit required')
    running: list[tuple[int, int]] = []
    ready: set[int] = set()
    completed: list[int] = []
    committed: list[int] = []
    next_start = next_commit = now = peak_running = peak_ready = 0
    while next_commit < len(durations):
        while next_start < len(durations) and len(running) < width:
            if outstanding_limit is not None and next_start - next_commit >= outstanding_limit:
                break
            heapq.heappush(running, (now + durations[next_start], next_start))
            next_start += 1
            peak_running = max(peak_running, len(running))
        if not running:
            raise AssertionError('model made no progress')
        now, index = heapq.heappop(running)
        completed.append(index)
        ready.add(index)
        while next_commit in ready:
            ready.remove(next_commit)
            committed.append(next_commit)
            next_commit += 1
        peak_ready = max(peak_ready, len(ready))
    return ScheduleResult(tuple(completed), tuple(committed), peak_running, peak_ready, now)


def post_drain_arrival(keep_doorbell: bool) -> tuple[bool, int]:
    """One chosen interleaving, not an exhaustive coordinator model."""
    busy = True
    queued = 0
    queued += 1
    pending_wake = keep_doorbell if busy else False
    busy = False
    if pending_wake:
        busy = True
        queued -= 1
        busy = False
    return busy, queued


class IndependentFeed:
    """Synchronous finite queues; deliberately no HTTP or byte accounting."""
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.queues: dict[str, list[str]] = {'slow': [], 'fast': []}
        self.failed: set[str] = set()
    def offer(self, value: str) -> None:
        for name, queue in self.queues.items():
            if name in self.failed:
                continue
            if len(queue) >= self.capacity:
                self.failed.add(name)
            else:
                queue.append(value)
    def drain(self, name: str) -> list[str]:
        values = self.queues[name][:]
        self.queues[name].clear()
        return values


class MechanismModels(unittest.TestCase):
    def test_completion_and_commit_are_different_orders(self):
        result = schedule([10, 1, 1], 2)
        self.assertEqual(result.completed, (1, 2, 0))
        self.assertEqual(result.committed, (0, 1, 2))

    def test_running_limit_does_not_bound_pending_results(self):
        result = schedule([100] + [1] * 6, 2)
        self.assertEqual(result.max_running, 2)
        self.assertEqual(result.max_pending_results, 6)

    def test_uncommitted_window_bounds_pending_but_delays_refill(self):
        rolling = schedule([100] + [1] * 6, 2)
        bounded = schedule([100] + [1] * 6, 2, outstanding_limit=2)
        self.assertLessEqual(bounded.max_pending_results, 1)
        self.assertGreater(bounded.finish_time, rolling.finish_time)

    def test_both_logged_orders_can_be_replayed(self):
        for recorded in [(0, 1, 2), (1, 2, 0)]:
            self.assertEqual(tuple(list(recorded)), recorded)

    def test_invalid_schedule_parameters_are_rejected(self):
        for durations, width in [([1], 0), ([0], 1), ([-1], 2)]:
            with self.assertRaises(ValueError):
                schedule(durations, width)

    def test_incremental_projection_is_not_total_snapshot_cost(self):
        n = 100
        projected = sum(1 for _ in range(n))
        copied_references = sum(range(1, n + 1))
        self.assertEqual(projected, 100)
        self.assertEqual(copied_references, 5050)

    def test_request_snapshot_survives_registry_change(self):
        registry = {'tool': 'v1'}
        captured = registry.copy()
        registry['tool'] = 'v2'
        self.assertEqual(captured['tool'], 'v1')
        self.assertEqual(registry['tool'], 'v2')

    def test_schema_snapshot_does_not_imply_current_authorization(self):
        captured_tool = 'v1'
        currently_allowed = False
        self.assertEqual(captured_tool, 'v1')
        self.assertFalse(currently_allowed)

    def test_old_lifecycle_cannot_own_reused_id(self):
        old, new = object(), object()
        registry = {'same-id': new}
        self.assertIsNot(registry['same-id'], old)

    def test_old_goal_revision_cannot_pause_new_revision(self):
        old_callback = ('goal', 3)
        resumed_goal = ('goal', 4)
        self.assertNotEqual(old_callback, resumed_goal)

    def test_busy_flag_alone_can_lose_wakeup(self):
        self.assertEqual(post_drain_arrival(False), (False, 1))

    def test_doorbell_preserves_chosen_late_wakeup(self):
        self.assertEqual(post_drain_arrival(True), (False, 0))

    def test_naive_undo_differs_from_replaying_active_contributions(self):
        base = 'X'
        active = [('A', 'A'), ('B', 'B')]
        naive_after_removing_a = base
        replayed = base
        for name, value in active:
            if name != 'A':
                replayed = value
        self.assertEqual(naive_after_removing_a, 'X')
        self.assertEqual(replayed, 'B')

    def test_update_failure_and_policy_block_are_distinct(self):
        def choose(old: str, event: str) -> str | None:
            return None if event == 'blocked' else old
        self.assertEqual(choose('v1', 'load-error'), 'v1')
        self.assertIsNone(choose('v1', 'blocked'))

    def test_same_durable_intent_can_hide_two_effect_worlds(self):
        before_effect = {'log': ('call-x',), 'external_effects': 0}
        after_effect = {'log': ('call-x',), 'external_effects': 1}
        self.assertEqual(before_effect['log'], after_effect['log'])
        self.assertNotEqual(before_effect['external_effects'], after_effect['external_effects'])

    def test_external_idempotency_adds_information_missing_from_log(self):
        applied: set[str] = set()
        count = 0
        for invocation in ['call-x', 'call-x']:
            if invocation not in applied:
                applied.add(invocation)
                count += 1
        self.assertEqual(count, 1)

    def test_failed_checkpoint_prevents_modeled_body(self):
        executed = []
        def run(checkpoint_ok: bool) -> None:
            if not checkpoint_ok:
                raise OSError('synthetic persistence refusal')
            executed.append('body')
        with self.assertRaises(OSError):
            run(False)
        self.assertEqual(executed, [])

    def test_only_lagging_subscriber_fails_in_independent_model(self):
        feed = IndependentFeed(1)
        received = []
        for value in ['a', 'b', 'c']:
            feed.offer(value)
            received.extend(feed.drain('fast'))
        self.assertEqual(received, ['a', 'b', 'c'])
        self.assertEqual(feed.failed, {'slow'})

    def test_event_count_limit_is_not_byte_limit(self):
        small, large = ['x'], ['x' * 10000]
        self.assertEqual(len(small), len(large))
        self.assertNotEqual(sum(map(len, small)), sum(map(len, large)))

    def test_handoff_high_watermark_can_advance_over_a_hole(self):
        handed, cursor = [], 4
        for seq in [5, 6]:
            if seq == 5:
                continue
            handed.append(seq)
            cursor = seq
        self.assertEqual(handed, [6])
        self.assertEqual(cursor + 1, 7)
        self.assertNotIn(5, range(cursor + 1, 10))

    def test_default_retry_decision_can_differ_from_final_guard(self):
        default_decision = False
        hook_decision = True
        hard_budget_allows = False
        self.assertFalse(default_decision)
        self.assertTrue(hook_decision)
        self.assertFalse(hook_decision and hard_budget_allows)

    def test_round_limit_does_not_determine_token_budget(self):
        two_rounds_small = [100, 100]
        two_rounds_large = [10000, 10000]
        self.assertEqual(len(two_rounds_small), len(two_rounds_large))
        self.assertNotEqual(sum(two_rounds_small), sum(two_rounds_large))


if __name__ == '__main__':
    unittest.main()
