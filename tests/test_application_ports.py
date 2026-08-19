

from pathlib import Path

from fnirs_flow.application.ports.project_repository import ProjectRepository
from fnirs_flow.application.project_use_cases import validate_project_flow


class MemoryProjectRepository:
    def __init__(self):
        self.projects = {
            "p": {
                "flow": {"schema_version": "0.3.0", "flow_id": "f", "flow_atoms": [], "edges": []},
                "state": {},
            }
        }

    def get(self, project_id):
        return self.projects.get(project_id)

    def get_flow(self, project_id):
        project = self.get(project_id)
        return project["flow"] if project else None

    def update_state(self, project_id, **values):
        self.projects[project_id]["state"].update(values)

    def get_output_dir(self, project_id):
        return Path("unused")


def test_in_memory_repository_satisfies_application_port():
    repository = MemoryProjectRepository()
    assert isinstance(repository, ProjectRepository)
    assert repository.get_flow("p")["flow_id"] == "f"
    result = validate_project_flow(repository, "p")
    assert result.is_valid
    assert repository.projects["p"]["state"]["validated_flow"]
