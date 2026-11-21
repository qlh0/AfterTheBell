# 这里只负责 HTTP 连接，不修改游戏状态。
init python:
    DEMO_API = "http://127.0.0.1:8000"

    def demo_request(path, payload):
        return renpy.fetch(
            DEMO_API + path,
            method="POST",
            json=payload,
            result="json",
            timeout=240,
        )

    # 最小分页：每页最多70个字符，避免AI长回复挤出默认对话框。
    def demo_show_text(text):
        for paragraph in text.splitlines():
            for offset in range(0, len(paragraph), 70):
                page = paragraph[offset:offset + 70]
                # 将自由输入中的括号作为普通文字，避免被当作Ren'Py标签。
                page = page.replace("[", "[[").replace("{", "{{")
                renpy.say(None, page)
