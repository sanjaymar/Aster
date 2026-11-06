import { BookOpen, LoaderCircle, X } from "lucide-react";
import {
    Children,
    cloneElement,
    isValidElement,
    useEffect,
    useId,
    useRef,
    useState,
    type ReactNode,
} from "react";

export const kindLabels: Record<string, string> = {
    note: "笔记",
    deck: "汇报",
    labnote: "实验日志",
    draft: "写作草稿",
    report: "研究报告",
    plan: "实验方案",
    result: "实验结果",
};
export const statusLabels: Record<string, string> = {
    queued: "排队中",
    running: "进行中",
    completed: "已完成",
    error: "执行失败",
    cancelled: "已取消",
    interrupted: "已中断",
    exhausted: "达到轮数限制",
    timeout: "等待超时",
};
export const date = (value: string) =>
    new Date(value).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
export function Spinner() {
    return <LoaderCircle size={16} className="spin" aria-label="加载中" />;
}
export function Empty({
    icon = <BookOpen size={30} />,
    title,
    children,
    action,
}: {
    icon?: ReactNode;
    title: string;
    children?: ReactNode;
    action?: ReactNode;
}) {
    return (
        <div className="empty">
            <div className="empty-icon">{icon}</div>
            <h3>{title}</h3>
            <p>{children}</p>
            {action}
        </div>
    );
}
export function Modal({
    title,
    children,
    onClose,
    wide = false,
}: {
    title: string;
    children: ReactNode;
    onClose: () => void;
    wide?: boolean;
}) {
    const ref = useRef<HTMLDialogElement>(null);
    const [error, setError] = useState("");
    useEffect(() => {
        const d = ref.current;
        d?.showModal();
        const handler = (e: Event) =>
            setError((e as CustomEvent<string>).detail);
        window.addEventListener("zhixu:error", handler);
        return () => {
            d?.close();
            window.removeEventListener("zhixu:error", handler);
        };
    }, []);
    return (
        <dialog
            aria-label={title}
            ref={ref}
            className={"modal " + (wide ? "wide" : "")}
            onCancel={(e) => {
                e.preventDefault();
                onClose();
            }}
            onClick={(e) => {
                if (e.target === ref.current) onClose();
            }}
        >
            <header className="modal-head">
                <h2>{title}</h2>
                <button
                    className="icon-button"
                    onClick={onClose}
                    aria-label="关闭"
                >
                    <X size={19} />
                </button>
            </header>
            <div className="modal-body">
                {error && (
                    <div className="error-banner" role="alert">
                        <span>{error}</span>
                        <button
                            onClick={() => setError("")}
                            aria-label="关闭错误"
                        >
                            <X size={15} />
                        </button>
                    </div>
                )}
                {children}
            </div>
        </dialog>
    );
}
export function Field({
    label,
    children,
    hint,
}: {
    label: string;
    children: ReactNode;
    hint?: string;
}) {
    const id = useId();
    const control = Children.map(children, (child) =>
        isValidElement<{ id?: string; "aria-describedby"?: string }>(child) &&
        typeof child.type === "string" &&
        ["input", "textarea", "select"].includes(child.type)
            ? cloneElement(child, {
                  id,
                  "aria-describedby": hint ? id + "-hint" : undefined,
              })
            : child,
    );
    return (
        <div className="field">
            <label htmlFor={id}>{label}</label>
            {control}
            {hint && <small id={id + "-hint"}>{hint}</small>}
        </div>
    );
}
