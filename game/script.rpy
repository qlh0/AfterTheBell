## 《那天放学后》主流程
##
## 设计边界：
## - 客户端不判断剧情，只渲染后端返回的白名单 scene_id / sprite_id 与文本；
## - 一次玩家输入 = 一次 HTTP 请求 = 一次角色回复（无流式）；
## - 后端是唯一权威状态，存档只记录 game_id + state_version。

image bg classroom = "images/bg_classroom.png"
image bg school_gate = "images/bg_school_gate.png"
image xuzhi normal = "images/xuzhi_normal.png"
image xuzhi guarded = "images/xuzhi_guarded.png"
image xuzhi smile = "images/xuzhi_smile.png"

transform sprite_pos:
    xalign 0.07
    yalign 1.0
    yoffset 24

default persistent.endings_seen = {}

default game_id = None
default state_version = 0
default turn_index = 0
default scene_id = "classroom"
default sprite_id = "xuzhi_guarded"
default displayed_scene = None
default displayed_sprite = None
default current_event_title = None
default chat_log = []
default input_text = ""
default ending_data = None
default backend_ok = False
default backend_error = ""
default selfcheck_mode = False


label splashscreen:
    if os.environ.get("ATB_SELFCHECK"):
        jump selfcheck
    return


label selfcheck:
    $ selfcheck_mode = True
    $ atb_selfcheck_reset()
    $ atb_selfcheck_note("boot=%s" % atb_boot())
    $ _err = atb_start()
    $ atb_selfcheck_note("start_err=%r" % (_err,))
    if _err is None:
        $ atb_selfcheck_note("game_id=%s" % game_id)
        $ _err = atb_send("你最近是不是在躲我？")
        $ atb_selfcheck_note("send_err=%r turn=%d version=%d" % (_err, turn_index, state_version))
        $ _err = atb_advance()
        $ atb_selfcheck_note("advance_err=%r scene=%s sprite=%s" % (_err, scene_id, sprite_id))
    $ atb_selfcheck_note("chat_log=%d" % len(chat_log))
    $ _res = renpy.call_screen("chat_ui")
    $ atb_selfcheck_note("screen_ok res=%r" % (_res,))
    $ selfcheck_mode = False
    $ atb_selfcheck_note("done")
    $ renpy.quit()


label start:
    $ quick_menu = False
    $ chat_log = []
    $ input_text = ""
    $ ending_data = None
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
