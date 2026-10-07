"""Internal runtime identity authenticates ownership without changing runtime state."""
import base64
import http.client
import json
import socket
import threading
import unittest
from unittest.mock import patch

from lib import runtime_managed_http as managed_http
from lib import runtime_managed_service as service


class IdentityConfigTests(unittest.TestCase):
    def config(self, generation=None):
        return service.Config(
            instance_id="fixture", image_digest="a" * 64, backup_key_id="fixture-key",
            backup_key=base64.b64encode(b"k" * 32).decode(), management_key="m" * 40,
            backend_key="b" * 40, storage_encryption_key="s" * 40, data_dir="/owned",
            node_executable="/owned/node", runtime_script="/owned/server.js",
            backup_cli="/owned/backup.mjs", initialize_fresh=False,
            runtime_generation=generation,
        )

    def test_legacy_config_and_identity_hold(self):
        config = self.config()
        with patch.object(service.sys, "platform", "linux"):
            service._validate_pure_config(config)
        with self.assertRaisesRegex(RuntimeError, "Runtime identity held"):
            service._build_runtime_identity(config)

    def test_identity_binds_context(self):
        identity = service._build_runtime_identity(self.config("f" * 32))
        self.assertEqual(identity, {"schema": "sg.runtime-identity.v1", "generation": "f" * 32,
                                   **service._build_context(self.config())})

    def test_invalid_generation_and_repr_redaction(self):
        for value in ("", "F" * 32, "f" * 31, "f" * 33, 1, True, "secret\nvalue"):
            with self.subTest(value=type(value).__name__), patch.object(service.sys, "platform", "linux"):
                with self.assertRaisesRegex(ValueError, "Invalid runtime generation"):
                    service._validate_pure_config(self.config(value))
        config = self.config("f" * 32)
        for secret in (config.backup_key, config.management_key, config.backend_key, config.storage_encryption_key):
            self.assertNotIn(secret, repr(config))

    def test_environment_generation_load(self):
        config = self.config()
        env = {"SG_INSTANCE_ID": config.instance_id, "SG_IMAGE_DIGEST": config.image_digest,
               "SG_BACKUP_KEY_ID": config.backup_key_id, "SG_BACKUP_KEY": config.backup_key,
               "SG_MANAGEMENT_KEY": config.management_key, "SG_BACKEND_KEY": config.backend_key,
               "STORAGE_ENCRYPTION_KEY": config.storage_encryption_key, "DATA_DIR": config.data_dir,
               "SG_NODE_EXECUTABLE": config.node_executable, "SG_RUNTIME_SCRIPT": config.runtime_script,
               "SG_BACKUP_CLI": config.backup_cli}
        with patch.object(service.sys, "platform", "linux"):
            self.assertIsNone(service.load_config(env).runtime_generation)
            env["SG_RUNTIME_GENERATION"] = "f" * 32
            self.assertEqual(service.load_config(env).runtime_generation, "f" * 32)
            env["SG_RUNTIME_GENERATION"] = ""
            with self.assertRaises(ValueError):
                service.load_config(env)


class IdentityHTTPTests(unittest.TestCase):
    def setUp(self):
        self.calls = 0
        self.identity = service._build_runtime_identity(IdentityConfigTests().config("f" * 32))
        self.server = managed_http.create_managed_server(
            lambda payload: {}, lambda payload: {}, lambda: True, "m" * 40, "b" * 40, "s" * 40,
            operation_context=service._build_context(IdentityConfigTests().config()), upstream_port=1,
            identity_probe=self.probe,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def probe(self):
        self.calls += 1
        return self.identity

    def request(self, path="/_management/identity", key="m" * 40, method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=2)
        connection.request(method, path, headers={"Authorization": "Bearer " + key, **(headers or {})})
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_actual_authenticated_identity_repeated_does_not_mutate(self):
        for _ in range(2):
            status, body = self.request()
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), self.identity)
        self.assertEqual(self.calls, 2)
        self.assertEqual(self.request("/_management/ready"), (200, b'{"ready":true}'))
        self.assertEqual(self.calls, 2)

    def test_backend_role_and_duplicate_auth_denied(self):
        self.assertEqual(self.request(key="b" * 40)[0], 401)
        with socket.create_connection(self.server.server_address, timeout=2) as connection:
            connection.sendall(("GET /_management/identity HTTP/1.1\r\nHost: fixture\r\n"
                                "Authorization: Bearer " + "m" * 40 + "\r\nAuthorization: Bearer " +
                                "m" * 40 + "\r\n\r\n").encode())
            response = http.client.HTTPResponse(connection)
            response.begin()
            self.assertEqual(response.status, 401)
            response.read()
        self.assertEqual(self.calls, 0)

    def test_invalid_path_framing_and_method(self):
        for path in ("/_management/identity?x=1", "/_management/%69dentity", "//_management/identity"):
            self.assertEqual(self.request(path)[0], 400)
        for headers in ({"Content-Length": "1"}, {"Content-Length": "00"},
                        {"Transfer-Encoding": "chunked"}, {"Expect": "100-continue"}):
            self.assertEqual(self.request(headers=headers)[0], 400)
        self.assertEqual(self.request(method="POST")[0], 405)
        self.assertEqual(self.request(method="POST", key="b" * 40)[0], 401)
        self.assertEqual(self.calls, 0)

    def test_duplicate_lengths_and_unframed_body_denied(self):
        for framing in (b"Content-Length: 0\r\nContent-Length: 0\r\n\r\n", b"\r\nowned-body"):
            with socket.create_connection(self.server.server_address, timeout=2) as connection:
                connection.sendall(b"GET /_management/identity HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer "
                                   + b"m" * 40 + b"\r\n" + framing)
                response = http.client.HTTPResponse(connection)
                response.begin()
                self.assertEqual(response.status, 400)
                response.read()
        self.assertEqual(self.calls, 0)

    def test_missing_exception_context_mismatch_and_extra_keys_hold(self):
        self.server.identity_probe = None
        self.assertEqual(self.request(), (503, b"Service Unavailable"))
        def fail():
            raise RuntimeError("synthetic secret")
        self.server.identity_probe = fail
        self.assertEqual(self.request(), (503, b"Service Unavailable"))
        self.server.identity_probe = self.probe
        for identity in (None, {**self.identity, "keyId": "other"},
                         {**self.identity, "generation": "F" * 32}, {**self.identity, "secret": "hidden"}):
            self.identity = identity
            self.assertEqual(self.request(), (503, b"Service Unavailable"))


if __name__ == "__main__":
    unittest.main()
