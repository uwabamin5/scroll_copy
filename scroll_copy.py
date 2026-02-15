#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXIT_OK = 0
EXIT_CONFIG_ERROR = 10
EXIT_SELECTOR_ERROR = 20
EXIT_RETRY_EXCEEDED = 30
EXIT_WRITE_ERROR = 40
EXIT_UNEXPECTED = 50


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def utc_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{uuid.uuid4().hex[:6]}"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_lines(path: Path, lines: list[str]) -> None:
    if not lines:
        return
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f]


def dedupe_exact(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ln in lines:
        if ln not in seen:
            seen.add(ln)
            out.append(ln)
    return out


def save_state(path: Path, state: dict[str, Any]) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_state(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def finalize_raw_to_final(raw_path: Path, final_path: Path, dedupe_mode: str = "exact") -> tuple[int, int]:
    lines = [ln for ln in read_lines(raw_path) if ln != ""]
    if dedupe_mode != "exact":
        raise ValueError(f"unsupported dedupe mode: {dedupe_mode}")
    deduped = dedupe_exact(lines)
    ensure_parent(final_path)
    with final_path.open("w", encoding="utf-8") as f:
        for ln in deduped:
            f.write(ln + "\n")
    return (len(lines), len(deduped))


@dataclass
class RunConfig:
    url: str
    container: str
    line_selector: str
    output_raw: Path
    output_final: Path
    state_file: Path
    resume: bool
    max_idle_scrolls: int
    scroll_step: int
    scroll_interval_ms: int
    checkpoint_interval: int
    max_retries: int
    retry_wait_ms: int
    dedupe_mode: str
    headless: bool
    timeout_ms: int
    log_level: str
    do_finalize: bool
    connect_existing: bool
    debug_port: int
    text_only: bool
    entry_selector: str
    speaker_selector: str


def build_state_base(cfg: RunConfig, run_id: str) -> dict[str, Any]:
    return {
        "version": 1,
        "run_id": run_id,
        "status": "running",
        "target": {
            "url": cfg.url,
            "container_selector": cfg.container,
            "line_selector": cfg.line_selector,
        },
        "progress": {
            "loop_count": 0,
            "scroll_top": 0,
            "total_lines_seen": 0,
            "unique_lines_seen": 0,
            "idle_scroll_count": 0,
            "last_new_line_at": None,
        },
        "files": {
            "raw_output": str(cfg.output_raw),
            "final_output": str(cfg.output_final),
            "log_file": str(cfg.output_raw.parent / "run.log"),
        },
        "runtime": {
            "max_idle_scrolls": cfg.max_idle_scrolls,
            "scroll_step": cfg.scroll_step,
            "scroll_interval_ms": cfg.scroll_interval_ms,
            "max_retries": cfg.max_retries,
            "retry_wait_ms": cfg.retry_wait_ms,
            "dedupe_mode": cfg.dedupe_mode,
        },
        "timestamps": {
            "started_at": now_iso(),
            "updated_at": now_iso(),
        },
        "last_error": None,
    }


def effective_run_config(args: argparse.Namespace) -> RunConfig:
    state_data: dict[str, Any] | None = None
    if args.resume:
        if not args.state_file.exists():
            raise ValueError(f"state file not found: {args.state_file}")
        state_data = load_state(args.state_file)

    def pick(field_name: str, state_path: tuple[str, ...] | None = None) -> Any:
        value = getattr(args, field_name)
        if value is not None:
            return value
        if state_data is None or state_path is None:
            return None
        cur: Any = state_data
        for k in state_path:
            if not isinstance(cur, dict) or k not in cur:
                return None
            cur = cur[k]
        return cur

    url = pick("url", ("target", "url"))
    container = pick("container", ("target", "container_selector"))
    line_selector = pick("line_selector", ("target", "line_selector"))

    # --connect-existing の場合は --url は省略可能
    if not args.connect_existing and not url:
        raise ValueError("--url は必須です（--connect-existing または --resume 時は省略可）")
    
    if not container:
        raise ValueError("--container は必須です（--resume 時は state.json から補完可）")
    
    # text_only モードの場合は line_selector が必須
    if args.text_only and not line_selector:
        raise ValueError("--text-only モードでは --line-selector が必須です")

    return RunConfig(
        url=url,
        container=container,
        line_selector=line_selector or '[class^="entryText-"]',
        output_raw=args.output_raw,
        output_final=args.output_final,
        state_file=args.state_file,
        resume=args.resume,
        max_idle_scrolls=args.max_idle_scrolls,
        scroll_step=args.scroll_step,
        scroll_interval_ms=args.scroll_interval_ms,
        checkpoint_interval=args.checkpoint_interval,
        max_retries=args.max_retries,
        retry_wait_ms=args.retry_wait_ms,
        dedupe_mode=args.dedupe_mode,
        headless=args.headless,
        timeout_ms=args.timeout_ms,
        log_level=args.log_level,
        do_finalize=args.finalize,
        connect_existing=args.connect_existing,
        debug_port=args.debug_port,
        text_only=args.text_only,
        entry_selector=args.entry_selector,
        speaker_selector=args.speaker_selector,
    )


def run_command(args: argparse.Namespace) -> int:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    try:
        cfg = effective_run_config(args)
    except ValueError as e:
        print(f"[config error] {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    run_id = utc_run_id()
    state = build_state_base(cfg, run_id)
    unique_seen: set[str] = set()

    # --resume が指定されていない場合は既存の raw_output を削除
    if not cfg.resume and cfg.output_raw.exists():
        cfg.output_raw.unlink()
        print(f"[init] 既存のraw出力ファイルを削除しました: {cfg.output_raw}")

    if cfg.resume and cfg.state_file.exists():
        old = load_state(cfg.state_file)
        run_id = old.get("run_id", run_id)
        state["run_id"] = run_id

        raw_lines = read_lines(cfg.output_raw)
        unique_seen.update(ln for ln in raw_lines if ln)
        state["progress"]["unique_lines_seen"] = len(unique_seen)
        state["progress"]["total_lines_seen"] = len(raw_lines)
        state["progress"]["loop_count"] = int(old.get("progress", {}).get("loop_count", 0))
        state["progress"]["idle_scroll_count"] = int(old.get("progress", {}).get("idle_scroll_count", 0))
        state["timestamps"]["started_at"] = old.get("timestamps", {}).get("started_at", now_iso())

    save_state(cfg.state_file, state)

    try:
        with sync_playwright() as p:
            if cfg.connect_existing:
                # 既存のブラウザに接続
                browser = p.chromium.connect_over_cdp(f"http://localhost:{cfg.debug_port}")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                print(f"[connect] 既存のブラウザに接続しました (現在のURL: {page.url})")
                
                # URLが指定されている場合のみ移動
                if cfg.url and page.url != cfg.url:
                    page.goto(cfg.url, wait_until="domcontentloaded", timeout=cfg.timeout_ms)
            else:
                # 新しいブラウザを起動
                browser = p.chromium.launch(headless=cfg.headless)
                page = browser.new_page()
                page.goto(cfg.url, wait_until="domcontentloaded", timeout=cfg.timeout_ms)

            container = page.locator(cfg.container)
            if container.count() == 0:
                raise RuntimeError(f"container not found: {cfg.container}")
            container.first.wait_for(state="visible", timeout=cfg.timeout_ms)

            consecutive_failures = 0

            while state["progress"]["idle_scroll_count"] < cfg.max_idle_scrolls:
                try:
                    texts: list[str]
                    if cfg.text_only:
                        # 本文のみモード（従来互換）
                        texts = container.first.evaluate(
                            """
                            (el, lineSelector) => {
                              const nodes = [...el.querySelectorAll(lineSelector)];
                              return nodes
                                .map(n => (n.innerText ?? n.textContent ?? '').trim())
                                .filter(Boolean);
                            }
                            """,
                            cfg.line_selector,
                        )
                    else:
                        # 話者名付きモード（デフォルト）
                        texts = container.first.evaluate(
                            """
                            (el, config) => {
                              const entries = [...el.querySelectorAll(config.entrySelector)];
                              return entries.map(entry => {
                                const speakerEl = entry.querySelector(config.speakerSelector);
                                const textEl = entry.querySelector(config.lineSelector);
                                
                                const speakerRaw = (speakerEl?.innerText ?? speakerEl?.textContent ?? '').trim();
                                const text = (textEl?.innerText ?? textEl?.textContent ?? '').trim();
                                
                                // 話者名から時刻情報を除去
                                // パターン: "名前 1 時間 30 分間 45 秒間", "名前 数字 分間", "名前 数字 秒間", "名前 数字 秒", etc.
                                const speaker = speakerRaw.replace(/\\s+\\d+\\s*(時間|分間?|秒間?).*$/, '').trim();
                                
                                if (!text) return '';
                                return speaker ? `${speaker}\\t${text}` : text;
                              }).filter(Boolean);
                            }
                            """,
                            {
                                "entrySelector": cfg.entry_selector,
                                "speakerSelector": cfg.speaker_selector,
                                "lineSelector": cfg.line_selector,
                            },
                        )

                    new_unique_count = 0
                    for t in texts:
                        if t not in unique_seen:
                            unique_seen.add(t)
                            new_unique_count += 1

                    append_lines(cfg.output_raw, texts)

                    state["progress"]["total_lines_seen"] += len(texts)
                    state["progress"]["unique_lines_seen"] = len(unique_seen)
                    state["progress"]["loop_count"] += 1

                    if new_unique_count > 0:
                        state["progress"]["idle_scroll_count"] = 0
                        state["progress"]["last_new_line_at"] = now_iso()
                    else:
                        state["progress"]["idle_scroll_count"] += 1

                    container.first.evaluate("(el, step) => { el.scrollBy(0, step); }", cfg.scroll_step)
                    scroll_top = container.first.evaluate("(el) => el.scrollTop")
                    state["progress"]["scroll_top"] = int(scroll_top)
                    state["timestamps"]["updated_at"] = now_iso()
                    state["last_error"] = None

                    if state["progress"]["loop_count"] % max(cfg.checkpoint_interval, 1) == 0:
                        save_state(cfg.state_file, state)

                    consecutive_failures = 0
                    time.sleep(cfg.scroll_interval_ms / 1000)

                except (PlaywrightTimeoutError, RuntimeError) as e:
                    consecutive_failures += 1
                    state["last_error"] = {
                        "code": "E_LOOP_OPERATION_FAILED",
                        "message": str(e),
                        "at": now_iso(),
                        "retry_count": consecutive_failures,
                    }
                    state["timestamps"]["updated_at"] = now_iso()
                    save_state(cfg.state_file, state)

                    if consecutive_failures > cfg.max_retries:
                        state["status"] = "interrupted"
                        state["last_error"] = {
                            "code": "E_RETRY_EXCEEDED",
                            "message": "max retries exceeded during collection loop",
                            "at": now_iso(),
                            "retry_count": consecutive_failures,
                        }
                        state["timestamps"]["updated_at"] = now_iso()
                        save_state(cfg.state_file, state)
                        browser.close()
                        return EXIT_RETRY_EXCEEDED

                    time.sleep(cfg.retry_wait_ms / 1000)

            state["status"] = "completed"
            state["timestamps"]["updated_at"] = now_iso()
            save_state(cfg.state_file, state)
            browser.close()

    except RuntimeError as e:
        state["status"] = "failed"
        state["last_error"] = {
            "code": "E_CONTAINER_NOT_FOUND",
            "message": str(e),
            "at": now_iso(),
            "retry_count": 0,
        }
        state["timestamps"]["updated_at"] = now_iso()
        save_state(cfg.state_file, state)
        print(f"[selector error] {e}", file=sys.stderr)
        return EXIT_SELECTOR_ERROR
    except OSError as e:
        print(f"[write error] {e}", file=sys.stderr)
        return EXIT_WRITE_ERROR
    except Exception as e:
        state["status"] = "failed"
        state["last_error"] = {
            "code": "E_UNEXPECTED",
            "message": str(e),
            "at": now_iso(),
            "retry_count": 0,
        }
        state["timestamps"]["updated_at"] = now_iso()
        save_state(cfg.state_file, state)
        print(f"[unexpected error] {e}", file=sys.stderr)
        return EXIT_UNEXPECTED

    if cfg.do_finalize:
        try:
            total, unique = finalize_raw_to_final(cfg.output_raw, cfg.output_final, cfg.dedupe_mode)
            print(f"[finalize] total={total}, unique={unique}, output={cfg.output_final}")
        except OSError as e:
            print(f"[write error] {e}", file=sys.stderr)
            return EXIT_WRITE_ERROR
        except Exception as e:
            print(f"[unexpected error] finalize failed: {e}", file=sys.stderr)
            return EXIT_UNEXPECTED

    print("[run] completed")
    return EXIT_OK


def finalize_command(args: argparse.Namespace) -> int:
    try:
        total, unique = finalize_raw_to_final(args.output_raw, args.output_final, args.dedupe_mode)
    except FileNotFoundError:
        print(f"[config error] raw file not found: {args.output_raw}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except OSError as e:
        print(f"[write error] {e}", file=sys.stderr)
        return EXIT_WRITE_ERROR
    except Exception as e:
        print(f"[unexpected error] {e}", file=sys.stderr)
        return EXIT_UNEXPECTED

    print(f"[finalize] total={total}, unique={unique}, output={args.output_final}")
    return EXIT_OK


def doctor_command(args: argparse.Namespace) -> int:
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=args.headless)
            page = browser.new_page()
            page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout_ms)

            container = page.locator(args.container)
            container_found = container.count() > 0
            
            result: dict[str, Any] = {
                "containerFound": container_found,
                "containerSelector": args.container,
            }
            
            if container_found:
                container.first.wait_for(state="visible", timeout=args.timeout_ms)
                
                # text_only モードの場合
                if args.text_only:
                    line_count = container.first.locator(args.line_selector).count()
                    result.update({
                        "mode": "text_only",
                        "lineCount": line_count,
                        "lineSelector": args.line_selector,
                    })
                else:
                    # 話者名付きモード（デフォルト）
                    entry_count = container.first.locator(args.entry_selector).count()
                    speaker_count = container.first.locator(args.speaker_selector).count()
                    text_count = container.first.locator(args.line_selector).count()
                    
                    # サンプルデータを取得
                    sample = None
                    if entry_count > 0:
                        sample = container.first.evaluate(
                            """
                            (el, config) => {
                              const entry = el.querySelector(config.entrySelector);
                              if (!entry) return null;
                              
                              const speakerEl = entry.querySelector(config.speakerSelector);
                              const textEl = entry.querySelector(config.lineSelector);
                              
                              const speakerRaw = (speakerEl?.innerText ?? speakerEl?.textContent ?? '').trim();
                              const text = (textEl?.innerText ?? textEl?.textContent ?? '').trim();
                              const speaker = speakerRaw.replace(/\\s+\\d+\\s*(時間|分間?|秒間?).*$/, '').trim();
                              
                              return { speaker, text };
                            }
                            """,
                            {
                                "entrySelector": args.entry_selector,
                                "speakerSelector": args.speaker_selector,
                                "lineSelector": args.line_selector,
                            },
                        )
                    
                    result.update({
                        "mode": "with_speaker",
                        "entryCount": entry_count,
                        "speakerCount": speaker_count,
                        "textCount": text_count,
                        "entrySelector": args.entry_selector,
                        "speakerSelector": args.speaker_selector,
                        "lineSelector": args.line_selector,
                        "sampleEntry": sample,
                    })

            print(json.dumps(result, ensure_ascii=False, indent=2))
            browser.close()

            if not container_found:
                return EXIT_SELECTOR_ERROR
            return EXIT_OK
    except Exception as e:
        print(f"[unexpected error] doctor failed: {e}", file=sys.stderr)
        return EXIT_UNEXPECTED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="スクロールテキスト収集CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="スクロール収集を実行")
    run.add_argument("--url", type=str, default=None)
    run.add_argument("--container", type=str, default=None)
    run.add_argument("--line-selector", dest="line_selector", type=str, default=None)
    run.add_argument("--output-raw", type=Path, default=Path("./raw_output.txt"))
    run.add_argument("--output-final", type=Path, default=Path("./final_output.txt"))
    run.add_argument("--state-file", type=Path, default=Path("./state.json"))
    run.add_argument("--resume", action="store_true")
    run.add_argument("--max-idle-scrolls", type=int, default=8)
    run.add_argument("--scroll-step", type=int, default=400)
    run.add_argument("--scroll-interval-ms", type=int, default=600)
    run.add_argument("--checkpoint-interval", type=int, default=5)
    run.add_argument("--max-retries", type=int, default=3)
    run.add_argument("--retry-wait-ms", type=int, default=1000)
    run.add_argument("--dedupe-mode", choices=["exact"], default="exact")
    run.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--timeout-ms", type=int, default=30000)
    run.add_argument("--log-level", choices=["debug", "info", "warn", "error"], default="info")
    run.add_argument("--finalize", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--connect-existing", action="store_true", help="既存のデバッグモードブラウザに接続")
    run.add_argument("--debug-port", type=int, default=9222, help="デバッグポート番号")
    run.add_argument("--text-only", action="store_true", help="本文のみ取得（話者名なし）")
    run.add_argument("--entry-selector", type=str, default='[class^="baseEntry-"]', help="エントリ親要素のセレクタ")
    run.add_argument("--speaker-selector", type=str, default='[id^="timestampSpeakerAriaLabel-"]', help="話者名要素のセレクタ")
    run.set_defaults(func=run_command)

    fin = sub.add_parser("finalize", help="rawから最終出力を生成")
    fin.add_argument("--output-raw", type=Path, default=Path("./raw_output.txt"))
    fin.add_argument("--output-final", type=Path, default=Path("./final_output.txt"))
    fin.add_argument("--dedupe-mode", choices=["exact"], default="exact")
    fin.set_defaults(func=finalize_command)

    doc = sub.add_parser("doctor", help="セレクタ事前検証")
    doc.add_argument("--url", type=str, required=True)
    doc.add_argument("--container", type=str, required=True)
    doc.add_argument("--line-selector", dest="line_selector", type=str, default='[class^="entryText-"]')
    doc.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    doc.add_argument("--timeout-ms", type=int, default=30000)
    doc.add_argument("--text-only", action="store_true", help="本文のみ取得（話者名なし）")
    doc.add_argument("--entry-selector", type=str, default='[class^="baseEntry-"]', help="エントリ親要素のセレクタ")
    doc.add_argument("--speaker-selector", type=str, default='[id^="timestampSpeakerAriaLabel-"]', help="話者名要素のセレクタ")
    doc.set_defaults(func=doctor_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
