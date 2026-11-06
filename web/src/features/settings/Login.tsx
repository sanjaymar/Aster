import { Leaf, LogIn } from "lucide-react";
import { useState } from "react";
import { api, send } from "../../shared/api";
import { Field, Spinner } from "../../shared/components";

export function Login({
    onLoggedIn,
    onError,
    error,
}: {
    onLoggedIn: () => void;
    onError: (s: string) => void;
    error: string;
}) {
    const [token, setToken] = useState(""),
        [busy, setBusy] = useState(false);
    return (
        <div className="login">
            <form
                onSubmit={async (e) => {
                    e.preventDefault();
                    setBusy(true);
                    try {
                        await api("/session", send("POST", { token }));
                        onLoggedIn();
                    } catch (e) {
                        onError((e as Error).message);
                    } finally {
                        setBusy(false);
                    }
                }}
            >
                <span className="brand-symbol">
                    <Leaf size={24} />
                </span>
                <h1>欢迎回到Aster</h1>
                <p className="muted">输入此研究空间的访问口令。</p>
                <Field label="访问口令">
                    <input
                        type="password"
                        autoComplete="current-password"
                        autoFocus
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                    />
                </Field>
                {error && (
                    <p className="error-text" role="alert">
                        {error}
                    </p>
                )}
                <button className="button primary" disabled={!token || busy}>
                    {busy ? <Spinner /> : <LogIn size={16} />}进入研究空间
                </button>
            </form>
        </div>
    );
}
