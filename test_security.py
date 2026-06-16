import base64
from core.security import security_manager

def test_encryption():
    original = "institutional-grade-key"
    encrypted = security_manager.encrypt(original)
    decrypted = security_manager.decrypt(encrypted)
    assert original == decrypted
    print("Security Test Passed")

if __name__ == "__main__":
    test_encryption()
