import { useEffect, useState } from "react";
import { api, type ProfileState, type Skill } from "../../shared/api";

export function useAssistantOptions(reader: boolean) {
    const [profiles, setProfiles] = useState<ProfileState | null>(null),
        [skills, setSkills] = useState<Skill[]>([]);
    const [modelId, setModelId] = useState(""),
        [skillId, setSkillId] = useState("");
    useEffect(() => {
        const models = () => {
            void api<ProfileState>("/models/profiles")
                .then(setProfiles)
                .catch(() => {});
        };
        const loadSkills = () => {
            void api<Skill[]>("/skills")
                .then((items) => setSkills(items.filter((s) => s.enabled)))
                .catch(() => {});
        };
        models();
        loadSkills();
        window.addEventListener("aster:models-updated", models);
        window.addEventListener("aster:skills-updated", loadSkills);
        return () => {
            window.removeEventListener("aster:models-updated", models);
            window.removeEventListener("aster:skills-updated", loadSkills);
        };
    }, []);
    const selected = profiles?.profiles.find(
        (p) =>
            p.id ===
            (modelId || profiles.defaults[reader ? "reader" : "assistant"]),
    );
    return {
        profiles,
        skills,
        modelId,
        setModelId,
        skillId,
        setSkillId,
        selected,
    };
}

export function AssistantOptions({
    options,
    reader,
    disabled,
}: {
    options: ReturnType<typeof useAssistantOptions>;
    reader: boolean;
    disabled: boolean;
}) {
    return (
        <div className="assistant-options">
            <select
                aria-label={reader ? "PDF 问答模型" : "问答模型"}
                value={options.modelId}
                disabled={disabled}
                onChange={(e) => options.setModelId(e.target.value)}
            >
                <option value="">
                    默认 ·{" "}
                    {options.profiles?.profiles.find(
                        (p) =>
                            p.id ===
                            options.profiles?.defaults[
                                reader ? "reader" : "assistant"
                            ],
                    )?.name || "模型"}
                </option>
                {options.profiles?.profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                        {p.name}
                        {p.provider === "codex" ? " · Codex" : ""}
                    </option>
                ))}
            </select>
            <select
                aria-label="助手 Skill"
                value={options.skillId}
                disabled={disabled}
                onChange={(e) => options.setSkillId(e.target.value)}
            >
                <option value="">Skills · 自动</option>
                {options.skills.map((s) => (
                    <option value={s.id} key={s.id}>
                        {s.name}
                    </option>
                ))}
            </select>
        </div>
    );
}
