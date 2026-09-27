import tempfile, unittest
from pathlib import Path
from src.domain import ConflictError, NotFoundError, ValidationError
from src.repository import Repository
from src.service import Service
class NoticeTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.repo=Repository(str(Path(self.tmp.name)/"test.db")); self.service=Service(self.repo)
        self.item=self.service.create_item({"title":"notice item","description":"traffic notice checks","severity":'warning',"quantity":5,"threshold":10,"external_ref":"NT-1"},"creator",'sensor_operator')
        self.service.transition(self.item["id"],"warning",1,"reviewer",'sensor_operator')
        self.current=self.service.get_item(self.item["id"],"viewer")
    def tearDown(self): self.repo.close(); self.tmp.cleanup()
    def _notice(self,ref,status="open",item_id=None):
        return self.service.add_record(item_id or self.item["id"],{"kind":"traffic_notice","detail":"notice","status":status,"external_ref":ref},"inspector",'bridge_engineer')
    def _last(self):
        return self.service.get_item(self.item["id"],"viewer")["last_decision"]
    def test_missing_notice_ref_rejected(self):
        with self.assertRaises(ValidationError): self.service.transition(self.item["id"],"restricted",self.current["version"],"reviewer",'bridge_engineer')
    def test_unknown_notice_rejected_and_state_kept(self):
        with self.assertRaises(NotFoundError) as ctx: self.service.transition(self.item["id"],"restricted",self.current["version"],"reviewer",'bridge_engineer',"TN-404")
        self.assertEqual(str(ctx.exception),"交通通告不存在")
        item=self.service.get_item(self.item["id"],"viewer")
        self.assertEqual(item["status"],"warning"); self.assertEqual(item["version"],self.current["version"])
        last=item["last_decision"]
        self.assertEqual(last["result"],"rejected"); self.assertEqual(last["reason"],"交通通告不存在")
        self.assertEqual(last["notice_ref"],"TN-404"); self.assertEqual(last["actor"],"reviewer")
    def test_closed_notice_rejected(self):
        self._notice("TN-C1","closed")
        with self.assertRaises(ConflictError) as ctx: self.service.transition(self.item["id"],"restricted",self.current["version"],"reviewer",'bridge_engineer',"TN-C1")
        self.assertEqual(str(ctx.exception),"交通通告已关闭")
        self.assertEqual(self.service.get_item(self.item["id"],"viewer")["status"],"warning")
        self.assertEqual(self._last()["reason"],"交通通告已关闭")
    def test_notice_of_other_bridge_rejected(self):
        other=self.service.create_item({"title":"other bridge","description":"another bridge","severity":'warning',"quantity":1,"threshold":10,"external_ref":"NT-2"},"creator",'sensor_operator')
        self._notice("TN-X1",item_id=other["id"])
        with self.assertRaises(ConflictError) as ctx: self.service.transition(self.item["id"],"restricted",self.current["version"],"reviewer",'bridge_engineer',"TN-X1")
        self.assertEqual(str(ctx.exception),"交通通告属于其他桥梁")
        self.assertEqual(self.service.get_item(self.item["id"],"viewer")["status"],"warning")
        self.assertEqual(self._last()["reason"],"交通通告属于其他桥梁")
    def test_valid_notice_allows_transition_and_clears_failure(self):
        with self.assertRaises(NotFoundError): self.service.transition(self.item["id"],"restricted",self.current["version"],"reviewer",'bridge_engineer',"TN-404")
        self._notice("TN-OK1")
        updated=self.service.transition(self.item["id"],"restricted",self.current["version"],"reviewer",'bridge_engineer',"TN-OK1")
        self.assertEqual(updated["status"],"restricted"); self.assertIsNone(updated["last_decision"])
        events=[e for e in self.service.audit("viewer",self.item["id"]) if e["action"]=="transition" and e["detail"].get("to")=="restricted"]
        self.assertEqual(events[0]["detail"]["notice_ref"],"TN-OK1")
    def test_notice_registration_requires_number(self):
        with self.assertRaises(ValidationError): self.service.add_record(self.item["id"],{"kind":"traffic_notice","detail":"no number","status":"open"},"inspector",'bridge_engineer')
    def test_close_record_lifecycle(self):
        notice=self._notice("TN-CL1")
        closed=self.service.close_record(self.item["id"],notice["id"],"inspector",'bridge_engineer')
        self.assertEqual(closed["status"],"closed")
        with self.assertRaises(ConflictError): self.service.close_record(self.item["id"],notice["id"],"inspector",'bridge_engineer')
if __name__=="__main__": unittest.main()
