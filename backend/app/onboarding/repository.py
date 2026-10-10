import json
import sqlite3

from .contracts import INITIAL_THETA, LearnerProfile, OnboardingInput, TopicMapping, UserConcept, UserConceptInput


class OnboardingRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_profile(self, user_id: int) -> LearnerProfile | None:
        row = self.connection.execute("SELECT * FROM onboarding_profiles WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            return None
        mappings = [TopicMapping.model_validate(item) for item in json.loads(row["mappings"])]
        concepts = []
        if row["status"] == "confirmed":
            concepts = [UserConcept.model_validate(dict(item)) for item in self.connection.execute(
                "SELECT * FROM user_concepts WHERE user_id=? ORDER BY concept_id, role", (user_id,),
            ).fetchall()]
        return LearnerProfile(
            user_id=user_id, revision=row["revision"], status=row["status"],
            onboarding=OnboardingInput.model_validate(json.loads(row["payload"])),
            mappings=mappings, unmapped=[item for item in mappings if item.concept_id is None],
            user_concepts=concepts, confirmed_at=row["confirmed_at"],
        )

    def save_draft(self, user_id: int, payload: OnboardingInput, mappings: list[TopicMapping], now: str) -> LearnerProfile:
        self.connection.execute(
            """INSERT INTO onboarding_profiles(user_id, payload, mappings, revision, status, updated_at)
               VALUES (?, ?, ?, 1, 'draft', ?)
               ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload, mappings=excluded.mappings,
                 revision=onboarding_profiles.revision+1, status='draft', updated_at=excluded.updated_at,
                 confirmed_at=NULL""",
            (user_id, payload.model_dump_json(), json.dumps([item.model_dump(mode="json") for item in mappings]), now),
        )
        result = self.get_profile(user_id)
        assert result is not None
        return result

    def confirm(self, profile: LearnerProfile, concepts: list[UserConceptInput], mappings: list[TopicMapping],
                now: str) -> LearnerProfile:
        cursor = self.connection.execute(
            """UPDATE onboarding_profiles SET status='confirmed', confirmed_at=?, updated_at=?, mappings=?
               WHERE user_id=? AND revision=? AND status='draft'""",
            (now, now, json.dumps([item.model_dump(mode="json") for item in mappings]), profile.user_id, profile.revision),
        )
        if cursor.rowcount != 1:
            raise ValueError("stale_revision")
        previous = {(row["concept_id"], row["role"]): dict(row) for row in self.connection.execute(
            "SELECT * FROM user_concepts WHERE user_id=?", (profile.user_id,),
        ).fetchall()}
        selected = {(item.concept_id, item.role) for item in concepts}
        for item in concepts:
            old = previous.get((item.concept_id, item.role))
            attempts = old["n_attempts"] if old else 0
            theta = old["theta"] if attempts else INITIAL_THETA[item.self_level]
            self.connection.execute(
                """INSERT INTO user_concepts(user_id, concept_id, role, self_level, theta, n_attempts)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, concept_id, role) DO UPDATE SET self_level=excluded.self_level,
                     theta=excluded.theta, n_attempts=excluded.n_attempts""",
                (profile.user_id, item.concept_id, item.role, item.self_level, theta, attempts),
            )
        for concept_id, role in previous.keys() - selected:
            self.connection.execute(
                "DELETE FROM user_concepts WHERE user_id=? AND concept_id=? AND role=?",
                (profile.user_id, concept_id, role),
            )
        result = self.get_profile(profile.user_id)
        assert result is not None
        return result
