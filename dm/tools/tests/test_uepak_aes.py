"""uepak.aes_decrypt, the AES-256 ECB that opens an Unreal pak's encrypted index, on published vectors through the platform's own library (CommonCrypto on a Mac, CNG on
Windows, OpenSSL's libcrypto on Linux: uepak.AES_BACKEND); no game files or keys. Before droidplay-core#359 only the Mac had one, and a Windows build of DreadOut 2 stopped at
its UE shader decode."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/gfx/tools'))
import uepak

# FIPS-197 appendix C.3 (AES-256), one block
FIPS_KEY = bytes(range(32))
FIPS_PLAIN = bytes.fromhex('00112233445566778899aabbccddeeff')
FIPS_CIPHER = bytes.fromhex('8ea2b7ca516745bfeafc49904b496089')
# NIST SP 800-38A F.1.5 / F.1.6 (ECB-AES256), four blocks
SP_KEY = bytes.fromhex('603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4')
SP_PLAIN = bytes.fromhex('6bc1bee22e409f96e93d7e117393172a ae2d8a571e03ac9c9eb76fac45af8e51 30c81c46a35ce411e5fbc1191a0a52ef f69f2445df4f9b17ad2b417be66c3710')
SP_CIPHER = bytes.fromhex('f3eed1bdb5d2a03c064b5a7e3db181f8 591ccb10d410ed26dc5ba74a31362870 b6ed21b99ca6f4f9f153e7b1beafed1d 23304b7a39f9f3ff067d8d8f9e24ecc7')


class Vectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: cls.decrypt = staticmethod(uepak.AES_BACKEND())
        except (OSError, AttributeError) as e: raise unittest.SkipTest(f'no AES library on {sys.platform} ({e})') from None
        cls.name = uepak.AES_BACKEND.__name__.lstrip('_')

    def test_fips197_c3(self):
        self.assertEqual(self.decrypt(FIPS_KEY, FIPS_CIPHER), FIPS_PLAIN, self.name)
        self.assertEqual(uepak.aes_decrypt(FIPS_KEY, FIPS_CIPHER), FIPS_PLAIN)

    def test_sp800_38a_four_blocks(self):
        """Each block on its own, as ECB has no chaining"""
        self.assertEqual(self.decrypt(SP_KEY, SP_CIPHER), SP_PLAIN, self.name)
        self.assertEqual(uepak.aes_decrypt(SP_KEY, SP_CIPHER), SP_PLAIN)

    def test_a_container_block(self):
        """1 MB at once, more than an IoStore block (64 or 256 KB), and a bytearray or memoryview as a reader may pass"""
        self.assertEqual(uepak.aes_decrypt(SP_KEY, SP_CIPHER * 16384), SP_PLAIN * 16384)
        self.assertEqual(uepak.aes_decrypt(bytearray(SP_KEY), memoryview(SP_CIPHER)), SP_PLAIN)

    def test_slices(self):
        """A buffer longer than one call takes (AES_SLICE) goes in slices, joined in order"""
        uepak.aes_decrypt(FIPS_KEY, FIPS_CIPHER)   # the library loaded, so it can be watched
        spy = Mock(wraps=uepak._aes)
        with patch.object(uepak, '_aes', spy), patch.object(uepak, 'AES_SLICE', 32):
            self.assertEqual(uepak.aes_decrypt(SP_KEY, SP_CIPHER), SP_PLAIN)
        self.assertEqual(spy.call_count, 2)

    def test_empty(self):
        self.assertEqual(uepak.aes_decrypt(SP_KEY, b''), b'')


class Refused(unittest.TestCase):
    """What every platform refuses alike, before or without its library"""
    def test_partial_block_and_short_key(self):
        with patch.object(uepak, 'AES_BACKEND', side_effect=AssertionError('library asked')), patch.object(uepak, '_aes', None):
            with self.assertRaisesRegex(ValueError, 'whole 16-byte blocks'): uepak.aes_decrypt(SP_KEY, SP_CIPHER[:31])
            with self.assertRaisesRegex(ValueError, '32-byte key'): uepak.aes_decrypt(SP_KEY[:16], SP_CIPHER)

    def test_no_library(self):
        """A platform without one says what is missing, as a ValueError the NSP scripts report as the build's error (the report's traceback was a FileNotFoundError for
        /usr/lib/libSystem.B.dylib)"""
        with patch.object(uepak, 'AES_BACKEND', side_effect=OSError('no libcrypto.so.3')), patch.object(uepak, '_aes', None):
            with self.assertRaisesRegex(ValueError, r'AES-encrypted, and no AES library could be loaded to read it \(no libcrypto\.so\.3\)'): uepak.aes_decrypt(SP_KEY, SP_CIPHER)


if __name__ == '__main__':
    unittest.main()
