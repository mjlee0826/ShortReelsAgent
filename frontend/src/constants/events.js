/**
 * 後端 Phase 1 / 生成進度的 WebSocket 事件型別（ProgressEvent.event_type 的 SSOT）。
 *
 * 先前 'job_finished' / 'job_error' 等字串散落於 useProgressSocket / useBlueprintStore /
 * AssetListPage，集中於此並對齊後端 ProgressEvent 契約，避免 magic string 與不一致。
 */

/** 進度事件型別。 */
export const PROGRESS_EVENT = {
  JOB_FINISHED: 'job_finished',
  JOB_ERROR: 'job_error',
  PIPELINE_START: 'pipeline_start',
  PIPELINE_FINISH: 'pipeline_finish',
  STAGE_START: 'stage_start',
  STAGE_FINISH: 'stage_finish',
  STAGE_ERROR: 'stage_error',
  // 導演 agentic loop（Phase 4）：思考串流 / 工具呼叫旁白 / 中途提問（B2 軟終端）
  DIRECTOR_THINKING_DELTA: 'director_thinking_delta',
  DIRECTOR_TOOL_CALL: 'director_tool_call',
  DIRECTOR_CLARIFICATION_NEEDED: 'director_clarification_needed',
};

/** 終端事件（收到即代表工作流結束，應主動關閉連線）。 */
export const TERMINAL_EVENT_TYPES = new Set([
  PROGRESS_EVENT.JOB_FINISHED,
  PROGRESS_EVENT.JOB_ERROR,
]);
