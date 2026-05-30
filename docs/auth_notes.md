# 前端認證(Logto)踩雷筆記與設計

> 記錄 2026-05-30/31 排查「重登後一直 401」的根因與最終設計。
> 與加速 plan 無關,屬獨立的前端認證主題,但坑很深,留檔避免重踩。
> 相關程式:`frontend/src/services/api.service.js`、`frontend/src/App.jsx`、
> `backend/auth/logto_jwt_verifier.py`。

---

## 1. Logto 的兩個 token,壽命差很多

| Token | 壽命(預設) | 存哪 | 用途 |
|---|---|---|---|
| **Access token** | ~1 小時 | Logto SDK localStorage | 當 Bearer 送後端,後端驗 JWT |
| **Refresh token / session** | **14 天**(可在 Logto Console 調) | Logto SDK 管理 | 換新 access token;決定「是否仍登入」 |

`useLogto()` 的 `isAuthenticated` 只看 localStorage 有無 session 快取,
**不保證 refresh token 在 server 端仍有效** —— 這是很多怪象的根源。

## 2. 最大的坑:opaque token vs JWT

**Logto 只有在「access token 請求帶了 resource 參數」時才發 JWT;沒帶 resource → 發 opaque token**(一串無點的隨機短字串)。

opaque token 不是 JWT,後端 `jwt.get_unverified_header()` 會報
`Error decoding token headers`(注意:**不是** `Signature has expired`)。

### 判斷方式(瀏覽器 Console)
```js
Object.entries(localStorage)
  .filter(([k]) => k.toLowerCase().includes('logto'))
  .forEach(([k, v]) => console.log(k, '=>', (v || '').slice(0, 80)));
```
看 `accessToken` 的 map key:
- key 是 `<resource>@`(如 `https://api.8752ng.logto.app/api@`)且值 `eyJ...` → **JWT,正常**
- key 是 `"@"`(resource 空)且值無點 → **opaque,resource 沒傳出去**

### 發 opaque 的兩個成因
1. **前端 `VITE_LOGTO_API_RESOURCE` 在 runtime 是 undefined** → `getAccessToken(undefined)` → opaque
   - vite 的 env 是**啟動/build 當下烤進去**,改 `.env` 後**必須重啟 vite / 重 build**
2. **Logto Console 沒註冊該 API resource**(indicator 要與前端 resource、後端 `LOGTO_AUDIENCE` 完全一致)

本專案三處設定須一致:
- 前端 `frontend/.env`:`VITE_LOGTO_API_RESOURCE=https://api.8752ng.logto.app/api`
- 後端 `.env`:`LOGTO_AUDIENCE=https://api.8752ng.logto.app/api`
- Logto Console → API resources → indicator 同上

## 3. interceptor 必須放模組層,不可放 React effect

`api.service.js` 的 axios interceptor **在模組載入時就註冊**,並用 Auth Bridge
(`setAuthBridge`)從 React 取得 `getAccessToken`/`signOut`,由 `AuthInterceptorSetup`
在 **render 階段**注入。

**為什麼不放 `useEffect`**:
- React effect 執行順序是「子先父後」,interceptor 若在父元件 effect 註冊,
  子元件(ProjectDashboard)的 fetch effect 會早一步送出 → 缺 token → 401(mount race)。
- 曾試在 `AuthGuard` 用 `useEffect` 主動驗 token,但 `useLogto()` 每次 render 回傳
  **全新的** `getAccessToken` reference → effect 依賴不穩定 → **無限 re-render + 狂送 request**。

**結論**:認證攔截屬於「請求/回應管線」橫切邏輯,放 interceptor(模組層),
不要放 render 流程。模組層沒有 render cycle,從根本杜絕迴圈。

## 4. refresh token 過期的優雅處理

當 refresh token 失效,`getAccessToken()` 會拋錯。處理設計:

- **request interceptor**:取 token 失敗印 warn,不靜默吞(方便除錯)。
- **response interceptor**:攔 **401 與 403**(缺 token 時後端 `HTTPBearer` 回 403,
  不是 401 —— 早期只攔 401 是漏洞),重換一次 token 重打;再失敗 → `forceReLogin()`。
- **`forceReLogin()`**:module-level flag 防並發重複觸發,`signOut` 清掉 localStorage
  殘留 token 並導向 `/login`;signOut 失敗則 `window.location.assign('/login')` 保底。

效果:refresh token 一過期,下次打 API 就乾淨地被導回登入頁重登,不再卡 401 / 狂送 request。

## 5. 降低過期頻率(Logto Console 設定)

refresh token TTL 是**閒置計時器**:搭配 **Rotate Refresh Token**(輪替)時,
每次用到就發新的、重新計時。所以天天用的人不會過期,只有**連續 N 天不開**才會被踢。

Logto Console → 你的 Application:
- **Rotate Refresh Token**:確認開啟(開了才有「用就續期」)
- **Refresh Token TTL**:預設 14 天,可拉長(越長越方便,但 token 被竊風險窗口越大)

## 6. 後端診斷 log(暫時)

`backend/auth/logto_jwt_verifier.py` 的 `verify_token` 加了一行:401 時印
`[LogtoJWT] ❌ 401 拒絕原因：<detail>`。問題釐清後可移除,回到單純
`return _verifier.verify(...)`。

---

*文件最後更新:2026-05-31*
