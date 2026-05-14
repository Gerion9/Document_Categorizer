import unittest

from app.services import case_pipeline_lock as locks


class CasePipelineLockTests(unittest.TestCase):
    def setUp(self) -> None:
        with locks._REGISTRY_LOCK:
            locks._CASE_LOCKS.clear()

    def tearDown(self) -> None:
        with locks._REGISTRY_LOCK:
            locks._CASE_LOCKS.clear()

    def test_lock_acquires_and_releases_for_same_case(self) -> None:
        with locks.case_pipeline_lock("case-1", blocking=False):
            with self.assertRaises(locks.CasePipelineBusy):
                with locks.case_pipeline_lock("case-1", blocking=False):
                    pass

        with locks.case_pipeline_lock("case-1", blocking=False):
            pass

    def test_locks_are_independent_per_case(self) -> None:
        with locks.case_pipeline_lock("case-1", blocking=False):
            with locks.case_pipeline_lock("case-2", blocking=False):
                pass

    def test_nonblocking_acquire_raises_busy_for_locked_case(self) -> None:
        with locks.case_pipeline_lock("case-1", blocking=False):
            with self.assertRaises(locks.CasePipelineBusy) as ctx:
                with locks.case_pipeline_lock("case-1", blocking=False):
                    pass

        self.assertEqual(ctx.exception.case_id, "case-1")

    def test_blocking_acquire_raises_busy_after_timeout(self) -> None:
        with locks.case_pipeline_lock("case-1", blocking=False):
            with self.assertRaises(locks.CasePipelineBusy):
                with locks.case_pipeline_lock("case-1", timeout=0.01):
                    pass


if __name__ == "__main__":
    unittest.main()
