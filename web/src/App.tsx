import { lazy, Suspense } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { Footer, Header, ScrollReset } from "./components/Layout";
import Landing from "./pages/Landing";

const Scan = lazy(() => import("./pages/Scan"));
const ScanResult = lazy(() => import("./pages/ScanResult"));
const Foods = lazy(() => import("./pages/Foods"));
const Food = lazy(() => import("./pages/Food"));
const Credits = lazy(() => import("./pages/Credits"));
const LabTests = lazy(() => import("./pages/lab/LabTests"));
const LabRun = lazy(() => import("./pages/lab/LabRun"));
const LabResult = lazy(() => import("./pages/lab/LabResult"));
const LabCalibration = lazy(() => import("./pages/lab/LabCalibration"));
const Developers = lazy(() => import("./pages/Developers"));
const NotFound = lazy(() => import("./pages/NotFound"));

export default function App() {
  const { pathname } = useLocation();
  const scanner = pathname === "/scan";   // the scanner is a full-bleed tool: no marketing chrome
  return (
    <ScrollReset>
      {!scanner && <Header />}
      <main id="main">
        <Suspense fallback={<div className="wrap page muted">Loading…</div>}>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/scan" element={<Scan />} />
            <Route path="/scan/:id" element={<ScanResult />} />
            <Route path="/foods" element={<Foods />} />
            <Route path="/foods/:id" element={<Food />} />
            <Route path="/lab-tests" element={<LabTests />} />
            <Route path="/lab-tests/run/:id" element={<LabRun />} />
            <Route path="/lab-tests/result/:id" element={<LabResult />} />
            <Route path="/lab-tests/calibration/:id?" element={<LabCalibration />} />
            <Route path="/developers" element={<Developers />} />
            <Route path="/credits" element={<Credits />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </main>
      {!scanner && <Footer />}
    </ScrollReset>
  );
}
