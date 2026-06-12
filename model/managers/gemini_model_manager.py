"""
GeminiModelManager：雲端視覺大腦 (Gemini)，透過 google.genai SDK 完成影片分析與 Agentic 推論。

設計模式
--------
- **Template Method**：繼承 ``BaseModelManager``，鎖序與 Singleton 由基底類別提供；
  子類只需實作 ``_initialize`` 與業務方法。
- **Strategy**：``PromptManager`` 可由外部注入（``set_prompt_manager``），
  不同 Task Mode 切換不同提示策略，符合開放封閉原則。
- **Null Object**：推論失敗時回傳含 ``error`` 欄位的 dict，下游無需特例處理。

媒體輸入策略
------------
依媒體型別分流，避免不必要的雲端往返：
- **圖片**：SDK 原生支援 ``PIL.Image``，直接 inline 帶入 ``contents``，免上傳/輪詢/刪除。
- **影片**：依檔案大小再分流——
  - ≤ ``GEMINI_INLINE_MAX_BYTES``：讀 bytes 包成 inline part，同步推論（無後台處理狀態）。
  - > 門檻：走 File API「上傳 → 輪詢 → generate_content → 刪除」，``finally`` 保證
    雲端暫存檔必被清除（隱私保護 + API 配額管理），這是大檔唯一可行路徑。

GPU 策略
--------
雲端 API 模型不佔本地 GPU；``_uses_gpu()`` 自動回 False，
forward 跳過 L2 GpuGate 與 ModelPool VRAM 重檢。
"""
import mimetypes
import os
import time
from google import genai
from google.genai import types
from pydantic import BaseModel
from prompt_manager.base_prompt_manager import BasePromptManager
from prompt_manager.default_prompt_manager import DefaultPromptManager
from prompt_manager.task_mode import TaskMode
from prompt_manager.prompt_factory import PromptFactory
from model.infra.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import (
    GEMINI_DEFAULT_MODEL,
    GEMINI_STRONG_MODEL,
    GEMINI_TASK_MODEL,
    GEMINI_FALLBACK_MODEL,
    GEMINI_POLL_MAX_COUNT,
    GEMINI_POLL_INTERVAL_SEC,
    GEMINI_INLINE_MAX_BYTES,
    GEMINI_VIDEO_DEFAULT_MIME,
)
from model.infra.usage_ledger import phase_for_mode, record_usage

# analyze_media 的媒體型別參數值（與 semantic_*_stage 傳入字串對齊，集中為常數免 magic string）
MEDIA_TYPE_IMAGE = "image"
MEDIA_TYPE_VIDEO = "video"

# Gemini File API 後台處理狀態字串
_FILE_STATE_PROCESSING = "PROCESSING"
_FILE_STATE_FAILED = "FAILED"


def _failure_result() -> dict:
    """推論失敗時回傳的 Null Object；每次新建避免共用可變 dict 被下游污染。"""
    return {"error": "Analysis failed", "caption": "Unknown action", "multimodal_event_index": []}


