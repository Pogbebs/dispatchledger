import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type DeliveryRow, type Driver } from "../api";
import { useAuth } from "../auth";
import { Pill, dayTime, gallons } from "../format";

const STATUSES = ["scheduled", "in_transit", "completed", "failed"];

export default function Deliveries() {
  const { user } = useAuth();
  const canDispatch = user?.role === "admin" || user?.role === "dispatcher";

  const [rows, setRows] = useState<DeliveryRow[]>([]);
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [status, setStatus] = useState("scheduled");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [completing, setCompleting] = useState<string | null>(null);
  const [amount, setAmount] = useState("");

  // Reassignment is a dispatcher's act, so it gets its own edit state rather
  // than sharing the driver's completion row.
  const [editing, setEditing] = useState<string | null>(null);
  const [driverId, setDriverId] = useState("");
  const [when, setWhen] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.deliveries(status || undefined));
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not load deliveries.",
      );
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!canDispatch) return;
    api.drivers().then(setDrivers).catch(() => {
      // A failed dropdown should not take the board down with it.
    });
  }, [canDispatch]);

  function startCompleting(row: DeliveryRow) {
    setEditing(null);
    setCompleting(row.id);
    // Pre-fill with the ordered amount: the driver adjusts down to what the
    // tank actually took, which is the normal case.
    setAmount(String(Math.round(Number(row.ordered_gal))));
  }

  function startEditing(row: DeliveryRow) {
    setCompleting(null);
    setEditing(row.id);
    setDriverId(row.driver_id ?? "");
    setWhen(row.scheduled_at.slice(0, 10));
  }

  async function confirm(id: string) {
    try {
      await api.completeDelivery(id, Number(amount).toFixed(2));
      setCompleting(null);
      await load();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not complete delivery.",
      );
    }
  }

  async function saveEdit(id: string) {
    setBusy(true);
    try {
      // Both fields are sent because both are editable on this row. The API
      // distinguishes an absent field from an explicit null, so sending null
      // here is what unassigns a driver.
      await api.rescheduleDelivery(id, {
        driver_id: driverId || null,
        scheduled_at: `${when}T08:00:00Z`,
      });
      setEditing(null);
      await load();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not reschedule.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Deliveries</h1>
          <div className="subtle">
            {loading
              ? "Loading…"
              : "Completing a delivery invoices the customer for the gallons actually delivered."}
          </div>
        </div>
        <div className="filters">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Scheduled</th>
              <th>Customer</th>
              <th>Product</th>
              <th>Driver</th>
              <th className="num">Ordered</th>
              <th className="num">Delivered</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="num">{dayTime(row.scheduled_at)}</td>
                <td>{row.customer_name}</td>
                <td>{row.product_name}</td>
                <td className="subtle">{row.driver_name ?? "Unassigned"}</td>
                <td className="num">{gallons(row.ordered_gal)}</td>
                <td className="num">{gallons(row.delivered_gal)}</td>
                <td>
                  <Pill status={row.status} />
                </td>
                <td className="cell-actions">
                  {editing === row.id ? (
                    <span className="inline-form">
                      <select
                        value={driverId}
                        onChange={(e) => setDriverId(e.target.value)}
                        aria-label="Driver"
                      >
                        <option value="">Unassigned</option>
                        {drivers.map((d) => (
                          <option key={d.id} value={d.id}>
                            {d.full_name}
                          </option>
                        ))}
                      </select>
                      <input
                        type="date"
                        value={when}
                        onChange={(e) => setWhen(e.target.value)}
                        aria-label="Scheduled date"
                      />
                      <button
                        className="btn btn-sm"
                        disabled={busy}
                        onClick={() => saveEdit(row.id)}
                      >
                        {busy ? "…" : "Save"}
                      </button>
                      <button
                        className="btn btn-quiet btn-sm"
                        onClick={() => setEditing(null)}
                      >
                        Cancel
                      </button>
                    </span>
                  ) : completing === row.id ? (
                    <span className="inline-form">
                      <input
                        type="number"
                        value={amount}
                        onChange={(e) => setAmount(e.target.value)}
                        style={{ width: 110 }}
                        aria-label="Gallons delivered"
                        autoFocus
                      />
                      <button
                        className="btn btn-sm"
                        onClick={() => confirm(row.id)}
                      >
                        Save
                      </button>
                      <button
                        className="btn btn-quiet btn-sm"
                        onClick={() => setCompleting(null)}
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    row.status !== "completed" && (
                      <span className="inline-form">
                        <button
                          className="btn btn-quiet btn-sm"
                          onClick={() => startCompleting(row)}
                        >
                          Complete
                        </button>
                        {canDispatch && (
                          <button
                            className="btn btn-quiet btn-sm"
                            onClick={() => startEditing(row)}
                          >
                            Reassign
                          </button>
                        )}
                      </span>
                    )
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {!loading && rows.length === 0 && (
          <div className="empty">No deliveries match this filter.</div>
        )}
      </div>
    </>
  );
}
