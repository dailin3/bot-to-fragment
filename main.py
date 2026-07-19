 """
 bot-to-fragment: 将 QQ 消息写入碎片文件，并通过 Web API 暴露给 Fragment Collector。
 
 替代旧的 bot-to-obsidian 插件。
 
 - on_message: QQ 消息 → fragments/YYYY-MM-DD-HHMMSS-######.md
 - GET /api/plug/fragments → 返回所有碎片文件列表
 - POST /api/plug/fragments/delete → 物理删除指定碎片文件
 """
 
 import os
 from datetime import datetime
 from quart import jsonify, request
 
 from astrbot.api.event import filter, AstrMessageEvent
 from astrbot.api.star import Context, Star
 from astrbot.api import logger
 
 FRAG_DIR = "/AstrBot/data/fragments"
 
 
 class BotToFragmentPlugin(Star):
     def __init__(self, context: Context):
         super().__init__(context)
 
     async def initialize(self):
         os.makedirs(FRAG_DIR, exist_ok=True)
 
         self.context.register_web_api(
             "/fragments",
             self._list_fragments,
             ["GET"],
             "List all fragment files with content",
         )
         self.context.register_web_api(
             "/fragments/delete",
             self._delete_fragment,
             ["POST"],
             "Delete a fragment file by id",
         )
 
         logger.info("bot-to-fragment 插件已加载")
 
     async def terminate(self):
         logger.info("bot-to-fragment 插件已卸载")
 
     @filter.event_message_type(filter.EventMessageType.ALL)
     async def on_message(self, event: AstrMessageEvent):
         """监听所有消息，写入碎片文件"""
         try:
             message_str = event.message_str
             if not message_str:
                 return
 
             now = datetime.now()
             time_str = now.strftime("%H:%M")
 
             os.makedirs(FRAG_DIR, exist_ok=True)
             fname = f"{now.strftime('%Y-%m-%d-%H%M%S')}-{now.microsecond:06d}.md"
             frag_path = os.path.join(FRAG_DIR, fname)
 
             with open(frag_path, "w") as f:
                 f.write(f"- {time_str} {message_str}\n")
 
             logger.debug(f"已写碎片: {frag_path}")
             yield event.plain_result("已保存")
 
         except Exception as e:
             logger.error(f"on_message 处理出错: {str(e)}")
 
     async def _list_fragments(self):
         """GET /api/plug/fragments —— 返回所有碎片文件列表"""
         try:
             fragments = []
             if os.path.isdir(FRAG_DIR):
                 for fname in sorted(os.listdir(FRAG_DIR)):
                     if not fname.endswith(".md"):
                         continue
                     fpath = os.path.join(FRAG_DIR, fname)
                     try:
                         with open(fpath, "r") as f:
                             content = f.read()
                     except Exception:
                         continue
 
                     frag_id = fname[:-3]  # 去掉 .md 后缀
                     # 从文件名解析时间戳: YYYY-MM-DD-HHMMSS-######.md
                     date_part = fname[:10]
                     time_part = fname[11:17]
                     timestamp = (
                         f"{date_part}T"
                         f"{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}+08:00"
                     )
 
                     fragments.append({
                         "id": frag_id,
                         "content": content,
                         "timestamp": timestamp,
                     })
 
             return jsonify({"fragments": fragments})
         except Exception as e:
             logger.error(f"list_fragments 出错: {str(e)}")
             return jsonify({"fragments": [], "error": str(e)}), 500
 
     async def _delete_fragment(self):
         """POST /api/plug/fragments/delete —— 物理删除碎片文件
 
         Body: {"id": "2026-07-19-143000-000001"}
         """
         try:
             data = await request.get_json()
             fragment_id = data.get("id", "") if data else ""
 
             # 安全检查：防止路径穿越
             if not fragment_id or ".." in fragment_id or "/" in fragment_id:
                 return jsonify({"error": "invalid fragment_id"}), 400
 
             fpath = os.path.join(FRAG_DIR, f"{fragment_id}.md")
             if not os.path.isfile(fpath):
                 return jsonify({"error": "not found"}), 404
 
             os.remove(fpath)
             logger.debug(f"已删除碎片: {fpath}")
             return jsonify({"status": "deleted", "id": fragment_id})
 
         except Exception as e:
             logger.error(f"delete_fragment 出错: {str(e)}")
             return jsonify({"error": str(e)}), 500
