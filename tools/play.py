"""终端模拟一局完整游戏（不启动 Ren'Py）。

用法：
    python tools/play.py --route communicate      # 主动沟通
    python tools/play.py --route control          # 过度干预
    python tools/play.py --route avoid            # 持续回避
    python tools/play.py --interactive            # 手动输入
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db import Database  # noqa: E402
from app.engine import Engine, EndingCommitted  # noqa: E402

ROUTES = {
    "communicate": [
        "你最近是不是在躲我？",
        "我不是想打扰你，只是有点担心你。",
        "我想问问，是不是跟那句话有关？",
        "我那天是在说陈屿他们班的事，真的不是说你。",
        "你想报理科重点班的话，我觉得挺好的，你自己决定就好。反正分班以后，我们还能一起走吧？",
        "不管考不考得上，我都支持你。分班以后，也还是能见面吧。",
        "其实我喜欢你，很久了。",
        "如果你需要时间，我可以等。",
        "你今天看起来轻松了一点。",
        "分班的事，你想好了吗？分班以后我们还能这样一起走吗？",
        "我喜欢你，不管下学期怎么分班。",
    ],
    "control": [
        "你不许去重点班，听我的。",
        "我是为了你好，你必须听我的。",
        "对不起，我刚才语气太重了。",
        "那句话，我是不是说错什么了？",
        "我那天是在说陈屿他们班，真的不是说你。",
        "你想报就报，我不该替你决定。",
        "我尊重你的选择，真的。",
        "不管考不考得上，我都还是你的朋友。",
        "刚才是我太急了，别往心里去。",
        "分班的事，你自己决定就好。",
        "分班的事我尊重你，我只想陪你走一段。",
    ],
    "avoid": [
        "嗯。", "哦。", "这样啊。", "哈哈。", "今天好热。", "食堂好多人。",
    ] * 5,
}


def show_turn(data: dict, text: str, verbose: bool) -> None:
    print(f"\n你   > {text}")
    for line in data.get("narration", []):
        print(f"     * {line}")
    print(f"许栀 > {data['dialogue']}")
    if data.get("ui_hints", {}).get("mood_shift"):
        print(f"     （{data['ui_hints']['mood_shift']}）")
    if verbose:
        changes = [f"{c['path']}={c['after']}" for c in data.get("committed_changes", [])]
        print(f"     [turn {data['turn']['index']} | 推进 {data['turn']['progress']}/"
              f"{data['turn']['budget']} | {data['planning_status']} | {', '.join(changes)}]")


def run_route(engine: Engine, route: str, verbose: bool) -> None:
    start = engine.start()
    game_id = start["game_id"]
    print(f"=== 开局 {game_id} ===")
    for line in start["narration"]:
        print(f"     * {line}")
    print(f"许栀 > {start['dialogue']}")

    for text in ROUTES[route]:
        try:
            data = engine.interact(game_id, text, "req_" + uuid.uuid4().hex[:12])
        except EndingCommitted:
            break
        show_turn(data, text, verbose)
        if data.get("ending"):
            print_ending(data["ending"])
            return

    # 剧本用完后继续沉默几轮，让结局自然收束
    for _ in range(10):
        try:
            data = engine.interact(game_id, "嗯。", "req_" + uuid.uuid4().hex[:12])
        except EndingCommitted:
            return
        show_turn(data, "嗯。", verbose)
        if data.get("ending"):
            print_ending(data["ending"])
            return


def print_ending(ending: dict) -> None:
    print(f"\n=== 结局：{ending['title']}（{ending['id']}）===")
    for line in ending["epilogue"]:
        print(f"     {line}")
    print(f"     {ending['closing_line']}")


def run_interactive(engine: Engine, verbose: bool) -> None:
    start = engine.start()
    game_id = start["game_id"]
    print(f"=== 开局 {game_id}（输入 :quit 退出，:advance 推进）===")
    for line in start["narration"]:
        print(f"     * {line}")
    print(f"许栀 > {start['dialogue']}")

    while True:
        try:
            text = input("\n你   > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text in (":quit", ":q"):
            break
        try:
            if text == ":advance":
                data = engine.advance(game_id, "req_" + uuid.uuid4().hex[:12])
                for line in data["narration"]:
                    print(f"     * {line}")
                continue
            data = engine.interact(game_id, text, "req_" + uuid.uuid4().hex[:12])
        except EndingCommitted as exc:
            print(f"（本局已结束：{exc.ending_id}）")
            break
        show_turn(data, text, verbose)
        if data.get("ending"):
            ending = data["ending"]
            print(f"\n=== 结局：{ending['title']} ===")
            for line in ending["epilogue"]:
                print(f"     {line}")
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="After the Bell 终端试玩")
    parser.add_argument("--route", choices=sorted(ROUTES), default="communicate")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--keep-db", action="store_true", help="保留数据库文件以便检查")
    args = parser.parse_args()

    if args.keep_db:
        db_path = ROOT / "backend" / "data" / "play.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"（数据库：{db_path}）")
    else:
        db_path = Path(tempfile.mkdtemp()) / "play.db"

    engine = Engine(Database(db_path))
    if args.interactive:
        run_interactive(engine, args.verbose)
    else:
        run_route(engine, args.route, args.verbose)


if __name__ == "__main__":
    main()
