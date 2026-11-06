/** Templates are user-editable documents, never synthetic experiment results. */
export const noteTypes: Record<string, string> = {
    note: "自由笔记",
    reading: "阅读笔记",
    idea: "研究想法",
    daily: "研究日志",
    meeting: "组会记录",
    method: "方法卡片",
    comparison: "文献对照",
};
export const templates = [
    {
        id: "blank",
        label: "空白",
        type: "note",
        description: "随时记录",
        content: "",
    },
    {
        id: "reading",
        label: "论文精读",
        type: "reading",
        description: "问题、方法、发现与疑问",
        content:
            "## 研究问题\n\n## 方法与数据\n\n## 主要发现\n\n## 局限与疑问\n\n## 我的理解\n",
    },
    {
        id: "idea",
        label: "研究想法",
        type: "idea",
        description: "假设、依据与验证",
        content:
            "## 想法\n\n## 已有依据\n\n## 竞争解释\n\n## 最小验证\n\n- [ ] 下一步\n",
    },
    {
        id: "daily",
        label: "研究日志",
        type: "daily",
        description: "进展、问题和下一步",
        content: "## 今日进展\n\n## 遇到的问题\n\n## 下一步\n\n- [ ] \n",
    },
    {
        id: "meeting",
        label: "组会记录",
        type: "meeting",
        description: "议题、决策与待办",
        content:
            "## 议题\n\n## 讨论记录\n\n## 决策\n\n| 任务 | 负责人 | 截止时间 |\n| --- | --- | --- |\n|  |  |  |\n",
    },
    {
        id: "method",
        label: "方法卡片",
        type: "method",
        description: "适用范围、参数和注意事项",
        content:
            "## 目的与适用范围\n\n## 输入与前提\n\n## 步骤\n\n| 参数 | 设定 | 依据 |\n| --- | --- | --- |\n|  |  |  |\n\n## 质控与常见问题\n",
    },
    {
        id: "comparison",
        label: "文献对照",
        type: "comparison",
        description: "把多篇文献放在同一张表",
        content:
            "## 比较问题\n\n| 文献 | 研究对象 | 方法 | 主要结果 | 局限 |\n| --- | --- | --- | --- | --- |\n|  |  |  |  |  |\n\n## 分歧与启发\n",
    },
];
