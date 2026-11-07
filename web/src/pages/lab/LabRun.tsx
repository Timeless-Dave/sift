import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Assay } from "../../api";
import { cardCapture, recorder, screenlightCapture } from "../../capture";
import { getDevice, getTier } from "../../util";
import "../../styles/lab.css";

interface Loaded { assay: Assay; device: string; tier: string }

export default function LabRun() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState("");
  const [stepIdx, setStepIdx] = useState(0);
  const [stepText, setStepText] = useState("");
  const [agentName, setAgentName] = useState("");
  const [practice, setPractice] = useState(false);
  const [working, setWorking] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [captureNonce, setCaptureNonce] = useState(0);
  const [thinking, setThinking] = useState(false);
  const [agentError, setAgentError] = useState("");
  const [input, setInput] = useState("");
  const [micLabel, setMicLabel] = useState("Hold to talk");
  const [micLive, setMicLive] = useState(false);
  const history = useRef<{ role: string; content: string }[]>([]);
  const recRef = useRef<ReturnType<typeof recorder> | null>(null);
  const recording = useRef(false);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const assay = await api.assay(id);
        const device = await getDevice();
        if (!live) return;
        setLoaded({ assay, device, tier: getTier() });
        setStepText(assay.protocol?.[0]?.instruction ?? "");
      } catch (e) {
        if (live) setError((e as Error).message);
      }
    })();
    return () => { live = false; };
  }, [id]);

  const show = useCallback((idx: number, text: string, agent = "") => {
    setStepIdx(idx);
    setStepText(text);
    setAgentName(agent);
    setWorking(false);
    setSubmitError("");
  }, []);

  const submit = useCallback(async (run: () => Promise<{ run_id: string }>) => {
    setWorking(true);
    setSubmitError("");
    try {
      const r = await run();
      navigate(`/lab-tests/result/${r.run_id}`);
    } catch (e) {
      setWorking(false);
      setSubmitError((e as Error).message);
    }
  }, [navigate]);

  const askAgent = useCallback(async (message: string) => {
    if (!message.trim() || !loaded) return;
    const steps = loaded.assay.protocol ?? [];
    history.current.push({ role: "user", content: message });
    setThinking(true);
    setAgentError("");
    try {
      const r = await api.agent({
        assay_id: loaded.assay.id,
        step_id: steps[stepIdx]?.id ?? "",
        message,
        history: history.current,
        tier: loaded.tier,
      });
      history.current.push({ role: "assistant", content: r.reply });
      const next = steps.findIndex((s) => s.id === r.step_id);
      show(next >= 0 ? next : stepIdx, r.reply, r.agent);
    } catch (e) {
      setAgentError((e as Error).message);
    } finally {
      setThinking(false);
    }
  }, [loaded, stepIdx, show]);

  const startRec = useCallback(async () => {
    try {
      recRef.current ??= recorder();
      await recRef.current.start();
      recording.current = true;
      setMicLabel("Listening…");
      setMicLive(true);
    } catch {
      setMicLabel("Mic blocked");
    }
  }, []);

  const stopRec = useCallback(async () => {
    if (!recording.current || !recRef.current) return;
    recording.current = false;
    setMicLabel("Hold to talk");
    setMicLive(false);
    const blob = await recRef.current.stop();
    try {
      const { text } = await api.transcribe(blob);
      setInput("");
      void askAgent(text);
    } catch (e) {
      setAgentError((e as Error).message);
    }
  }, [askAgent]);

  if (error) {
    return (
      <div className="wrap page lab-run">
        <section className="page-head">
          <Link className="back" to="/lab-tests">← All tests</Link>
          <h1 className="h1">Run this test</h1>
          <p role="alert">Couldn&apos;t load the test: {error}</p>
        </section>
      </div>
    );
  }
  if (!loaded) return <div className="wrap page lab-run"><p className="muted">Loading the protocol…</p></div>;

  const { assay } = loaded;
  const steps = assay.protocol ?? [];
  if (!assay.runnable) {
    return (
      <div className="wrap page lab-run">
        <section className="card">
          <h1 className="h1">{assay.name}</h1>
          <p>This test is planned and can&apos;t be run yet.</p>
          <p><Link to="/lab-tests">Back to tests</Link></p>
        </section>
      </div>
    );
  }
  if (!steps.length) {
    return (
      <div className="wrap page lab-run">
        <section className="card">
          <h1 className="h1">{assay.name}</h1>
          <p>This test has no steps to follow, so it can&apos;t run. Go back and try another test.</p>
          <p><Link to="/lab-tests">Back to tests</Link></p>
        </section>
      </div>
    );
  }

  const step = steps[stepIdx];
  const kit = [...(assay.reagents ?? []), ...(assay.equipment ?? [])];

  return (
    <div className="wrap page lab-run">
      <section className="run">
        <Link className="back" to="/lab-tests">← All tests</Link>
        <p className="food">{assay.food}</p>
        <h1 className="h1">{assay.name}</h1>
        <p className="lede">{assay.summary}</p>
        {kit.length > 0 && (
          <details className="kit card">
            <summary>What you need</summary>
            <ul>{kit.map((i) => <li key={i}>{i}</li>)}</ul>
          </details>
        )}
        {loaded.tier === "research" && (
          <label className="practice">
            <input
              type="checkbox"
              checked={practice}
              onChange={(e) => {
                setPractice(e.target.checked);
                show(stepIdx, steps[stepIdx].instruction);
              }}
            />
            {" "}Practice run (walk the protocol, nothing is saved)
          </label>
        )}
        <ol className="steps">
          {steps.map((s, i) => (
            <li key={s.id} className={i < stepIdx ? "done" : i === stepIdx ? "now" : ""} aria-current={i === stepIdx ? "step" : undefined}>
              {s.title}
            </li>
          ))}
        </ol>
        <div className="stage" aria-live="polite">
          {thinking && <p className="working">Lab Agent is thinking…</p>}
          {agentError && <p className="cam-error" role="alert">{agentError}</p>}
          <div className="step-card card">
            <h2 className="h2">{step.title}</h2>
            <p className="agent-text">{stepText}</p>
            {agentName && (
              <p className="agent-tag">{agentName === "offline" ? "From the written protocol" : "Lab Agent"}</p>
            )}
            {step.wait_seconds ? <Timer key={`${step.id}-t`} seconds={step.wait_seconds} /> : null}
            <div className="row nav">
              {stepIdx > 0 && (
                <button type="button" className="btn ghost" onClick={() => show(stepIdx - 1, steps[stepIdx - 1].instruction)}>
                  Back
                </button>
              )}
              {!step.capture && stepIdx + 1 < steps.length && (
                <button type="button" className="btn" onClick={() => show(stepIdx + 1, steps[stepIdx + 1].instruction)}>
                  Done, next step
                </button>
              )}
            </div>
            {working && <p className="working">Reading the sample…</p>}
            {!working && submitError && (
              <>
                <p className="cam-error" role="alert">{submitError}</p>
                <button type="button" className="btn" onClick={() => { setSubmitError(""); setCaptureNonce((n) => n + 1); }}>
                  Try again
                </button>
              </>
            )}
            {!working && !submitError && step.capture && practice && (
              <p className="muted">In a practice run the capture is skipped. Untick practice to run it for real.</p>
            )}
            {!working && !submitError && step.capture === "card" && !practice && (
              <CardMount
                key={`${step.id}-card-${captureNonce}`}
                onImage={(jpeg) => submit(() => api.runCard(assay.id, jpeg, loaded.device, loaded.tier))}
              />
            )}
            {!working && !submitError && step.capture === "screenlight" && !practice &&
              (!(assay.analysis?.sequence?.length)
                ? <p className="cam-error" role="alert">This test can&apos;t run its light scan: the assay data has no colour sequence. Go back to All tests and try another test.</p>
                : (
                  <ScreenlightMount
                    key={`${step.id}-light-${captureNonce}`}
                    sequence={assay.analysis!.sequence!}
                    frameMs={assay.analysis?.frame_ms ?? 450}
                    onFrames={(frames) => submit(() => api.runScreenlight(assay.id, frames, loaded.device, loaded.tier))}
                  />
                ))}
          </div>
        </div>
        <form
          className="ask"
          onSubmit={(e) => { e.preventDefault(); const v = input; setInput(""); void askAgent(v); }}
        >
          <label htmlFor="ask-input" className="sr">Ask the Lab Agent</label>
          <input
            id="ask-input"
            autoComplete="off"
            placeholder="Ask a question, or say “next”"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button
            type="button"
            className={`btn ghost mic${micLive ? " live" : ""}`}
            aria-label="Hold to talk"
            onPointerDown={startRec}
            onPointerUp={stopRec}
            onPointerLeave={stopRec}
          >
            {micLabel}
          </button>
          <button className="btn" type="submit">Send</button>
        </form>
      </section>
    </div>
  );
}

function Timer({ seconds }: { seconds: number }) {
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    setLeft(seconds);
    const t = window.setInterval(() => {
      setLeft((v) => {
        if (v <= 1) { clearInterval(t); return 0; }
        return v - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [seconds]);
  return <div className="timer mono" role="timer">{left > 0 ? `${left} s` : "Time's up"}</div>;
}

function CardMount({ onImage }: { onImage: (jpeg: Blob) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const cb = useRef(onImage);
  cb.current = onImage;
  useEffect(() => {
    if (!ref.current) return;
    const stop = cardCapture(ref.current, (jpeg) => cb.current(jpeg));
    return () => stop();
  }, []);
  return <div ref={ref} />;
}

function ScreenlightMount({ sequence, frameMs, onFrames }: {
  sequence: string[]; frameMs: number; onFrames: (frames: Record<string, number[][]>) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cb = useRef(onFrames);
  cb.current = onFrames;
  useEffect(() => {
    if (!ref.current) return;
    const stop = screenlightCapture(ref.current, sequence, frameMs, (frames) => cb.current(frames));
    return () => stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <div ref={ref} />;
}
