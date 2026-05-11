"""
Strategy Pattern + Singleton：Logto JWT 存取令牌驗證器

以 JWKS 端點取得公鑰、驗證 Bearer token 的簽名、有效期與受眾，
並以 TTL 快取公鑰集合降低對 Logto 的依賴頻率。
"""

import os
import time
import httpx
from jose import jwt, JWTError, jwk
from jose.utils import base64url_decode
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# 從環境變數讀取 Logto 設定
_ISSUER     = os.getenv("LOGTO_ISSUER",   "")
_JWKS_URI   = os.getenv("LOGTO_JWKS_URI", "")
_AUDIENCE   = os.getenv("LOGTO_AUDIENCE", "")

_bearer_scheme = HTTPBearer()


class LogtoJWTVerifier:
    """
    Strategy Pattern：封裝 JWKS 快取策略與 JWT 驗證邏輯。
    模組層級建立單例，避免每次請求重複抓取公鑰。
    """

    _JWKS_TTL = 3600  # 公鑰快取有效期（秒）

    def __init__(self):
        self._jwks_cache: dict | None = None
        self._cached_at: float = 0.0

    # --- 私有方法 ---

    def _fetch_jwks(self) -> dict:
        """向 Logto JWKS 端點抓取公鑰集合。"""
        if not _JWKS_URI:
            raise HTTPException(status_code=503, detail="LOGTO_JWKS_URI 未設定，無法驗證令牌")
        try:
            resp = httpx.get(_JWKS_URI, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"無法取得 JWKS 公鑰：{e}")

    def _get_jwks(self) -> dict:
        """取得 JWKS；若快取過期則重新抓取。"""
        if self._jwks_cache is None or (time.time() - self._cached_at) > self._JWKS_TTL:
            self._jwks_cache = self._fetch_jwks()
            self._cached_at = time.time()
            print("[LogtoJWT] 🔑 JWKS 公鑰快取已更新")
        return self._jwks_cache

    def _find_key(self, kid: str, allow_refresh: bool = True):
        """從快取的 JWKS 中尋找對應 kid 的公鑰；找不到時強制刷新一次（應對金鑰輪替）。"""
        jwks = self._get_jwks()
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                return key_data
        # kid 找不到：可能是金鑰輪替，強制刷新快取後再試一次
        if allow_refresh:
            print(f"[LogtoJWT] ⚠️ kid '{kid}' 不在快取中，嘗試刷新 JWKS...")
            self._jwks_cache = None
            return self._find_key(kid, allow_refresh=False)
        return None

    # --- 公開方法 ---

    def verify(self, token: str) -> str:
        """
        驗證 JWT 並回傳 user_id（sub claim）。
        驗證項目：RS256 簽名、iss、aud、exp。
        """
        if not _ISSUER or not _AUDIENCE:
            raise HTTPException(status_code=503, detail="Logto 環境變數未完整設定（LOGTO_ISSUER / LOGTO_AUDIENCE）")

        try:
            # 取出 header 中的 kid，決定用哪把公鑰驗簽
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid", "")
        except JWTError as e:
            raise HTTPException(status_code=401, detail=f"無效的令牌格式：{e}")

        key_data = self._find_key(kid)
        if key_data is None:
            raise HTTPException(status_code=401, detail=f"無法找到對應的公鑰 (kid={kid})")

        # Logto 預設使用 ES384；保留 RS256 相容性
        alg = unverified_header.get("alg", "RS256")

        try:
            payload = jwt.decode(
                token,
                key_data,
                algorithms=[alg],
                audience=_AUDIENCE,
                issuer=_ISSUER,
            )
        except JWTError as e:
            raise HTTPException(status_code=401, detail=f"令牌驗證失敗：{e}")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="令牌缺少 sub 聲明")

        return user_id


# 模組層級單例
_verifier = LogtoJWTVerifier()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme)) -> str:
    """
    FastAPI Dependency：從 Authorization Bearer header 提取並驗證 JWT，
    回傳 user_id 供端點直接使用。
    """
    return _verifier.verify(credentials.credentials)
