import {
    BookOpen,
    Feather,
    FlaskConical,
    LayoutDashboard,
    MessageSquare,
    Plus,
    Settings,
    Upload,
    Trash2,
} from "lucide-react";
import type { Project } from "../shared/api";

const pages = [
    { id: "overview", label: "项目概览", icon: LayoutDashboard },
    { id: "library", label: "文献阅读", icon: BookOpen },
    { id: "notes", label: "笔记", icon: BookOpen },
    { id: "experiments", label: "实验记录", icon: FlaskConical },
    { id: "writing", label: "论文写作", icon: Feather },
    { id: "assistant", label: "问答", icon: MessageSquare },
];

type Props = {
    projects: Project[];
    project?: Project;
    projectId: string;
    page: string;
    sourcesCount: number;
    onNavigate: (page: string) => void;
    onSelect: (id: string) => void;
    onNew: () => void;
    onRestore: () => void;
    onChat: () => void;
    onTrash: () => void;
};

export function Sidebar({
    projects,
    project,
    projectId,
    page,
    sourcesCount,
    onNavigate,
    onSelect,
    onNew,
    onRestore,
    onChat,
    onTrash,
}: Props) {
    return (
        <aside className="sidebar">
            <a
                className="brand"
                href="#"
                onClick={(event) => {
                    event.preventDefault();
                    onNavigate("overview");
                }}
            >
                <span className="brand-symbol">A</span>
                <span>Aster</span>
            </a>
            <button
                className="new-conversation"
                aria-label="开始新对话"
                onClick={onChat}
                disabled={!project}
            >
                <Plus size={17} />
                新对话
            </button>
            <div className="project-picker">
                <label htmlFor="project-picker">研究项目</label>
                <div className="inline">
                    <select
                        id="project-picker"
                        value={projectId}
                        onChange={(event) => onSelect(event.target.value)}
                    >
                        {!projects.length && (
                            <option value="">还没有项目</option>
                        )}
                        {projects.map((item) => (
                            <option key={item.id} value={item.id}>
                                {item.title}
                            </option>
                        ))}
                    </select>
                    <button
                        className="icon-button"
                        aria-label="新建项目"
                        onClick={onNew}
                    >
                        <Plus size={17} />
                    </button>
                </div>
            </div>
            <nav aria-label="项目功能">
                {pages
                    .filter(
                        (item) =>
                            item.id !== "experiments" ||
                            project?.domain !== "general",
                    )
                    .map((item) => (
                        <div className="navigation-item" key={item.id}>
                            <button
                                className={page === item.id ? "active" : ""}
                                onClick={() => onNavigate(item.id)}
                                disabled={!project}
                            >
                                <item.icon size={17} />
                                {item.id === "writing" &&
                                project?.domain === "general"
                                    ? "写作与报告"
                                    : item.label}
                                {item.id === "library" && sourcesCount > 0 && (
                                    <span className="nav-count">
                                        {sourcesCount}
                                    </span>
                                )}
                            </button>
                        </div>
                    ))}
            </nav>
            <div className="sidebar-bottom">
                <button onClick={onTrash}>
                    <Trash2 size={16} />
                    回收站
                </button>
                <button onClick={onRestore}>
                    <Upload size={16} />
                    恢复项目备份
                </button>
                <button
                    className={page === "settings" ? "active" : ""}
                    onClick={() => onNavigate("settings")}
                >
                    <Settings size={16} />
                    设置与模型
                </button>
            </div>
        </aside>
    );
}
