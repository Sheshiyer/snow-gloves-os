import unittest, tempfile, pathlib, os, sys, base64, hashlib, sqlite3
from unittest.mock import patch
from lib.runtime_management_coordinator import RuntimeManagementCoordinator, SQLITE_HEADER
from lib.runtime_storage_guard import StorageBudget, preflight
from lib.runtime_operation_identity import checkpoint_digest, restore_digest
from lib.runtime_supervisor import Supervisor

CRYPTO_CLI = str(pathlib.Path(os.environ.get("SG_TEST_CRYPTO_DIR", str(pathlib.Path(__file__).resolve().parents[1] / "infra/cloudflare-runtime"))) / "backup_file_cli.mjs")

@unittest.skipUnless(sys.platform == "linux", "Linux storage integration tests only")
class TestRuntimeStorageIntegration(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.t.name).resolve()
        self.root.chmod(0o700)
        self.db_path = self.root / "storage.sqlite"
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE fixture(value TEXT)")
        conn.execute("INSERT INTO fixture VALUES('integration storage payload')")
        conn.commit()
        conn.close()
        self.db_path.chmod(0o600)
        self.ctx = {
            "instanceId": "int-inst-01",
            "runtimeVersion": "3.8.50",
            "imageDigest": "c" * 64,
            "keyId": "integration-key-1"
        }
        self.sup = Supervisor(str(self.root), ["/usr/bin/true"], "s" * 40, "m" * 40)
        self.key = base64.b64encode(os.urandom(32)).decode("ascii")

    def tearDown(self):
        self.t.cleanup()

    def _snapshot_root(self):
        snap = {}
        for p in self.root.iterdir():
            st = p.lstat()
            h = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
            snap[p.name] = (st.st_size, st.st_mode, h)
        return snap

    def _make_coord(self, budget=None):
        return RuntimeManagementCoordinator(self.sup, self.ctx, self.key, "/usr/local/bin/node", CRYPTO_CLI, storage_budget=budget)

    def _crypto_checkpoint(self, coord=None, job_id="1" * 32):
        c = coord or self._make_coord()
        dig = checkpoint_digest(self.ctx, job_id)
        rec = c.checkpoint({"job_id": job_id, "request_digest": dig})
        self.assertEqual(rec["state"], "artifact-verified")
        return c, job_id, dig, rec

    def test_01_checkpoint_quota_denial_before_journal_prepare_or_snapshot(self):
        b = StorageBudget(max_snapshots=1, max_encrypted=1, max_journals=1)
        c = self._make_coord(b)
        before = self._snapshot_root()
        job_id = "2" * 32
        dig = checkpoint_digest(self.ctx, job_id)
        with patch("lib.runtime_management_coordinator.preflight", side_effect=RuntimeError("Storage admission held")) as g_spy:
            with self.assertRaises(RuntimeError):
                c.checkpoint({"job_id": job_id, "request_digest": dig})
            g_spy.assert_called_once()
        self.assertEqual(self._snapshot_root(), before)

    def test_02_restore_quota_denial_before_intent_prepare_or_decryption(self):
        c, sid, sdig, rec = self._crypto_checkpoint()
        b_tight = StorageBudget(max_plain_restores=1, max_recovery=1, max_intents=1)
        c_tight = self._make_coord(b_tight)
        rid = "3" * 32
        p = {"restore_job_id": rid, "source_checkpoint_job_id": sid, "source_request_digest": sdig, **rec["artifact"]}
        p["request_digest"] = restore_digest(self.ctx, rid, sid, sdig, rec["artifact"])
        before = self._snapshot_root()
        with patch("lib.runtime_management_coordinator.preflight", side_effect=RuntimeError("Storage admission held")) as g_spy:
            with self.assertRaises(RuntimeError):
                c_tight.restore(p)
            g_spy.assert_called_once()
        self.assertEqual(self._snapshot_root(), before)

    def test_03_completed_checkpoint_replay_at_exhausted_quota(self):
        c, sid, sdig, rec = self._crypto_checkpoint()
        b_exhaust = StorageBudget(max_entries=1)
        c_exhaust = self._make_coord(b_exhaust)
        before = self._snapshot_root()
        with patch("lib.runtime_management_coordinator.preflight") as g_spy:
            replay = c_exhaust.checkpoint({"job_id": sid, "request_digest": sdig})
            g_spy.assert_not_called()
        self.assertEqual(replay, rec)
        self.assertEqual(self._snapshot_root(), before)

    def test_04_completed_restore_replay_at_exhausted_budget_no_effects(self):
        c, sid, sdig, rec = self._crypto_checkpoint()
        rid = "4" * 32
        p = {"restore_job_id": rid, "source_checkpoint_job_id": sid, "source_request_digest": sdig, **rec["artifact"]}
        p["request_digest"] = restore_digest(self.ctx, rid, sid, sdig, rec["artifact"])
        with patch.object(self.sup, "restore") as mut, patch.object(self.sup, "_check_http_health", return_value=True, create=True):
            res1 = c.restore(p)
            self.assertEqual(res1["state"], "completed-local")
            mut.assert_called_once()
            b_exhaust = StorageBudget(max_entries=1)
            c_exhaust = self._make_coord(b_exhaust)
            before = self._snapshot_root()
            with patch("lib.runtime_management_coordinator.preflight") as g_spy, patch.object(c_exhaust, "_run_cli") as cli_spy:
                res2 = c_exhaust.restore(p)
                g_spy.assert_not_called()
                cli_spy.assert_not_called()
            self.assertTrue(res2.get("historical"))
            self.assertEqual(self._snapshot_root(), before)

    def test_05_low_fstatvfs_available_denies_checkpoint_before_new_records(self):
        c = self._make_coord()
        job_id = "5" * 32
        dig = checkpoint_digest(self.ctx, job_id)
        before = self._snapshot_root()
        fake_vfs = os.statvfs_result((4096, 4096, 100000000, 100000000, 0, 1000000, 1000000, 1000000, 0, 255))
        with patch("lib.runtime_storage_guard.os.fstatvfs", return_value=fake_vfs):
            with self.assertRaises(RuntimeError):
                c.checkpoint({"job_id": job_id, "request_digest": dig})
        self.assertEqual(self._snapshot_root(), before)

    def test_06_checkpoint_stage_encrypt_failure_retains_snapshot_and_journal(self):
        c = self._make_coord()
        job_id = "6" * 32
        dig = checkpoint_digest(self.ctx, job_id)
        orig_pf = c._storage_preflight
        def guarded_pf(stage):
            if stage == "checkpoint_encrypt":
                raise RuntimeError("quota pressure at encrypt")
            orig_pf(stage)
        with patch.object(c, "_storage_preflight", side_effect=guarded_pf):
            with self.assertRaises(RuntimeError):
                c.checkpoint({"job_id": job_id, "request_digest": dig})
        j_path = self.root / f"sg-job-{job_id}.json"
        self.assertTrue(j_path.exists())
        j_data = c._journal.lookup(job_id, dig)
        self.assertEqual(j_data["state"], "prepared")
        snaps = list(self.root.glob("sg-snapshot-*.sqlite"))
        self.assertEqual(len(snaps), 1)
        self.assertTrue(snaps[0].read_bytes().startswith(SQLITE_HEADER))
        self.assertFalse((self.root / f"sg-encrypted-{job_id}.bin").exists())

    def test_07_restore_mutate_stage_failure_retains_plain_and_prepared_intent(self):
        c, sid, sdig, rec = self._crypto_checkpoint()
        rid = "7" * 32
        p = {"restore_job_id": rid, "source_checkpoint_job_id": sid, "source_request_digest": sdig, **rec["artifact"]}
        p["request_digest"] = restore_digest(self.ctx, rid, sid, sdig, rec["artifact"])
        orig_pf = c._storage_preflight
        def guarded_pf(stage):
            if stage == "restore_mutate":
                raise RuntimeError("quota pressure at mutate")
            orig_pf(stage)
        with patch.object(c, "_storage_preflight", side_effect=guarded_pf), patch.object(self.sup, "restore") as mut:
            with self.assertRaises(RuntimeError):
                c.restore(p)
            mut.assert_not_called()
        intents = list(self.root.glob(f"sg-restore-{rid}.json"))
        self.assertEqual(len(intents), 1)
        intent_rec = c._intents.lookup(p)
        self.assertEqual(intent_rec["state"], "prepared")
        plains = list(self.root.glob(f"sg-restore-plain-{rid}-*.sqlite"))
        self.assertEqual(len(plains), 1)
        self.assertTrue(plains[0].read_bytes().startswith(SQLITE_HEADER))

    def test_08_corrupted_existing_journal_holds_without_prepare_fallback(self):
        c = self._make_coord()
        job_id = "8" * 32
        dig = checkpoint_digest(self.ctx, job_id)
        j_path = self.root / f"sg-job-{job_id}.json"
        j_path.write_bytes(b"{\"corrupt\":true}")
        j_path.chmod(0o600)
        before = self._snapshot_root()
        with self.assertRaises(RuntimeError):
            c.checkpoint({"job_id": job_id, "request_digest": dig})
        self.assertEqual(self._snapshot_root(), before)

    def test_09_readonly_lookup_none_leaves_snapshot_unchanged(self):
        c = self._make_coord()
        before = self._snapshot_root()
        self.assertIsNone(c._journal.lookup("9" * 32, "0" * 64))
        p = {"restore_job_id": "9" * 32, "source_checkpoint_job_id": "8" * 32, "source_request_digest": "0" * 64,
             "leaf": "sg-encrypted-" + "8" * 32 + ".bin", "bytes": 100, "sha256": "a" * 64}
        p["request_digest"] = restore_digest(self.ctx, p["restore_job_id"], p["source_checkpoint_job_id"], p["source_request_digest"], {"leaf": p["leaf"], "bytes": 100, "sha256": "a" * 64})
        self.assertIsNone(c._intents.lookup(p))
        self.assertEqual(self._snapshot_root(), before)

    def test_10_restore_lookup_mutation_intent_held(self):
        c, sid, sdig, rec = self._crypto_checkpoint()
        rid = "a" * 32
        p = {"restore_job_id": rid, "source_checkpoint_job_id": sid, "source_request_digest": sdig, **rec["artifact"]}
        p["request_digest"] = restore_digest(self.ctx, rid, sid, sdig, rec["artifact"])
        c._intents.prepare(p)
        c._intents.begin_mutation(p)
        with self.assertRaises(RuntimeError):
            c._intents.lookup(p)

    def test_11_stage_class_boundary_counters_success(self):
        b_chk = StorageBudget(max_snapshots=1, max_encrypted=1, max_journals=1)
        c_chk = self._make_coord(b_chk)
        _, sid, sdig, rec = self._crypto_checkpoint(c_chk, job_id="b" * 32)
        b_res = StorageBudget(max_plain_restores=1, max_recovery=1, max_intents=1)
        c_res = self._make_coord(b_res)
        rid = "c" * 32
        p = {"restore_job_id": rid, "source_checkpoint_job_id": sid, "source_request_digest": sdig, **rec["artifact"]}
        p["request_digest"] = restore_digest(self.ctx, rid, sid, sdig, rec["artifact"])
        with patch.object(self.sup, "restore"), patch.object(self.sup, "_check_http_health", return_value=True, create=True):
            res = c_res.restore(p)
            self.assertEqual(res["state"], "completed-local")

    def test_12_tight_root_class_table_holds_subsequent_checkpoint_at_artifact_limit(self):
        b_exact = StorageBudget(max_snapshots=1, max_encrypted=1, max_journals=1)
        c = self._make_coord(b_exact)
        self._crypto_checkpoint(c, job_id="d" * 32)
        job2 = "e" * 32
        dig2 = checkpoint_digest(self.ctx, job2)
        before = self._snapshot_root()
        with self.assertRaises(RuntimeError):
            c.checkpoint({"job_id": job2, "request_digest": dig2})
        self.assertEqual(self._snapshot_root(), before)

    def test_14_prepared_checkpoint_last_journal_slot_completes(self):
        job = "f" * 32
        c = self._make_coord(StorageBudget(max_journals=1, max_snapshots=1, max_encrypted=1))
        dig = checkpoint_digest(self.ctx, job)
        c._journal.prepare(job, dig)
        result = c.checkpoint({"job_id": job, "request_digest": dig})
        self.assertEqual(result["state"], "artifact-verified")

    def test_15_prepared_restore_last_intent_slot_completes(self):
        c, sid, dig, rec = self._crypto_checkpoint()
        rid = "0" * 32
        payload = {"restore_job_id": rid, "source_checkpoint_job_id": sid, "source_request_digest": dig, **rec["artifact"]}
        payload["request_digest"] = restore_digest(self.ctx, rid, sid, dig, rec["artifact"])
        c._intents.prepare(payload)
        tight = self._make_coord(StorageBudget(max_intents=1, max_plain_restores=1, max_recovery=1))
        with patch.object(self.sup, "restore") as mutation, patch.object(self.sup, "_check_http_health", return_value=True, create=True):
            self.assertEqual(tight.restore(payload)["state"], "completed-local")
            mutation.assert_called_once()

    def test_16_corrupt_completed_artifact_cannot_replay_at_quota(self):
        c, sid, dig, rec = self._crypto_checkpoint()
        (self.root / rec["artifact"]["leaf"]).write_bytes(b"changed")
        tight = self._make_coord(StorageBudget(max_entries=1))
        before = self._snapshot_root()
        with patch.object(tight._journal, "prepare") as prepare, patch.object(tight, "_run_cli") as crypto:
            with self.assertRaises(RuntimeError):
                tight.checkpoint({"job_id": sid, "request_digest": dig})
            prepare.assert_not_called()
            crypto.assert_not_called()
        self.assertEqual(before, self._snapshot_root())

    def test_17_record_path_replaced_during_parse_lookup_held(self):
        import lib.runtime_job_journal as module
        c = self._make_coord()
        job = "f" * 32
        dig = checkpoint_digest(self.ctx, job)
        c._journal.prepare(job, dig)
        target = self.root / ("sg-job-" + job + ".json")
        original = module._parse_and_validate_record
        def replace_record(raw):
            result = original(raw)
            target.rename(self.root / "retained-original-record")
            target.write_bytes(raw)
            target.chmod(0o600)
            return result
        with patch.object(module, "_parse_and_validate_record", side_effect=replace_record):
            with self.assertRaises(RuntimeError):
                c._journal.lookup(job, dig)

    def test_13_preflight_exact_stage_projected_and_counted_bytes(self):
        st = os.stat(self.root)
        ident = (st.st_dev, st.st_ino, st.st_uid, 0o700)
        res = preflight(str(self.root), ident, "checkpoint", StorageBudget())
        self.assertGreater(res["counted_bytes"], 0)
        self.assertEqual(res["projected_snapshots"], 1)
        self.assertEqual(res["projected_encrypted"], 1)
        self.assertEqual(res["projected_journals"], 1)

if __name__ == "__main__":
    unittest.main()
