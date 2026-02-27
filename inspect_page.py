#!/usr/bin/env python3
"""
ページ構造診断スクリプト

既存のデバッグモードブラウザに接続し、現在開いているページの構造を分析して、
正しいセレクタを特定します。
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def analyze_page_structure(page: Any) -> dict[str, Any]:
    """ページ構造を分析してセレクタ候補を返す"""
    
    result = page.evaluate("""
        () => {
            const result = {
                containerCandidates: [],
                textElementCandidates: [],
                speakerElementCandidates: [],
                entryElementCandidates: [],
                recommendations: {}
            };
            
            // 1. スクロール可能なコンテナを検索
            const allElements = document.querySelectorAll('*');
            const containerCandidates = [];
            
            // 既存のセレクタをチェック
            const oldContainer = document.querySelector('#scrollToTargetTargetedFocusZone');
            result.containerCandidates.push({
                selector: '#scrollToTargetTargetedFocusZone',
                found: !!oldContainer,
                reason: oldContainer ? 'Found' : 'Element not found (likely changed)'
            });
            
            // スクロール可能な要素を検索
            allElements.forEach(el => {
                const style = window.getComputedStyle(el);
                const overflow = style.overflow + style.overflowY;
                const hasScroll = overflow.includes('auto') || overflow.includes('scroll');
                const hasHeight = el.scrollHeight > el.clientHeight;
                
                if (hasScroll && hasHeight && el.scrollHeight > 500) {
                    const id = el.id;
                    const classes = Array.from(el.classList).join('.');
                    let selector = '';
                    
                    if (id) {
                        selector = '#' + id;
                    } else if (classes) {
                        selector = '.' + classes;
                    } else {
                        selector = el.tagName.toLowerCase();
                    }
                    
                    containerCandidates.push({
                        selector: selector,
                        found: true,
                        elementCount: 1,
                        hasOverflow: true,
                        dimensions: {
                            width: el.clientWidth,
                            height: el.clientHeight,
                            scrollHeight: el.scrollHeight
                        },
                        childCount: el.children.length,
                        id: id || '',
                        classes: classes || ''
                    });
                }
            });
            
            // 重複を除去してスコアリング
            const uniqueContainers = [];
            const seen = new Set();
            containerCandidates.forEach(c => {
                if (!seen.has(c.selector)) {
                    seen.add(c.selector);
                    // スコアリング: scrollHeight が大きく、子要素が多いものを優先
                    c.score = (c.dimensions?.scrollHeight || 0) / 100 + (c.childCount || 0);
                    uniqueContainers.push(c);
                }
            });
            
            uniqueContainers.sort((a, b) => (b.score || 0) - (a.score || 0));
            result.containerCandidates.push(...uniqueContainers.slice(0, 5));
            
            // 2. 最も有望なコンテナを選択
            const bestContainer = uniqueContainers[0];
            if (!bestContainer) {
                return result;
            }
            
            const containerEl = document.querySelector(bestContainer.selector);
            if (!containerEl) {
                return result;
            }
            
            // 3. コンテナ内のテキスト要素を分析
            const textPatterns = [
                '[class*="text"]',
                '[class*="entry"]',
                '[class*="message"]',
                '[class*="content"]',
                '[class*="line"]'
            ];
            
            textPatterns.forEach(pattern => {
                const elements = containerEl.querySelectorAll(pattern);
                if (elements.length > 0) {
                    const sample = elements[0];
                    const text = (sample.innerText || sample.textContent || '').trim();
                    
                    // より具体的なセレクタを生成
                    let specificSelector = pattern;
                    if (sample.className) {
                        const classes = Array.from(sample.classList);
                        if (classes.length > 0) {
                            // class名のプレフィックスマッチを試みる
                            const firstClass = classes[0];
                            const prefix = firstClass.split('-')[0];
                            if (prefix) {
                                specificSelector = `[class^="${prefix}-"]`;
                            }
                        }
                    }
                    
                    result.textElementCandidates.push({
                        selector: specificSelector,
                        count: elements.length,
                        sampleText: text.substring(0, 100),
                        tagName: sample.tagName.toLowerCase()
                    });
                }
            });
            
            // 4. 話者名要素を分析
            const speakerPatterns = [
                '[id*="speaker"]',
                '[id*="timestamp"]',
                '[class*="speaker"]',
                '[class*="author"]',
                '[class*="name"]'
            ];
            
            speakerPatterns.forEach(pattern => {
                const elements = containerEl.querySelectorAll(pattern);
                if (elements.length > 0) {
                    const sample = elements[0];
                    const text = (sample.innerText || sample.textContent || '').trim();
                    
                    // より具体的なセレクタを生成
                    let specificSelector = pattern;
                    if (sample.id) {
                        const idPrefix = sample.id.split('-')[0];
                        if (idPrefix) {
                            specificSelector = `[id^="${idPrefix}-"]`;
                        }
                    }
                    
                    result.speakerElementCandidates.push({
                        selector: specificSelector,
                        count: elements.length,
                        sampleText: text.substring(0, 100),
                        tagName: sample.tagName.toLowerCase()
                    });
                }
            });
            
            // 5. エントリ親要素を分析
            const entryPatterns = [
                '[class*="entry"]',
                '[class*="item"]',
                '[class*="row"]'
            ];
            
            entryPatterns.forEach(pattern => {
                const elements = containerEl.querySelectorAll(pattern);
                if (elements.length > 0) {
                    const sample = elements[0];
                    
                    // より具体的なセレクタを生成
                    let specificSelector = pattern;
                    if (sample.className) {
                        const classes = Array.from(sample.classList);
                        if (classes.length > 0) {
                            const firstClass = classes[0];
                            const prefix = firstClass.split('-')[0];
                            if (prefix) {
                                specificSelector = `[class^="${prefix}-"]`;
                            }
                        }
                    }
                    
                    result.entryElementCandidates.push({
                        selector: specificSelector,
                        count: elements.length,
                        tagName: sample.tagName.toLowerCase()
                    });
                }
            });
            
            // 6. 推奨セレクタを決定
            result.recommendations = {
                container: bestContainer.selector,
                textElement: result.textElementCandidates[0]?.selector || '[class^="entryText-"]',
                speakerElement: result.speakerElementCandidates[0]?.selector || '[id^="timestampSpeakerAriaLabel-"]',
                entryElement: result.entryElementCandidates[0]?.selector || '[class^="baseEntry-"]',
                confidence: bestContainer.score > 50 ? 'high' : 'medium'
            };
            
            return result;
        }
    """)
    
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="ページ構造診断スクリプト")
    parser.add_argument("--connect-existing", action="store_true", help="既存のデバッグモードブラウザに接続")
    parser.add_argument("--debug-port", type=int, default=9222, help="デバッグポート番号")
    parser.add_argument("--url", type=str, help="診断対象URL（新規ブラウザ起動時）")
    parser.add_argument("--output", type=Path, default=Path("page_structure.json"), help="出力ファイル")
    parser.add_argument("--headless", action="store_true", help="ヘッドレスモード")
    
    args = parser.parse_args()
    
    if not args.connect_existing and not args.url:
        print("エラー: --connect-existing または --url のいずれかを指定してください", file=sys.stderr)
        return 1
    
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            if args.connect_existing:
                print(f"[接続中] デバッグポート {args.debug_port} のブラウザに接続しています...")
                browser = p.chromium.connect_over_cdp(f"http://localhost:{args.debug_port}")
                context = browser.contexts[0]
                
                # すべてのタブを列挙
                all_pages = context.pages
                print(f"[タブ検出] {len(all_pages)} 個のタブが見つかりました")
                
                # chrome:// と devtools:// 以外のタブを探す
                valid_pages = [p for p in all_pages
                              if not p.url.startswith('chrome://')
                              and not p.url.startswith('devtools://')]
                
                if not valid_pages:
                    print("[エラー] 有効なタブが見つかりません。chrome:// や devtools:// 以外のページを開いてください。", file=sys.stderr)
                    browser.close()
                    return 1
                
                # 複数の有効なタブがある場合は選択させる
                if len(valid_pages) > 1:
                    print("\n[タブ選択] 複数の有効なタブが見つかりました:")
                    for i, p in enumerate(valid_pages, 1):
                        # URLを短縮表示
                        url_display = p.url if len(p.url) <= 100 else p.url[:97] + "..."
                        print(f"  {i}. {url_display}")
                    
                    # ユーザーに選択させる
                    try:
                        choice = input(f"\n使用するタブの番号を入力してください (1-{len(valid_pages)}, デフォルト: 1): ").strip()
                        if choice == "":
                            choice = "1"
                        tab_index = int(choice) - 1
                        if tab_index < 0 or tab_index >= len(valid_pages):
                            print(f"[警告] 無効な番号です。最初のタブを使用します。")
                            tab_index = 0
                    except (ValueError, KeyboardInterrupt):
                        print(f"\n[警告] 入力が無効です。最初のタブを使用します。")
                        tab_index = 0
                    
                    page = valid_pages[tab_index]
                else:
                    page = valid_pages[0]
                
                print(f"[接続完了] 現在のURL: {page.url}")
            else:
                print(f"[起動中] 新しいブラウザを起動しています...")
                browser = p.chromium.launch(headless=args.headless)
                page = browser.new_page()
                print(f"[移動中] {args.url} に移動しています...")
                page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
                print(f"[完了] ページを読み込みました")
            
            print("\n[分析中] ページ構造を分析しています...")
            result = analyze_page_structure(page)
            
            # 結果を保存
            with args.output.open("w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            print(f"\n[保存完了] 結果を {args.output} に保存しました\n")
            
            # 結果をコンソールに表示
            print("=" * 80)
            print("診断結果")
            print("=" * 80)
            
            print("\n【コンテナ候補】")
            for i, c in enumerate(result["containerCandidates"][:3], 1):
                print(f"\n{i}. {c['selector']}")
                print(f"   見つかった: {c['found']}")
                if c.get('dimensions'):
                    print(f"   サイズ: {c['dimensions']['width']}x{c['dimensions']['height']}")
                    print(f"   スクロール高さ: {c['dimensions']['scrollHeight']}")
                    print(f"   子要素数: {c.get('childCount', 0)}")
            
            print("\n【テキスト要素候補】")
            for i, t in enumerate(result["textElementCandidates"][:3], 1):
                print(f"\n{i}. {t['selector']}")
                print(f"   要素数: {t['count']}")
                print(f"   サンプル: {t['sampleText'][:50]}...")
            
            print("\n【話者名要素候補】")
            for i, s in enumerate(result["speakerElementCandidates"][:3], 1):
                print(f"\n{i}. {s['selector']}")
                print(f"   要素数: {s['count']}")
                print(f"   サンプル: {s['sampleText'][:50]}...")
            
            print("\n【推奨セレクタ】")
            rec = result.get("recommendations", {})
            if rec:
                print(f"コンテナ: {rec.get('container', 'N/A')}")
                print(f"テキスト要素: {rec.get('textElement', 'N/A')}")
                print(f"話者名要素: {rec.get('speakerElement', 'N/A')}")
                print(f"エントリ要素: {rec.get('entryElement', 'N/A')}")
                print(f"信頼度: {rec.get('confidence', 'N/A')}")
            else:
                print("推奨セレクタが見つかりませんでした。")
            
            if rec and rec.get('container'):
                print("\n【推奨コマンド】")
                print("\n# doctorコマンドで検証:")
                print(f"python scroll_copy.py doctor \\")
                print(f"  --url \"{page.url}\" \\")
                print(f"  --container \"{rec.get('container', '')}\" \\")
                print(f"  --line-selector \"{rec.get('textElement', '')}\" \\")
                print(f"  --entry-selector \"{rec.get('entryElement', '')}\" \\")
                print(f"  --speaker-selector \"{rec.get('speakerElement', '')}\"")
                
                print("\n# 実行コマンド (既存ブラウザ接続):")
                print(f"python scroll_copy.py run \\")
                print(f"  --connect-existing \\")
                print(f"  --container \"{rec.get('container', '')}\" \\")
                print(f"  --line-selector \"{rec.get('textElement', '')}\" \\")
                print(f"  --entry-selector \"{rec.get('entryElement', '')}\" \\")
                print(f"  --speaker-selector \"{rec.get('speakerElement', '')}\" \\")
                print(f"  --output-raw \"./out/raw_output.txt\" \\")
                print(f"  --output-final \"./out/final_output.txt\"")
            else:
                print("\n【推奨コマンド】")
                print("適切なセレクタが見つかりませんでした。")
                print("ブラウザのDevToolsで手動で調査することをお勧めします。")
            
            print("\n" + "=" * 80)
            
            browser.close()
            return 0
            
    except Exception as e:
        print(f"\n[エラー] {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob
