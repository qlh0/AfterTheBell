## 《那天放学后》主流程
##
## 设计边界：
## - 客户端不判断剧情，只渲染后端返回的白名单 scene_id / sprite_id 与文本；
## - 一次玩家输入 = 一次 HTTP 请求 = 一次角色回复（无流式）；
## - 后端是唯一权威状态，存档只记录 game_id + state_version。

image bg classroom = "images/bg_classroom.png"
image bg school_gate = "images/bg_school_gate.png"
image bg corridor = "images/bg_corridor.png"
image bg library = "images/bg_library.png"
image bg shop = "images/bg_shop.png"
image xuzhi normal = "images/xuzhi_normal.png"
image xuzhi guarded = "images/xuzhi_guarded.png"
image xuzhi smile = "images/xuzhi_smile.png"
image xuzhi shy = "images/xuzhi_shy.png"
image xuzhi surprised = "images/xuzhi_surprised.png"

transform sprite_pos:
    xalign 0.5
    yalign 1.0
    fit "scale-down"
    xysize (1280, 720)

default persistent.endings_seen = {}

default game_id = None
default state_version = 0
default turn_index = 0
default scene_id = "classroom"
default day = 1
default day_label = "第一天"
default sprite_id = "xuzhi_guarded"
default displayed_scene = None
default displayed_sprite = None
default pending_day_break = None
default pending_day_presentation = None
default pending_day_plan = False
default day_plan_opening = ""
default selfcheck_ending_id = "romance"
default current_event_title = None
default chat_log = []
default current_narration = []
default current_dialogue = ""
default panel_mode = "dialogue"
default input_text = ""
default suggestions = []
default used_suggestions = []
default log_expanded = False
default ending_data = None
default backend_ok = False
default backend_error = ""
default selfcheck_mode = False
default selfcheck_shot_name = "chat"


label splashscreen:
    if os.environ.get("ATB_SELFCHECK"):
        jump selfcheck
    return


label selfcheck:
    $ selfcheck_mode = True
    $ atb_selfcheck_reset()
    $ atb_selfcheck_note("boot=%s" % atb_boot())
    $ atb_selfcheck_note("bg_images=%s" % ",".join(sorted(i for i in renpy.list_images() if i.startswith("bg "))))
    $ _err = atb_start()
    $ atb_selfcheck_note("start_err=%r" % (_err,))
    if _err is None:
        $ atb_selfcheck_note("game_id=%s" % game_id)
        $ atb_render_scene(transition=False)
        $ selfcheck_shot_name = "chat_start"
        $ _res_start = renpy.call_screen("chat_ui")
        $ atb_selfcheck_note("start_screen_ok res=%r" % (_res_start,))
        $ _err = atb_send("你最近是不是在躲我？")
        $ atb_selfcheck_note("send_err=%r turn=%d version=%d" % (_err, turn_index, state_version))
        $ panel_mode = "dialogue"
        $ _sug_before = len(atb_visible_suggestions())
        $ atb_mark_suggestion_used(suggestions[0]["text"]) if suggestions else None
        $ atb_selfcheck_note("suggestions_filtered %d->%d" % (_sug_before, len(atb_visible_suggestions())))
        $ atb_render_scene(transition=False)
        $ selfcheck_shot_name = "chat_dialogue"
        $ _res = renpy.call_screen("chat_ui")
        $ atb_selfcheck_note("screen_ok res=%r" % (_res,))
        $ _err = atb_advance()
        $ atb_selfcheck_note("advance_err=%r scene=%s sprite=%s" % (_err, scene_id, sprite_id))
        $ _err = atb_advance()
        $ atb_selfcheck_note("advance2_err=%r pending_plan=%r" % (_err, pending_day_plan))
    $ atb_selfcheck_note("chat_log=%d suggestions=%d" % (len(chat_log), len(suggestions)))
    $ atb_render_scene(transition=False)
    $ selfcheck_shot_name = "chat"
    $ log_expanded = False
    $ _res = renpy.call_screen("chat_ui")
    $ atb_selfcheck_note("screen2_ok res=%r" % (_res,))
    $ selfcheck_shot_name = "chat_log"
    $ log_expanded = True
    $ _res_log = renpy.call_screen("chat_ui")
    $ atb_selfcheck_note("log_screen_ok res=%r" % (_res_log,))
    $ log_expanded = False
    python:
        for _sid in ("corridor", "library", "shop"):
            scene_id = _sid
            day = 1
            day_label = "第一天"
            displayed_scene = None
            atb_render_scene(transition=False)
            selfcheck_shot_name = "scene_" + _sid
            renpy.call_screen("chat_ui")
    $ atb_selfcheck_note("scene_tour_ok")
    $ atb_apply_presentation({"day": 2, "day_label": "第二天", "scene_id": "classroom", "sprite_id": "xuzhi_normal"})
    $ atb_selfcheck_note("day_deferred day=%s scene=%s pending=%r" % (day, scene_id, pending_day_break))
    $ atb_commit_presentation(pending_day_presentation)
    $ pending_day_presentation = None
    $ atb_selfcheck_note("day_committed day=%s scene=%s" % (day, scene_id))
    $ pending_day_break = None
    $ pending_day_plan = False
    $ atb_selfcheck_note("day_transition_apply_ok")
    $ atb_render_scene(transition=False)
    $ _plan_text = renpy.call_screen("day_plan")
    $ _plan_err = atb_submit_day_plan(_plan_text)
    $ atb_selfcheck_note("day_plan_ok err=%r opening=%s" % (_plan_err, day_plan_opening))
    $ _res_day = renpy.call_screen("day_break", day_label="第二天")
    $ atb_selfcheck_note("day_break_ok res=%r" % (_res_day,))
    $ atb_selfcheck_note("ending_begin")
    python:
        import json
        with open(os.path.join(config.gamedir, "..", "content", "endings.json"), encoding="utf-8") as _f:
            _all_endings = json.load(_f)["endings"]
        for _eid in ("romance", "friends", "missed"):
            selfcheck_ending_id = _eid
            _ending_res = renpy.call_screen("ending_view", _all_endings[_eid])
            atb_selfcheck_note("ending_%s_ok res=%r" % (_eid, _ending_res))
    $ selfcheck_mode = False
    $ atb_selfcheck_note("done")
    $ renpy.quit()


label start:
    $ quick_menu = False
    $ chat_log = []
    $ input_text = ""
    $ suggestions = []
    $ log_expanded = False
    $ ending_data = None
    $ pending_day_break = None
    $ pending_day_presentation = None
    $ pending_day_plan = False
    $ day_plan_opening = ""
    $ displayed_scene = None
    $ displayed_sprite = None
    $ game_id = None
    $ state_version = 0
    $ turn_index = 0
    $ current_event_title = None

    call boot_backend

    $ _err = atb_start()
    if _err is not None:
        call screen backend_down(_err)
        $ _err = atb_start()
        if _err is not None:
            return

    jump chat_loop


label boot_backend:
    while not atb_boot():
        call screen backend_down(backend_error)
    return


label chat_loop:
    $ atb_render_scene()
    $ _res = renpy.call_screen("chat_ui")

    if _res is None:
        return

    if _res[0] == "quit":
        if renpy.confirm("结束本局并回到标题？"):
            $ quick_menu = True
            return
        jump chat_loop

    # 上一轮已经把跨天状态交回来；先让玩家看完，再转场。
    if pending_day_break:
        $ _day_break_label = pending_day_break
        $ pending_day_break = None
        call screen day_break(_day_break_label)
        $ atb_commit_presentation(pending_day_presentation)
        $ pending_day_presentation = None
        $ atb_render_scene(transition=False)

    if pending_day_plan:
        $ pending_day_plan = False
        $ _plan_text = renpy.call_screen("day_plan")
        $ _plan_err = atb_submit_day_plan(_plan_text)
        if _plan_err is None:
            jump chat_loop
        $ atb_log_error(_plan_err)

    if _res[0] == "advance":
        $ _err = atb_advance()
    else:
        $ input_text = ""
        $ _err = atb_send(_res[1])

    if _err is not None:
        $ atb_log_error(_err)

    if ending_data is not None:
        jump ending_scene

    jump chat_loop


label ending_scene:
    $ renpy.hide_screen("chat_ui")
    $ _ending = ending_data

    scene bg school_gate with fade
    show xuzhi smile at sprite_pos with dissolve

    call screen ending_view(_ending)

    $ persistent.endings_seen = dict(persistent.endings_seen or {})
    $ persistent.endings_seen[_ending["id"]] = True
    $ quick_menu = True
    return


label after_load:
    $ _load_status = atb_after_load()

    if _load_status == "offline":
        call screen backend_down("读取存档需要后端在线才能继续。")
    elif _load_status == "no_game":
        $ renpy.notify("这个存档里没有对局信息，请重新开始。")
    elif _load_status:
        $ renpy.notify("存档与服务器状态已对齐。")

    return
