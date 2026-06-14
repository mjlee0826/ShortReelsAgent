"""命令列介面：把子指令對應到 pipeline 階段並執行。

子指令：
    fetch    只抓素材（階段 1）
    curate   只策展（階段 2；無人工選取且未加 --fallback 時僅產預覽與範本）
    prompts  只生成 prompt（階段 4；離線）
    package  只打包凍結（階段 5）
    all      依序跑 fetch → curate(自動 fallback) → prompts → package

具體階段在此組裝後注入 ``DatasetBuildPipeline``，避免 pipeline 反向相依各階段。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from .config_loader import load_dataset_spec
from .curation.stage import CurateStage
from .fetch.stage import FetchStage
from .logging_setup import configure_logging, get_logger
from .packaging.stage import PackageStage
from .pipeline import BuildContext, DatasetBuildPipeline, PipelineStage
from .prompts.stage import PromptStage

logger = get_logger(__name__)

# 子指令名稱
CMD_FETCH: str = "fetch"
CMD_CURATE: str = "curate"
CMD_PROMPTS: str = "prompts"
CMD_PACKAGE: str = "package"
CMD_ALL: str = "all"
SUBCOMMANDS: list[str] = [CMD_FETCH, CMD_CURATE, CMD_PROMPTS, CMD_PACKAGE, CMD_ALL]

# 結束代碼
_EXIT_OK: int = 0
_EXIT_ERROR: int = 1


def _load_env_files() -> None:
    """載入 .env 金鑰：先讀執行目錄（專案根）的 .env，再讀 eval/.env（與 .env.example 同處）。

    已存在於環境（例如先前 export）的變數優先，不會被 .env 覆蓋。
    """
    load_dotenv()  # cwd / 專案根的 .env（若有）
    load_dotenv(Path(__file__).resolve().parent / ".env")  # eval/.env


def _build_stages(command: str) -> list[PipelineStage]:
    """依子指令組出要執行的階段清單。"""
    mapping: dict[str, list[PipelineStage]] = {
        CMD_FETCH: [FetchStage()],
        CMD_CURATE: [CurateStage()],
        CMD_PROMPTS: [PromptStage()],
        CMD_PACKAGE: [PackageStage()],
        CMD_ALL: [FetchStage(), CurateStage(), PromptStage(), PackageStage()],
    }
    return mapping[command]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析命令列參數。"""
    parser = argparse.ArgumentParser(
        prog="python -m eval",
        description="ShortReels 評測 dataset 建置工具",
    )
    parser.add_argument("command", choices=SUBCOMMANDS, help="要執行的階段")
    parser.add_argument("-c", "--config", required=True, help="dataset spec（YAML）路徑")
    parser.add_argument(
        "--fallback",
        action="store_true",
        help="curate 時若無人工選取，改自動依品質挑選覆蓋秒數預算（會明確標示非人工策展）",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="輸出 DEBUG 等級 log")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI 進入點；回傳結束代碼。"""
    args = _parse_args(argv)
    configure_logging(verbose=args.verbose)
    _load_env_files()  # 讓 PEXELS_API_KEY / PIXABAY_API_KEY 可由 .env 提供

    try:
        spec = load_dataset_spec(args.config)
    except (FileNotFoundError, ValueError) as exc:  # 設定檔問題：友善訊息
        logger.error("讀取設定檔失敗：%s", exc)
        return _EXIT_ERROR

    output_dir = Path(spec.output_dir).expanduser().resolve()
    # all 隱含允許 fallback；單獨 curate 需顯式 --fallback
    allow_fallback = args.fallback or args.command == CMD_ALL
    context = BuildContext(spec=spec, output_dir=output_dir, allow_fallback=allow_fallback)

    try:
        DatasetBuildPipeline(_build_stages(args.command)).run(context)
    except EnvironmentError as exc:  # 多半是缺 API key
        logger.error("執行失敗：%s", exc)
        return _EXIT_ERROR

    logger.info("完成：%s（輸出根目錄 %s）", args.command, output_dir)
    return _EXIT_OK
