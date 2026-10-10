import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch

from scripts.lib.runtime_storage_guard import StorageBudget, preflight


class TestStorageBudget(unittest.TestCase):
    def test_invalid_types_and_bounds(self):
        with self.assertRaises(RuntimeError):
            StorageBudget(max_root_bytes=True)
        with self.assertRaises(RuntimeError):
            StorageBudget(max_entries="256")
        with self.assertRaises(RuntimeError):
            StorageBudget(max_depth=0)
        with self.assertRaises(RuntimeError):
            StorageBudget(max_depth=9)
        with self.assertRaises(RuntimeError):
            StorageBudget(timeout_ms=5001)
        with self.assertRaises(RuntimeError):
            StorageBudget(min_free_bytes=5 * 1024 * 1024 * 1024)


class TestPreflightPure(unittest.TestCase):
    def test_invalid_operation_and_budget_subclass(self):
        class SubBudget(StorageBudget):
            pass
        with self.assertRaises(RuntimeError):
            preflight("/tmp", (1, 1, 0, 0o700), "invalid_op", StorageBudget())
        with self.assertRaises(RuntimeError):
            preflight("/tmp", (1, 1, 0, 0o700), "checkpoint", SubBudget())

    def test_invalid_expected_identity(self):
        b = StorageBudget()
        with self.assertRaises(RuntimeError):
            preflight("/tmp", (1, 1, 0), "checkpoint", b)
        with self.assertRaises(RuntimeError):
            preflight("/tmp", (1, 1, 0, 0o755), "checkpoint", b)
        with self.assertRaises(RuntimeError):
            preflight("/tmp", (1, 1, -1, 0o700), "checkpoint", b)
        with self.assertRaises(RuntimeError):
            preflight("/tmp", ("1", 1, 0, 0o700), "checkpoint", b)


@unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux")
class TestPreflightLinux(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.real_root = os.path.realpath(self.test_dir)
        os.chmod(self.real_root, 0o700)
        st = os.stat(self.real_root)
        self.identity = (st.st_dev, st.st_ino, st.st_uid, 0o700)
        self.budget = StorageBudget(
            max_root_bytes=1024 * 1024 * 1024,
            min_free_bytes=1024 * 1024,
        )

    def tearDown(self):
        shutil.rmtree(self.real_root, ignore_errors=True)

    def test_success_empty_and_side_effects(self):
        res = preflight(self.real_root, self.identity, "checkpoint", self.budget)
        self.assertEqual(res["entries"], 0)
        self.assertEqual(res["projected_snapshots"], 1)
        self.assertEqual(res["projected_encrypted"], 1)
        self.assertEqual(res["projected_journals"], 1)
        self.assertEqual(res["projected_plain_restores"], 0)
        self.assertEqual(os.listdir(self.real_root), [])

    def test_restore_projection(self):
        res = preflight(self.real_root, self.identity, "restore", self.budget)
        self.assertEqual(res["projected_plain_restores"], 1)
        self.assertEqual(res["projected_recovery"], 1)
        self.assertEqual(res["projected_intents"], 1)
        self.assertEqual(res["projected_snapshots"], 0)

    def test_symlink_path_denial(self):
        link_path = os.path.join(tempfile.gettempdir(), "symlink_test_root")
        try:
            os.symlink(self.real_root, link_path)
            with self.assertRaises(RuntimeError):
                preflight(link_path, self.identity, "checkpoint", self.budget)
        finally:
            if os.path.islink(link_path):
                os.unlink(link_path)

    def test_contained_symlink_denial(self):
        sub_file = os.path.join(self.real_root, "target.txt")
        with open(sub_file, "w") as f:
            f.write("data")
        os.symlink(sub_file, os.path.join(self.real_root, "sublink"))
        with self.assertRaises(RuntimeError):
            preflight(self.real_root, self.identity, "checkpoint", self.budget)

    def test_hardlink_denial(self):
        orig = os.path.join(self.real_root, "orig.txt")
        with open(orig, "w") as f:
            f.write("data")
        link = os.path.join(self.real_root, "link.txt")
        os.link(orig, link)
        with self.assertRaises(RuntimeError):
            preflight(self.real_root, self.identity, "checkpoint", self.budget)

    def test_fifo_denial(self):
        fifo_path = os.path.join(self.real_root, "test_fifo")
        os.mkfifo(fifo_path)
        with self.assertRaises(RuntimeError):
            preflight(self.real_root, self.identity, "checkpoint", self.budget)

    def test_permission_denial(self):
        bad_file = os.path.join(self.real_root, "bad.txt")
        with open(bad_file, "w") as f:
            f.write("bad")
        os.chmod(bad_file, 0o666)
        with self.assertRaises(RuntimeError):
            preflight(self.real_root, self.identity, "checkpoint", self.budget)

    def test_nested_valid_modes(self):
        sub_dir = os.path.join(self.real_root, "subdir")
        os.mkdir(sub_dir, 0o755)
        file1 = os.path.join(sub_dir, "live.db")
        with open(file1, "w") as f:
            f.write("db-data")
        os.chmod(file1, 0o644)
        res = preflight(self.real_root, self.identity, "checkpoint", self.budget)
        self.assertEqual(res["entries"], 2)

    def test_sparse_logical_bytes_counted(self):
        sparse_file = os.path.join(self.real_root, "sparse.img")
        with open(sparse_file, "wb") as f:
            f.seek(10 * 1024 * 1024)
            f.write(b"x")
        b = StorageBudget(max_root_bytes=5 * 1024 * 1024, min_free_bytes=1024)
        with self.assertRaises(RuntimeError):
            preflight(self.real_root, self.identity, "checkpoint", b)

    def test_max_depth_and_entries_limit(self):
        d1 = os.path.join(self.real_root, "d1")
        d2 = os.path.join(d1, "d2")
        d3 = os.path.join(d2, "d3")
        os.makedirs(d3)
        b_depth = StorageBudget(max_depth=2, min_free_bytes=1024)
        with self.assertRaises(RuntimeError):
            preflight(self.real_root, self.identity, "checkpoint", b_depth)

        b_entries = StorageBudget(max_entries=8, min_free_bytes=1024)
        with self.assertRaises(RuntimeError):
            preflight(self.real_root, self.identity, "checkpoint", b_entries)

    def test_class_count_limits(self):
        for i in range(2):
            with open(os.path.join(self.real_root, f"sg-snapshot-{i:032x}.sqlite"), "w") as f:
                f.write("s")
        b = StorageBudget(max_snapshots=2, min_free_bytes=1024)
        with self.assertRaises(RuntimeError):
            preflight(self.real_root, self.identity, "checkpoint", b)

    def test_timeout(self):
        with patch("time.monotonic", side_effect=[0.0, 10.0, 20.0]):
            with self.assertRaises(RuntimeError):
                preflight(self.real_root, self.identity, "checkpoint", self.budget)

    def test_statvfs_bavail_check(self):
        b = StorageBudget(min_free_bytes=3 * 1024 * 1024 * 1024)
        with patch("os.fstatvfs") as mock_vfs:
            class DummyVFS:
                f_frsize = 4096
                f_bavail = 10
                f_bfree = 100000000
            mock_vfs.return_value = DummyVFS()
            with self.assertRaises(RuntimeError):
                preflight(self.real_root, self.identity, "checkpoint", b)


if __name__ == "__main__":
    unittest.main()
