import tempfile, unittest
from pathlib import Path
from src.repository import Repository
from src.service import Service
from src.rules import NOTICE_KIND, NOTICE_REQUIRED_TARGETS, STATES, TRANSITION_ROLES
class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.repo=Repository(str(Path(self.tmp.name)/"test.db")); self.service=Service(self.repo)
    def tearDown(self): self.repo.close(); self.tmp.cleanup()
    def test_complete_workflow_and_audit(self):
        item=self.service.create_item({"title":"workflow item","description":"complete business flow","severity":'warning',"quantity":12,"threshold":6,"external_ref":"WF-1"},"creator",'sensor_operator')
        self.assertEqual(item["status"],STATES[0])
        self.service.add_record(item["id"],{"kind":"evidence","detail":"evidence registered","status":"closed","external_ref":"EV-1"},"recorder",'sensor_operator')
        self.service.add_record(item["id"],{"kind":NOTICE_KIND,"detail":"traffic notice registered","status":"open","external_ref":"NT-1"},"recorder",'sensor_operator')
        current=item
        for target in STATES[1:]:
            current=self.service.transition(current["id"],target,current["version"],"reviewer",TRANSITION_ROLES[target][0],notice_no="NT-1")
        self.assertEqual(current["status"],STATES[-1])
        self.assertEqual(len(self.service.list_records(current["id"],"viewer")),2)
        events=self.service.audit("viewer",current["id"]); self.assertGreaterEqual(len(events),len(STATES)+1); self.assertTrue(self.repo.verify_audit_chain())
        gated=[e for e in events if e["action"]=="transition" and e["detail"]["to"] in NOTICE_REQUIRED_TARGETS]
        self.assertTrue(gated); self.assertTrue(all(e["detail"].get("notice_no")=="NT-1" for e in gated))
if __name__=="__main__": unittest.main()
