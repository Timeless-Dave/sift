import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Assay, type RunRow } from "../../api";
import { csvCell, download, getDevice, setDevice } from "../../util";
import "../../styles/lab.css";

interface Cal {
  samples: { known_value: number; created: number }[];
  model: { kind: string; metrics: Record<string, unknown> } | null;
}

export default function LabCalibration() {
  const { id: paramId } = useParams();
  const [assays, setAssays] = useState<Assay[] | null>(null);
  const [assay, setAssay] = useState<Assay | null>(null);
  const [device, setDeviceLabel] = useState("");
  const [cal, setCal] = useState<Cal | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [error, setError] = useState("");
  const [trainOut, setTrainOut] = useState("");

  const load = useCallback(async (assayId: string | undefined) => {
    const list = (await api.assays()).filter((a) => a.runnable);
    if (!list.length) return { list, picked: null as Assay | null };
    const pickedId = assayId && list.some((a) => a.id === assayId) ? assayId : list[0].id;
    const [a, dev] = await Promise.all([api.assay(pickedId), getDevice()]);
    const [calRaw, runsRaw] = await Promise.all([api.calibration(pickedId, dev), api.runs(pickedId)]);
    return {
      list,
      picked: a,
      device: dev,
      cal: { ...calRaw, samples: calRaw.samples ?? [] },
      runs: Array.isArray(runsRaw) ? runsRaw : [],
    };
  }, []);

  const refresh = useCallback((assayId: string | undefined) => {
    setError("");
    setTrainOut("");
    load(assayId).then(
      (s) => {
        setAssays(s.list);
        setAssay(s.picked);
        if (s.device !== undefined) setDeviceLabel(s.device);
        if (s.cal !== undefined) setCal(s.cal);
        if (s.runs !== undefined) setRuns(s.runs);
      },
      (e) => setError((e as Error).message),
    );
  }, [load]);

  useEffect(() => { refresh(paramId); }, [refresh, paramId]);

  if (error) {
    return (
      <div className="wrap page lab-cal">
        <section className="page-head">
          <Link className="back" to="/lab-tests">← All tests</Link>
          <h1 className="h1">Calibration and runs</h1>
          <p role="alert">Couldn&apos;t load the calibration data: {error}</p>
        </section>
      </div>
    );
  }
  if (!assays) return <div className="wrap page lab-cal"><p className="muted">Loading the calibration data…</p></div>;
  if (!assays.length || !assay || !cal) {
    return (
      <div className="wrap page lab-cal">
        <section className="card">
          <h1 className="h1">Calibration and runs</h1>
          <p>No test is runnable yet.</p>
          <p><Link to="/lab-tests">Back to tests</Link></p>
        </section>
      </div>
    );
  }

  const levels = [...new Set(cal.samples.map((s) => s.known_value))].sort((a, b) => a - b);

  const saveLabel = (label: string) => {
    setDevice(label.trim());
    refresh(assay.id);
  };

  const train = async () => {
    setTrainOut("Training…");
    try {
      await api.train(assay.id, device);
      refresh(assay.id);
    } catch (e) {
      setTrainOut((e as Error).message);
    }
  };

  const exportCsv = () => {
    const head = "run_id,created,device,status,label,value,unit,confidence,known\n";
    const body = runs.map((r) => [
      r.id,
      new Date(r.created * 1000).toISOString(),
      r.device,
      r.status,
      r.result?.label ?? "",
      r.result?.value ?? "",
      r.result?.unit ?? "",
      r.result?.confidence ?? "",
      r.truth ?? "",
    ].map(csvCell).join(",")).join("\n");
    download(`sift-${assay.id}-runs.csv`, head + body, "text/csv");
  };

  return (
    <div className="wrap page lab-cal">
      <section className="lab">
        <Link className="back" to="/lab-tests">← All tests</Link>
        <h1 className="h1">Calibration and runs</h1>
        <nav className="assay-tabs" aria-label="Choose a test">
          {assays.map((a) => (
            <Link key={a.id} to={`/lab-tests/calibration/${a.id}`} aria-current={a.id === assay.id ? "page" : undefined}>
              {a.name}
            </Link>
          ))}
        </nav>

        <form
          className="device"
          onSubmit={(e) => {
            e.preventDefault();
            saveLabel(new FormData(e.target as HTMLFormElement).get("device") as string);
          }}
        >
          <label>
            This phone&apos;s calibration label
            <input name="device" key={device} defaultValue={device} required />
          </label>
          <div><button className="btn ghost" type="submit">Save label</button></div>
          <p className="muted">Calibration is stored per phone model. Use the same label on every phone of this model.</p>
        </form>

        <h2 className="h2">Calibration for this phone</h2>
        {cal.model ? (
          <table className="data">
            <tbody>
              {Object.entries(cal.model.metrics).map(([k, v]) => (
                <tr key={k}><th>{k}</th><td>{String(v)}</td></tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p>
            No model yet. Run the test on samples with known amounts, open each result, and add it to calibration.{" "}
            {assay.method === "screenlight"
              ? "Training needs at least 6 scans across 3 or more known levels."
              : "A curve needs 3 or more known levels."}
          </p>
        )}
        <p>
          {cal.samples.length} calibration sample{cal.samples.length === 1 ? "" : "s"} at levels:{" "}
          {levels.join(", ") || "none yet"}
        </p>
        <div className="row">
          <button type="button" className="btn" onClick={() => void train()} disabled={!cal.samples.length}>
            Train model
          </button>
          <button type="button" className="btn ghost" onClick={exportCsv} disabled={!runs.length}>
            Export runs (CSV)
          </button>
        </div>
        <p className="train-out" role="status">{trainOut}</p>

        <h2 className="h2">Accuracy so far</h2>
        <p>All phones: {assay.accuracy?.summary}</p>
        <p>This phone: {assay.accuracy?.by_device?.[device]?.summary ?? "Not measured yet: no runs with known answers."}</p>

        <h2 className="h2">Recent runs</h2>
        {runs.length ? (
          <table className="data runs">
            <thead><tr><th>When</th><th>Phone</th><th>Result</th><th>Known</th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td><Link to={`/lab-tests/result/${r.id}`}>{new Date(r.created * 1000).toLocaleString()}</Link></td>
                  <td>{r.device}</td>
                  <td>{r.result?.label ?? r.status}{r.result?.value != null ? ` (${String(r.result.value)})` : ""}</td>
                  <td>{r.truth ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p>No runs yet. <Link to={`/lab-tests/run/${assay.id}`}>Run this test</Link>.</p>
        )}
      </section>
    </div>
  );
}
