import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type DeliveryRow } from "../api";
import { Pill, dayTime, gallons } from "../format";

const STATUSES = ["scheduled", "in_transit", "completed", "failed"];

export default function Deliveries() {
  const [rows, setRows] = useState<DeliveryRow[]>([]);
  const [status, setStatus] = useState("scheduled");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [completing, setCompleting] = useState<string | null>(null);
  const [amount, setAmount] = useState("");

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

  function startCompleting(row: DeliveryRow) {
    setCompleting(row.id);
    // Pre-fill with the ordered amount: the driver adjusts down to what the
    // tank actually took, which is the normal case.
    setAmount(String(Math.round(Number(row.ordered_gal))));
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
                <td>
                  {row.status !== "completed" &&
                    (completing === row.id ? (
                      <span style={{ display: "flex", gap: 6 }}>
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
                      <button
                        className="btn btn-quiet btn-sm"
                        onClick={() => startCompleting(row)}
                      >
                        Complete
                      </button>
                    ))}
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
