"""Model and instruction-skill management. Secrets never appear in responses."""

from aster.models.profiles import ProfileInput, DefaultsInput
from aster.agent.skills import SkillInput


def configure(app):
    manager = app.state.manager

    @app.get("/api/models/profiles")
    def profiles():
        return manager.profiles.public()

    @app.post("/api/models/profiles", status_code=201)
    def create_profile(body: ProfileInput):
        return manager.profiles.save(body)

    @app.put("/api/models/profiles/{profile_id}")
    def update_profile(profile_id: str, body: ProfileInput):
        return manager.profiles.save(body, profile_id)

    @app.delete("/api/models/profiles/{profile_id}")
    def delete_profile(profile_id: str):
        return manager.profiles.delete(profile_id)

    @app.put("/api/models/defaults")
    def defaults(body: DefaultsInput):
        return manager.profiles.defaults(body)

    @app.get("/api/models/profiles/{profile_id}/health")
    def model_health(profile_id: str):
        return manager.profiles.health(profile_id)

    @app.get("/api/skills")
    def skills():
        return manager.skills.all()

    @app.post("/api/skills", status_code=201)
    def create_skill(body: SkillInput):
        return manager.skills.save(body)

    @app.put("/api/skills/{skill_id}")
    def update_skill(skill_id: str, body: SkillInput):
        return manager.skills.save(body, skill_id)

    @app.delete("/api/skills/{skill_id}")
    def delete_skill(skill_id: str):
        return manager.skills.delete(skill_id)
