import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import type { Agent } from "../types";

interface Line { cls: string; text: string }

/** Modal chat with one new-generation agent. Remembers earlier turns through the response id. */
export default function ChatDialog({ agent, onClose }: { agent: Agent | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [prev, setPrev] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (agent && !d.open) { setLines([]); setPrev(null); setText(""); d.showModal(); }
    if (!agent && d.open) d.close();
  }, [agent]);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [lines]);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!agent || !text.trim()) return;
    const message = text; setText(""); setBusy(true);
    setLines((l) => [...l, { cls: "u", text: `You: ${message}` }]);
    try {
      const r = await api.chatAgent({ project: agent.project ?? "", account: agent.account ?? "", name: agent.name, message, previous: prev });
      setPrev(r.id ?? null);
      setLines((l) => [...l, { cls: "", text: r.text }]);
    } catch (err) {
      setLines((l) => [...l, { cls: "bad", text: (err as Error).message }]);
    } finally { setBusy(false); }
  }

  return (
    <dialog ref={ref} onClose={onClose}>
      <strong>{agent ? `Chat with ${agent.name}` : ""}</strong>
      <div id="clog" ref={log}>{lines.map((l, i) => <p key={i} className={l.cls}>{l.text}</p>)}</div>
      <form onSubmit={send} style={{ display: "flex", gap: 6 }}>
        <input value={text} onChange={(e) => setText(e.target.value)} required maxLength={4000} placeholder="Ask the agent…" autoComplete="off" aria-label="Message" />
        <button className="primary" disabled={busy}>Send</button>
        <button type="button" onClick={() => ref.current?.close()}>Close</button>
      </form>
    </dialog>
  );
}
