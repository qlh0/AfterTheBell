# state整体保存于Ren'Py存档中；后端成功返回后才替换。
default game_state = None
default request_path = ""
default request_payload = {}
default response_data = None
default request_error = ""
default player_input = ""

screen demo_status():
    if game_state:
        frame:
            xalign 0.02
            yalign 0.02
            vbox:
                text ("{} | 节点 {}/10".format(game_state["scene"]["time"], game_state["month_index"] + 1)) substitute False
                text ("心动 {} | 学力 {}".format(game_state["love"], game_state["study"])) substitute False
                text ("{} | 本月对话 {}/5".format(game_state["scene"]["location"], game_state["turns"])) substitute False

label start:
    scene black

    # 生成9月开场。/start无需额外数据。
    $ request_path = "/start"
    $ request_payload = {}
    call demo_send_request
    $ game_state = response_data["state"]
    show screen demo_status
    $ demo_show_text(response_data["text"])

    while not game_state["ended"]:

        # 为本次操作创建请求；不会在客户端自行推进月份或结算。
        $ request_path = "/step"
        $ request_payload = {"state": game_state}

        if game_state["phase"] == "dialogue":
            menu:
                "继续对话":
                    $ player_input = ""
                    while not player_input:
                        $ player_input = renpy.input("你想说什么？", length=500).strip()
                    $ demo_show_text("小帅：" + player_input)
                    $ request_payload.update(action="dialogue", text=player_input)
                "结束本月对话，安排时间":
                    $ request_payload.update(action="end_dialogue")

        elif game_state["phase"] == "plan":
            menu:
                "自己填写行动（收到追问时也选此项）":
                    $ player_input = ""
                    while not player_input:
                        $ player_input = renpy.input("接下来这段时间，你打算做什么？", length=1000).strip()
                "以复习为主，向老师请教薄弱知识":
                    $ player_input = "以复习为主，向老师请教薄弱知识。"
                "主动了解小美的想法，安排合适的相处时间":
                    $ player_input = "主动了解小美的想法，尊重她意愿安排相处时间，同时保持基本复习。"
                "多陪伴母亲，兼顾基本复习":
                    $ player_input = "多陪伴母亲，了解她的需要，兼顾基本复习。"
            $ demo_show_text("我的安排：" + player_input)
            $ request_payload.update(action="plan", text=player_input)

        elif game_state["phase"] == "relationship":
            menu:
                "接受，与小美确认关系":
                    $ request_payload.update(action="relationship", accept=True)
                "暂不接受":
                    $ request_payload.update(action="relationship", accept=False)

        elif game_state["phase"] == "review":
            # 使用程序批准的数值和理由，而不是从AI正文推测。
            $ settlement = game_state["settlements"][-1]
            $ demo_show_text("心动：{} → {}。{}".format(settlement["before"]["love"], settlement["after"]["love"], settlement["love_reason"]))
            $ demo_show_text("学力：{} → {}。{}".format(settlement["before"]["study"], settlement["after"]["study"], settlement["study_reason"]))
            menu:
                "继续（6月结算后进入结局）":
                    $ request_payload.update(action="next")

        call demo_send_request
        $ game_state = response_data["state"]
        $ demo_show_text(response_data["text"])

    hide screen demo_status
    "本局结束。返回主菜单后，可以重新开始。"
    return


# 共用请求流程：失败不替换状态，玩家可以重试同一次操作。
label demo_send_request:
    $ renpy.block_rollback()
    $ request_error = ""
    $ response_data = None

    while response_data is None:
        show text "正在生成剧情，请稍候……" at truecenter
        $ renpy.pause(0.1)
        python:
            try:
                response_data = demo_request(request_path, request_payload)
            except Exception as error:
                request_error = str(error)
        hide text
        $ renpy.block_rollback()

        if response_data is None:
            $ demo_show_text("请求失败，当前进度未提交。请查看后端终端。错误：" + request_error)
            menu:
                "重试":
                    pass
                "返回主菜单":
                    $ renpy.full_restart()

    return
