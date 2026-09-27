import tempfile, unittest
from pathlib import Path
from src.domain import ConflictError, ValidationError
from src.repository import Repository
from src.service import Service
from src.rules import NOTICE_KIND
class NoticeGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.repo=Repository(str(Path(self.tmp.name)/"test.db")); self.service=Service(self.repo)
        item=self.service.create_item({"title":"bridge A","description":"notice gate","severity":'warning',"quantity":8,"threshold":4,"external_ref":"BR-A"},"creator",'sensor_operator')
        self.other=self.service.create_item({"title":"bridge B","description":"other bridge","severity":'warning',"quantity":8,"threshold":4,"external_ref":"BR-B"},"creator",'sensor_operator')
        self.item=self.service.transition(item["id"],"warning",item["version"],"reviewer","sensor_operator")
    def tearDown(self): self.repo.close(); self.tmp.cleanup()
    def _notice(self,item_id,ref,status="open"):
        return self.service.add_record(item_id,{"kind":NOTICE_KIND,"detail":"traffic notice","status":status,"external_ref":ref},"recorder",'sensor_operator')
    def _status(self):
        return self.service.get_item(self.item["id"],"viewer")["status"]
    def test_missing_notice_number_rejected_without_failure_record(self):
        with self.assertRaises(ValidationError): self.service.transition(self.item["id"],"restricted",self.item["version"],"reviewer","bridge_engineer")
        self.assertEqual(self._status(),"warning"); self.assertIsNone(self.service.last_decision_failure("viewer"))
    def test_unknown_notice_keeps_state_and_records_failure(self):
        with self.assertRaises(ConflictError) as ctx: self.service.transition(self.item["id"],"restricted",self.item["version"],"reviewer","bridge_engineer",notice_no="NT-404")
        self.assertIn("不存在",str(ctx.exception)); self.assertEqual(self._status(),"warning")
        failure=self.service.last_decision_failure("viewer")
        self.assertEqual(failure["item_id"],self.item["id"]); self.assertEqual(failure["notice_no"],"NT-404"); self.assertEqual(failure["target"],"restricted"); self.assertIn("不存在",failure["reason"])
    def test_closed_notice_rejected(self):
        self._notice(self.item["id"],"NT-1",status="closed")
        with self.assertRaises(ConflictError) as ctx: self.service.transition(self.item["id"],"restricted",self.item["version"],"reviewer","bridge_engineer",notice_no="NT-1")
        self.assertIn("已关闭",str(ctx.exception)); self.assertEqual(self._status(),"warning")
        self.assertIn("已关闭",self.service.last_decision_failure("viewer")["reason"])
    def test_notice_from_other_bridge_rejected(self):
        self._notice(self.other["id"],"NT-2")
        with self.assertRaises(ConflictError) as ctx: self.service.transition(self.item["id"],"restricted",self.item["version"],"reviewer","bridge_engineer",notice_no="NT-2")
        self.assertIn("其他桥梁",str(ctx.exception)); self.assertEqual(self._status(),"warning")
        self.assertIn("其他桥梁",self.service.last_decision_failure("viewer")["reason"])
    def test_valid_notice_allows_transition_and_audits_number(self):
        self._notice(self.item["id"],"NT-3")
        updated=self.service.transition(self.item["id"],"restricted",self.item["version"],"reviewer","bridge_engineer",notice_no="NT-3")
        self.assertEqual(updated["status"],"restricted"); self.assertIsNone(self.service.last_decision_failure("viewer"))
        events=[e for e in self.service.audit("viewer",self.item["id"]) if e["action"]=="transition"]
        self.assertEqual(events[-1]["detail"]["notice_no"],"NT-3")
    def test_last_failure_is_most_recent(self):
        with self.assertRaises(ConflictError): self.service.transition(self.item["id"],"restricted",self.item["version"],"reviewer","bridge_engineer",notice_no="NT-A")
        self._notice(self.other["id"],"NT-B")
        with self.assertRaises(ConflictError): self.service.transition(self.item["id"],"restricted",self.item["version"],"reviewer","bridge_engineer",notice_no="NT-B")
        self.assertEqual(self.service.last_decision_failure("viewer")["notice_no"],"NT-B")
if __name__=="__main__": unittest.main()
