"use client";

export function CoverageOverlay({ outside, onReturn }: { outside: boolean; onReturn: () => void }) {
  return (
    <>
      <div className="coverageDim" aria-hidden="true" />
      {outside ? (
        <div className="coverageNotice" role="status">
          <span><strong>Outside Trackstar coverage</strong><small>Trackstar currently covers Napa + Solano.</small></span>
          <button onClick={onReturn} type="button">View coverage</button>
        </div>
      ) : null}
    </>
  );
}
