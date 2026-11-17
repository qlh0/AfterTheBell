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
        ## ---------------- 底部对话面板 ----------------
        frame:
            background Solid("#0a0e16f0")
            xfill True
            yalign 1.0
            ysize 322
            padding (24, 12)

            vbox:
                spacing 7

                hbox:
                    spacing 10
                    text "许栀" size 20 color "#f2c9a2" bold True
                    if store.current_event_title:
                        text "- [current_event_title]" size 14 color "#93a1b8" yalign 0.5
                    null width 1
                    text ("序章" if store.turn_index == 0 else "第%d回合" % store.turn_index):
                        size 12
                        color "#6f7d94"
                        yalign 0.6

                fixed:
                    xfill True
                    ysize 140

                    viewport:
                        ysize 140
                        mousewheel True
                        draggable True
                        yinitial 1.0
                        vbox:
                            spacing 9
                            for item in store.chat_log[-6:]:
                                use chat_entry(item)

                    ## 顶部渐隐：只露出一半的旧消息自然淡出，不显得被切断
                    vbox:
                        xsize 1232
                        spacing 0
                        add Solid("#0a0e16ee"):
                            xsize 1232
                            ysize 5
                        add Solid("#0a0e16c4"):
                            xsize 1232
                            ysize 5
                        add Solid("#0a0e1690"):
                            xsize 1232
                            ysize 5
                        add Solid("#0a0e1658"):
                            xsize 1232
                            ysize 5

                if store.suggestions:
                    hbox:
                        spacing 8
                        for sug in store.suggestions:
                            textbutton sug["label"]:
                                style "chip_button"
                                action SetVariable("input_text", sug["text"])

                hbox:
                    spacing 10
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

                hbox:
                    spacing 8
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

    key "K_RETURN" action If(not store.log_expanded and store.input_text.strip() != "", Return(("send", store.input_text)), NullAction())


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
            text "···" size 17 color "#f2c9a2"


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
        timer 0.8 action Return(True)

    add Solid("#05070bcc")

    frame:
        background Solid("#0c1119f2")
        xalign 0.5
        yalign 0.5
        xsize 780
        padding (44, 36)

        vbox:
            spacing 16
            text ending["title"] size 42 color "#f2c9a2" xalign 0.5 text_align 0.5
            text ending["subtitle"] size 15 color "#93a1b8" xalign 0.5
            null height 8
            for line in ending["epilogue"]:
                text line size 20 color "#e6ecf6" xalign 0.5 text_align 0.5
            null height 10
            text ending["closing_line"] size 16 color "#93a1b8" italic True xalign 0.5 text_align 0.5
            null height 6
            text "本局对局记录已保存" size 13 color "#6f7d94" xalign 0.5
            null height 12
            textbutton "回到标题" action Return(True) xalign 0.5
