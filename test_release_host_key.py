import base64
from pathlib import Path
import tempfile
import unittest
from release_vm import verify_pinned_host_key

class PinnedHostTests(unittest.TestCase):
    def test_exact_host_pin_permissions_and_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'known'
            raw=b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20'+bytes(range(32))
            path.write_text('192.0.2.1 ssh-ed25519 '+base64.b64encode(raw).decode()+'\n')
            path.chmod(0o600);verify_pinned_host_key(path,'192.0.2.1')
            with self.assertRaises(RuntimeError):verify_pinned_host_key(path,'192.0.2.2')
            link=path.parent/'link';link.symlink_to(path)
            with self.assertRaises(RuntimeError):verify_pinned_host_key(link,'192.0.2.1')
            path.chmod(0o666)
            with self.assertRaises(RuntimeError):verify_pinned_host_key(path,'192.0.2.1')
            path.chmod(0o600);path.write_text('192.0.2.1 ssh-ed25519 broken')
            with self.assertRaises(RuntimeError):verify_pinned_host_key(path,'192.0.2.1')
