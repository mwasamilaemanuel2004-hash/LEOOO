import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from core.config import settings

class SecurityManager:
    def __init__(self, key: str = None):
        raw_key = key or settings.encryption_key
        if isinstance(raw_key, str):
            try:
                self.key_bytes = base64.urlsafe_b64decode(raw_key)
            except:
                self.key_bytes = raw_key.encode().ljust(32)[:32]
        else:
            self.key_bytes = raw_key

        if len(self.key_bytes) not in [16, 24, 32]:
            self.key_bytes = self.key_bytes.ljust(32)[:32]

        self.aesgcm = AESGCM(self.key_bytes)

    def encrypt(self, data: str) -> str:
        if not data: return ""
        nonce = os.urandom(12)
        ciphertext = self.aesgcm.encrypt(nonce, data.encode(), None)
        return base64.b64encode(nonce + ciphertext).decode()

    def decrypt(self, token: str) -> str:
        if not token: return ""
        data = base64.b64decode(token)
        nonce = data[:12]
        ciphertext = data[12:]
        return self.aesgcm.decrypt(nonce, ciphertext, None).decode()

security_manager = SecurityManager()
