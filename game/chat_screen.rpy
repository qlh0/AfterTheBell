## 游戏内界面（M3）：
## 女主站在画面正中；底部是角色对白 / 旁白 / 建议回复 / 输入框；
## 右上角「聊天记录」按钮点开后，从右侧滑出一块记录面板，不遮挡女主。

style chat_button is button:
    padding (10, 4)

style chat_button_text is button_text:
    size 17
    color "#dbe4f2"
    hover_color "#ffe0b5"
    insensitive_color "#5a6478"

style chip_button is button:
    background Solid("#192434")
    hover_background Solid("#24344a")
    padding (12, 5)

style chip_button_text is button_text:
    size 14
    color "#a9b8cd"
    hover_color "#ffe0b5"

style log_button is button:
    background Solid("#0a0e16d8")
    hover_background Solid("#16202e")
    padding (12, 6)

style log_button_text is button_text:
    size 16
    color "#dbe4f2"
    hover_color "#ffe0b5"


screen chat_entry(item):
    if item["who"] == "narrator":
        text item["text"] size 19 color "#b3c0d2"
    elif item["who"] == "xuzhi":
        text ("{color=#f2c9a2}许栀{/color}  " + item["text"]) size 19 color "#eaeff8"
    else:
        text ("{color=#7f9dcb}你{/color}  " + item["text"]) size 19 color "#eaeff8"


screen chat_ui():
    modal True
    zorder 50

    if store.selfcheck_mode:
        timer 0.8 action [Function(atb_screenshot, store.selfcheck_shot_name), Return(("quit", None))]

    if store.log_expanded:
        ## ---------------- 右侧聊天记录抽屉（不遮女主） ----------------
        frame:
            background Solid("#0a0e16f2")
            xalign 1.0
            xoffset -12
            yoffset 58
            xsize 380
            ysize 650
            padding (18, 12)

            vbox:
                spacing 8
                hbox:
                    text "聊天记录" size 18 color "#f2c9a2"
                    text ("共 %d 条" % len(store.chat_log)) size 12 color "#6f7d94" yalign 0.6
                    null width 1
                    textbutton "收起" style "chat_button" action SetVariable("log_expanded", False)

                viewport:
                    ysize 578
                    mousewheel True
                    draggable True
                    yinitial 1.0
                    vbox:
                        spacing 10
                        for item in store.chat_log:
                            use chat_entry(item)

    else:
        ## ---------------- 底部对话面板（固定高度，留白一致） ----------------
        frame:
            background Solid("#0a0e16f0")
            xfill True
            yalign 1.0
            ysize 236
            padding (24, 14)

            fixed:
                xfill True
                ysize 208

                vbox:
                    spacing 6

                    hbox:
                        spacing 10
                        if store.panel_mode == "narration":
                            text "旁白" size 20 color "#b3c0d2" bold True
                        else:
                            text "许栀" size 20 color "#f2c9a2" bold True
                        if store.current_event_title:
                            text "- [current_event_title]" size 14 color "#93a1b8" yalign 0.5
                        null width 1
                        text store.day_label size 12 color "#8fa0b8" yalign 0.6
                        text "/" size 12 color "#5f6f86" yalign 0.6
                        text ("序章" if store.turn_index == 0 else "第%d回合" % store.turn_index):
                            size 12
                            color "#6f7d94"
                            yalign 0.6

                    if store.panel_mode == "narration":
                        ## 旁白页：只显示旁白，不显示任何对话或输入框
                        vbox:
                            spacing 10
                            for line in store.current_narration:
                                text line size 21 color "#c7d3e3" xsize 1180

                    else:
                        ## 对话页：只显示她这一句 + 建议回复 + 输入框
                        if store.current_dialogue:
                            text store.current_dialogue:
                                size 20
                                color "#eaeff8"
                                xsize 1180
                        else:
                            text "（她没接话，你可以先开口。）" size 17 color "#6f7d94"

                        $ _visible_suggestions = atb_visible_suggestions()
                        if _visible_suggestions:
                            hbox:
                                spacing 8
                                for sug in _visible_suggestions:
                                    textbutton sug["label"]:
                                        style "chip_button"
                                        action [Function(atb_mark_suggestion_used, sug["text"]),
                                                SetVariable("input_text", sug["text"])]

                        hbox:
                            spacing 8
                            text "你：" size 19 color "#7f9dcb" yalign 0.5
                            frame:
                                background Solid("#151d2b")
                                padding (12, 5)
                                xsize 1040
                                input:
                                    value VariableInputValue("input_text")
                                    length 200
                                    size 19
                                    color "#eef2f8"
                                    caret Solid("#f2c9a2", xsize=2)
                                    xsize 1000
                            textbutton "发送":
                                style "chat_button"
                                action If(store.input_text.strip() != "", Return(("send", store.input_text)), NullAction())
                                sensitive store.input_text.strip() != ""

                ## 底部动作条：推进时间 / 结束本局（或旁白页的继续）
                hbox:
                    yalign 1.0
                    spacing 8
                    if store.panel_mode == "narration":
                        textbutton "继续":
                            style "chat_button"
                            action SetVariable("panel_mode", "dialogue")
                        null width 6
                        text "点「继续」进入对话" size 12 color "#6f7d94" yalign 0.6
                    else:
                        textbutton "推进时间" style "chat_button" action Return(("advance", None))
                        textbutton "结束本局" style "chat_button" action Return(("quit", None))
                        null width 6
                        text "Enter 发送，上面是可参考的说法，点一下填进输入框，可以自己改" size 12 color "#6f7d94" yalign 0.6

        ## ---------------- 右上角：展开聊天记录 ----------------
        textbutton ("聊天记录 (%d)" % len(store.chat_log)):
            style "log_button"
            xalign 1.0
            xoffset -16
            yoffset 14
            action SetVariable("log_expanded", True)

    key "K_RETURN" action If(not store.log_expanded and store.panel_mode == "dialogue" and store.input_text.strip() != "", Return(("send", store.input_text)), NullAction())