class GeminiModelManager(BaseModelManager):
    """
    統一的雲端大腦 (Gemini)：影片語意分析（analyze_media）與 Agentic 導演規劃（generate_director_plan）。

    已遷移至 ``google.genai`` 最新架構（google-genai SDK）。
    ``device_id`` 對雲端 API 無意義，``self.device`` 未設置，``_uses_gpu()`` 自動回 False。
    """

    # 雲端 API 無 VRAM / 執行緒安全問題，client 可並發；不以 L3 鎖序列化推論（否則多 asset 的
    # Gemini 呼叫會排隊成「一個一個跑」，COMPLEX 影片 stage 的 wait 即源於此）。並發度交由
    # API 資源池（RPS semaphore）控制。詳見 base_model_manager.inference_guard。
    SERIALIZE_INFERENCE = False

    def _initialize(self, device_id: int = 0):
        """初始化 Gemini Client。device_id 對雲端 API 無效，保留簽名一致性。"""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("嚴重錯誤：找不到 GEMINI_API_KEY 環境變數！請設定後再執行。")

        self.client = genai.Client(api_key=api_key)
        self.default_model = GEMINI_DEFAULT_MODEL
        self.strong_model = GEMINI_STRONG_MODEL
        self.prompt_manager = DefaultPromptManager()

    def set_prompt_manager(self, prompt_manager: BasePromptManager):
        """替換 Prompt Manager（Strategy Pattern）。"""
        self.prompt_manager = prompt_manager

    def _model_for(self, mode: TaskMode) -> str:
        """依任務 ``mode`` 查 per-task 模型對照表;查無退回後備模型(避免 KeyError)。"""
        return GEMINI_TASK_MODEL.get(mode.value, GEMINI_FALLBACK_MODEL)

    def _record(self, response, model: str, mode: TaskMode) -> None:
        """把本次呼叫的 token 用量記入當前成本帳本(無帳本則 no-op);phase 由 mode 推得。"""
        phase = phase_for_mode(mode)
        if phase is not None:
            record_usage(response, model, phase)

    @staticmethod
    def _build_config(schema: type[BaseModel] | None):
        """
        依 PromptSpec.schema 決定生成設定：

        schema 非 None → 啟用結構化輸出(``response_mime_type=application/json`` + ``response_schema``)，
        由 Gemini 保證輸出結構與 enum 合法、免去手寫 JSON 與 regex 抓取的脆弱;schema 為 None
        (理論上 Gemini 路徑各 task 皆有 schema)回 None,退化為純文字生成。
        """
        if schema is None:
            return None
        return types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        )

    @synchronized_inference
    def analyze_media(self, media_input, media_type: str = MEDIA_TYPE_VIDEO, mode: TaskMode = TaskMode.VIDEO_EVENT_INDEX) -> dict:
        """
        依媒體型別分派視覺語意推論，回傳語意 JSON（失敗時為含 ``error`` 的 Null Object）。

        - 圖片（``media_type == "image"``）：``media_input`` 為 ``PIL.Image``，直接 inline，免上傳。
        - 影片（其餘）：``media_input`` 為本地檔案路徑，交由 :meth:`_analyze_video` 依大小分流。
        """
        spec = PromptFactory.create_prompt(mode, self.prompt_manager)
        model = self._model_for(mode)  # 依任務 mode 選模型(per-task 對照表)
        if media_type == MEDIA_TYPE_IMAGE:
            # 圖片遠低於 inline 上限，SDK 原生吃 PIL.Image，直接同步推論最省
            return self._generate_inline([media_input], spec, model, mode)
        return self._analyze_video(media_input, spec, model, mode)

    def _analyze_video(self, video_path: str, spec, model: str, mode: TaskMode) -> dict:
        """
        影片分流（Strategy）：≤ ``GEMINI_INLINE_MAX_BYTES`` 走 inline（省上傳/輪詢/刪除往返），
        否則走 File API（大檔唯一可行路徑）；無法取得檔案大小時保守退回 File API。
        """
        if self._fits_inline(video_path):
            return self._generate_inline([self._build_video_part(video_path)], spec, model, mode)
        return self._analyze_via_file_api(video_path, spec, model, mode)

    @staticmethod
    def _fits_inline(file_path: str) -> bool:
        """檔案是否小到可走 inline；無法 stat（不存在等）時回 False 以退回 File API。"""
        try:
            return os.path.getsize(file_path) <= GEMINI_INLINE_MAX_BYTES
        except OSError:
            return False

    @staticmethod
    def _build_video_part(video_path: str) -> types.Part:
        """讀影片 bytes 包成 inline Part；MIME 由副檔名推斷，推斷不出用後備 mp4。"""
        mime_type = mimetypes.guess_type(video_path)[0] or GEMINI_VIDEO_DEFAULT_MIME
        with open(video_path, "rb") as f:
            return types.Part.from_bytes(data=f.read(), mime_type=mime_type)

    def _generate_inline(self, parts: list, spec, model: str, mode: TaskMode) -> dict:
        """
        inline 同步推論：媒體 part 與 prompt 一併送進 ``generate_content``。

        媒體不落雲端、無 upload/輪詢/delete 生命週期；失敗吞例外回 Null Object，
        維持與 File API 路徑一致的下游契約。``spec.schema`` 啟用結構化輸出。
        """
        try:
            response = self.client.models.generate_content(
                model=model,
                contents=[*parts, spec.text],
                config=self._build_config(spec.schema),
            )
            # 記錄 token 用量供分階段成本統計(無 job 帳本時 no-op)
            self._record(response, model, mode)
            return self._parse_json_output(response.text)
        except Exception as e:
            print(f"[Gemini API Error] 推理失敗: {str(e)}")
            return _failure_result()

    def _analyze_via_file_api(self, video_path: str, spec, model: str, mode: TaskMode) -> dict:
        """
        大影片走 File API：upload → 輪詢（最多 ``GEMINI_POLL_MAX_COUNT`` 次）→ generate_content
        → delete（``finally`` 保證）。雲端暫存檔無論成敗必被清除（隱私 + 配額）。
        """
        video_file = None
        try:
            print(f"[Gemini API] 正在上傳影片至雲端: {video_path}")
            video_file = self.client.files.upload(file=video_path)

            # 輪詢等待 Gemini 後台處理影片完成
            poll_count = 0
            while video_file.state.name == _FILE_STATE_PROCESSING:
                if poll_count >= GEMINI_POLL_MAX_COUNT:
                    raise TimeoutError("Gemini 影片處理逾時（超過 5 分鐘），請稍後重試或換短影片。")
                poll_count += 1
                # 後台處理輪詢：刻意不在迴圈內印 log，長影片可達上百圈會刷爆 console；
                # 上方「上傳」與下方「開始推論」兩則訊息已足以界定這段等待
                time.sleep(GEMINI_POLL_INTERVAL_SEC)
                video_file = self.client.files.get(name=video_file.name)

            if video_file.state.name == _FILE_STATE_FAILED:
                raise ValueError("Gemini 影片處理失敗。")

            print("[Gemini API] 開始進行語意與時間碼推論...")
            response = self.client.models.generate_content(
                model=model,
                contents=[video_file, spec.text],
                config=self._build_config(spec.schema),
            )
            # 記錄 token 用量供分階段成本統計(無 job 帳本時 no-op)
            self._record(response, model, mode)
            return self._parse_json_output(response.text)

        except Exception as e:
            print(f"[Gemini API Error] 推理失敗: {str(e)}")
            return _failure_result()
        finally:
            # 確保上傳的檔案會被刪除，保護隱私與配額
            if video_file:
                try:
                    # 清理成功屬預期行為，不印 log；僅在刪除失敗時警告（涉及配額與隱私風險）
                    self.client.files.delete(name=video_file.name)
                except Exception as e:
                    print(f"[Gemini API Warning] 無法刪除雲端暫存檔: {e}")

    @synchronized_inference
    def generate_director_plan(self, prompt: str, schema: type[BaseModel] | None = None) -> str:
        """
        導演藍圖生成：one-shot ``generate_content`` + ``response_schema`` 結構化輸出。

        模型由 per-task 對照表決定（``DIRECTOR_BLUEPRINT`` → 結構化 + 推理強的型號）。
        改用單次 ``generate_content``（取代舊 Chat Session）：reflection 每次重試本就是獨立呼叫、
        未用到多輪對話記憶，one-shot 更單純；``schema`` 交給 ``response_schema`` 保證輸出結構合法。
        """
        model = self._model_for(TaskMode.DIRECTOR_BLUEPRINT)
        response = self.client.models.generate_content(
            model=model,
            contents=prompt,
            config=self._build_config(schema),
        )
        # 記錄 token 用量(Phase 4);reflection 重試會多次呼叫、各自累加
        self._record(response, model, TaskMode.DIRECTOR_BLUEPRINT)
        return response.text

    @synchronized_inference
    def generate_casting_plan(self, prompt: str, schema: type[BaseModel] | None = None) -> str:
        """
        導演選角生成（兩階段第一段）：one-shot ``generate_content`` + ``response_schema`` 結構化輸出。

        對稱於 :meth:`generate_director_plan`，但走 ``DIRECTOR_CASTING`` 的 per-task 模型（預設較輕的
        Flash）：本階段只做選材、吃精簡卡片、只輸出要用的素材 id，用不到 Pro 等級推理。``schema``
        交給 ``response_schema`` 保證輸出為合法 ``CastingSelection``。
        """
        model = self._model_for(TaskMode.DIRECTOR_CASTING)
        response = self.client.models.generate_content(
            model=model,
            contents=prompt,
            config=self._build_config(schema),
        )
        # 記錄 token 用量(Phase 4;與 scheduling 同階段累加)
        self._record(response, model, TaskMode.DIRECTOR_CASTING)
        return response.text

    def generate_text(self, mode: TaskMode, prompt: str, schema: type[BaseModel] | None = None) -> str:
        """
        純文字 / 結構化生成（供 music 配樂關鍵字萃取等輕量任務）：依 ``mode`` 選模型、記錄用量、回傳文字。

        取代 ``music_director`` 直接打 ``self.client`` 的舊寫法,讓所有 Gemini 出口統一經
        manager 記錄成本。刻意不加 ``@synchronized_inference``：維持與舊版 raw client 相同的
        非序列化行為,讓 music 分支能與 template 分支的雲端呼叫並行（fork-join 紅利）。
        ``schema`` 非 None 時啟用結構化輸出。失敗時拋例外交回呼叫端（music 端已有 try/except 降級）。
        """
        model = self._model_for(mode)
        response = self.client.models.generate_content(
            model=model, contents=prompt, config=self._build_config(schema)
        )
        self._record(response, model, mode)
        return response.text
