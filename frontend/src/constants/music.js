/**
 * 配樂策略的共用常數與選項建構（SSOT）。
 *
 * GenerationForm（初始 / 重新生成）與 ChangeMusicModal（music-only 換曲）共用同一組配樂策略，
 * 先前各自重複定義；集中於此。兩呼叫端唯一差異是「不加配樂」選項的顯示文字，
 * 故以 makeMusicOptions(noneLabel) 帶入。值需與後端 music_strategy 對齊。
 */

/** 配樂策略值（與後端對齊；避免 magic string 散落）。 */
export const MUSIC_STRATEGY = {
  SEARCH_COPYRIGHT: 'search_copyright',
  SEARCH_FREE: 'search_free',
  NONE: 'none',
};

/** 「不加配樂」策略值（呼叫端常需單獨比對是否顯示上傳欄位）。 */
export const MUSIC_NONE = MUSIC_STRATEGY.NONE;

/** 預設配樂策略。 */
export const MUSIC_STRATEGY_DEFAULT = MUSIC_STRATEGY.SEARCH_COPYRIGHT;

/** 允許上傳的自訂 BGM 副檔名（給 <input accept>）。 */
export const ALLOWED_AUDIO_ACCEPT = '.mp3,.wav,.m4a,.aac,.flac,.ogg';

/**
 * 建構配樂策略下拉選項。前兩項（搜尋含版權 / 搜尋免費）固定，none 標籤由呼叫端帶入。
 * @param {string} noneLabel 「不加配樂 / 移除配樂」選項的顯示文字
 * @returns {{value: string, label: string}[]} 餵給 ui/Select 的 options
 */
export function makeMusicOptions(noneLabel) {
  return [
    { value: MUSIC_STRATEGY.SEARCH_COPYRIGHT, label: '🎵 搜尋配樂（可能含版權）' },
    { value: MUSIC_STRATEGY.SEARCH_FREE, label: '🆓 搜尋免費配樂 (Jamendo CC 授權)' },
    { value: MUSIC_STRATEGY.NONE, label: noneLabel },
  ];
}