transform day_break_line1:
    alpha 0.0
    linear 0.6 alpha 1.0
    pause 1.6
    linear 0.6 alpha 0.0


transform day_break_line2:
    alpha 0.0
    pause 0.8
    linear 1.2 alpha 1.0
    pause 1.2
    linear 0.6 alpha 0.0


transform day_break_line3:
    alpha 0.0
    pause 4.2
    linear 0.8 alpha 1.0


screen day_break(day_label):
    zorder 300
    modal True
    add Solid("#000000")
    vbox:
        xalign 0.5
        yalign 0.46
        spacing 22
        text "Day 01 - END" size 38 color "#f2f2f2" xalign 0.5 at day_break_line1
        text "有些话，今天还没能说出口。\n不过，明天也还能见面。" size 23 color "#c8c8c8" xalign 0.5 text_align 0.5 at day_break_line2
    text "DAY 02 — 放学后" size 42 color "#f2f2f2" xalign 0.5 yalign 0.5 at day_break_line3
    if store.selfcheck_mode:
        timer 1.0 action Function(atb_screenshot, "day_break_1")
        timer 2.8 action Function(atb_screenshot, "day_break_2")
        timer 4.7 action Function(atb_screenshot, "day_break_3")
    timer 6.2 action Return()


screen day_plan():
    modal True
    zorder 280
    add Solid("#05070be6")
    default plan_text = "明天想约她去图书馆，一起复习数学。" if store.selfcheck_mode else ""

    if store.selfcheck_mode:
        timer 0.2 action Function(atb_screenshot, "day_plan")
        timer 0.4 action Return("明天想约她去图书馆，一起复习数学。")

    frame:
        background Solid("#0c1119f2")
        xalign 0.5
        yalign 0.5
        xsize 760
        padding (40, 32)

        vbox:
            xalign 0.5
            spacing 12
            text "第二天" size 22 color "#8fa0b8" xalign 0.5
            text "放学后，你打算做什么？" size 30 color "#f2c9a2" xalign 0.5
            text "写一句，或者直接选一个方向。她不会自动知道你的计划。" size 15 color "#a8b4c8" xalign 0.5 text_align 0.5
            null height 4
            input value ScreenVariableInputValue("plan_text") length 140 xalign 0.5 xsize 620 text_align 0.5
            hbox:
                xalign 0.5
                spacing 10
                textbutton "去图书馆把题讲清楚" style "chip_button" action SetScreenVariable("plan_text", "明天想约她去图书馆，把不会的题问清楚。")
                textbutton "找她把话说开" style "chip_button" action SetScreenVariable("plan_text", "明天想找个机会，把昨天没说完的话说清楚。")
            hbox:
                xalign 0.5
                spacing 10
                textbutton "一起去小卖部" style "chip_button" action SetScreenVariable("plan_text", "明天想和她一起去小卖部，轻松一点。")
                textbutton "顺其自然" style "chip_button" action SetScreenVariable("plan_text", "顺其自然。")
            null height 4
            hbox:
                xalign 0.5
                spacing 20
                textbutton "确定" style "chat_button" action Return(plan_text.strip() or "顺其自然。")
                textbutton "跳过，顺其自然" style "chat_button" action Return("顺其自然。")


screen thinking_overlay():
    zorder 200
    frame:
        background Solid("#0a0e16dd")
        padding (16, 8)
        xalign 0.5
        yalign 0.04
        hbox:
            spacing 6
            text "许栀正在回复" size 17 color "#f2c9a2"


screen backend_down(message):
    modal True
    zorder 300
    add Solid("#0b0f17")

    vbox:
        xalign 0.5
        yalign 0.44
        spacing 18
        text "连不上游戏后端" size 36 color "#f2c9a2" xalign 0.5
        text "请先运行 run_dev.bat（或手动启动 backend 服务），然后点重新连接。" size 19 color "#c8d2e2" xalign 0.5
        text "[message]" size 14 color "#8e9bb0" xalign 0.5 text_align 0.5
        null height 8
        hbox:
            xalign 0.5
            spacing 24
            textbutton "重新连接" action Return("retry")
            textbutton "退出游戏" action Quit(confirm=False)


screen ending_view(ending):
    modal True
    zorder 100

    if store.selfcheck_mode:
        timer 0.6 action Function(atb_screenshot, "ending_" + store.selfcheck_ending_id)
        timer 0.9 action Return(True)

    add Solid("#05070bcc")

    frame:
        background Solid("#0c1119f2")
        xalign 0.5
        yalign 0.5
        xsize 860
        padding (42, 30)

        vbox:
            spacing 10
            text ending["title"] size 38 color "#f2c9a2" xalign 0.5 text_align 0.5
            text ending["subtitle"] size 14 color "#93a1b8" xalign 0.5
            null height 4
            for line in ending["epilogue"]:
                text line size 18 color "#e6ecf6" xalign 0.5 text_align 0.5
            null height 6
            text ending["closing_line"] size 14 color "#93a1b8" italic True xalign 0.5 text_align 0.5
            null height 4
            text "本局对局记录已保存" size 12 color "#6f7d94" xalign 0.5
            null height 8
            textbutton "回到标题" action Return(True) xalign 0.5
