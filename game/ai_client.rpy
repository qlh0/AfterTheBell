## 与后端通信的唯一出口。
## 所有网络调用都集中在这里：Ren'Py 其它脚本不直接碰 HTTP。
## 首版使用普通 HTTP/JSON（renpy.fetch），一次请求拿完整结果，不做流式。

init -10 python:
    import os
    import uuid

    ATB_API_BASE = os.environ.get("ATB_API_URL", "http://127.0.0.1:8756")

    def atb_new_request_id():
        return "req_" + uuid.uuid4().hex[:12]

    def atb_http(path, payload=None, timeout=45):
        """返回 (data, error)。任何失败都变成可展示的错误字符串，不抛异常。"""
        url = ATB_API_BASE + path
        try:
            if payload is None:
                data = renpy.fetch(url, method="GET", timeout=timeout, result="json")
            else:
                data = renpy.fetch(url, method="POST", json=payload, timeout=timeout, result="json")
        except Exception as e:
            return None, str(e)
        if isinstance(data, dict) and data.get("error"):
            return None, str(data.get("detail") or data["error"])
        return data, None

    def atb_boot():
        """启动时探活：后端没起来就给出明确提示，而不是白屏等超时。"""
        data, err = atb_http("/health", timeout=6)
        if err:
            store.backend_ok = False
            store.backend_error = err
            return False
        store.backend_ok = True
        store.backend_error = ""
        return True

    def atb_apply_presentation(presentation):
        store.scene_id = presentation.get("scene_id", "classroom")
        store.sprite_id = presentation.get("sprite_id", "xuzhi_guarded")
        store.current_event_title = presentation.get("event_title")

    def atb_render_scene(transition=True):
        """按后端给的白名单 scene/sprite 切换画面；不执行任何模型输出的代码。"""
        changed = False
        if store.displayed_scene != store.scene_id:
            renpy.scene()
            renpy.show("bg " + store.scene_id)
            store.displayed_scene = store.scene_id
            store.displayed_sprite = None
            changed = True
        sprite = store.sprite_id.replace("xuzhi_", "xuzhi ")
        if store.displayed_sprite != store.sprite_id:
            renpy.show(sprite, at_list=[sprite_pos])
            store.displayed_sprite = store.sprite_id
            changed = True
        if changed and transition:
            renpy.with_statement(Dissolve(0.25))

    def atb_append(who, text):
        store.chat_log.append({"who": who, "text": text})
        if len(store.chat_log) > 80:
            store.chat_log = store.chat_log[-80:]

    def atb_set_turn(narration, dialogue):
        """底部面板分页：有旁白先只显示旁白，点「继续」才进入对话页。"""
        store.current_narration = list(narration or [])
        store.current_dialogue = dialogue or ""
        store.panel_mode = "narration" if store.current_narration else "dialogue"

    def atb_visible_suggestions():
        """已经点过/发过的建议不再出现；同一轮里相同文本只留一个。"""
        seen = set()
        out = []
        for sug in store.suggestions:
            text = (sug.get("text") or "").strip()
            if not text or text in store.used_suggestions or text in seen:
                continue
            seen.add(text)
            out.append(sug)
        return out

    def atb_mark_suggestion_used(text):
        text = (text or "").strip()
        if text and text not in store.used_suggestions:
            store.used_suggestions.append(text)
            if len(store.used_suggestions) > 100:
                store.used_suggestions = store.used_suggestions[-100:]

    def atb_start():
        store.chat_log = []
        store.used_suggestions = []
        data, err = atb_http("/game/start", {}, timeout=15)
        if err:
            return err
        store.game_id = data["game_id"]
        store.state_version = data["state_version"]
        store.turn_index = (data.get("state") or {}).get("turn", {}).get("index", 0)
        store.ending_data = None
        for line in data.get("narration", []):
            atb_append("narrator", line)
        atb_append("xuzhi", data.get("dialogue", ""))
        atb_set_turn(data.get("narration", []), data.get("dialogue", ""))
        atb_apply_presentation(data["presentation"])
        store.suggestions = data.get("suggestions", []) or []
        return None

    def atb_consume(data):
        store.state_version = data["state_version"]
        store.turn_index = data["turn"]["index"]
        for line in data.get("narration", []):
            atb_append("narrator", line)
        if data.get("dialogue"):
            atb_append("xuzhi", data["dialogue"])
        atb_set_turn(data.get("narration", []), data.get("dialogue", ""))
        atb_apply_presentation(data["presentation"])
        store.suggestions = data.get("suggestions", []) or []
        if data.get("ending"):
            store.ending_data = data["ending"]

    def atb_send(text):
        text = (text or "").strip()
        if not text:
            return "empty_text"
        atb_mark_suggestion_used(text)
        atb_append("player", text)
        payload = {
            "text": text,
            "request_id": atb_new_request_id(),
            "expected_state_version": store.state_version,
        }
        renpy.show_screen("thinking_overlay")
        renpy.pause(0.05, hard=True)
        data, err = atb_http("/game/%s/interact" % store.game_id, payload, timeout=60)
        renpy.hide_screen("thinking_overlay")
        if err:
            return err
        atb_consume(data)
        return None

    def atb_advance():
        payload = {
            "request_id": atb_new_request_id(),
            "expected_state_version": store.state_version,
            "intent": "continue",
        }
        renpy.show_screen("thinking_overlay")
        renpy.pause(0.05, hard=True)
        data, err = atb_http("/game/%s/advance" % store.game_id, payload, timeout=45)
        renpy.hide_screen("thinking_overlay")
        if err:
            return err
        store.state_version = data["state_version"]
        store.turn_index = data["turn"]["index"]
        for line in data.get("narration", []):
            atb_append("narrator", line)
        atb_set_turn(data.get("narration", []), data.get("dialogue", ""))
        atb_apply_presentation(data["presentation"])
        store.suggestions = data.get("suggestions", []) or []
        return None

    def atb_sync():
        data, err = atb_http("/game/%s/state" % store.game_id, timeout=10)
        if err:
            return err
        store.state_version = data.get("state_version", store.state_version)
        turn = (data.get("state") or {}).get("turn") or {}
        store.turn_index = turn.get("index", store.turn_index)
        return None

    def atb_log_error(err):
        if "409" in str(err) or "conflict" in str(err).lower():
            atb_sync()
            atb_append("narrator", "（状态已同步，刚才那句话没有送达，再说一次吧。）")
        elif "404" in str(err):
            atb_append("narrator", "（找不到这一局的存档，请重新开始。）")
        else:
            atb_append("narrator", "（消息没有送达：%s）" % err)

    def atb_after_load():
        """读档：以服务端快照为准，必要时把服务器回退到存档点。"""
        if not store.game_id:
            return "no_game"
        data, err = atb_http("/game/%s/state" % store.game_id, timeout=10)
        if err:
            store.backend_ok = False
            store.backend_error = err
            return "offline"
        remote = int(data.get("state_version", 0))
        if remote == int(store.state_version):
            pass
        elif remote > int(store.state_version):
            res, err2 = atb_http("/game/%s/restore/%d" % (store.game_id, int(store.state_version)), {}, timeout=20)
            if err2:
                return err2
            store.state_version = res["state_version"]
        else:
            store.state_version = remote
        store.displayed_scene = None
        store.displayed_sprite = None
        atb_render_scene(transition=False)
        return None

    def atb_screenshot(name):
        """开发自检用：把当前画面存到 game/ 下，便于核对 UI。"""
        try:
            renpy.screenshot(os.path.join(config.gamedir, "shot_%s.png" % name))
        except Exception:
            pass

    def atb_selfcheck_reset():
        for path in (os.path.join(config.gamedir, "selfcheck.txt"),
                     r"D:\AfterTheBell\game\selfcheck.txt"):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    def atb_selfcheck_note(line):
        """开发自检用：每步立刻落盘，卡住也能看出走到哪一步。"""
        for path in (os.path.join(config.gamedir, "selfcheck.txt"),
                     r"D:\AfterTheBell\game\selfcheck.txt"):
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(str(line) + "\n")
                return True
            except Exception:
                continue
        print("ATB_SELFCHECK " + str(line))
        return False
