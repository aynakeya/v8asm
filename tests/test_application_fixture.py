from __future__ import annotations

import shutil
import unittest

from run_application_fixture import FIXTURE, SCENARIOS, observe


@unittest.skipUnless(shutil.which("node"), "node is required for application observations")
class ApplicationFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = (FIXTURE / "taskboard.js").read_text(encoding="utf-8")
        cls.observations = {case: observe("node", source, case) for case in SCENARIOS}

    def test_original_scenarios_complete(self) -> None:
        for case, result in self.observations.items():
            with self.subTest(scenario=case):
                self.assertEqual(result["status"], "ok", result)

    def test_workflow_and_transaction_rollback(self) -> None:
        workflow = self.observations["workflow"]["value"]
        self.assertEqual([task["title"] for task in workflow["tasks"]], ["ship parser", "audit scopes"])
        self.assertEqual(workflow["tasks"][0]["tags"], ["v8", "js"])
        self.assertEqual(workflow["output"][4]["value"][0]["title"], "audit closures")
        self.assertEqual(workflow["output"][-2]["error"], "RangeError:missing:missing")
        self.assertEqual(workflow["output"][-1]["error"], "SyntaxError:unknown command:unknown")
        transaction = self.observations["transactions"]["value"]
        self.assertEqual(transaction["failure"], "RangeError:board full")
        self.assertEqual(transaction["size"], 1)
        self.assertEqual(transaction["tasks"][0]["title"], "keep")
        self.assertTrue(transaction["tasks"][0]["done"])
        self.assertEqual(transaction["notices"], ["add:T1", "update:T1", "add:T2", "undo:T2", "restore:T1"])
        self.assertEqual(transaction["audit"][-5:], ["rollback:board full", "settled", "update:T1", "commit", "settled"])

    def test_captures_iterators_and_async_cleanup(self) -> None:
        self.assertEqual(self.observations["selection"]["value"]["deferred"], [
            "0:0:parser", "0:1:parser", "0:2:parser", "2:0:scope", "2:1:scope",
        ])
        self.assertEqual(self.observations["iterators"]["value"], {
            "accepted": [1, 3],
            "events": ["next:0", "next:1", "next:2", "close", "next:0", "fail:1", "close", "cancel", "finally"],
        })
        self.assertEqual(self.observations["generators"]["value"]["events"], ["release", "abort", "release"])
        asynchronous = self.observations["async"]["value"]
        self.assertEqual([result["status"] for result in asynchronous["results"]], ["fulfilled", "rejected"])
        self.assertEqual(asynchronous["streamed"], [6])
        self.assertEqual(asynchronous["events"], [
            "start:1", "start:2", "saved:1", "settled:1", "settled:2",
            "start:3", "saved:3", "settled:3", "stream:closed",
        ])

    def test_numeric_observations_do_not_lose_json_edge_cases(self) -> None:
        value = self.observations["codec"]["value"]
        self.assertEqual(value["total"], {"$type": "bigint", "value": "9007199254741504"})
        self.assertEqual(value["negative_zero"], {"$type": "number", "value": "-0"})
        self.assertEqual(value["nan"], {"$type": "number", "value": "NaN"})
        self.assertEqual(value["infinity"], {"$type": "number", "value": "Infinity"})
        self.assertFalse(value["hole"])
        self.assertTrue(value["explicit"])
        self.assertEqual(self.observations["plugins"]["value"]["skipped"], {"$type": "undefined"})

    def test_observer_distinguishes_rejection_pending_and_timeout(self) -> None:
        programs = {
            "throw": 'globalThis.taskboard = async () => { await 0; throw new Error("offline"); };',
            "pending": "globalThis.taskboard = () => new Promise(() => {});",
            "timeout": "globalThis.taskboard = async () => { while (true) await 0; };",
        }
        for status, source in programs.items():
            with self.subTest(status=status):
                self.assertEqual(observe("node", source, "probe")["status"], status)


if __name__ == "__main__":
    unittest.main()
