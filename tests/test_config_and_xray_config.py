import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from mid_transport_server.config import ConfigError, load_config
from mid_transport_server.xray_config import build_portal_config
from mid_transport_server.release_assets import parse_sha256_text, _safe_extract_zip
from mid_transport_server.errors import AssetError


VALID_UUID = "11111111-1111-4111-8111-111111111111"


class ConfigAndXrayConfigTests(unittest.TestCase):
    def write_config(self, text: str) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
        tmp.write(text)
        tmp.close()
        return Path(tmp.name)

    def test_loads_minimal_yaml_and_builds_contract_json(self):
        path = self.write_config(
            f"""
xray:
  releaseTag: "mt-v26.3.27"
  installRoot: "./runtime/xray-mt"
  autoDownload: false
  restartOnExit: true
  restartDelaySeconds: 3
portal:
  reverseListenAddress: "0.0.0.0"
  reverseListenPort: 8443
  publicListenAddress: "0.0.0.0"
  publicMainPort: 7000
  reverseCredentialId: "{VALID_UUID}"
  reverseOutboundTag: "mt-reverse-out"
  reverseInboundTag: "mt-vless-reverse"
  publicMainInboundTag: "mt-public-main"
health:
  enabled: true
  listenAddress: "127.0.0.1"
  listenPort: 18080
logging:
  level: "info"
  file: "./logs/mid-transport-server.log"
"""
        )
        config = load_config(path)
        generated = build_portal_config(config)
        self.assertEqual(generated["inbounds"][0]["protocol"], "vless")
        self.assertEqual(generated["inbounds"][0]["settings"]["clients"][0]["reverse"]["tag"], "mt-reverse-out")
        self.assertEqual(generated["inbounds"][1]["protocol"], "dokodemo-door")
        self.assertEqual(generated["routing"]["rules"][0]["outboundTag"], "mt-reverse-out")

    def test_rejects_conflicting_public_and_reverse_ports(self):
        path = self.write_config(
            f"""
xray:
  releaseTag: "mt-v26.3.27"
portal:
  reverseListenPort: 8443
  publicMainPort: 8443
  reverseCredentialId: "{VALID_UUID}"
health:
  listenAddress: "127.0.0.1"
  listenPort: 18080
logging:
  file: "./logs/test.log"
"""
        )
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_rejects_nil_reverse_credential_id(self):
        path = self.write_config(
            """
xray:
  releaseTag: "mt-v26.3.27"
portal:
  reverseListenPort: 8443
  publicMainPort: 7000
  reverseCredentialId: "00000000-0000-0000-0000-000000000000"
health:
  listenAddress: "127.0.0.1"
  listenPort: 18080
logging:
  file: "./logs/test.log"
"""
        )
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_rejects_placeholder_reverse_credential_id(self):
        path = self.write_config(
            """
xray:
  releaseTag: "mt-v26.3.27"
portal:
  reverseListenPort: 8443
  publicMainPort: 7000
  reverseCredentialId: "<MT_UUID>"
health:
  listenAddress: "127.0.0.1"
  listenPort: 18080
logging:
  file: "./logs/test.log"
"""
        )
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_parse_sha256_text(self):
        digest = "0" * 64
        self.assertEqual(parse_sha256_text(f"{digest}  xray-mt-linux-amd64.tar.gz\n", "xray-mt-linux-amd64.tar.gz"), digest)

    def test_zip_extract_rejects_prefix_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "windows-amd64"
            archive = root / "evil.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../windows-amd64_evil/file.txt", "bad")

            with self.assertRaises(AssetError):
                _safe_extract_zip(archive, target)


if __name__ == "__main__":
    unittest.main()
