"""Optional Windows current-user DPAPI storage. No plaintext token file."""
import ctypes
from ctypes import wintypes
import os


class TokenStore:
    def __init__(self, directory):
        self.path = directory / 'mdt-token.dpapi'
        self.supported = os.name == 'nt'

    def _crypt(self, data, decrypt=False):
        if not self.supported:
            raise ValueError('Remembering the token is available on Windows only.')
        class Blob(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        incoming, outgoing = Blob(len(data), buffer), Blob()
        api = ctypes.WinDLL('crypt32', use_last_error=True)
        fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        fn.restype = wintypes.BOOL
        if not fn(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
            raise ValueError('Windows could not protect or unlock the saved token. Enter it again.')
        try:
            return ctypes.string_at(outgoing.data, outgoing.size)
        finally:
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree.restype = ctypes.c_void_p
            kernel.LocalFree(outgoing.data)

    def load(self):
        if not self.supported or not self.path.exists():
            return ''
        try:
            return self._crypt(self.path.read_bytes(), True).decode('utf-8')
        except (OSError, ValueError, UnicodeError):
            return ''

    def save(self, token):
        protected = self._crypt(token.encode('utf-8'))
        temp = self.path.with_suffix('.tmp')
        temp.write_bytes(protected)
        os.replace(temp, self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)
