import Image from "@tiptap/extension-image";
import { TaskList, TaskItem } from "@tiptap/extension-list";
import { TableKit } from "@tiptap/extension-table";
import { Markdown } from "@tiptap/markdown";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
    Bold,
    Code,
    Italic,
    List,
    ListOrdered,
    Quote,
    Redo2,
    Table2,
    Undo2,
    ListChecks,
    Code2,
    Minus,
    Link2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

export function RichTextEditor({
    value,
    onChange,
    label = "正文",
    compact = false,
}: {
    value: string;
    onChange: (value: string) => void;
    label?: string;
    compact?: boolean;
}) {
    const callback = useRef(onChange);
    callback.current = onChange;
    const lastEmitted = useRef(value);
    const [source, setSource] = useState(false);
    const [linkOpen, setLinkOpen] = useState(false),
        [link, setLink] = useState("");
    const editor = useEditor({
        immediatelyRender: false,
        extensions: [
            StarterKit.configure({ link: { openOnClick: false } }),
            TableKit.configure({ table: { resizable: false } }),
            Image.configure({ allowBase64: false }),
            Markdown.configure({ markedOptions: { gfm: true } }),
            TaskList,
            TaskItem.configure({ nested: true }),
        ],
        content: value,
        contentType: "markdown",
        editorProps: {
            attributes: {
                role: "textbox",
                "aria-label": label,
                "aria-multiline": "true",
                spellcheck: "false",
            },
            handlePaste: (_view, event) => {
                const clipboard = event.clipboardData;
                if (!clipboard || clipboard.getData("text/html")) return false;
                const text = clipboard.getData("text/plain");
                if (!text.includes("\t")) return false;
                const rows = text
                    .replace(/\r\n/g, "\n")
                    .replace(/\n$/, "")
                    .split("\n")
                    .map((row) => row.split("\t"));
                if (
                    rows.length > 200 ||
                    Math.max(...rows.map((row) => row.length)) > 30
                )
                    return false;
                editor
                    ?.chain()
                    .focus()
                    .insertContent({
                        type: "table",
                        content: rows.map((row, i) => ({
                            type: "tableRow",
                            content: row.map((text) => ({
                                type: i === 0 ? "tableHeader" : "tableCell",
                                content: [
                                    {
                                        type: "paragraph",
                                        content: text
                                            ? [{ type: "text", text }]
                                            : [],
                                    },
                                ],
                            })),
                        })),
                    })
                    .run();
                return true;
            },
        },
        onUpdate: ({ editor }) => {
            const markdown = editor
                .getMarkdown()
                .replace(
                    /\\\[\\\[([SCV]):([a-f0-9]{32})\\\]\\\]/g,
                    "[[$1:$2]]",
                );
            lastEmitted.current = markdown;
            callback.current(markdown);
        },
    });
    useEffect(() => {
        if (editor && !editor.isDestroyed && value !== lastEmitted.current) {
            editor.commands.setContent(value, {
                contentType: "markdown",
                emitUpdate: false,
            });
            lastEmitted.current = value;
        }
    }, [editor, value]);
    if (!editor) return null;
    const button = (
        title: string,
        icon: React.ReactNode,
        action: () => void,
        active = false,
    ) => (
        <button
            type="button"
            title={title}
            aria-label={title}
            className={active ? "active" : ""}
            onClick={action}
        >
            {icon}
        </button>
    );
    return (
        <div className={`rich-editor ${compact ? "compact" : ""}`}>
            <div
                className="format-toolbar"
                onMouseDown={(e) => {
                    if ((e.target as HTMLElement).closest("button"))
                        e.preventDefault();
                }}
            >
                <select
                    aria-label="段落样式"
                    value={
                        editor.isActive("heading", { level: 1 })
                            ? "1"
                            : editor.isActive("heading", { level: 2 })
                              ? "2"
                              : editor.isActive("heading", { level: 3 })
                                ? "3"
                                : "0"
                    }
                    onChange={(e) => {
                        const level = Number(e.target.value);
                        if (level)
                            editor
                                .chain()
                                .focus()
                                .toggleHeading({ level: level as 1 | 2 | 3 })
                                .run();
                        else editor.chain().focus().setParagraph().run();
                    }}
                >
                    <option value="0">正文</option>
                    <option value="1">标题 1</option>
                    <option value="2">标题 2</option>
                    <option value="3">标题 3</option>
                </select>
                {button(
                    "加粗",
                    <Bold size={15} />,
                    () => {
                        editor.chain().focus().toggleBold().run();
                    },
                    editor.isActive("bold"),
                )}
                {button(
                    "斜体",
                    <Italic size={15} />,
                    () => {
                        editor.chain().focus().toggleItalic().run();
                    },
                    editor.isActive("italic"),
                )}
                {button("无序列表", <List size={15} />, () => {
                    editor.chain().focus().toggleBulletList().run();
                })}
                {button("有序列表", <ListOrdered size={15} />, () => {
                    editor.chain().focus().toggleOrderedList().run();
                })}
                {button(
                    "任务清单",
                    <ListChecks size={15} />,
                    () => {
                        editor.chain().focus().toggleTaskList().run();
                    },
                    editor.isActive("taskList"),
                )}
                {button(
                    "代码块",
                    <Code2 size={15} />,
                    () => {
                        editor.chain().focus().toggleCodeBlock().run();
                    },
                    editor.isActive("codeBlock"),
                )}
                {button("链接", <Link2 size={15} />, () => {
                    setLink(editor.getAttributes("link").href || "");
                    setLinkOpen((v) => !v);
                })}
                {button("分割线", <Minus size={15} />, () => {
                    editor.chain().focus().setHorizontalRule().run();
                })}
                {button("引用段落", <Quote size={15} />, () => {
                    editor.chain().focus().toggleBlockquote().run();
                })}
                {button("插入表格", <Table2 size={15} />, () => {
                    editor
                        .chain()
                        .focus()
                        .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
                        .run();
                })}
                {editor.isActive("table") && (
                    <>
                        <button
                            type="button"
                            onClick={() =>
                                editor.chain().focus().addRowAfter().run()
                            }
                        >
                            加行
                        </button>
                        <button
                            type="button"
                            onClick={() =>
                                editor.chain().focus().addColumnAfter().run()
                            }
                        >
                            加列
                        </button>
                        <button
                            type="button"
                            onClick={() =>
                                editor.chain().focus().deleteRow().run()
                            }
                        >
                            删行
                        </button>
                        <button
                            type="button"
                            onClick={() =>
                                editor.chain().focus().deleteColumn().run()
                            }
                        >
                            删列
                        </button>
                        <button
                            type="button"
                            onClick={() =>
                                editor.chain().focus().deleteTable().run()
                            }
                        >
                            删表
                        </button>
                    </>
                )}
                <span className="toolbar-spacer" />
                {button("撤销", <Undo2 size={15} />, () => {
                    editor.chain().focus().undo().run();
                })}
                {button("重做", <Redo2 size={15} />, () => {
                    editor.chain().focus().redo().run();
                })}
                {button(
                    "Markdown 源文",
                    <Code size={15} />,
                    () => setSource((v) => !v),
                    source,
                )}
            </div>
            {linkOpen && (
                <div className="editor-link-input">
                    <input
                        aria-label="链接地址"
                        type="url"
                        placeholder="https://"
                        value={link}
                        onChange={(e) => setLink(e.target.value)}
                    />
                    <button
                        type="button"
                        className="text-button"
                        onClick={() => {
                            if (!link)
                                editor
                                    .chain()
                                    .focus()
                                    .extendMarkRange("link")
                                    .unsetLink()
                                    .run();
                            else if (/^https?:\/\//i.test(link))
                                editor
                                    .chain()
                                    .focus()
                                    .extendMarkRange("link")
                                    .setLink({ href: link })
                                    .run();
                            setLinkOpen(false);
                        }}
                    >
                        应用
                    </button>
                </div>
            )}
            {source ? (
                <textarea
                    aria-label={`${label}源文`}
                    className="markdown-source"
                    value={value}
                    onChange={(e) => {
                        lastEmitted.current = e.target.value;
                        editor.commands.setContent(e.target.value, {
                            contentType: "markdown",
                            emitUpdate: false,
                        });
                        onChange(e.target.value);
                    }}
                />
            ) : (
                <EditorContent editor={editor} />
            )}
        </div>
    );
}
