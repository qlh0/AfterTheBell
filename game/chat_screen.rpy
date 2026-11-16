## 游戏内界面：聊天面板、等待提示、后端离线提示、结局卡。

screen chat_ui():
    modal True
    zorder 50

    if store.selfcheck_mode:
        timer 0.8 action Return(("quit", None))

    frame:
        background Solid("#0a0e16e8")
        xalign 1.0
        xoffset -20
        yalign 0.5
        xsize 600
        ysize 660
        padding (20, 16)

        vbox:
            spacing 8

            hbox:
                spacing 10
                text "许栀" size 22 color "#f2c9a2" bold True
                if store.current_event_title:
                    text "- [current_event_title]" size 15 color "#93a1b8" yalign 0.5
                null width 1
                text "第 [store.turn_index] 回合" size 13 color "#6f7d94" xalign 1.0

            viewport:
                ysize 466
                mousewheel True
                draggable True
                yinitial 1.0
                scrollbars "vertical"

                vbox:
                    spacing 14
                    xsize 528

                    for item in store.chat_log:
                        if item["who"] == "narrator":
                            text item["text"] size 17 color "#93a1b8" italic True
                        else:
                            hbox:
                                spacing 10
                                add Solid("#f2c9a2" if item["who"] == "xuzhi" else "#7f9dcb"):
                                    xsize 3
                                    ysize 24
                                    yalign 0.12
                                vbox:
                                    spacing 3
                                    text ("许栀" if item["who"] == "xuzhi" else "你"):
                                        size 12
                                        color ("#f2c9a2" if item["who"] == "xuzhi" else "#7f9dcb")
                                    text item["text"] size 20 color "#eaeff8"

            frame:
                background Solid("#151d2b")
                padding (12, 6)
                xfill True
                input:
                    value VariableInputValue("input_text")
                    length 200
                    size 20
                    color "#eef2f8"
                    caret Solid("#f2c9a2")
                    xsize 500

            hbox:
                spacing 10
                textbutton "发送":
                    action If(store.input_text.strip() != "", Return(("send", store.input_text)), NullAction())
                    sensitive store.input_text.strip() != ""
                textbutton "推进时间" action Return(("advance", None))
                textbutton "结束本局" action Return(("quit", None))
                null width 1
                text "Enter 发送" size 12 color "#5d6a80" yalign 0.6

    key "K_RETURN" action If(store.input_text.strip() != "", Return(("send", store.input_text)), NullAction())


screen thinking_overlay():
    zorder 200
    frame:
        background Solid("#0a0e16dd")
        padding (16, 8)
        xalign 0.5
        yalign 0.06
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
            null height 12
            textbutton "回到标题" action Return(True) xalign 0.5
