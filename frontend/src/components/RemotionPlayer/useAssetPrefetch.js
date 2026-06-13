import { useEffect, useRef } from 'react';
import { prefetch } from 'remotion';
import { collectBlueprintAssetUrls } from '../../utils/assetUrl';

// 預抓方式：下載成 blob URL 常駐記憶體、由 free() 釋放；不用 base64（體積膨脹數倍）
const PREFETCH_METHOD = 'blob-url';

/**
 * 依藍圖預抓全部素材並管理其生命週期，消除預覽即時播放時的「素材未就緒 → 黑屏」競態。
 *
 * 採增量 diff（以 URL 字串為鍵）：每次藍圖 / 根 URL 變動時，只 free 已移除的素材、只 prefetch 新增的，
 * 故藍圖微調（物件 identity 改變但素材清單未變）為 no-op，不會整批重抓。元件卸載時釋放全部 blob，
 * 避免離開編輯器後記憶體洩漏。
 *
 * 注意：prefetch() 內部以 fetch() 下載、受 CORS 管制（與不受管制的 <Video>/<Img> 標籤不同）；
 * 失敗（CORS / 404）僅記錄警告、不中斷編輯器——預覽仍可退回原本的即時載入行為。
 *
 * @param {object|null} blueprint 影片藍圖
 * @param {string} assetsRootUrl 素材靜態根 URL
 */
export function useAssetPrefetch(blueprint, assetsRootUrl) {
  // url -> prefetch handle（{ free, waitUntilDone }）；跨 render 保存，作為 diff 的現況基準
  const handlesRef = useRef(new Map());

  // 增量同步：依目前藍圖算出「應預抓集合」，與現況 diff 後做最小變更
  useEffect(() => {
    const handles = handlesRef.current;
    const desiredUrls = new Set(collectBlueprintAssetUrls(blueprint, assetsRootUrl));

    // 釋放不再需要的素材（已從藍圖移除）
    for (const [url, handle] of handles) {
      if (!desiredUrls.has(url)) {
        handle.free();
        handles.delete(url);
      }
    }

    // 預抓新增的素材；吞錯避免單一素材失敗炸掉整個編輯器
    for (const url of desiredUrls) {
      if (!handles.has(url)) {
        const handle = prefetch(url, { method: PREFETCH_METHOD });
        handles.set(url, handle);
        handle.waitUntilDone().catch((error) => {
          console.warn('[Prefetch] 素材預抓失敗（預覽將退回即時載入）：', url, error);
        });
      }
    }

    // 此 effect 的 cleanup 刻意不做 free-all：否則每次藍圖變動都會整批釋放再重抓，失去增量 diff 意義。
    // 真正的全量釋放交由下方「僅卸載時」的 effect 處理。
  }, [blueprint, assetsRootUrl]);

  // 僅在元件卸載時釋放全部 blob（空依賴：cleanup 只在 unmount 跑一次）
  useEffect(() => {
    const handles = handlesRef.current;
    return () => {
      for (const [, handle] of handles) handle.free();
      handles.clear();
    };
  }, []);
}
