"""SSH 主机密码的本地加密存储

本机单用户场景下的取舍：
- 密钥是一份 32 字节随机串，放在数据目录的 .ssh_key（权限 0600），
  与数据库同机存放、但不随数据库导出；
- 加密用 HMAC-SHA256 构造密钥流做异或，并附加 MAC 校验完整性，
  全部走标准库，不为此引入 cryptography 之类的新依赖；
- 目标不是抵御已取得本机 root 的攻击者，而是避免口令明文落库、避免被
  随手 cat 出来或随数据库文件泄露。

如需更强的保护，可把 encrypt_secret / decrypt_secret 换成 keyring 或
cryptography.fernet，接口保持不变即可。
"""

import base64
import hashlib
import hmac
import os
from pathlib import Path

from config import DB_DIR

_KEY_PATH = Path(DB_DIR) / ".ssh_key"
_NONCE_LEN = 16
_MAC_LEN = 32


def _machine_key() -> bytes:
    """读取（或首次生成）本机密钥"""
    if not _KEY_PATH.exists():
        _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _KEY_PATH.write_bytes(os.urandom(32))
        try:
            os.chmod(_KEY_PATH, 0o600)
        except OSError:
            pass
    return _KEY_PATH.read_bytes()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """用 HMAC-SHA256 作 PRF，按计数器模式生成密钥流"""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, ks: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, ks))


def encrypt_secret(plain: str) -> str:
    """加密口令，返回可安全存入数据库的字符串；空串原样返回"""
    if not plain:
        return ""
    key = _machine_key()
    nonce = os.urandom(_NONCE_LEN)
    data = plain.encode("utf-8")
    ct = _xor(data, _keystream(key, nonce, len(data)))
    mac = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    return base64.b64encode(nonce + mac + ct).decode("ascii")


def decrypt_secret(token: str) -> str:
    """解密口令；校验失败或数据损坏时返回空串（宁可让用户重输，也不返回错误口令）"""
    if not token:
        return ""
    try:
        raw = base64.b64decode(token)
        if len(raw) < _NONCE_LEN + _MAC_LEN:
            return ""
        nonce = raw[:_NONCE_LEN]
        mac = raw[_NONCE_LEN:_NONCE_LEN + _MAC_LEN]
        ct = raw[_NONCE_LEN + _MAC_LEN:]
        key = _machine_key()
        if not hmac.compare_digest(hmac.new(key, nonce + ct, hashlib.sha256).digest(), mac):
            return ""
        return _xor(ct, _keystream(key, nonce, len(ct))).decode("utf-8")
    except Exception:
        return ""
