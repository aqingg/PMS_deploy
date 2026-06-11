import json
from sqlalchemy import Column, Integer, String, Text
from .database import Base

def safe_json_load(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True)
    owner = Column(String, index=True)
    editors = Column(Text)
    department = Column(String, index=True)
    projectName = Column(String, index=True)
    projectInfo = Column(Text)
    projectWorkFlow = Column(Text)

    comment = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    orderIndex = Column(Integer, nullable=True, default=0)

    def calc_progress(self):
        try:
            wf = safe_json_load(self.projectWorkFlow, {})
            task_tree = wf.get("taskTree", [])

            def collect(nodes):
                for n in nodes:
                    yield n
                    yield from collect(n.get("children", []))

            nodes = list(collect(task_tree))
            if not nodes:
                return 0

            done_count = sum(1 for n in nodes if n.get("status") in ("Done", "Decline"))
            return done_count / len(nodes)

        except Exception:
            return 0

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "owner": self.owner,
            "editors": safe_json_load(self.editors, []),
            "department": self.department,
            "projectName": self.projectName,

            "projectInfo": safe_json_load(self.projectInfo, {
                "projectInfo": [],
                "owner": {"label": "Owner", "value": ""},
                "proxies": {"label": "Proxies", "value": ""},
                "uuid": {"label": "uuid", "value": ""}
            }),

            "projectWorkFlow": safe_json_load(self.projectWorkFlow, {
                "taskTree": [],
                "taskDetails": {}
            }),

            "comment": self.comment or "",
            "tags": safe_json_load(self.tags, []),
            "orderIndex": self.orderIndex or 0,

            "progress": self.calc_progress()
        }
