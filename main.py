"""
bot-to-fragment: 将 QQ 消息写入碎片文件，并通过 Web API 暴露给 Fragment Collector。

替代旧的 bot-to-obsidian 插件。

- on_message: QQ 消息 -> fragments/YYYY-MM-DD-HHMMSS-######.md
- GET /api/plug/fragments -> 返回所有碎片文件列表
- POST /api/plug/fragments/delete -> 物理删除指定碎片文件
"""

import os
import re
from datetime import datetime, timedelta, timezone

from quart import jsonify, request

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

FRAG_DIR = "/AstrBot/data/fragments"
FRAG_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{6}-\d{6}$")
BUSINESS_TIMEZONE = timezone(timedelta(hours=8))


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
        """监听所有消息，写入碎片文件。"""
        try:
            message_str = event.message_str
            if not message_str:
                return

            now = datetime.now(BUSINESS_TIMEZONE)
            time_str = now.strftime("%H:%M")

            os.makedirs(FRAG_DIR, exist_ok=True)
            fname = f"{now.strftime('%Y-%m-%d-%H%M%S')}-{now.microsecond:06d}.md"
            frag_path = os.path.join(FRAG_DIR, fname)

            with open(frag_path, "w", encoding="utf-8") as fragment_file:
                fragment_file.write(f"- {time_str} {message_str}\n")

            logger.debug(f"已写碎片: {frag_path}")
            yield event.plain_result("已保存")

        except Exception as exc:
            logger.error(f"on_message 处理出错: {exc}")

    async def _list_fragments(self):
        """GET /api/plug/fragments: 返回所有有效碎片文件。"""
        try:
            fragments = []
            if os.path.isdir(FRAG_DIR):
                for fname in sorted(os.listdir(FRAG_DIR)):
                    if not fname.endswith(".md"):
                        continue

                    fragment_id = fname[:-3]
                    if not FRAG_ID_PATTERN.fullmatch(fragment_id):
                        logger.warning(f"跳过无效碎片文件名: {fname}")
                        continue

                    fragment_path = os.path.join(FRAG_DIR, fname)
                    if os.path.islink(fragment_path) or not os.path.isfile(fragment_path):
                        logger.warning(f"跳过非普通碎片文件: {fname}")
                        continue

                    try:
                        parsed_at = datetime.strptime(
                            fragment_id[:17], "%Y-%m-%d-%H%M%S"
                        ).replace(tzinfo=BUSINESS_TIMEZONE)
                        with open(
                            fragment_path, "r", encoding="utf-8"
                        ) as fragment_file:
                            content = fragment_file.read()
                    except (OSError, UnicodeError, ValueError) as exc:
                        logger.warning(f"跳过无法读取的碎片 {fname}: {exc}")
                        continue

                    fragments.append(
                        {
                            "id": fragment_id,
                            "content": content,
                            "timestamp": parsed_at.isoformat(),
                        }
                    )

            return jsonify({"fragments": fragments})
        except Exception as exc:
            logger.error(f"list_fragments 出错: {exc}")
            return jsonify({"fragments": [], "error": str(exc)}), 500

    async def _delete_fragment(self):
        """POST /api/plug/fragments/delete: 物理删除指定碎片文件。"""
        try:
            data = await request.get_json()
            fragment_id = data.get("id", "") if data else ""

            if not FRAG_ID_PATTERN.fullmatch(fragment_id):
                return jsonify({"error": "invalid fragment_id"}), 400

            fragment_path = os.path.join(FRAG_DIR, f"{fragment_id}.md")
            if os.path.islink(fragment_path) or not os.path.isfile(fragment_path):
                return jsonify({"error": "not found"}), 404

            os.remove(fragment_path)
            logger.debug(f"已删除碎片: {fragment_path}")
            return jsonify({"status": "deleted", "id": fragment_id})

        except Exception as exc:
            logger.error(f"delete_fragment 出错: {exc}")
            return jsonify({"error": str(exc)}), 500
