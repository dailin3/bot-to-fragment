import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import yaml
from quart import Quart


class _Filter:
    class EventMessageType:
        ALL = "all"

    @staticmethod
    def event_message_type(_message_type):
        return lambda handler: handler


class _Star:
    def __init__(self, context):
        self.context = context


astrbot = types.ModuleType("astrbot")
astrbot_api = types.ModuleType("astrbot.api")
astrbot_event = types.ModuleType("astrbot.api.event")
astrbot_star = types.ModuleType("astrbot.api.star")
astrbot_api.logger = MagicMock()
astrbot_event.AstrMessageEvent = object
astrbot_event.filter = _Filter
astrbot_star.Context = object
astrbot_star.Star = _Star
sys.modules.update(
    {
        "astrbot": astrbot,
        "astrbot.api": astrbot_api,
        "astrbot.api.event": astrbot_event,
        "astrbot.api.star": astrbot_star,
    }
)

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bot_to_fragment_plugin", PLUGIN_ROOT / "main.py"
)
plugin_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = plugin_module
SPEC.loader.exec_module(plugin_module)


class BotToFragmentPluginTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.fragments = Path(self.temp_dir.name)
        plugin_module.FRAG_DIR = str(self.fragments)
        self.app = Quart(__name__)
        self.plugin = plugin_module.BotToFragmentPlugin.__new__(
            plugin_module.BotToFragmentPlugin
        )

    def test_metadata_uses_an_importable_plugin_name(self):
        metadata = yaml.safe_load(
            (PLUGIN_ROOT / "metadata.yaml").read_text(encoding="utf-8")
        )

        self.assertTrue(metadata["name"].isidentifier())
        self.assertEqual(metadata["repo"], "https://github.com/dailin3/bot-to-fragment")

    async def test_initialize_registers_collector_routes(self):
        self.plugin.context = MagicMock()

        await self.plugin.initialize()

        calls = self.plugin.context.register_web_api.call_args_list
        self.assertEqual(
            [call.args[0] for call in calls],
            ["/fragments", "/fragments/delete", "/fragments/health"],
        )
        self.assertEqual(
            [call.args[2] for call in calls],
            [["GET"], ["POST"], ["GET"]],
        )

    async def test_health_returns_healthy_when_fragment_directory_is_available(self):
        async with self.app.app_context():
            response = await self.plugin._health()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(await response.get_json(), {"healthy": True})

    async def test_health_returns_service_unavailable_when_fragment_directory_is_missing(
        self,
    ):
        plugin_module.FRAG_DIR = str(self.fragments / "missing")

        async with self.app.app_context():
            response, status = await self.plugin._health()

        self.assertEqual(status, 503)
        self.assertEqual(await response.get_json(), {"healthy": False})

    async def test_message_is_written_as_a_fragment(self):
        event = MagicMock()
        event.message_str = "remember this"
        event.plain_result.return_value = "saved"

        results = [result async for result in self.plugin.on_message(event)]

        fragment_files = list(self.fragments.glob("*.md"))
        self.assertEqual(results, ["saved"])
        self.assertEqual(len(fragment_files), 1)
        self.assertRegex(
            fragment_files[0].stem,
            r"^\d{4}-\d{2}-\d{2}-\d{6}-\d{6}$",
        )
        self.assertRegex(
            fragment_files[0].read_text(encoding="utf-8"),
            r"^- \d{2}:\d{2} remember this\n$",
        )

    async def test_list_returns_valid_files_and_skips_unsafe_entries(self):
        fragment_id = "2026-07-19-143000-000001"
        (self.fragments / f"{fragment_id}.md").write_text(
            "- 14:30 hello\n", encoding="utf-8"
        )
        (self.fragments / "not-a-fragment.md").write_text("ignore", encoding="utf-8")
        (self.fragments / "2026-07-19-143001-000002.md").symlink_to(
            self.fragments / f"{fragment_id}.md"
        )

        async with self.app.app_context():
            response = await self.plugin._list_fragments()
            payload = await response.get_json()

        self.assertEqual(
            payload,
            {
                "fragments": [
                    {
                        "id": fragment_id,
                        "content": "- 14:30 hello\n",
                        "timestamp": "2026-07-19T14:30:00+08:00",
                    }
                ]
            },
        )

    async def test_delete_is_physical_and_idempotent(self):
        fragment_id = "2026-07-19-143000-000001"
        fragment_path = self.fragments / f"{fragment_id}.md"
        fragment_path.write_text("hello", encoding="utf-8")

        async with self.app.test_request_context(
            "/api/plug/fragments/delete",
            method="POST",
            json={"id": fragment_id},
        ):
            response = await self.plugin._delete_fragment()
        self.assertFalse(fragment_path.exists())
        self.assertEqual(response.status_code, 200)

        async with self.app.test_request_context(
            "/api/plug/fragments/delete",
            method="POST",
            json={"id": fragment_id},
        ):
            response, status = await self.plugin._delete_fragment()
        self.assertEqual(status, 404)
        self.assertEqual((await response.get_json())["error"], "not found")


if __name__ == "__main__":
    unittest.main()
